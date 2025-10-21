#!/bin/bash
# run_setup.sh - Установка всех зависимостей на RPi для BMI30 тестирования

set -e

echo "[INFO] BMI30 Setup для Raspberry Pi"
echo "[INFO] ================================"

# Проверка, что мы на RPi
if ! command -v gpio &> /dev/null && ! [ -f /boot/bootcode.bin ] 2>/dev/null; then
    echo "[WARN] Похоже, это не Raspberry Pi, но продолжаю..."
fi

# 1. Обновление системы
echo "[INFO] Обновление пакетов..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# 2. Установка OpenOCD
echo "[INFO] Установка OpenOCD..."
if ! command -v openocd &> /dev/null; then
    sudo apt-get install -y -qq openocd
fi

# 3. Установка Python зависимостей
echo "[INFO] Установка Python3 и pip..."
sudo apt-get install -y -qq python3 python3-pip python3-dev

# 4. Установка PyUSB и других пакетов
echo "[INFO] Установка PyUSB, libusb..."
sudo apt-get install -y -qq libudev-dev libffi-dev libusb-1.0-0 libusb-1.0-0-dev
pip3 install --upgrade pip -q
pip3 install pyusb -q

# 5. Установка GPIO утилит
echo "[INFO] Установка RPi GPIO утилит..."
sudo apt-get install -y -qq wiringpi

# 6. Настройка прав доступа для USB
echo "[INFO] Настройка прав доступа для USB..."
sudo usermod -a -G plugdev $(whoami) || true
sudo usermod -a -G dialout $(whoami) || true

# 7. Конфигурация OpenOCD
echo "[INFO] Настройка OpenOCD для RPi GPIO..."
sudo tee /etc/openocd/rpi.cfg > /dev/null <<'EOF'
source [find interface/raspberrypi-gpio.cfg]
source [find target/stm32h7x.cfg]
EOF

echo ""
echo "[OK] Установка завершена!"
echo ""
echo "ℹ️  Важно: Если получил ошибку прав доступа, перезагрузись:"
echo "    sudo reboot"
echo ""
echo "📋 Дальше:"
echo "    1. Подключи ST-Link к GPIO (Pin 11, 13, GND)"
echo "    2. Запусти: ./run_test.sh"
echo ""
