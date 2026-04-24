#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$WORKSPACE_DIR}"
BACKUP_ROOT="${BACKUP_ROOT:-$WORKSPACE_DIR/backups}"
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_FOLDER_ID="${REMOTE_FOLDER_ID:-}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-30}"
ON_CALENDAR="${ON_CALENDAR:-*-*-* 23:00:00}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/backup_to_cloud.conf}"

DRY_RUN=0
INSTALL_TIMER=0

# Optional static config for menu/non-interactive runs.
if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

usage() {
    cat <<'EOF'
Usage:
  ./utilities/backup_to_cloud.sh [options]

Options:
  --source <path>            Что архивировать (default: /home/techaid/Documents)
  --output-dir <path>        Куда складывать архивы локально (default: /home/techaid/Documents/backups)
  --remote <rclone-remote>   Куда выгружать архив (пример: gdrive:)
  --remote-folder-id <id>    Google Drive Folder ID (например из ссылки)
  --drive-link <url>         Ссылка на Google Drive папку, ID извлекается автоматически
  --retain-days <n>          Сколько дней хранить локальные архивы (default: 30)
  --install-timer            Установить systemd --user таймер (ежедневно)
    --on-calendar <expr>       Расписание timer (default: *-*-* 23:00:00)
    --config <path>            Файл конфигурации (default: ./utilities/backup_to_cloud.conf)
  --dry-run                  Только показать действия, не выполнять
  -h, --help                 Показать эту справку

Пример разового запуска:
  ./utilities/backup_to_cloud.sh --remote gdrive: --drive-link "https://drive.google.com/drive/folders/1ABC..."

Пример установки таймера:
  ./utilities/backup_to_cloud.sh --remote gdrive: --drive-link "https://drive.google.com/drive/folders/1ABC..." --install-timer
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

extract_drive_folder_id() {
    local input="$1"
    local id=""

    if [[ "$input" =~ /folders/([A-Za-z0-9_-]+) ]]; then
        id="${BASH_REMATCH[1]}"
    elif [[ "$input" =~ ([?]|[&])id=([A-Za-z0-9_-]+) ]]; then
        id="${BASH_REMATCH[1]}"
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
    # Always use Raspberry Pi serial-derived ID so it reflects the real device.
    device_suffix="$(detect_serial_suffix)"
    device_suffix="$(printf '%s' "$device_suffix" | tr -cd 'A-Za-z0-9_-')"
    device_suffix="${device_suffix^^}"
    [[ -z "$device_suffix" ]] && device_suffix="unknown"
    printf '%s_%s.tar.gz' "$timestamp" "$device_suffix"
}

install_user_timer() {
    local unit_dir service_file timer_file script_path
    unit_dir="$HOME/.config/systemd/user"
    service_file="$unit_dir/bmi30-cloud-backup.service"
    timer_file="$unit_dir/bmi30-cloud-backup.timer"
    script_path="$SCRIPT_DIR/backup_to_cloud.sh"

    mkdir -p "$unit_dir"

    cat > "$service_file" <<EOF
[Unit]
Description=BMI30 cloud backup (single archive)

[Service]
Type=oneshot
Environment=SOURCE_DIR=$SOURCE_DIR
Environment=BACKUP_ROOT=$BACKUP_ROOT
Environment=LOCAL_RETENTION_DAYS=$LOCAL_RETENTION_DAYS
Environment=REMOTE_TARGET=$REMOTE_TARGET
Environment=REMOTE_FOLDER_ID=$REMOTE_FOLDER_ID
ExecStart=$script_path
EOF

    cat > "$timer_file" <<EOF
[Unit]
Description=Run BMI30 cloud backup automatically

[Timer]
OnCalendar=$ON_CALENDAR
Persistent=false

[Install]
WantedBy=timers.target
EOF

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Сгенерированы unit-файлы: $service_file и $timer_file"
        return
    fi

    systemctl --user daemon-reload
    systemctl --user enable --now bmi30-cloud-backup.timer

    log "Таймер установлен: bmi30-cloud-backup.timer"
    log "Проверить: systemctl --user status bmi30-cloud-backup.timer"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source)
                SOURCE_DIR="$2"
                shift 2
                ;;
            --output-dir)
                BACKUP_ROOT="$2"
                shift 2
                ;;
            --remote)
                REMOTE_TARGET="$2"
                shift 2
                ;;
            --remote-folder-id)
                REMOTE_FOLDER_ID="$2"
                shift 2
                ;;
            --drive-link)
                REMOTE_FOLDER_ID="$(extract_drive_folder_id "$2")"
                if [[ -z "$REMOTE_FOLDER_ID" ]]; then
                    fail "Не удалось извлечь Folder ID из ссылки: $2"
                fi
                shift 2
                ;;
            --retain-days)
                LOCAL_RETENTION_DAYS="$2"
                shift 2
                ;;
            --on-calendar)
                ON_CALENDAR="$2"
                shift 2
                ;;
            --config)
                CONFIG_FILE="$2"
                if [[ -f "$CONFIG_FILE" ]]; then
                    # shellcheck source=/dev/null
                    source "$CONFIG_FILE"
                else
                    fail "Файл конфигурации не найден: $CONFIG_FILE"
                fi
                shift 2
                ;;
            --install-timer)
                INSTALL_TIMER=1
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
    local source_abs source_parent source_name archive_name archive_path
    source_abs="$(cd -- "$SOURCE_DIR" && pwd)"
    source_parent="$(dirname -- "$source_abs")"
    source_name="$(basename -- "$source_abs")"

    mkdir -p "$BACKUP_ROOT"
    BACKUP_ROOT="$(cd -- "$BACKUP_ROOT" && pwd)"

    archive_name="$(build_archive_name)"
    archive_path="$BACKUP_ROOT/$archive_name"

    local -a tar_args
    tar_args=(
        -czf "$archive_path"
        --exclude-vcs
        --exclude="$source_name/.git"
        --exclude="$source_name/.venv"
        --exclude="$source_name/.usbvenv"
        --exclude="$source_name/.codex"
        --exclude="$source_name/.pytest_cache"
        --exclude="$source_name/.mypy_cache"
        --exclude="$source_name/__pycache__"
        --exclude="$source_name/backups"
        --exclude="$source_name/*.log"
        --exclude="$source_name/full_mismatch_*"
        -C "$source_parent"
        "$source_name"
    )

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Создал бы архив: $archive_path"
        printf 'tar %q\n' "${tar_args[@]}"
    else
        tar "${tar_args[@]}"
        echo "[INFO] Архив создан: $archive_path" >&2
        du -h "$archive_path" | awk '{print "[INFO] Размер архива:", $1}' >&2
    fi

    [[ "$DRY_RUN" -eq 1 ]] || printf "%s" "$archive_path"
}

upload_archive() {
    local archive_path="$1"

    if [[ -z "$REMOTE_TARGET" ]]; then
        log "REMOTE_TARGET не задан, выгрузка в облако пропущена"
        return
    fi

    if (( DRY_RUN == 0 )); then command -v rclone >/dev/null 2>&1 || fail "Нужен rclone для выгрузки в облако: sudo apt install rclone"; fi
    local -a cmd
    cmd=(rclone copy "$archive_path" "$REMOTE_TARGET")
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Выгрузил бы архив в облако"
        printf '%q ' "${cmd[@]}"
        printf '\n'
        return
    fi

    "${cmd[@]}"
    log "Архив выгружен в облако: $REMOTE_TARGET"
}

cleanup_local_backups() {
    if [[ ! -d "$BACKUP_ROOT" ]]; then
        return
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[dry-run] Очистил бы локальные архивы старше $LOCAL_RETENTION_DAYS дней в $BACKUP_ROOT"
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
    parse_args "$@"

    [[ -d "$SOURCE_DIR" ]] || fail "SOURCE_DIR не найден: $SOURCE_DIR"

    if [[ "$INSTALL_TIMER" -eq 1 ]]; then
        install_user_timer
        return
    fi

    local archive
    archive="$(create_archive)"
    upload_archive "$archive"
    cleanup_local_backups

    echo "[INFO] Готово"
}

main "$@"
