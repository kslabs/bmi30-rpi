#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$WORKSPACE_DIR}"
STATE_DIR="${STATE_DIR:-$WORKSPACE_DIR/.bmi30_cloud_sync}"
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
REQUIRE_TODAY=0

usage() {
    cat <<'EOF'
Usage:
  ./utilities/cloud_sync_now.sh [options]

Options:
  --config <path>  Config file (default: ./utilities/backup_to_cloud.conf)
  --today-only     When reading from cloud, update only from today's archive
  --dry-run        Show actions without creating/uploading/updating
  -h, --help       Show this help

Logic:
  If this project changed locally today, publish it to cloud and stop.
  If there are no local changes today, read today's cloud version and update if needed.
EOF
}

log() {
    printf '[INFO] %s\n' "$*" >&2
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
}

require_value() {
    local opt="$1"
    local val="${2:-}"
    [[ -n "$val" ]] || fail "После $opt нужен аргумент"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --config)
                require_value "$1" "${2:-}"
                CONFIG_FILE="$2"
                load_config
                shift 2
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

project_changed_today() {
    bmi30_project_changed_today "$SOURCE_DIR"
}

run_publish() {
    local -a cmd
    cmd=(bash "$SCRIPT_DIR/backup_to_cloud.sh" --if-changed)
    [[ "$DRY_RUN" -eq 1 ]] && cmd+=(--dry-run)
    "${cmd[@]}"
}

run_update() {
    local -a cmd
    cmd=(bash "$SCRIPT_DIR/update_from_cloud.sh")
    [[ "$REQUIRE_TODAY" -eq 1 ]] && cmd+=(--today-only)
    [[ "$DRY_RUN" -eq 1 ]] && cmd+=(--dry-run)
    "${cmd[@]}"
}

main() {
    load_config
    parse_args "$@"

    local current_signature known_signature
    current_signature="$(project_signature)"
    known_signature="$(read_known_signature)"

    if project_changed_today && [[ -z "$known_signature" || "${current_signature,,}" != "${known_signature,,}" ]]; then
        log "Сегодня есть локальные изменения: сохраняю проект в облако и не выполняю обновление"
        run_publish
        return
    fi

    if [[ -n "$known_signature" && "${current_signature,,}" != "${known_signature,,}" ]]; then
        log "Локальная версия отличается, но сегодняшних локальных изменений нет: проверяю облако"
        run_update
        return
    fi

    log "Сегодняшних локальных изменений нет: проверяю сегодняшнюю версию в облаке"
    run_update
}

main "$@"
