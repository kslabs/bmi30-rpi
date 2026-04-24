#!/usr/bin/env bash
set -euo pipefail

TIMER_NAME="bmi30-cloud-backup.timer"
SERVICE_NAME="bmi30-cloud-backup.service"

printf "BMI30 Backup Status\n"
printf "===================\n\n"

if ! command -v systemctl >/dev/null 2>&1; then
    printf "systemctl не найден.\n"
    exit 1
fi

timer_enabled="no"
timer_active="no"
next_run="-"
last_run="-"

if systemctl --user list-unit-files "$TIMER_NAME" >/dev/null 2>&1; then
    if systemctl --user is-enabled "$TIMER_NAME" >/dev/null 2>&1; then
        timer_enabled="yes"
    fi
    if systemctl --user is-active "$TIMER_NAME" >/dev/null 2>&1; then
        timer_active="yes"
    fi

    while IFS= read -r line; do
        [[ "$line" == NEXT* ]] && continue
        [[ -z "$line" ]] && continue
        next_run="$(awk '{print $1, $2, $3, $4, $5}' <<<"$line")"
        last_run="$(awk '{print $6, $7, $8, $9, $10}' <<<"$line")"
        break
    done < <(systemctl --user list-timers "$TIMER_NAME" --no-pager --no-legend 2>/dev/null || true)
fi

printf "Timer enabled: %s\n" "$timer_enabled"
printf "Timer active:  %s\n" "$timer_active"
printf "Next run:      %s\n" "$next_run"
printf "Last run:      %s\n" "$last_run"
printf "\n"

if systemctl --user list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
    printf "Последние строки сервиса:\n"
    systemctl --user status "$SERVICE_NAME" --no-pager 2>/dev/null | tail -n 12 || true
else
    printf "Сервис бэкапа ещё не установлен.\n"
fi
