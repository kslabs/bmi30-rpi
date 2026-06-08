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
COMMON_LIB="$SCRIPT_DIR/cloud_sync_common.sh"

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

usage() {
    cat <<'EOF'
Usage:
  ./utilities/update_from_cloud.sh [options]

Options:
  --source <path>            Directory to update (default: repo root)
  --output-dir <path>        Local archive/snapshot directory (default: ./backups)
  --remote <rclone-remote>   Cloud target, for example: gdrive:
  --remote-folder-id <id>    Google Drive folder ID
  --install-timer            Install a per-user systemd update timer
  --on-calendar <expr>       Timer schedule (default: *-*-* 23:00:00)
  --config <path>            Config file (default: ./utilities/backup_to_cloud.conf)
  --today-only               Update only from an archive published today
  --force                    Apply latest cloud archive even if signatures match
  --dry-run                  Show actions without changing files
  -h, --help                 Show this help

Examples:
  ./utilities/update_from_cloud.sh
  ./utilities/update_from_cloud.sh --install-timer
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
}

install_user_timer() {
    local unit_dir service_file timer_file script_path config_abs
    unit_dir="$HOME/.config/systemd/user"
    service_file="$unit_dir/bmi30-cloud-update.service"
    timer_file="$unit_dir/bmi30-cloud-update.timer"
    script_path="$SCRIPT_DIR/cloud_sync_now.sh"
    config_abs="$CONFIG_FILE"

    if [[ "$config_abs" != /* ]]; then
        config_abs="$(cd -- "$(dirname -- "$config_abs")" && pwd)/$(basename -- "$config_abs")"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Сгенерировал бы unit-файлы: $service_file и $timer_file"
        log "[dry-run] Service: ExecStart=$script_path --today-only, CONFIG_FILE=$config_abs"
        log "[dry-run] Timer: OnCalendar=$ON_CALENDAR"
        return
    fi

    mkdir -p "$unit_dir"

    cat > "$service_file" <<EOF
[Unit]
Description=BMI30 cloud project update

[Service]
Type=oneshot
WorkingDirectory=$WORKSPACE_DIR
Environment=CONFIG_FILE=$config_abs
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$script_path --today-only
EOF

    cat > "$timer_file" <<EOF
[Unit]
Description=Update BMI30 project from latest cloud archive

[Timer]
OnCalendar=$ON_CALENDAR
Persistent=true

[Install]
WantedBy=timers.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now bmi30-cloud-update.timer

    log "Таймер обновления установлен: bmi30-cloud-update.timer"
    log "Проверить: systemctl --user status bmi30-cloud-update.timer"
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

    if ! "${cmd[@]}"; then
        fail "Не удалось скачать указатель последнего архива: $remote_marker"
    fi

    printf '%s' "$marker_path"
}

load_latest_marker() {
    local marker_path="$1"
    unset ARCHIVE_NAME ARCHIVE_SHA256 PROJECT_SIGNATURE PROJECT_CONTENT_SIGNATURE PROJECT_SIGNATURE_VERSION DEVICE_SUFFIX CREATED_AT SOURCE_BASENAME

    [[ -f "$marker_path" ]] || fail "Указатель архива не найден: $marker_path"
    # shellcheck source=/dev/null
    source "$marker_path"

    [[ "${ARCHIVE_NAME:-}" == bmi30_backup_*.tar.gz ]] || fail "Некорректное имя архива в $marker_path"
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
    [[ "$PRE_UPDATE_SNAPSHOT" == "1" ]] || return

    local source_abs source_parent source_name backup_abs archive_path timestamp device_suffix
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
    tar "${tar_args[@]}"

    log "Снимок перед обновлением создан: $archive_path"
}

download_archive() {
    local incoming_dir archive_path remote_archive actual_hash
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

    if ! "${cmd[@]}"; then
        fail "Не удалось скачать архив: $remote_archive"
    fi

    actual_hash="$(sha256sum "$archive_path" | awk '{print $1}')"
    [[ "${actual_hash,,}" == "${ARCHIVE_SHA256,,}" ]] || fail "SHA-256 архива не совпадает: $archive_path"

    log "Архив скачан и проверен: $archive_path"
    printf '%s' "$archive_path"
}

apply_archive() {
    local archive_path="$1"
    local extracted source_name

    APPLY_TEMP_DIR="$(mktemp -d)"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Применил бы архив к проекту: $archive_path -> $SOURCE_DIR"
        return
    fi

    tar -xzf "$archive_path" -C "$APPLY_TEMP_DIR"
    source_name="${SOURCE_BASENAME:-$(basename -- "$(cd -- "$SOURCE_DIR" && pwd)")}"

    if [[ -d "$APPLY_TEMP_DIR/$source_name" ]]; then
        extracted="$APPLY_TEMP_DIR/$source_name"
    else
        extracted="$(find "$APPLY_TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | sed -n '1p')"
    fi

    [[ -n "$extracted" && -d "$extracted" ]] || fail "Не удалось найти корень проекта в архиве"

    local -a rsync_args
    rsync_args=(-a --delete)
    bmi30_add_project_rsync_excludes rsync_args
    rsync_args+=("$extracted/" "$SOURCE_DIR/")
    rsync "${rsync_args[@]}"

    log "Проект обновлён из облачного архива: $ARCHIVE_NAME"
}

write_update_state() {
    local update_state="$STATE_DIR/update_state.env"
    local publish_state="$STATE_DIR/publish_state.env"
    local local_content_signature
    local_content_signature="$(project_signature)"
    mkdir -p "$STATE_DIR"

    {
        printf 'REMOTE_PROJECT_SIGNATURE=%q\n' "$PROJECT_SIGNATURE"
        printf 'REMOTE_PROJECT_CONTENT_SIGNATURE=%q\n' "${PROJECT_CONTENT_SIGNATURE:-$local_content_signature}"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "${PROJECT_SIGNATURE_VERSION:-legacy}"
        printf 'ARCHIVE_NAME=%q\n' "$ARCHIVE_NAME"
        printf 'ARCHIVE_SHA256=%q\n' "$ARCHIVE_SHA256"
        printf 'REMOTE_DEVICE_SUFFIX=%q\n' "${DEVICE_SUFFIX:-}"
        printf 'REMOTE_CREATED_AT=%q\n' "${CREATED_AT:-}"
        printf 'UPDATED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$update_state"

    {
        printf 'PROJECT_SIGNATURE=%q\n' "$PROJECT_SIGNATURE"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "${PROJECT_CONTENT_SIGNATURE:-$local_content_signature}"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "${PROJECT_SIGNATURE_VERSION:-legacy}"
        printf 'ARCHIVE_NAME=%q\n' "$ARCHIVE_NAME"
        printf 'ARCHIVE_SHA256=%q\n' "$ARCHIVE_SHA256"
        printf 'DEVICE_SUFFIX=%q\n' "$(detect_serial_suffix)"
        printf 'PUBLISHED_AT=%q\n' "${CREATED_AT:-}"
    } > "$publish_state"
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
    marker_path="$(download_latest_marker)"
    load_latest_marker "$marker_path"

    if [[ "$REQUIRE_TODAY" -eq 1 ]] && ! marker_is_today; then
        log "Сегодняшнего облачного архива нет, обновление пропущено: ${CREATED_AT:-unknown}"
        return
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
        write_update_state
        return
    fi

    create_pre_update_snapshot
    archive_path="$(download_archive)"
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

    write_update_state
    log "Готово"
}

main "$@"
