#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$WORKSPACE_DIR}"
BACKUP_ROOT="${BACKUP_ROOT:-$WORKSPACE_DIR/backups}"
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_FOLDER_ID="${REMOTE_FOLDER_ID:-}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-30}"
LOCAL_ARCHIVE_RETENTION_COUNT="${LOCAL_ARCHIVE_RETENTION_COUNT:-5}"
PRUNE_REMOTE_ARCHIVES="${PRUNE_REMOTE_ARCHIVES:-0}"
REMOTE_LATEST_FILE="${REMOTE_LATEST_FILE:-bmi30_latest.env}"
ARCHIVE_PREFIX="${ARCHIVE_PREFIX:-bmi30_backup}"
ALLOW_AUTO_PUBLISH="${ALLOW_AUTO_PUBLISH:-0}"
CLOUD_RCLONE_DRIVE_CHUNK_SIZE="${CLOUD_RCLONE_DRIVE_CHUNK_SIZE:-64M}"
CLOUD_RCLONE_TPS_LIMIT="${CLOUD_RCLONE_TPS_LIMIT:-2}"
CLOUD_RCLONE_STATS_INTERVAL="${CLOUD_RCLONE_STATS_INTERVAL:-10s}"
CLOUD_RCLONE_TIMEOUT_SECONDS="${CLOUD_RCLONE_TIMEOUT_SECONDS:-480}"
STATE_DIR="${STATE_DIR:-$WORKSPACE_DIR/.bmi30_cloud_sync}"
PUBLISH_ON_CALENDAR="${PUBLISH_ON_CALENDAR:-*-*-* 22:00:00}"
ON_CALENDAR="${ON_CALENDAR:-}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/backup_to_cloud.conf}"
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
LOCAL_ONLY=0
UPLOAD_IF_CHANGED=0
RELEASE_BUILD_ID=""
RELEASE_ARCHIVE_TIMESTAMP=""
RELEASE_CREATED_AT=""
RELEASE_BUNDLE_ID=""
REQUIRED_RELEASE_DOCS=(
    "host/README_VENDOR_HOST.md"
    "host/HOST_RPI.md"
)

usage() {
    cat <<'EOF'
Usage:
  ./utilities/backup_to_cloud.sh [options]

Options:
  --source <path>            Firmware project directory to archive (default: repo root)
  --output-dir <path>        Local release archive directory (default: ./backups)
  --remote <rclone-remote>   Upload target, for example: gdrive:
  --remote-folder-id <id>    Google Drive folder ID
  --drive-link <url>         Extract Google Drive folder ID from a folder URL
  --retain-days <n>          Keep local archives for N days (default: 30)
  --install-timer            Install a per-user systemd publish timer
  --on-calendar <expr>       Timer schedule (default: *-*-* 22:00:00)
  --config <path>            Config file (default: ./utilities/backup_to_cloud.conf)
  --local-only               Create local firmware release and skip cloud upload
  --if-changed               Publish only if changed; requires ALLOW_AUTO_PUBLISH=1
  --allow-auto-publish       Permit --if-changed auto publish for an approved release device
  --force                    Create/upload even when --if-changed would skip
  --dry-run                  Show actions without creating/uploading archives
  -h, --help                 Show this help

Examples:
  ./utilities/backup_to_cloud.sh --local-only
  ./utilities/backup_to_cloud.sh --remote gdrive: --drive-link "https://drive.google.com/drive/folders/1ABC..."
  ./utilities/backup_to_cloud.sh --force
  ./utilities/backup_to_cloud.sh --install-timer
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

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
    fi
    ON_CALENDAR="${ON_CALENDAR:-$PUBLISH_ON_CALENDAR}"
}

require_value() {
    local opt="$1"
    local val="${2:-}"
    [[ -n "$val" ]] || fail "После $opt нужен аргумент"
}

extract_drive_folder_id() {
    local input="$1"
    local id=""

    if [[ "$input" =~ /folders/([A-Za-z0-9_-]+) ]]; then
        id="${BASH_REMATCH[1]}"
    elif [[ "$input" =~ ([?]|[&])id=([A-Za-z0-9_-]+) ]]; then
        id="${BASH_REMATCH[2]}"
    fi

    printf '%s' "$id"
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

build_archive_name() {
    local timestamp prefix
    timestamp="${RELEASE_ARCHIVE_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}"
    # Keep the legacy prefix: old deployed updaters reject other archive names.
    # The marker/manifest still identifies this as a full firmware release.
    prefix="$(printf '%s' "${ARCHIVE_PREFIX:-bmi30_backup}" | tr -cd 'A-Za-z0-9_-')"
    [[ -z "$prefix" ]] && prefix="bmi30_backup"
    printf '%s_%s.tar.gz' "$prefix" "$timestamp"
}

validate_settings() {
    [[ -d "$SOURCE_DIR" ]] || fail "SOURCE_DIR не найден: $SOURCE_DIR"
    command -v rsync >/dev/null 2>&1 || fail "rsync не установлен"
    [[ "$LOCAL_RETENTION_DAYS" =~ ^[0-9]+$ ]] || fail "LOCAL_RETENTION_DAYS должен быть целым числом"
    [[ "$LOCAL_ARCHIVE_RETENTION_COUNT" =~ ^[0-9]+$ ]] || fail "LOCAL_ARCHIVE_RETENTION_COUNT должен быть целым числом"
    [[ "$CLOUD_RCLONE_TPS_LIMIT" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "CLOUD_RCLONE_TPS_LIMIT должен быть числом"
    [[ "$CLOUD_RCLONE_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || fail "CLOUD_RCLONE_TIMEOUT_SECONDS должен быть положительным целым числом"
}

add_rclone_upload_limits() {
    local array_name="$1"
    local -n _cmd="$array_name"

    _cmd+=(
        --drive-chunk-size "$CLOUD_RCLONE_DRIVE_CHUNK_SIZE"
        --tpslimit "$CLOUD_RCLONE_TPS_LIMIT"
        --tpslimit-burst 1
        --low-level-retries 5
        --retries 2
        --retries-sleep 30s
        --contimeout 15s
        --timeout 2m
        --stats "$CLOUD_RCLONE_STATS_INTERVAL"
        --stats-one-line
        --stats-log-level NOTICE
    )
}

run_bounded_cloud_copy() {
    local label="$1"
    local bytes="$2"
    shift 2

    local rc=0
    bmi30_run_timed_copy "$label" "$bytes" \
        timeout --foreground --signal=INT --kill-after=15s \
        "${CLOUD_RCLONE_TIMEOUT_SECONDS}s" "$@" || rc=$?

    if (( rc == 124 )); then
        warn "$label остановлена после ${CLOUD_RCLONE_TIMEOUT_SECONDS}с: проверь квоту Google Drive и повтори публикацию"
    fi
    return "$rc"
}

validate_active_release_bundle() {
    local switcher="$SOURCE_DIR/switch_bmi30_split_versions.sh"
    RELEASE_BUNDLE_ID="$(bmi30_active_bundle_id "$(cd -- "$SOURCE_DIR" && pwd)" || true)"
    [[ -n "$RELEASE_BUNDLE_ID" ]] || fail "Active env не содержит корректный BMI30_SPLIT_BUNDLE_ID"
    [[ -x "$switcher" ]] || fail "Переключатель полного runtime не найден: $switcher"
    "$switcher" --validate "$RELEASE_BUNDLE_ID" \
        || fail "Активный полный bundle не прошёл проверку: $RELEASE_BUNDLE_ID"
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

project_signature() {
    bmi30_project_signature "$SOURCE_DIR"
}

legacy_project_signature() {
    bmi30_legacy_project_signature "$SOURCE_DIR"
}

project_changed_today() {
    bmi30_project_changed_today "$SOURCE_DIR"
}

release_file_hash() {
    local rel="${1:-}"
    local path
    [[ -n "$rel" ]] || return 0
    if [[ "$rel" = /* ]]; then
        path="$rel"
    else
        path="$SOURCE_DIR/$rel"
    fi
    [[ -f "$path" ]] && sha256sum "$path" | awk '{print $1}'
}

prepare_release_manifest() {
    local content_signature="$1"
    local active_env="$SOURCE_DIR/host/bmi30_split_active_version.env"
    local manifest="$SOURCE_DIR/host/bmi30_firmware_release.env"
    local core_rel gui_rel portal_rel engine_rel core_path engine_name label required_doc

    [[ -f "$active_env" ]] || fail "Не найден active websplit env: $active_env"
    for required_doc in "${REQUIRED_RELEASE_DOCS[@]}"; do
        [[ -f "$SOURCE_DIR/$required_doc" ]] || fail "Обязательная документация не найдена: $required_doc"
    done
    unset BMI30_SPLIT_BUNDLE_ID BMI30_CORE_PATH BMI30_GUI_PATH BMI30_PORTAL_PATH BMI30_ENGINE_SOURCE
    # shellcheck source=/dev/null
    source "$active_env"
    [[ "${BMI30_SPLIT_BUNDLE_ID:-}" == "$RELEASE_BUNDLE_ID" ]] \
        || fail "Active bundle изменился во время подготовки release"
    core_rel="${BMI30_CORE_PATH:-}"
    gui_rel="${BMI30_GUI_PATH:-}"
    portal_rel="${BMI30_PORTAL_PATH:-}"
    engine_rel="${BMI30_ENGINE_SOURCE:-}"

    if [[ -z "$engine_rel" && -n "$core_rel" ]]; then
        if [[ "$core_rel" = /* ]]; then
            core_path="$core_rel"
        else
            core_path="$SOURCE_DIR/$core_rel"
        fi
        if [[ -f "$core_path" ]]; then
            engine_name="$(sed -n -E "s/^[[:space:]]*DEFAULT_ENGINE_FILE[[:space:]]*=.*[\"']([^\"']+)[\"'].*/\1/p" "$core_path" | sed -n '1p')"
            if [[ "$engine_name" == */* ]]; then
                engine_rel="$engine_name"
            elif [[ -n "$engine_name" ]]; then
                engine_rel="host/$engine_name"
            fi
        fi
    fi

    RELEASE_BUILD_ID="$(date +%Y-%m-%d-%H%M%S)"
    RELEASE_ARCHIVE_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    RELEASE_CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    label="$(date '+%Y-%m-%d %H:%M:%S %Z')"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Создал бы release manifest: $manifest ($RELEASE_BUILD_ID)"
        return
    fi

    {
        printf '# Auto-generated by utilities/backup_to_cloud.sh\n'
        printf 'BMI30_FIRMWARE_VERSION=%q\n' "$RELEASE_BUILD_ID"
        printf 'BMI30_FIRMWARE_LABEL=%q\n' "$label"
        printf 'BMI30_FIRMWARE_CREATED_AT=%q\n' "$RELEASE_CREATED_AT"
        printf 'BMI30_FIRMWARE_CONTENT_SIGNATURE=%q\n' "$content_signature"
        printf 'BMI30_FIRMWARE_SIGNATURE_VERSION=%q\n' "$BMI30_PROJECT_SIGNATURE_VERSION"
        printf 'BMI30_FIRMWARE_BUNDLE_ID=%q\n' "$RELEASE_BUNDLE_ID"
        printf 'BMI30_FIRMWARE_CORE_PATH=%q\n' "$core_rel"
        printf 'BMI30_FIRMWARE_CORE_SHA256=%q\n' "$(release_file_hash "$core_rel")"
        printf 'BMI30_FIRMWARE_ENGINE_PATH=%q\n' "$engine_rel"
        printf 'BMI30_FIRMWARE_ENGINE_SHA256=%q\n' "$(release_file_hash "$engine_rel")"
        printf 'BMI30_FIRMWARE_GUI_PATH=%q\n' "$gui_rel"
        printf 'BMI30_FIRMWARE_GUI_SHA256=%q\n' "$(release_file_hash "$gui_rel")"
        printf 'BMI30_FIRMWARE_PORTAL_PATH=%q\n' "$portal_rel"
        printf 'BMI30_FIRMWARE_PORTAL_SHA256=%q\n' "$(release_file_hash "$portal_rel")"
        printf 'BMI30_FIRMWARE_VENDOR_DOC_PATH=%q\n' "${REQUIRED_RELEASE_DOCS[0]}"
        printf 'BMI30_FIRMWARE_VENDOR_DOC_SHA256=%q\n' "$(release_file_hash "${REQUIRED_RELEASE_DOCS[0]}")"
        printf 'BMI30_FIRMWARE_HOST_DOC_PATH=%q\n' "${REQUIRED_RELEASE_DOCS[1]}"
        printf 'BMI30_FIRMWARE_HOST_DOC_SHA256=%q\n' "$(release_file_hash "${REQUIRED_RELEASE_DOCS[1]}")"
    } > "$manifest"
    log "Release manifest создан: $RELEASE_BUILD_ID"
}

read_known_signature() {
    local state_file

    for state_file in "$STATE_DIR/publish_state.env" "$STATE_DIR/update_state.env"; do
        [[ -f "$state_file" ]] || continue
        unset PROJECT_SIGNATURE REMOTE_PROJECT_SIGNATURE PROJECT_CONTENT_SIGNATURE REMOTE_PROJECT_CONTENT_SIGNATURE
        # shellcheck source=/dev/null
        source "$state_file"

        if [[ -n "${PROJECT_CONTENT_SIGNATURE:-}" ]]; then
            printf '%s' "$PROJECT_CONTENT_SIGNATURE"
            return
        fi
        if [[ -n "${REMOTE_PROJECT_CONTENT_SIGNATURE:-}" ]]; then
            printf '%s' "$REMOTE_PROJECT_CONTENT_SIGNATURE"
            return
        fi
    done
}

write_publish_state() {
    local archive_path="$1"
    local content_signature="$2"
    local legacy_signature="$3"
    local archive_hash="$4"
    local state_file="$STATE_DIR/publish_state.env"

    mkdir -p "$STATE_DIR"
    {
        printf 'RELEASE_KIND=%q\n' "firmware"
        printf 'PROJECT_SIGNATURE=%q\n' "$legacy_signature"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "$content_signature"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "$BMI30_PROJECT_SIGNATURE_VERSION"
        printf 'ARCHIVE_NAME=%q\n' "$(basename -- "$archive_path")"
        printf 'ARCHIVE_SHA256=%q\n' "$archive_hash"
        printf 'DEVICE_SUFFIX=%q\n' "$(detect_serial_suffix)"
        printf 'FIRMWARE_VERSION=%q\n' "${RELEASE_BUILD_ID:-}"
        printf 'PUBLISHED_AT=%q\n' "${RELEASE_CREATED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
    } > "$state_file"
}

install_user_timer() {
    local unit_dir service_file timer_file script_path config_abs
    unit_dir="$HOME/.config/systemd/user"
    service_file="$unit_dir/bmi30-cloud-backup.service"
    timer_file="$unit_dir/bmi30-cloud-backup.timer"
    script_path="$SCRIPT_DIR/backup_to_cloud.sh"
    config_abs="$CONFIG_FILE"

    if [[ "$config_abs" != /* ]]; then
        config_abs="$(cd -- "$(dirname -- "$config_abs")" && pwd)/$(basename -- "$config_abs")"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Сгенерировал бы unit-файлы: $service_file и $timer_file"
        log "[dry-run] Service: ExecStart=$script_path --if-changed, CONFIG_FILE=$config_abs"
        log "[dry-run] Timer: OnCalendar=$ON_CALENDAR"
        return
    fi

    mkdir -p "$unit_dir"

    cat > "$service_file" <<EOF
[Unit]
Description=BMI30 cloud firmware publish

[Service]
Type=oneshot
WorkingDirectory=$WORKSPACE_DIR
Environment=CONFIG_FILE=$config_abs
Environment=ALLOW_AUTO_PUBLISH=1
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$script_path --if-changed
EOF

    cat > "$timer_file" <<EOF
[Unit]
Description=Publish BMI30 firmware release automatically

[Timer]
OnCalendar=$ON_CALENDAR
Persistent=true

[Install]
WantedBy=timers.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now bmi30-cloud-backup.timer

    log "Таймер публикации установлен: bmi30-cloud-backup.timer"
    log "Проверить: systemctl --user status bmi30-cloud-backup.timer"
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
            --drive-link)
                require_value "$1" "${2:-}"
                REMOTE_FOLDER_ID="$(extract_drive_folder_id "$2")"
                [[ -n "$REMOTE_FOLDER_ID" ]] || fail "Не удалось извлечь Folder ID из ссылки: $2"
                shift 2
                ;;
            --retain-days)
                require_value "$1" "${2:-}"
                LOCAL_RETENTION_DAYS="$2"
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
            --local-only)
                LOCAL_ONLY=1
                shift
                ;;
            --if-changed)
                UPLOAD_IF_CHANGED=1
                shift
                ;;
            --allow-auto-publish)
                ALLOW_AUTO_PUBLISH=1
                shift
                ;;
            --auto-publish)
                warn "--auto-publish больше не используется: прошивку надо публиковать осознанно одной release-командой"
                shift
                ;;
            --force)
                UPLOAD_IF_CHANGED=0
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

create_archive() {
    local source_abs source_name backup_abs archive_name archive_path stage_dir
    source_abs="$(cd -- "$SOURCE_DIR" && pwd)"
    source_name="$(basename -- "$source_abs")"

    mkdir -p "$BACKUP_ROOT"
    backup_abs="$(cd -- "$BACKUP_ROOT" && pwd)"

    archive_name="$(build_archive_name)"
    archive_path="$backup_abs/$archive_name"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Создал бы архив: $archive_path"
        log "[dry-run] Включил бы активный полный bundle: $RELEASE_BUNDLE_ID"
    else
        local start_ts end_ts elapsed_s archive_bytes
        local -a rsync_args
        stage_dir="$(mktemp -d /tmp/bmi30-firmware-release.XXXXXX)"
        trap 'rm -rf -- "${stage_dir:-}"' RETURN
        mkdir -p "$stage_dir/$source_name"

        rsync_args=(-a --delete)
        bmi30_add_project_rsync_excludes rsync_args "$RELEASE_BUNDLE_ID"
        rsync_args+=("$source_abs/" "$stage_dir/$source_name/")

        start_ts="$(date +%s)"
        rsync "${rsync_args[@]}"
        tar -czf "$archive_path" -C "$stage_dir" "$source_name"
        end_ts="$(date +%s)"
        elapsed_s=$((end_ts - start_ts))
        archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
        log "Архив создан: $archive_path"
        du -h "$archive_path" | awk '{print "[INFO] Размер архива:", $1}' >&2
        bmi30_log_copy_result "Создание архива" "$archive_bytes" "$elapsed_s"
    fi

    printf '%s' "$archive_path"
}

verify_required_release_docs_in_archive() {
    local archive_path="$1"
    local source_name required_doc
    source_name="$(basename -- "$(cd -- "$SOURCE_DIR" && pwd)")"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Проверил бы обязательную документацию в архиве"
        return
    fi

    for required_doc in "${REQUIRED_RELEASE_DOCS[@]}"; do
        tar -tzf "$archive_path" "$source_name/$required_doc" >/dev/null \
            || fail "Обязательная документация не попала в архив: $required_doc"
    done
    tar -tzf "$archive_path" \
        "$source_name/host/bmi30_split_bundles/$RELEASE_BUNDLE_ID/manifest.env" >/dev/null \
        || fail "Активный bundle не попал в firmware-архив: $RELEASE_BUNDLE_ID"
    tar -tzf "$archive_path" \
        "$source_name/host/bmi30_split_bundles/$RELEASE_BUNDLE_ID/SHA256SUMS" >/dev/null \
        || fail "SHA256SUMS активного bundle не попал в firmware-архив: $RELEASE_BUNDLE_ID"
    log "Обязательная документация проверена в архиве: ${REQUIRED_RELEASE_DOCS[*]}"
    log "Активный полный bundle проверен в архиве: $RELEASE_BUNDLE_ID"
}

upload_archive() {
    local archive_path="$1"
    local content_signature="${2:-}"
    local legacy_signature="${3:-}"

    if [[ "$LOCAL_ONLY" -eq 1 ]]; then
        log "Локальный режим: выгрузка в облако пропущена"
        return
    fi

    if [[ -z "$REMOTE_TARGET" ]]; then
        log "REMOTE_TARGET не задан, выгрузка в облако пропущена"
        return
    fi

    if ! command -v rclone >/dev/null 2>&1; then
        warn "rclone не установлен, облачная выгрузка не выполнена"
        warn "Локальный архив сохранён: $archive_path"
        return 2
    fi

    [[ -n "$content_signature" ]] || content_signature="$(project_signature)"
    [[ -n "$legacy_signature" ]] || legacy_signature="$(legacy_project_signature)"

    local archive_name archive_hash created_at device_suffix marker_path remote_archive remote_marker
    local archive_bytes marker_bytes
    archive_name="$(basename -- "$archive_path")"
    created_at="${RELEASE_CREATED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
    device_suffix="$(detect_serial_suffix)"
    marker_path="$STATE_DIR/$REMOTE_LATEST_FILE"
    remote_archive="$(remote_join "$REMOTE_TARGET" "$archive_name")"
    remote_marker="$(remote_join "$REMOTE_TARGET" "$REMOTE_LATEST_FILE")"

    local -a cmd
    cmd=(rclone copyto "$archive_path" "$remote_archive")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi
    add_rclone_upload_limits cmd

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Выгрузил бы архив в облако"
        printf '%q ' "${cmd[@]}"
        printf '\n'
        log "[dry-run] Обновил бы указатель последнего архива: $remote_marker"
        return
    fi

    archive_hash="$(sha256sum "$archive_path" | awk '{print $1}')"

    archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
    if ! run_bounded_cloud_copy "Выгрузка архива в облако" "$archive_bytes" "${cmd[@]}"; then
        return 3
    fi

    mkdir -p "$STATE_DIR"
    {
        printf 'RELEASE_KIND=%q\n' "firmware"
        printf 'ARCHIVE_NAME=%q\n' "$archive_name"
        printf 'ARCHIVE_SHA256=%q\n' "$archive_hash"
        printf 'PROJECT_SIGNATURE=%q\n' "$legacy_signature"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "$content_signature"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "$BMI30_PROJECT_SIGNATURE_VERSION"
        printf 'FIRMWARE_VERSION=%q\n' "${RELEASE_BUILD_ID:-}"
        printf 'FIRMWARE_BUNDLE_ID=%q\n' "$RELEASE_BUNDLE_ID"
        printf 'DEVICE_SUFFIX=%q\n' "$device_suffix"
        printf 'CREATED_AT=%q\n' "$created_at"
        printf 'SOURCE_BASENAME=%q\n' "$(basename -- "$(cd -- "$SOURCE_DIR" && pwd)")"
    } > "$marker_path"

    local -a marker_cmd
    marker_cmd=(rclone copyto "$marker_path" "$remote_marker")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        marker_cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi
    add_rclone_upload_limits marker_cmd

    marker_bytes="$(bmi30_file_size_bytes "$marker_path")"
    if ! run_bounded_cloud_copy "Выгрузка указателя в облако" "$marker_bytes" "${marker_cmd[@]}"; then
        return 4
    fi

    write_publish_state "$archive_path" "$content_signature" "$legacy_signature" "$archive_hash"
    log "Архив выгружен в облако: $REMOTE_TARGET"
    log "Указатель последнего архива обновлён: $REMOTE_LATEST_FILE"

    prune_remote_archives "$archive_name"
}

prune_remote_archives() {
    local keep_name="$1"

    [[ "${PRUNE_REMOTE_ARCHIVES:-1}" == "1" ]] || return 0
    [[ -n "$REMOTE_TARGET" ]] || return 0
    [[ -n "$keep_name" ]] || return 0

    if ! command -v rclone >/dev/null 2>&1; then
        warn "rclone не установлен, очистка старых облачных архивов пропущена"
        return 0
    fi

    local -a lsf_cmd
    lsf_cmd=(rclone lsf "$REMOTE_TARGET" --include 'bmi30_backup_*.tar.gz' --include 'bmi30_firmware_*.tar.gz')
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        lsf_cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    local remote_list
    if ! remote_list="$("${lsf_cmd[@]}" 2>/dev/null)"; then
        warn "Не удалось получить список облачных архивов для очистки"
        return 0
    fi

    local name deleted=0
    while IFS= read -r name; do
        name="${name%/}"
        [[ -n "$name" ]] || continue
        [[ "$name" == bmi30_backup_*.tar.gz || "$name" == bmi30_firmware_*.tar.gz ]] || continue
        [[ "$name" == "$keep_name" ]] && continue

        if [[ "$DRY_RUN" -eq 1 ]]; then
            log "[dry-run] Удалил бы старый облачный архив: $name"
            continue
        fi

        local -a del_cmd
        del_cmd=(rclone deletefile "$(remote_join "$REMOTE_TARGET" "$name")")
        if [[ -n "$REMOTE_FOLDER_ID" ]]; then
            del_cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
        fi

        if "${del_cmd[@]}"; then
            deleted=$((deleted + 1))
        else
            warn "Не удалось удалить облачный архив: $name"
        fi
    done <<< "$remote_list"

    if [[ "$DRY_RUN" -ne 1 && "$deleted" -gt 0 ]]; then
        log "Очистка облака: удалено старых архивов: $deleted (оставлен только $keep_name)"
    fi
}

cleanup_local_backups() {
    [[ -d "$BACKUP_ROOT" ]] || return 0

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Удалил бы локальные архивы старше $LOCAL_RETENTION_DAYS дней в $BACKUP_ROOT"
        find "$BACKUP_ROOT" -maxdepth 1 -type f \
            \( -name 'bmi30_backup_*.tar.gz' -o -name 'bmi30_firmware_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
            -mtime "+$LOCAL_RETENTION_DAYS" -print
        return
    fi

    find "$BACKUP_ROOT" -maxdepth 1 -type f \
        \( -name 'bmi30_backup_*.tar.gz' -o -name 'bmi30_firmware_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
        -mtime "+$LOCAL_RETENTION_DAYS" -delete

    local count=0 file
    while IFS= read -r file; do
        count=$((count + 1))
        if (( count > LOCAL_ARCHIVE_RETENTION_COUNT )); then
            rm -f -- "$file"
        fi
    done < <(
        find "$BACKUP_ROOT" -maxdepth 1 -type f \
            \( -name 'bmi30_backup_*.tar.gz' -o -name 'bmi30_firmware_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
            -printf '%T@ %p\n' \
            | sort -nr \
            | sed -E 's/^[^ ]+ //'
    )
}

main() {
    load_config
    parse_args "$@"
    validate_settings
    validate_active_release_bundle

    if [[ "$INSTALL_TIMER" -eq 1 ]]; then
        install_user_timer
        return
    fi

    local archive upload_status content_signature legacy_signature last_signature
    content_signature=""
    legacy_signature=""

    if [[ "$UPLOAD_IF_CHANGED" -eq 1 ]]; then
        if [[ "${ALLOW_AUTO_PUBLISH:-0}" != "1" ]]; then
            log "Автопубликация отключена: --if-changed ничего не выгружает без ALLOW_AUTO_PUBLISH=1"
            log "Для осознанного выпуска прошивки используй: ./utilities/backup_to_cloud.sh --force"
            return
        fi

        content_signature="$(project_signature)"
        last_signature="$(read_known_signature)"

        if [[ -n "$last_signature" && "$content_signature" == "$last_signature" ]]; then
            log "Изменений в проекте нет, новый архив не создаётся"
            return
        fi

        if ! project_changed_today; then
            log "Сегодня в проекте нет локальных изменений, новый архив не создаётся"
            return
        fi
    fi

    [[ -n "$content_signature" ]] || content_signature="$(project_signature)"
    legacy_signature="$(legacy_project_signature)"
    prepare_release_manifest "$content_signature"
    archive="$(create_archive)"
    verify_required_release_docs_in_archive "$archive"
    upload_status=0
    upload_archive "$archive" "$content_signature" "$legacy_signature" || upload_status=$?
    cleanup_local_backups

    if [[ "$upload_status" -ne 0 ]]; then
        warn "Firmware release создан локально, но облачная выгрузка завершилась с ошибкой ($upload_status)"
        return "$upload_status"
    fi

    log "Готово"
}

main "$@"
