#!/usr/bin/env bash
set -u

WORKSPACE_DIR="/home/techaid/Documents"
SERVICE_NAME="bmi30-migrate-usb-to-emmc-once.service"
MARKER_PATH="$WORKSPACE_DIR/.bmi30_migrate_usb_to_emmc_once"
LOG_PATH="$WORKSPACE_DIR/bmi30_migrate_to_emmc_once.log"

exec >>"$LOG_PATH" 2>&1

printf "\n=== %s: USB -> eMMC migration once ===\n" "$(date -Is)"

rm -f "$MARKER_PATH"
systemctl disable "$SERVICE_NAME" || true
systemctl daemon-reload || true

cd "$WORKSPACE_DIR" || exit 1
./utilities/migrate_system_to_emmc.sh --yes
status=$?

printf "=== %s: migration exited with status %d ===\n" "$(date -Is)" "$status"
exit "$status"