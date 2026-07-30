#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$WORKSPACE_DIR}"
BACKUP_ROOT="${BACKUP_ROOT:-$WORKSPACE_DIR/backups}"
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_FOLDER_ID="${REMOTE_FOLDER_ID:-}"
REMOTE_LATEST_FILE="${REMOTE_LATEST_FILE:-bmi30_latest.env}"
STATE_DIR="${STATE_DIR:-$WORKSPACE_DIR/.bmi30_cloud_sync}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/backup_to_cloud.conf}"
UPDATE_ON_CALENDAR="${UPDATE_ON_CALENDAR:-*-*-* 23:00:00}"
ON_CALENDAR="${ON_CALENDAR:-}"
PRE_UPDATE_SNAPSHOT="${PRE_UPDATE_SNAPSHOT:-1}"
PRE_UPDATE_RETENTION_COUNT="${PRE_UPDATE_RETENTION_COUNT:-3}"
INCOMING_RETENTION_COUNT="${INCOMING_RETENTION_COUNT:-2}"
RESTART_AFTER_UPDATE="${RESTART_AFTER_UPDATE:-1}"
BMI30_CORE_SERVICE="${BMI30_CORE_SERVICE:-bmi30-core.service}"
BMI30_PORTAL_SERVICE="${BMI30_PORTAL_SERVICE:-bmi30-hotspot-info.service}"
BMI30_PORTAL_DST="${BMI30_PORTAL_DST:-/usr/local/bin/bmi30-hotspot-info-server.py}"
COMMON_LIB="$SCRIPT_DIR/cloud_sync_common.sh"
PROGRESS_FILE="${BMI30_PROGRESS_FILE:-}"
PROGRESS_ACTION="${BMI30_PROGRESS_ACTION:-update}"

if [[ -f "$COMMON_LIB" ]]; then
    # shellcheck source=/dev/null
    source "$COMMON_LIB"
else
    printf '[ERROR] Общая библиотека синхронизации не найдена: %s\n' "$COMMON_LIB" >&2
    exit 1
fi

DRY_RUN=0
INSTALL_TIMER=0
FORCE_UPDATE=0
REQUIRE_TODAY=0

APPLY_TEMP_DIR=""
PREVIOUS_ACTIVE_ENV_BACKUP=""
PREVIOUS_RELEASE_MANIFEST_BACKUP=""

usage() {
    cat <<'EOF'
Usage:
  ./utilities/update_from_cloud.sh [options]

Options:
  --source <path>            Directory to update (default: repo root)
  --output-dir <path>        Local archive/snapshot directory (default: ./backups)
  --remote <rclone-remote>   Cloud target, for example: gdrive:
  --remote-folder-id <id>    Google Drive folder ID
  --install-timer            Compatibility command: disable the legacy auto-install timer
  --on-calendar <expr>       Legacy compatibility option (Portal checks hourly)
  --config <path>            Config file (default: ./utilities/backup_to_cloud.conf)
  --today-only               Update only from an archive published today
  --no-restart               Do not restart BMI30 runtime after applying an update
  --force                    Apply latest cloud archive even if signatures match
  --dry-run                  Show actions without changing files
  -h, --help                 Show this help

Examples:
  ./utilities/update_from_cloud.sh
  ./utilities/update_from_cloud.sh --install-timer  # disables legacy unattended installs
EOF
}

log() {
    printf '[INFO] %s\n' "$*" >&2
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

fail() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

json_escape() {
    local value="${1:-}"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '%s' "$value"
}

write_progress() {
    [[ -n "$PROGRESS_FILE" ]] || return 0
    local progress="$1"
    local message="$2"
    local progress_dir temporary
    progress_dir="$(dirname -- "$PROGRESS_FILE")"
    mkdir -p "$progress_dir"
    temporary="$progress_dir/.portal_operation.update.$$"
    {
        printf '{"action":"%s","status":"running","progress":%d,' \
            "$(json_escape "$PROGRESS_ACTION")" \
            "$progress"
        printf '"message":"%s","error":"","updated_at":%d}\n' \
            "$(json_escape "$message")" \
            "$(date +%s)"
    } > "$temporary"
    mv -f -- "$temporary" "$PROGRESS_FILE"
}

cleanup() {
    if [[ -n "$APPLY_TEMP_DIR" && -d "$APPLY_TEMP_DIR" ]]; then
        rm -rf "$APPLY_TEMP_DIR"
    fi
}

trap cleanup EXIT

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
    fi
    ON_CALENDAR="${ON_CALENDAR:-$UPDATE_ON_CALENDAR}"
}

require_value() {
    local opt="$1"
    local val="${2:-}"
    [[ -n "$val" ]] || fail "После $opt нужен аргумент"
}

remote_join() {
    local base="$1"
    local name="$2"

    if [[ "$base" == *: ]]; then
        printf '%s%s' "$base" "$name"
    else
        printf '%s/%s' "${base%/}" "$name"
    fi
}

detect_serial_suffix() {
    local serial=""

    if [[ -r /proc/device-tree/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /proc/device-tree/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /sys/firmware/devicetree/base/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /sys/firmware/devicetree/base/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /proc/cpuinfo ]]; then
        serial="$(awk -F: '/^Serial/ {gsub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo || true)"
    fi

    serial="$(printf '%s' "$serial" | tr -cd '0-9A-Fa-f')"
    if [[ -n "$serial" && ${#serial} -ge 9 ]]; then
        printf '%s' "${serial: -9}"
    else
        printf 'unknown'
    fi
}

validate_settings() {
    [[ -d "$SOURCE_DIR" ]] || fail "SOURCE_DIR не найден: $SOURCE_DIR"
    [[ -n "$REMOTE_TARGET" ]] || fail "REMOTE_TARGET не задан"
    command -v rclone >/dev/null 2>&1 || fail "rclone не установлен"
    command -v rsync >/dev/null 2>&1 || fail "rsync не установлен"
    [[ "$PRE_UPDATE_RETENTION_COUNT" =~ ^[0-9]+$ ]] || fail "PRE_UPDATE_RETENTION_COUNT должен быть целым числом"
    [[ "$INCOMING_RETENTION_COUNT" =~ ^[0-9]+$ ]] || fail "INCOMING_RETENTION_COUNT должен быть целым числом"
}

install_user_timer() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Автоматический install timer не устанавливается; Portal проверяет marker раз в час"
        return
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now bmi30-cloud-update.timer >/dev/null 2>&1 || true
    fi
    log "Автоматическая установка отключена. Portal проверяет cloud marker в фоне, а release ставится только кнопкой Update."
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source)
                require_value "$1" "${2:-}"
                SOURCE_DIR="$2"
                shift 2
                ;;
            --output-dir)
                require_value "$1" "${2:-}"
                BACKUP_ROOT="$2"
                shift 2
                ;;
            --remote)
                require_value "$1" "${2:-}"
                REMOTE_TARGET="$2"
                shift 2
                ;;
            --remote-folder-id)
                require_value "$1" "${2:-}"
                REMOTE_FOLDER_ID="$2"
                shift 2
                ;;
            --on-calendar)
                require_value "$1" "${2:-}"
                ON_CALENDAR="$2"
                shift 2
                ;;
            --config)
                require_value "$1" "${2:-}"
                CONFIG_FILE="$2"
                load_config
                shift 2
                ;;
            --install-timer)
                INSTALL_TIMER=1
                shift
                ;;
            --force)
                FORCE_UPDATE=1
                shift
                ;;
            --today-only)
                REQUIRE_TODAY=1
                shift
                ;;
            --no-restart)
                RESTART_AFTER_UPDATE=0
                shift
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                fail "Неизвестный аргумент: $1"
                ;;
        esac
    done
}

project_signature() {
    bmi30_project_signature "$SOURCE_DIR"
}

legacy_project_signature() {
    bmi30_legacy_project_signature "$SOURCE_DIR"
}

download_latest_marker() {
    local marker_path remote_marker
    local start_ts end_ts elapsed_s marker_bytes
    mkdir -p "$STATE_DIR"
    marker_path="$STATE_DIR/remote_$REMOTE_LATEST_FILE"
    remote_marker="$(remote_join "$REMOTE_TARGET" "$REMOTE_LATEST_FILE")"

    local -a cmd
    cmd=(rclone copyto "$remote_marker" "$marker_path")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Скачал бы указатель последнего архива: $remote_marker"
        printf '%s' "$marker_path"
        return
    fi

    start_ts="$(date +%s)"
    if ! "${cmd[@]}"; then
        fail "Не удалось скачать указатель последнего архива: $remote_marker"
    fi
    end_ts="$(date +%s)"
    elapsed_s=$((end_ts - start_ts))
    marker_bytes="$(bmi30_file_size_bytes "$marker_path")"
    bmi30_log_copy_result "Скачивание указателя архива" "$marker_bytes" "$elapsed_s"

    printf '%s' "$marker_path"
}

load_latest_marker() {
    local marker_path="$1"
    unset RELEASE_KIND ARCHIVE_NAME ARCHIVE_SHA256 PROJECT_SIGNATURE PROJECT_CONTENT_SIGNATURE PROJECT_SIGNATURE_VERSION FIRMWARE_VERSION FIRMWARE_BUNDLE_ID DEVICE_SUFFIX CREATED_AT SOURCE_BASENAME

    [[ -f "$marker_path" ]] || fail "Указатель архива не найден: $marker_path"
    # shellcheck source=/dev/null
    source "$marker_path"

    [[ "${ARCHIVE_NAME:-}" == bmi30_backup_*.tar.gz || "${ARCHIVE_NAME:-}" == bmi30_firmware_*.tar.gz ]] || fail "Некорректное имя архива в $marker_path"
    [[ "${ARCHIVE_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]] || fail "Некорректный SHA-256 архива в $marker_path"
    bmi30_signature_is_valid "${PROJECT_SIGNATURE:-}" || fail "Некорректная совместимая подпись проекта в $marker_path"
    if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
        bmi30_signature_is_valid "$PROJECT_CONTENT_SIGNATURE" || fail "Некорректная подпись содержимого проекта в $marker_path"
    fi
}

marker_is_today() {
    local marker_day today
    marker_day="$(date -d "${CREATED_AT:-}" +%Y-%m-%d 2>/dev/null || true)"
    today="$(date +%Y-%m-%d)"

    [[ -n "$marker_day" && "$marker_day" == "$today" ]]
}

create_pre_update_snapshot() {
    [[ "$PRE_UPDATE_SNAPSHOT" == "1" ]] || return 0

    local source_abs source_parent source_name backup_abs archive_path timestamp device_suffix
    local start_ts end_ts elapsed_s archive_bytes
    source_abs="$(cd -- "$SOURCE_DIR" && pwd)"
    source_parent="$(dirname -- "$source_abs")"
    source_name="$(basename -- "$source_abs")"
    mkdir -p "$BACKUP_ROOT"
    backup_abs="$(cd -- "$BACKUP_ROOT" && pwd)"
    timestamp="$(date +%Y%m%d_%H%M%S)"
    device_suffix="$(detect_serial_suffix)"
    device_suffix="$(printf '%s' "$device_suffix" | tr -cd 'A-Za-z0-9_-')"
    device_suffix="${device_suffix^^}"
    archive_path="$backup_abs/pre_update_${timestamp}_${device_suffix}.tar.gz"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Создал бы снимок перед обновлением: $archive_path"
        return
    fi

    local -a tar_args
    tar_args=(-czf "$archive_path")
    bmi30_add_project_tar_excludes tar_args "$source_name"
    tar_args+=(
        -C "$source_parent"
        "$source_name"
    )
    start_ts="$(date +%s)"
    tar "${tar_args[@]}"
    end_ts="$(date +%s)"
    elapsed_s=$((end_ts - start_ts))
    archive_bytes="$(bmi30_file_size_bytes "$archive_path")"

    log "Снимок перед обновлением создан: $archive_path"
    bmi30_log_copy_result "Создание снимка перед обновлением" "$archive_bytes" "$elapsed_s"
}

download_archive() {
    local incoming_dir archive_path remote_archive actual_hash
    local start_ts end_ts elapsed_s archive_bytes
    incoming_dir="$STATE_DIR/incoming"
    mkdir -p "$incoming_dir"
    archive_path="$incoming_dir/$ARCHIVE_NAME"
    remote_archive="$(remote_join "$REMOTE_TARGET" "$ARCHIVE_NAME")"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Скачал бы архив: $remote_archive"
        printf '%s' "$archive_path"
        return
    fi

    if [[ -f "$archive_path" ]]; then
        actual_hash="$(sha256sum "$archive_path" | awk '{print $1}')"
        if [[ "${actual_hash,,}" == "${ARCHIVE_SHA256,,}" ]]; then
            log "Используется уже скачанный архив: $archive_path"
            printf '%s' "$archive_path"
            return
        fi
    fi

    local -a cmd
    cmd=(rclone copyto "$remote_archive" "$archive_path")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    start_ts="$(date +%s)"
    if ! "${cmd[@]}"; then
        fail "Не удалось скачать архив: $remote_archive"
    fi
    end_ts="$(date +%s)"
    elapsed_s=$((end_ts - start_ts))
    archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
    bmi30_log_copy_result "Скачивание архива" "$archive_bytes" "$elapsed_s"

    actual_hash="$(sha256sum "$archive_path" | awk '{print $1}')"
    [[ "${actual_hash,,}" == "${ARCHIVE_SHA256,,}" ]] || fail "SHA-256 архива не совпадает: $archive_path"

    log "Архив скачан и проверен: $archive_path"
    printf '%s' "$archive_path"
}

apply_archive() {
    local archive_path="$1"
    local extracted source_name
    local start_ts end_ts elapsed_s archive_bytes apply_bytes

    APPLY_TEMP_DIR="$(mktemp -d)"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Применил бы архив к проекту: $archive_path -> $SOURCE_DIR"
        return
    fi

    archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
    start_ts="$(date +%s)"
    tar -xzf "$archive_path" -C "$APPLY_TEMP_DIR"
    end_ts="$(date +%s)"
    elapsed_s=$((end_ts - start_ts))
    bmi30_log_copy_result "Распаковка архива" "$archive_bytes" "$elapsed_s"

    source_name="${SOURCE_BASENAME:-$(basename -- "$(cd -- "$SOURCE_DIR" && pwd)")}"

    if [[ -d "$APPLY_TEMP_DIR/$source_name" ]]; then
        extracted="$APPLY_TEMP_DIR/$source_name"
    else
        extracted="$(find "$APPLY_TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | sed -n '1p')"
    fi

    [[ -n "$extracted" && -d "$extracted" ]] || fail "Не удалось найти корень проекта в архиве"

    local archive_bundle_id bundle_dir current_active_env current_release_manifest
    archive_bundle_id="$(bmi30_active_bundle_id "$extracted" || true)"
    bundle_dir="$extracted/host/bmi30_split_bundles/$archive_bundle_id"
    if [[ -n "${FIRMWARE_BUNDLE_ID:-}" ]]; then
        [[ "$archive_bundle_id" == "$FIRMWARE_BUNDLE_ID" ]] \
            || fail "Bundle ID в архиве не совпадает с marker: ${archive_bundle_id:-<empty>} != $FIRMWARE_BUNDLE_ID"
        [[ -d "$bundle_dir" ]] || fail "Активный полный bundle отсутствует в firmware-архиве: $FIRMWARE_BUNDLE_ID"
    elif [[ ! -d "$bundle_dir" ]]; then
        archive_bundle_id=""
    fi

    current_active_env="$SOURCE_DIR/host/bmi30_split_active_version.env"
    if [[ -f "$current_active_env" ]]; then
        mkdir -p "$STATE_DIR"
        PREVIOUS_ACTIVE_ENV_BACKUP="$STATE_DIR/active_env.before_update"
        install -m 0644 "$current_active_env" "$PREVIOUS_ACTIVE_ENV_BACKUP"
    fi
    current_release_manifest="$SOURCE_DIR/host/bmi30_firmware_release.env"
    if [[ -f "$current_release_manifest" ]]; then
        mkdir -p "$STATE_DIR"
        PREVIOUS_RELEASE_MANIFEST_BACKUP="$STATE_DIR/firmware_release.before_update.env"
        install -m 0644 "$current_release_manifest" "$PREVIOUS_RELEASE_MANIFEST_BACKUP"
    fi

    local -a rsync_args
    rsync_args=(-a --delete)
    bmi30_add_project_rsync_excludes rsync_args "$archive_bundle_id"
    rsync_args+=("$extracted/" "$SOURCE_DIR/")
    apply_bytes="$(bmi30_dir_size_bytes "$extracted")"
    if ! bmi30_run_timed_copy "Применение архива к проекту" "$apply_bytes" rsync "${rsync_args[@]}"; then
        fail "Не удалось применить архив к проекту"
    fi

    log "Проект обновлён из облачного архива: $ARCHIVE_NAME"
}

run_privileged() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
        return
    fi
    if command -v sudo >/dev/null 2>&1; then
        if [[ -t 0 && -t 1 ]]; then
            sudo "$@"
        else
            sudo -n "$@"
        fi
        return
    fi
    return 127
}

resolve_release_path() {
    local rel="${1:-}"
    [[ -n "$rel" ]] || return 1

    if [[ "$rel" = /* ]]; then
        printf '%s' "$rel"
    else
        printf '%s/%s' "$SOURCE_DIR" "$rel"
    fi
}

extract_default_engine_file() {
    local core_file="$1"
    local engine_file
    engine_file="$(sed -n -E "s/^[[:space:]]*DEFAULT_ENGINE_FILE[[:space:]]*=.*[\"']([^\"']+)[\"'].*/\1/p" "$core_file" | sed -n '1p')"
    [[ -n "$engine_file" ]] || return 1
    if [[ "$engine_file" == */* ]]; then
        printf '%s' "$engine_file"
    else
        printf 'host/%s' "$engine_file"
    fi
}

verify_manifest_component() {
    local label="$1"
    local manifest_rel="$2"
    local expected_hash="$3"
    local active_rel="$4"
    local path actual_hash

    [[ -n "$manifest_rel" && -n "$expected_hash" ]] || fail "Release manifest не содержит $label path/hash"
    [[ "$manifest_rel" == "$active_rel" ]] || fail "Release manifest $label path не совпадает с active env: $manifest_rel != $active_rel"
    path="$(resolve_release_path "$manifest_rel")"
    [[ -f "$path" ]] || fail "Release manifest $label file не найден: $path"
    actual_hash="$(sha256sum "$path" | awk '{print $1}')"
    [[ "${actual_hash,,}" == "${expected_hash,,}" ]] || fail "Release manifest $label SHA-256 не совпадает: $manifest_rel"
}

verify_firmware_manifest() {
    local core_rel="$1"
    local engine_rel="$2"
    local gui_rel="$3"
    local portal_rel="$4"
    local bundle_id="${5:-}"
    local manifest="$SOURCE_DIR/host/bmi30_firmware_release.env"

    if [[ ! -f "$manifest" ]]; then
        [[ -z "${FIRMWARE_VERSION:-}" ]] || fail "В marker указана firmware version, но release manifest отсутствует"
        warn "Release manifest отсутствует: это допустимо только для старого облачного архива"
        return
    fi

    unset BMI30_FIRMWARE_VERSION BMI30_FIRMWARE_LABEL BMI30_FIRMWARE_CREATED_AT BMI30_FIRMWARE_BUNDLE_ID
    unset BMI30_FIRMWARE_CONTENT_SIGNATURE BMI30_FIRMWARE_SIGNATURE_VERSION
    unset BMI30_FIRMWARE_CORE_PATH BMI30_FIRMWARE_CORE_SHA256
    unset BMI30_FIRMWARE_ENGINE_PATH BMI30_FIRMWARE_ENGINE_SHA256
    unset BMI30_FIRMWARE_GUI_PATH BMI30_FIRMWARE_GUI_SHA256
    unset BMI30_FIRMWARE_PORTAL_PATH BMI30_FIRMWARE_PORTAL_SHA256
    unset BMI30_FIRMWARE_VENDOR_DOC_PATH BMI30_FIRMWARE_VENDOR_DOC_SHA256
    unset BMI30_FIRMWARE_HOST_DOC_PATH BMI30_FIRMWARE_HOST_DOC_SHA256
    # shellcheck source=/dev/null
    source "$manifest"

    [[ -n "${BMI30_FIRMWARE_VERSION:-}" ]] || fail "Release manifest не содержит BMI30_FIRMWARE_VERSION"
    if [[ -n "${FIRMWARE_VERSION:-}" ]]; then
        [[ "$BMI30_FIRMWARE_VERSION" == "$FIRMWARE_VERSION" ]] || fail "Firmware version marker/manifest не совпадает"
    fi
    if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
        [[ "${BMI30_FIRMWARE_CONTENT_SIGNATURE,,}" == "${PROJECT_CONTENT_SIGNATURE,,}" ]] || fail "Content signature marker/manifest не совпадает"
    fi
    if [[ -n "${FIRMWARE_BUNDLE_ID:-}" ]]; then
        [[ "${BMI30_FIRMWARE_BUNDLE_ID:-}" == "$FIRMWARE_BUNDLE_ID" ]] || fail "Bundle ID marker/manifest не совпадает"
    fi
    if [[ -n "${BMI30_FIRMWARE_BUNDLE_ID:-}" ]]; then
        [[ "$BMI30_FIRMWARE_BUNDLE_ID" == "$bundle_id" ]] || fail "Bundle ID manifest/active env не совпадает"
    fi

    verify_manifest_component "core" "${BMI30_FIRMWARE_CORE_PATH:-}" "${BMI30_FIRMWARE_CORE_SHA256:-}" "$core_rel"
    verify_manifest_component "engine" "${BMI30_FIRMWARE_ENGINE_PATH:-}" "${BMI30_FIRMWARE_ENGINE_SHA256:-}" "$engine_rel"
    verify_manifest_component "GUI" "${BMI30_FIRMWARE_GUI_PATH:-}" "${BMI30_FIRMWARE_GUI_SHA256:-}" "$gui_rel"
    verify_manifest_component "portal" "${BMI30_FIRMWARE_PORTAL_PATH:-}" "${BMI30_FIRMWARE_PORTAL_SHA256:-}" "$portal_rel"
    if [[ "${BMI30_FIRMWARE_SIGNATURE_VERSION:-}" =~ ^[0-9]+$ ]] \
        && (( BMI30_FIRMWARE_SIGNATURE_VERSION >= 5 )); then
        verify_manifest_component "vendor documentation" \
            "${BMI30_FIRMWARE_VENDOR_DOC_PATH:-}" "${BMI30_FIRMWARE_VENDOR_DOC_SHA256:-}" \
            "host/README_VENDOR_HOST.md"
        verify_manifest_component "host documentation" \
            "${BMI30_FIRMWARE_HOST_DOC_PATH:-}" "${BMI30_FIRMWARE_HOST_DOC_SHA256:-}" \
            "host/HOST_RPI.md"
    fi
    log "Release manifest проверен: $BMI30_FIRMWARE_VERSION"
}

verify_active_release_files() {
    local active_env bundle_id core_rel gui_rel portal_rel engine_rel
    local core_path gui_path portal_path engine_path missing

    active_env="$SOURCE_DIR/host/bmi30_split_active_version.env"
    [[ -f "$active_env" ]] || fail "Активный websplit env не найден после обновления: $active_env"

    unset BMI30_SPLIT_BUNDLE_ID BMI30_CORE_PATH BMI30_GUI_PATH BMI30_PORTAL_PATH BMI30_ENGINE_SOURCE
    # shellcheck source=/dev/null
    source "$active_env"

    bundle_id="${BMI30_SPLIT_BUNDLE_ID:-}"
    core_rel="${BMI30_CORE_PATH:-}"
    gui_rel="${BMI30_GUI_PATH:-}"
    portal_rel="${BMI30_PORTAL_PATH:-}"
    engine_rel="${BMI30_ENGINE_SOURCE:-}"

    missing=0

    if ! core_path="$(resolve_release_path "$core_rel")" || [[ ! -f "$core_path" ]]; then
        warn "Core file из активной прошивки не найден: ${core_rel:-<empty>}"
        missing=1
    fi
    if ! gui_path="$(resolve_release_path "$gui_rel")" || [[ ! -f "$gui_path" ]]; then
        warn "GUI file из активной прошивки не найден: ${gui_rel:-<empty>}"
        missing=1
    fi
    if ! portal_path="$(resolve_release_path "$portal_rel")" || [[ ! -f "$portal_path" ]]; then
        warn "Portal file из активной прошивки не найден: ${portal_rel:-<empty>}"
        missing=1
    fi

    if [[ -z "$engine_rel" && -n "${core_path:-}" && -f "$core_path" ]]; then
        engine_rel="$(extract_default_engine_file "$core_path" || true)"
    fi
    if ! engine_path="$(resolve_release_path "$engine_rel")" || [[ ! -f "$engine_path" ]]; then
        warn "Engine file из активной прошивки не найден: ${engine_rel:-<empty>}"
        missing=1
    fi

    [[ "$missing" -eq 0 ]] || fail "Release неполный: не все активные websplit-файлы доступны"

    verify_firmware_manifest "$core_rel" "$engine_rel" "$gui_rel" "$portal_rel" "$bundle_id"

    log "Активная прошивка проверена: core=$(basename -- "$core_path"), engine=$(basename -- "$engine_path")"
}

active_runtime_matches_release() {
    local active_env manifest core_path engine_path gui_path portal_path runtime_manifest
    active_env="$SOURCE_DIR/host/bmi30_split_active_version.env"
    manifest="$SOURCE_DIR/host/bmi30_firmware_release.env"
    [[ -f "$active_env" && -f "$manifest" ]] || return 1

    unset BMI30_FIRMWARE_VERSION BMI30_FIRMWARE_BUNDLE_ID
    unset BMI30_FIRMWARE_CORE_PATH BMI30_FIRMWARE_CORE_SHA256
    unset BMI30_FIRMWARE_ENGINE_PATH BMI30_FIRMWARE_ENGINE_SHA256
    unset BMI30_FIRMWARE_GUI_PATH BMI30_FIRMWARE_GUI_SHA256
    unset BMI30_FIRMWARE_PORTAL_PATH BMI30_FIRMWARE_PORTAL_SHA256
    # shellcheck source=/dev/null
    source "$manifest"
    [[ -n "${BMI30_FIRMWARE_VERSION:-}" ]] || return 1
    [[ -z "${FIRMWARE_VERSION:-}" || "$BMI30_FIRMWARE_VERSION" == "$FIRMWARE_VERSION" ]] || return 1

    unset BMI30_SPLIT_BUNDLE_ID BMI30_CORE_PATH BMI30_ENGINE_SOURCE BMI30_GUI_PATH BMI30_PORTAL_PATH BMI30_FIRMWARE_MANIFEST
    # shellcheck source=/dev/null
    source "$active_env"
    [[ -z "${BMI30_FIRMWARE_BUNDLE_ID:-}" || "${BMI30_SPLIT_BUNDLE_ID:-}" == "$BMI30_FIRMWARE_BUNDLE_ID" ]] || return 1

    core_path="$(resolve_release_path "${BMI30_CORE_PATH:-}")" || return 1
    engine_path="$(resolve_release_path "${BMI30_ENGINE_SOURCE:-}")" || return 1
    gui_path="$(resolve_release_path "${BMI30_GUI_PATH:-}")" || return 1
    portal_path="$(resolve_release_path "${BMI30_PORTAL_PATH:-}")" || return 1
    [[ -f "$core_path" && -f "$engine_path" && -f "$gui_path" && -f "$portal_path" ]] || return 1
    [[ "$(sha256sum "$core_path" | awk '{print $1}')" == "${BMI30_FIRMWARE_CORE_SHA256:-}" ]] || return 1
    [[ "$(sha256sum "$engine_path" | awk '{print $1}')" == "${BMI30_FIRMWARE_ENGINE_SHA256:-}" ]] || return 1
    [[ "$(sha256sum "$gui_path" | awk '{print $1}')" == "${BMI30_FIRMWARE_GUI_SHA256:-}" ]] || return 1
    [[ "$(sha256sum "$portal_path" | awk '{print $1}')" == "${BMI30_FIRMWARE_PORTAL_SHA256:-}" ]] || return 1

    runtime_manifest="${BMI30_FIRMWARE_MANIFEST:-}"
    [[ -n "$runtime_manifest" ]] || return 1
    [[ "$runtime_manifest" = /* ]] || runtime_manifest="$SOURCE_DIR/$runtime_manifest"
    [[ -f "$runtime_manifest" ]] || return 1
    cmp -s "$manifest" "$runtime_manifest" || return 1
    [[ -f "$BMI30_PORTAL_DST" ]] || return 1
    cmp -s "$portal_path" "$BMI30_PORTAL_DST" || return 1
    [[ "$(systemctl is-active "$BMI30_CORE_SERVICE" 2>/dev/null || true)" == "active" ]] || return 1
    [[ "$(systemctl is-active "$BMI30_PORTAL_SERVICE" 2>/dev/null || true)" == "active" ]] || return 1
}

install_systemd_units_after_update() {
    local unit_dir unit dst installed
    unit_dir="$SOURCE_DIR/ops/systemd"
    [[ -d "$unit_dir" ]] || return 0

    installed=0
    for unit in "$unit_dir"/*.service "$unit_dir"/*.timer; do
        [[ -f "$unit" ]] || continue
        dst="/etc/systemd/system/$(basename -- "$unit")"
        if run_privileged install -m 644 "$unit" "$dst"; then
            log "Systemd unit обновлён: $dst"
            installed=1
        else
            warn "Не удалось установить systemd unit: $unit -> $dst"
            warn "Проверь sudo/NOPASSWD или запусти: sudo install -m 644 \"$unit\" \"$dst\""
        fi
    done

    if [[ "$installed" -eq 1 ]]; then
        if run_privileged systemctl daemon-reload; then
            log "systemd daemon-reload выполнен"
        else
            warn "Не удалось выполнить systemctl daemon-reload"
        fi
    fi
}

enforce_cloud_timer_policy() {
    command -v systemctl >/dev/null 2>&1 || return 0
    if ! systemctl --user list-unit-files >/dev/null 2>&1; then
        log "Portal выполняет только фоновую проверку marker; автоматическая установка firmware не включалась"
        return 0
    fi

    if systemctl --user list-unit-files bmi30-cloud-update.timer >/dev/null 2>&1; then
        if systemctl --user disable --now bmi30-cloud-update.timer >/dev/null 2>&1; then
            log "Старый таймер автоматической установки отключён; обновление выполняется только кнопкой Portal"
        else
            warn "Не удалось отключить старый bmi30-cloud-update.timer"
        fi
    fi

    if [[ -f "$HOME/.config/systemd/user/bmi30-cloud-backup.timer" ]]; then
        if systemctl --user disable --now bmi30-cloud-backup.timer >/dev/null 2>&1; then
            log "Автоматическая публикация отключена; выпуск release остаётся ручным"
        else
            warn "Не удалось отключить bmi30-cloud-backup.timer"
        fi
    fi
    return 0
}

restart_runtime_after_update() {
    [[ "$RESTART_AFTER_UPDATE" == "1" ]] || return 0

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Активировал бы полный release bundle, проверил manifest и службы $BMI30_CORE_SERVICE / $BMI30_PORTAL_SERVICE"
        return
    fi

    install_systemd_units_after_update

    local active_env bundle_id switcher release_manifest
    active_env="$SOURCE_DIR/host/bmi30_split_active_version.env"
    bundle_id="$(bmi30_active_bundle_id "$(cd -- "$SOURCE_DIR" && pwd)" || true)"
    switcher="$SOURCE_DIR/switch_bmi30_split_versions.sh"
    release_manifest="$SOURCE_DIR/host/bmi30_firmware_release.env"

    if [[ -n "$bundle_id" ]]; then
        [[ -d "$SOURCE_DIR/host/bmi30_split_bundles/$bundle_id" ]] \
            || fail "Release bundle не установлен в проект: $bundle_id"
        [[ -x "$switcher" ]] || fail "Переключатель полного runtime не найден: $switcher"
        [[ -f "$release_manifest" ]] || fail "Release manifest не найден перед активацией: $release_manifest"
        log "Активирую полный runtime bundle из облачного release: $bundle_id"
        if ! BMI30_ACTIVATE_PRESERVE_CONFIG=1 \
            BMI30_RELEASE_MANIFEST_OVERRIDE="$release_manifest" \
            BMI30_PREVIOUS_ACTIVE_ENV_OVERRIDE="$PREVIOUS_ACTIVE_ENV_BACKUP" \
            BMI30_SPLIT_SELECTED_BY_OVERRIDE=cloud-update \
            "$switcher" --activate "$bundle_id"
        then
            fail "Не удалось активировать полный runtime bundle: $bundle_id"
        fi
        verify_active_release_files
        active_runtime_matches_release || fail "Активированный runtime не совпадает с облачным release"
        enforce_cloud_timer_policy
        log "Облачный release активирован и отвечает: $bundle_id"
        return
    fi

    verify_active_release_files

    local portal_src portal_rel
    portal_src="${BMI30_PORTAL_SRC:-}"

    if [[ -f "$active_env" ]]; then
        unset BMI30_PORTAL_PATH
        # shellcheck source=/dev/null
        source "$active_env"
        portal_rel="${BMI30_PORTAL_PATH:-}"
        if [[ -n "$portal_rel" ]]; then
            if [[ "$portal_rel" = /* ]]; then
                portal_src="$portal_rel"
            else
                portal_src="$SOURCE_DIR/$portal_rel"
            fi
        fi
    fi

    if [[ -z "$portal_src" ]]; then
        portal_src="$SOURCE_DIR/hotspot_info_server.py"
    fi

    if [[ -f "$portal_src" ]]; then
        if run_privileged install -p -m 755 "$portal_src" "$BMI30_PORTAL_DST"; then
            log "Portal runtime copy обновлена: $BMI30_PORTAL_DST"
            local portal_src_hash portal_dst_hash
            portal_src_hash="$(sha256sum "$portal_src" | awk '{print $1}')"
            portal_dst_hash="$(sha256sum "$BMI30_PORTAL_DST" 2>/dev/null | awk '{print $1}')"
            [[ -n "$portal_dst_hash" && "${portal_src_hash,,}" == "${portal_dst_hash,,}" ]] \
                || fail "Установленная portal runtime copy не совпадает с release source"
        else
            warn "Не удалось установить portal runtime copy: $portal_src -> $BMI30_PORTAL_DST"
            warn "Проверь sudo/NOPASSWD или запусти: sudo install -m 755 \"$portal_src\" \"$BMI30_PORTAL_DST\""
        fi
    else
        warn "Portal source не найден, runtime copy не обновлена: $portal_src"
    fi

    if command -v systemctl >/dev/null 2>&1; then
        if run_privileged systemctl restart "$BMI30_CORE_SERVICE"; then
            log "Перезапущен сервис: $BMI30_CORE_SERVICE"
        else
            warn "Не удалось перезапустить $BMI30_CORE_SERVICE"
            warn "Проверь sudo/NOPASSWD или запусти: sudo systemctl restart $BMI30_CORE_SERVICE"
        fi

        if run_privileged systemctl restart "$BMI30_PORTAL_SERVICE"; then
            log "Перезапущен сервис: $BMI30_PORTAL_SERVICE"
        else
            warn "Не удалось перезапустить $BMI30_PORTAL_SERVICE"
            warn "Проверь sudo/NOPASSWD или запусти: sudo systemctl restart $BMI30_PORTAL_SERVICE"
        fi
    else
        warn "systemctl недоступен, runtime после обновления не перезапущен"
    fi
}

write_rollback_state() {
    [[ -f "$PREVIOUS_ACTIVE_ENV_BACKUP" ]] || return 0

    local rollback_state="$STATE_DIR/rollback_state.env"
    local previous_bundle_id previous_version previous_label previous_notes previous_created_at
    local bundle_manifest

    unset BMI30_SPLIT_BUNDLE_ID BMI30_SPLIT_VERSION BMI30_SPLIT_LABEL BMI30_BUNDLE_ORIGIN
    # shellcheck source=/dev/null
    source "$PREVIOUS_ACTIVE_ENV_BACKUP"
    previous_bundle_id="${BMI30_SPLIT_BUNDLE_ID:-}"
    [[ "$previous_bundle_id" =~ ^[A-Za-z0-9._-]+$ ]] || {
        warn "Предыдущий bundle ID некорректен; portal rollback не включён"
        return 0
    }
    [[ -d "$SOURCE_DIR/host/bmi30_split_bundles/$previous_bundle_id" ]] || {
        warn "Предыдущий bundle отсутствует; portal rollback не включён: $previous_bundle_id"
        return 0
    }

    previous_version="${BMI30_SPLIT_VERSION:-$previous_bundle_id}"
    previous_label="${BMI30_SPLIT_LABEL:-}"
    previous_notes="${BMI30_BUNDLE_ORIGIN:-}"
    previous_created_at=""

    bundle_manifest="$SOURCE_DIR/host/bmi30_split_bundles/$previous_bundle_id/manifest.env"
    if [[ -f "$bundle_manifest" ]]; then
        unset BMI30_BUNDLE_LABEL BMI30_BUNDLE_ORIGIN BMI30_BUNDLE_CREATED_AT
        # shellcheck source=/dev/null
        source "$bundle_manifest"
        previous_label="${BMI30_BUNDLE_LABEL:-$previous_label}"
        previous_notes="${BMI30_BUNDLE_ORIGIN:-$previous_notes}"
        previous_created_at="${BMI30_BUNDLE_CREATED_AT:-}"
    fi

    if [[ -f "$PREVIOUS_RELEASE_MANIFEST_BACKUP" ]]; then
        unset BMI30_FIRMWARE_VERSION BMI30_FIRMWARE_LABEL BMI30_FIRMWARE_CREATED_AT
        # shellcheck source=/dev/null
        source "$PREVIOUS_RELEASE_MANIFEST_BACKUP"
        previous_version="${BMI30_FIRMWARE_VERSION:-$previous_version}"
        previous_label="${previous_label:-${BMI30_FIRMWARE_LABEL:-}}"
        previous_created_at="${previous_created_at:-${BMI30_FIRMWARE_CREATED_AT:-}}"
    fi

    {
        printf 'ROLLBACK_AVAILABLE=1\n'
        printf 'ROLLBACK_BUNDLE_ID=%q\n' "$previous_bundle_id"
        printf 'ROLLBACK_FIRMWARE_VERSION=%q\n' "$previous_version"
        printf 'ROLLBACK_LABEL=%q\n' "$previous_label"
        printf 'ROLLBACK_NOTES=%q\n' "$previous_notes"
        printf 'ROLLBACK_CREATED_AT=%q\n' "$previous_created_at"
        printf 'ROLLBACK_SAVED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'UPDATED_TO_VERSION=%q\n' "${FIRMWARE_VERSION:-}"
        printf 'UPDATED_TO_BUNDLE_ID=%q\n' "${FIRMWARE_BUNDLE_ID:-}"
        printf 'UPDATED_ARCHIVE_NAME=%q\n' "${ARCHIVE_NAME:-}"
        printf 'UPDATED_ARCHIVE_SHA256=%q\n' "${ARCHIVE_SHA256:-}"
    } > "$rollback_state"
    log "Portal rollback сохранён: $previous_bundle_id"
}

write_update_state() {
    local update_state="$STATE_DIR/update_state.env"
    local publish_state="$STATE_DIR/publish_state.env"
    local local_content_signature
    local_content_signature="$(project_signature)"
    mkdir -p "$STATE_DIR"

    {
        printf 'RELEASE_KIND=%q\n' "${RELEASE_KIND:-firmware}"
        printf 'REMOTE_PROJECT_SIGNATURE=%q\n' "$PROJECT_SIGNATURE"
        printf 'REMOTE_PROJECT_CONTENT_SIGNATURE=%q\n' "${PROJECT_CONTENT_SIGNATURE:-$local_content_signature}"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "${PROJECT_SIGNATURE_VERSION:-legacy}"
        printf 'FIRMWARE_VERSION=%q\n' "${FIRMWARE_VERSION:-}"
        printf 'FIRMWARE_BUNDLE_ID=%q\n' "${FIRMWARE_BUNDLE_ID:-}"
        printf 'ARCHIVE_NAME=%q\n' "$ARCHIVE_NAME"
        printf 'ARCHIVE_SHA256=%q\n' "$ARCHIVE_SHA256"
        printf 'REMOTE_DEVICE_SUFFIX=%q\n' "${DEVICE_SUFFIX:-}"
        printf 'REMOTE_CREATED_AT=%q\n' "${CREATED_AT:-}"
        printf 'UPDATED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$update_state"

    {
        printf 'RELEASE_KIND=%q\n' "${RELEASE_KIND:-firmware}"
        printf 'PROJECT_SIGNATURE=%q\n' "$PROJECT_SIGNATURE"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "${PROJECT_CONTENT_SIGNATURE:-$local_content_signature}"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "${PROJECT_SIGNATURE_VERSION:-legacy}"
        printf 'FIRMWARE_VERSION=%q\n' "${FIRMWARE_VERSION:-}"
        printf 'FIRMWARE_BUNDLE_ID=%q\n' "${FIRMWARE_BUNDLE_ID:-}"
        printf 'ARCHIVE_NAME=%q\n' "$ARCHIVE_NAME"
        printf 'ARCHIVE_SHA256=%q\n' "$ARCHIVE_SHA256"
        printf 'DEVICE_SUFFIX=%q\n' "$(detect_serial_suffix)"
        printf 'PUBLISHED_AT=%q\n' "${CREATED_AT:-}"
    } > "$publish_state"

    write_rollback_state
}

prune_files_by_count() {
    local directory="$1"
    local keep_count="$2"
    shift 2
    [[ -d "$directory" ]] || return 0

    local count=0 file
    while IFS= read -r file; do
        count=$((count + 1))
        if (( count > keep_count )); then
            rm -f -- "$file"
        fi
    done < <(
        find "$directory" -maxdepth 1 -type f \( "$@" \) -printf '%T@ %p\n' \
            | sort -nr \
            | sed -E 's/^[^ ]+ //'
    )
}

cleanup_update_artifacts() {
    prune_files_by_count "$BACKUP_ROOT" "$PRE_UPDATE_RETENTION_COUNT" \
        -name 'pre_update_*.tar.gz'
    prune_files_by_count "$STATE_DIR/incoming" "$INCOMING_RETENTION_COUNT" \
        -name 'bmi30_backup_*.tar.gz' -o -name 'bmi30_firmware_*.tar.gz'
}

main() {
    load_config
    parse_args "$@"

    if [[ "$INSTALL_TIMER" -eq 1 ]]; then
        install_user_timer
        return
    fi

    validate_settings

    local marker_path current_signature archive_path new_signature remote_signature signature_kind
    local previous_archive previous_archive_hash marker_changed
    write_progress 5 "Checking the cloud release marker…"
    marker_path="$(download_latest_marker)"
    load_latest_marker "$marker_path"
    write_progress 12 "Comparing firmware versions and signatures…"

    if [[ "$REQUIRE_TODAY" -eq 1 ]] && ! marker_is_today; then
        local installed_archive=""
        if [[ -f "$STATE_DIR/update_state.env" ]]; then
            installed_archive="$(
                unset ARCHIVE_NAME
                # shellcheck source=/dev/null
                source "$STATE_DIR/update_state.env" 2>/dev/null
                printf '%s' "${ARCHIVE_NAME:-}"
            )"
        fi
        if [[ "$installed_archive" == "$ARCHIVE_NAME" ]]; then
            log "Сегодняшнего облачного архива нет, уже установленный release оставлен без изменений: ${CREATED_AT:-unknown}"
            return
        fi
        log "Обнаружен ещё не установленный облачный release; продолжаю обновление независимо от даты публикации"
    fi

    if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
        remote_signature="$PROJECT_CONTENT_SIGNATURE"
        current_signature="$(project_signature)"
        signature_kind="содержимого проекта"
    else
        remote_signature="$PROJECT_SIGNATURE"
        current_signature="$(legacy_project_signature)"
        signature_kind="legacy"
    fi

    if [[ "$FORCE_UPDATE" -eq 0 && "${current_signature,,}" == "${remote_signature,,}" ]]; then
        log "Проект уже соответствует последнему облачному архиву: $ARCHIVE_NAME"
        previous_archive=""
        previous_archive_hash=""
        if [[ -f "$STATE_DIR/update_state.env" ]]; then
            previous_archive="$(unset ARCHIVE_NAME; source "$STATE_DIR/update_state.env" 2>/dev/null; printf '%s' "${ARCHIVE_NAME:-}")"
            previous_archive_hash="$(unset ARCHIVE_SHA256; source "$STATE_DIR/update_state.env" 2>/dev/null; printf '%s' "${ARCHIVE_SHA256:-}")"
        fi
        marker_changed=0
        if [[ "$previous_archive" != "$ARCHIVE_NAME" || "${previous_archive_hash,,}" != "${ARCHIVE_SHA256,,}" ]]; then
            marker_changed=1
        fi
        if [[ "$marker_changed" -eq 1 ]]; then
            log "Указатель облачного архива изменился при той же подписи; применяю новый release manifest"
            write_progress 35 "Downloading the firmware archive…"
            archive_path="$(download_archive)"
            write_progress 60 "Applying the verified firmware archive…"
            apply_archive "$archive_path"
            if [[ "$DRY_RUN" -eq 1 ]]; then
                return
            fi
            if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
                new_signature="$(project_signature)"
            else
                new_signature="$(legacy_project_signature)"
            fi
            [[ "${new_signature,,}" == "${remote_signature,,}" ]] \
                || fail "После применения release manifest изменилась подпись проекта"
            write_progress 80 "Activating the new firmware runtime…"
            restart_runtime_after_update
            write_progress 96 "Saving update and rollback state…"
            write_update_state
        else
            if [[ "$RESTART_AFTER_UPDATE" == "1" ]] && ! active_runtime_matches_release; then
                log "Проект обновлён, но active runtime не соответствует release; выполняю активацию"
                write_progress 80 "Activating the new firmware runtime…"
                restart_runtime_after_update
            fi
            write_progress 96 "Saving update state…"
            write_update_state
        fi
        cleanup_update_artifacts
        return
    fi

    write_progress 20 "Saving the current firmware for rollback…"
    create_pre_update_snapshot
    write_progress 35 "Downloading the firmware archive…"
    archive_path="$(download_archive)"
    write_progress 60 "Applying the verified firmware archive…"
    apply_archive "$archive_path"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Проверка итоговой подписи пропущена, потому что файлы не изменялись"
        return
    fi

    if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
        new_signature="$(project_signature)"
    else
        new_signature="$(legacy_project_signature)"
    fi
    if [[ "${new_signature,,}" != "${remote_signature,,}" ]]; then
        warn "После обновления подпись проекта отличается от облачной ($signature_kind)"
        warn "Локальная: $new_signature"
        warn "Облачная:  $remote_signature"
        return 5
    fi

    write_progress 80 "Activating the new firmware runtime…"
    restart_runtime_after_update
    write_progress 96 "Saving update and rollback state…"
    write_update_state
    cleanup_update_artifacts
    log "Готово"
}

main "$@"
