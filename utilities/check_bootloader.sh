#!/usr/bin/env bash
set -euo pipefail

BOOT_ORDER_USB_FIRST="0xf2614"

get_boot_order() {
    local order=""

    if command -v vcgencmd >/dev/null 2>&1; then
        order="$(vcgencmd bootloader_config 2>/dev/null | awk -F= '/^BOOT_ORDER=/{print $2; exit}')"
    fi

    if [[ -z "$order" ]] && command -v rpi-eeprom-config >/dev/null 2>&1; then
        order="$(rpi-eeprom-config 2>/dev/null | awk -F= '/^BOOT_ORDER=/{print $2; exit}')"
    fi

    printf '%s' "$order"
}

BOOT_ORDER="$(get_boot_order)"

printf "Состояние загрузчика Raspberry Pi\n"
printf "===============================\n"

if [[ -z "$BOOT_ORDER" ]]; then
    printf "BOOT_ORDER: не удалось определить\n"
    exit 1
fi

printf "BOOT_ORDER: %s\n" "$BOOT_ORDER"
printf "\nИнтерпретация:\n"
if [[ "$BOOT_ORDER" == "$BOOT_ORDER_USB_FIRST" ]]; then
    printf "  Включен режим USB-first.\n"
    printf "  Если USB подключен, система обычно загрузится с USB.\n"
    printf "  Если USB отсутствует, система должна перейти к внутреннему накопителю.\n"
else
    printf "  Используется другой порядок загрузки EEPROM.\n"
    printf "  Для вашей рабочей схемы стоит отдельно проверить, кто идет раньше: USB или eMMC.\n"
fi
