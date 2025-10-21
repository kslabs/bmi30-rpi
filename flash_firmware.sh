#!/bin/bash
# Скрипт для прошивания BMI30 через OpenOCD и ST-Link

set -e

FIRMWARE="/home/techaid/Documents/firmware/BMI30.stm32h7.elf"
OPENOCD_CFG="/tmp/stm32h7_st_link.cfg"

if [ ! -f "$FIRMWARE" ]; then
    echo "ERROR: Firmware not found: $FIRMWARE"
    exit 1
fi

# Создаём конфиг OpenOCD для ST-Link и STM32H7
cat > "$OPENOCD_CFG" << 'EOF'
# STM32H7 with ST-Link v2
source [find interface/stlink.cfg]
transport select hla_swd

source [find target/stm32h7x.cfg]

init
target current stm32h7x

# Halt target
halt

# Mass erase
stm32h7x mass_erase 0

# Flash the firmware
program "$FIRMWARE" 0x08000000 verify reset exit
EOF

echo "OpenOCD config created: $OPENOCD_CFG"
echo ""
echo "Starting OpenOCD with ST-Link..."
echo "Flashing firmware: $FIRMWARE"
echo ""

# Запуск OpenOCD
openocd -f "$OPENOCD_CFG" \
    -c "init" \
    -c "targets" \
    -c "halt" \
    -c "stm32h7x mass_erase 0" \
    -c "program $FIRMWARE 0x08000000 verify" \
    -c "reset run" \
    -c "exit"

echo ""
echo "✓ Firmware flashed successfully!"
echo ""
echo "Waiting for device re-enumeration..."
sleep 2

# Проверим, переподключилось ли устройство
lsusb | grep -i "cafe:4001" && echo "✓ Device re-enumerated" || echo "⚠ Device not found, may need to reconnect USB cable"
