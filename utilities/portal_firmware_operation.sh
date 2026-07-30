#!/usr/bin/env bash
# Run a portal-triggered firmware update or one-step rollback outside the
# portal service cgroup, so restarting the portal cannot interrupt the job.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="${BMI30_FIRMWARE_WORKSPACE:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
STATE_DIR="${STATE_DIR:-$WORKSPACE_DIR/.bmi30_cloud_sync}"
OPERATION_FILE="${BMI30_PROGRESS_FILE:-$STATE_DIR/portal_operation.json}"
ROLLBACK_FILE="${BMI30_ROLLBACK_FILE:-$STATE_DIR/rollback_state.env}"
LOCK_FILE="$STATE_DIR/portal_operation.lock"
LOG_FILE="$STATE_DIR/portal_operation.log"
RCLONE_CONFIG="${RCLONE_CONFIG:-/home/techaid/.config/rclone/rclone.conf}"
ACTION="${1:-}"

json_escape() {
    local value="${1:-}"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '%s' "$value"
}

write_operation() {
    local status="$1"
    local progress="$2"
    local message="$3"
    local error="${4:-}"
    local temporary

    mkdir -p "$STATE_DIR"
    temporary="$STATE_DIR/.portal_operation.tmp.$$"
    {
        printf '{"action":"%s","status":"%s","progress":%d,' \
            "$(json_escape "$ACTION")" \
            "$(json_escape "$status")" \
            "$progress"
        printf '"message":"%s","error":"%s","updated_at":%d}\n' \
            "$(json_escape "$message")" \
            "$(json_escape "$error")" \
            "$(date +%s)"
    } > "$temporary"
    mv -f -- "$temporary" "$OPERATION_FILE"
}

fail_operation() {
    local message="$1"
    write_operation "failed" "${2:-1}" "Operation failed." "$message"
    printf '[ERROR] %s\n' "$message" >> "$LOG_FILE"
    exit 1
}

mark_rollback_consumed() {
    local temporary="$STATE_DIR/.rollback_state.tmp.$$"
    awk '
        BEGIN { found = 0 }
        /^ROLLBACK_AVAILABLE=/ {
            print "ROLLBACK_AVAILABLE=0"
            found = 1
            next
        }
        { print }
        END {
            if (!found) print "ROLLBACK_AVAILABLE=0"
        }
    ' "$ROLLBACK_FILE" > "$temporary"
    printf 'ROLLBACK_CONSUMED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$temporary"
    mv -f -- "$temporary" "$ROLLBACK_FILE"
}

main() {
    [[ "$ACTION" == "update" || "$ACTION" == "rollback" ]] \
        || fail_operation "Expected operation: update or rollback."

    mkdir -p "$STATE_DIR"
    exec 9>"$LOCK_FILE"
    flock -n 9 || fail_operation "Another firmware operation is already running."
    : > "$LOG_FILE"

    if [[ "$ACTION" == "update" ]]; then
        [[ -x "$SCRIPT_DIR/update_from_cloud.sh" ]] \
            || fail_operation "Cloud update script is unavailable."
        write_operation "running" 3 "Preparing firmware update…"
        export BMI30_PROGRESS_FILE="$OPERATION_FILE"
        export BMI30_PROGRESS_ACTION="update"
        export RCLONE_CONFIG
        if bash "$SCRIPT_DIR/update_from_cloud.sh" >> "$LOG_FILE" 2>&1; then
            write_operation "succeeded" 100 "Firmware update completed."
            exit 0
        fi
        fail_operation "Firmware update failed. See $LOG_FILE for details." 95
    fi

    [[ -f "$ROLLBACK_FILE" ]] || fail_operation "No saved rollback state is available."
    unset ROLLBACK_AVAILABLE ROLLBACK_BUNDLE_ID
    # shellcheck source=/dev/null
    source "$ROLLBACK_FILE"
    [[ "${ROLLBACK_AVAILABLE:-0}" == "1" ]] \
        || fail_operation "No saved rollback version is available."
    [[ "${ROLLBACK_BUNDLE_ID:-}" =~ ^[A-Za-z0-9._-]+$ ]] \
        || fail_operation "Saved rollback bundle ID is invalid."
    [[ -d "$WORKSPACE_DIR/host/bmi30_split_bundles/$ROLLBACK_BUNDLE_ID" ]] \
        || fail_operation "Saved rollback bundle is missing."

    write_operation "running" 15 "Validating saved firmware…"
    "$WORKSPACE_DIR/switch_bmi30_split_versions.sh" --validate "$ROLLBACK_BUNDLE_ID" \
        >> "$LOG_FILE" 2>&1 \
        || fail_operation "Saved rollback bundle failed validation." 20

    write_operation "running" 40 "Activating saved firmware…"
    BMI30_SPLIT_SELECTED_BY_OVERRIDE=portal-rollback \
        "$WORKSPACE_DIR/switch_bmi30_split_versions.sh" --activate "$ROLLBACK_BUNDLE_ID" \
        >> "$LOG_FILE" 2>&1 \
        || fail_operation "Unable to activate the saved rollback bundle." 85

    write_operation "running" 95 "Finalizing rollback…"
    mark_rollback_consumed
    write_operation "succeeded" 100 "Firmware rollback completed."
}

main "$@"
