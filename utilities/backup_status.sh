#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/backup_to_cloud.conf}"
BACKUP_ROOT="${BACKUP_ROOT:-$WORKSPACE_DIR/backups}"
REMOTE_LATEST_FILE="${REMOTE_LATEST_FILE:-bmi30_latest.env}"

PUBLISH_TIMER_NAME="bmi30-cloud-backup.timer"
PUBLISH_SERVICE_NAME="bmi30-cloud-backup.service"
UPDATE_TIMER_NAME="bmi30-cloud-update.timer"
UPDATE_SERVICE_NAME="bmi30-cloud-update.service"

if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

show_timer_status() {
    local label="$1"
    local timer_name="$2"
    local service_name="$3"
    local timer_enabled="no"
    local timer_active="no"
    local next_run="-"
    local last_run="-"

    printf "%s\n" "$label"
    printf "%s\n" "-------------------"

    if ! command -v systemctl >/dev/null 2>&1; then
        printf "systemctl не найден, статус таймера недоступен.\n\n"
        return
    fi

    if ! systemctl --user list-unit-files >/dev/null 2>&1; then
        printf "systemd --user сейчас недоступен в этой сессии.\n\n"
        return
    fi

    if systemctl --user list-unit-files "$timer_name" >/dev/null 2>&1; then
        if systemctl --user is-enabled "$timer_name" >/dev/null 2>&1; then
            timer_enabled="yes"
        fi
        if systemctl --user is-active "$timer_name" >/dev/null 2>&1; then
            timer_active="yes"
        fi

        next_run="$(systemctl --user show "$timer_name" -p NextElapseUSecRealtime --value 2>/dev/null || true)"
        last_run="$(systemctl --user show "$timer_name" -p LastTriggerUSec --value 2>/dev/null || true)"
        [[ -n "$next_run" ]] || next_run="-"
        [[ -n "$last_run" ]] || last_run="-"
    fi

    printf "Timer enabled: %s\n" "$timer_enabled"
    printf "Timer active:  %s\n" "$timer_active"
    printf "Next run:      %s\n" "$next_run"
    printf "Last run:      %s\n" "$last_run"

    if systemctl --user list-unit-files "$service_name" >/dev/null 2>&1; then
        printf "\nПоследние строки сервиса:\n"
        systemctl --user status "$service_name" --no-pager 2>/dev/null | tail -n 10 || true
    else
        printf "\nСервис ещё не установлен.\n"
    fi

    printf "\n"
}

printf "BMI30 Cloud Sync Status\n"
printf "=======================\n\n"
printf "Config:      %s\n" "$CONFIG_FILE"
printf "Mode:        dynamic leader by today's project changes\n"
printf "Backup dir:  %s\n" "$BACKUP_ROOT"
printf "Remote:      %s\n" "${REMOTE_TARGET:-local only}"
printf "Folder ID:   %s\n" "${REMOTE_FOLDER_ID:-not set}"
printf "Marker:      %s\n" "${REMOTE_LATEST_FILE:-bmi30_latest.env}"
printf "\n"

if command -v rclone >/dev/null 2>&1; then
    printf "rclone:      %s\n" "$(rclone version 2>/dev/null | sed -n '1p')"
    if rclone listremotes 2>/dev/null | grep -qx "${REMOTE_TARGET%%:*}:"; then
        printf "Remote cfg:  found\n"
    else
        printf "Remote cfg:  not found for %s\n" "${REMOTE_TARGET%%:*}:"
    fi
else
    printf "rclone:      not installed\n"
fi

printf "\n"

if [[ -d "$BACKUP_ROOT" ]]; then
    printf "Последние локальные архивы:\n"
    find "$BACKUP_ROOT" -maxdepth 1 -type f \
        \( -name 'bmi30_backup_*.tar.gz' -o -name 'pre_update_*.tar.gz' -o -name '20????????_*.tar.gz' \) \
        -printf '%TY-%Tm-%Td %TH:%TM  %9s  %p\n' 2>/dev/null \
        | sort -r \
        | sed -n '1,8p'
else
    printf "Локальных архивов пока нет.\n"
fi

printf "\n"

show_timer_status "Publish timer 22:00" "$PUBLISH_TIMER_NAME" "$PUBLISH_SERVICE_NAME"
show_timer_status "Update timer 23:00" "$UPDATE_TIMER_NAME" "$UPDATE_SERVICE_NAME"
