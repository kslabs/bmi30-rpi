#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$WORKSPACE_DIR}"
BACKUP_ROOT="${BACKUP_ROOT:-$WORKSPACE_DIR/backups}"
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_FOLDER_ID="${REMOTE_FOLDER_ID:-}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-30}"
REMOTE_LATEST_FILE="${REMOTE_LATEST_FILE:-bmi30_latest.env}"
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

usage() {
    cat <<'EOF'
Usage:
  ./utilities/backup_to_cloud.sh [options]

Options:
  --source <path>            Directory to archive (default: repo root)
  --output-dir <path>        Local archive directory (default: ./backups)
  --remote <rclone-remote>   Upload target, for example: gdrive:
  --remote-folder-id <id>    Google Drive folder ID
  --drive-link <url>         Extract Google Drive folder ID from a folder URL
  --retain-days <n>          Keep local archives for N days (default: 30)
  --install-timer            Install a per-user systemd publish timer
  --on-calendar <expr>       Timer schedule (default: *-*-* 22:00:00)
  --config <path>            Config file (default: ./utilities/backup_to_cloud.conf)
  --local-only               Create local archive and skip cloud upload
  --if-changed               Skip archive/upload when project did not change today
  --force                    Create/upload even when --if-changed would skip
  --dry-run                  Show actions without creating/uploading archives
  -h, --help                 Show this help

Examples:
  ./utilities/backup_to_cloud.sh --local-only
  ./utilities/backup_to_cloud.sh --remote gdrive: --drive-link "https://drive.google.com/drive/folders/1ABC..."
  ./utilities/backup_to_cloud.sh --if-changed
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
    local timestamp device_suffix
    timestamp="$(date +%Y%m%d_%H%M%S)"
    device_suffix="$(detect_serial_suffix)"
    device_suffix="$(printf '%s' "$device_suffix" | tr -cd 'A-Za-z0-9_-')"
    device_suffix="${device_suffix^^}"
    [[ -z "$device_suffix" ]] && device_suffix="UNKNOWN"
    printf 'bmi30_backup_%s_%s.tar.gz' "$timestamp" "$device_suffix"
}

validate_settings() {
    [[ -d "$SOURCE_DIR" ]] || fail "SOURCE_DIR не найден: $SOURCE_DIR"
    [[ "$LOCAL_RETENTION_DAYS" =~ ^[0-9]+$ ]] || fail "LOCAL_RETENTION_DAYS должен быть целым числом"
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
        printf 'PROJECT_SIGNATURE=%q\n' "$legacy_signature"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "$content_signature"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "$BMI30_PROJECT_SIGNATURE_VERSION"
        printf 'ARCHIVE_NAME=%q\n' "$(basename -- "$archive_path")"
        printf 'ARCHIVE_SHA256=%q\n' "$archive_hash"
        printf 'DEVICE_SUFFIX=%q\n' "$(detect_serial_suffix)"
        printf 'PUBLISHED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
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
Description=BMI30 cloud backup

[Service]
Type=oneshot
WorkingDirectory=$WORKSPACE_DIR
Environment=CONFIG_FILE=$config_abs
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$script_path --if-changed
EOF

    cat > "$timer_file" <<EOF
[Unit]
Description=Run BMI30 cloud backup automatically

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
            --auto-publish)
                warn "--auto-publish больше не нужен: ведущий определяется по изменениям проекта"
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
    local source_abs source_parent source_name backup_abs archive_name archive_path
    source_abs="$(cd -- "$SOURCE_DIR" && pwd)"
    source_parent="$(dirname -- "$source_abs")"
    source_name="$(basename -- "$source_abs")"

    mkdir -p "$BACKUP_ROOT"
    backup_abs="$(cd -- "$BACKUP_ROOT" && pwd)"

    archive_name="$(build_archive_name)"
    archive_path="$backup_abs/$archive_name"

    local -a tar_args
    tar_args=(
        -czf "$archive_path"
    )
    bmi30_add_project_tar_excludes tar_args "$source_name"
    tar_args+=(
        -C "$source_parent"
        "$source_name"
    )

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Создал бы архив: $archive_path"
        {
            printf 'tar'
            printf ' %q' "${tar_args[@]}"
            printf '\n'
        } >&2
    else
        local start_ts end_ts elapsed_s archive_bytes
        start_ts="$(date +%s)"
        tar "${tar_args[@]}"
        end_ts="$(date +%s)"
        elapsed_s=$((end_ts - start_ts))
        archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
        log "Архив создан: $archive_path"
        du -h "$archive_path" | awk '{print "[INFO] Размер архива:", $1}' >&2
        bmi30_log_copy_result "Создание архива" "$archive_bytes" "$elapsed_s"
    fi

    printf '%s' "$archive_path"
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

    local archive_name archive_hash created_at device_suffix marker_path remote_marker
    local archive_bytes marker_bytes
    archive_name="$(basename -- "$archive_path")"
    created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    device_suffix="$(detect_serial_suffix)"
    marker_path="$STATE_DIR/$REMOTE_LATEST_FILE"
    remote_marker="$(remote_join "$REMOTE_TARGET" "$REMOTE_LATEST_FILE")"

    local -a cmd
    cmd=(rclone copy "$archive_path" "$REMOTE_TARGET")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Выгрузил бы архив в облако"
        printf '%q ' "${cmd[@]}"
        printf '\n'
        log "[dry-run] Обновил бы указатель последнего архива: $remote_marker"
        return
    fi

    archive_hash="$(sha256sum "$archive_path" | awk '{print $1}')"

    archive_bytes="$(bmi30_file_size_bytes "$archive_path")"
    if ! bmi30_run_timed_copy "Выгрузка архива в облако" "$archive_bytes" "${cmd[@]}"; then
        return 3
    fi

    mkdir -p "$STATE_DIR"
    {
        printf 'ARCHIVE_NAME=%q\n' "$archive_name"
        printf 'ARCHIVE_SHA256=%q\n' "$archive_hash"
        printf 'PROJECT_SIGNATURE=%q\n' "$legacy_signature"
        printf 'PROJECT_CONTENT_SIGNATURE=%q\n' "$content_signature"
        printf 'PROJECT_SIGNATURE_VERSION=%q\n' "$BMI30_PROJECT_SIGNATURE_VERSION"
        printf 'DEVICE_SUFFIX=%q\n' "$device_suffix"
        printf 'CREATED_AT=%q\n' "$created_at"
        printf 'SOURCE_BASENAME=%q\n' "$(basename -- "$(cd -- "$SOURCE_DIR" && pwd)")"
    } > "$marker_path"

    local -a marker_cmd
    marker_cmd=(rclone copyto "$marker_path" "$remote_marker")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        marker_cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    marker_bytes="$(bmi30_file_size_bytes "$marker_path")"
    if ! bmi30_run_timed_copy "Выгрузка указателя в облако" "$marker_bytes" "${marker_cmd[@]}"; then
        return 4
    fi

    write_publish_state "$archive_path" "$content_signature" "$legacy_signature" "$archive_hash"
    log "Архив выгружен в облако: $REMOTE_TARGET"
    log "Указатель последнего архива обновлён: $REMOTE_LATEST_FILE"
}

cleanup_local_backups() {
    [[ -d "$BACKUP_ROOT" ]] || return

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Удалил бы локальные архивы старше $LOCAL_RETENTION_DAYS дней в $BACKUP_ROOT"
        find "$BACKUP_ROOT" -maxdepth 1 -type f \
            \( -name 'bmi30_backup_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
            -mtime "+$LOCAL_RETENTION_DAYS" -print
        return
    fi

    find "$BACKUP_ROOT" -maxdepth 1 -type f \
        \( -name 'bmi30_backup_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
        -mtime "+$LOCAL_RETENTION_DAYS" -delete
}

main() {
    load_config
    parse_args "$@"
    validate_settings

    if [[ "$INSTALL_TIMER" -eq 1 ]]; then
        install_user_timer
        return
    fi

    local archive upload_status content_signature legacy_signature last_signature
    content_signature=""
    legacy_signature=""

    if [[ "$UPLOAD_IF_CHANGED" -eq 1 ]]; then
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

    archive="$(create_archive)"
    upload_status=0
    legacy_signature="$(legacy_project_signature)"
    upload_archive "$archive" "$content_signature" "$legacy_signature" || upload_status=$?
    cleanup_local_backups

    if [[ "$upload_status" -ne 0 ]]; then
        warn "Backup создан локально, но облачная выгрузка завершилась с ошибкой ($upload_status)"
        return "$upload_status"
    fi

    log "Готово"
}

main "$@"
