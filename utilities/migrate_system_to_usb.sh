#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Использование:
    sudo ./utilities/migrate_system_to_usb.sh [--yes] [--skip-eeprom]

Назначение:
    Копирует систему с eMMC на USB-диск.

Опции:
    --yes          Не спрашивать подтверждение.
    --skip-eeprom  Не менять BOOT_ORDER в EEPROM.
EOF
    exit 0
fi

exec "$SCRIPT_DIR/migrate_system_between_disks.sh" --source-role internal --target-role usb "$@"
