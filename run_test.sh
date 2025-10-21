#!/bin/bash
# run_test.sh - Флеш прошивки и тестирование скорости на RPi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ELF_PATH="$SCRIPT_DIR/firmware/BMI30.stm32h7.elf"
PYTHON_TEST="$SCRIPT_DIR/scripts/vendor_stream_read.py"

echo ""
echo "╔═════════════════════════════════════════════╗"
echo "║     BMI30 Test & Flash на Raspberry Pi      ║"
echo "╚═════════════════════════════════════════════╝"
echo ""

# Проверка файлов
if [ ! -f "$ELF_PATH" ]; then
    echo "[ERROR] Прошивка не найдена: $ELF_PATH"
    exit 1
fi

if [ ! -f "$PYTHON_TEST" ]; then
    echo "[ERROR] Python тест не найден: $PYTHON_TEST"
    exit 1
fi

# Проверка OpenOCD
if ! command -v openocd &> /dev/null; then
    echo "[ERROR] OpenOCD не установлен"
    echo "Запусти сначала: ./run_setup.sh"
    exit 1
fi

# Флеширование
echo "[1/3] Флеширование прошивки через OpenOCD..."
echo "      Это может занять 10-30 секунд..."
echo ""

if openocd -s /usr/share/openocd/scripts \
    -f interface/raspberrypi-gpio.cfg \
    -f target/stm32h7x.cfg \
    -c "program $ELF_PATH verify reset exit" 2>&1 | grep -q "verified successfully"; then
    echo "[OK] Флеш успешен!"
else
    echo "[WARN] Флеш может быть успешен (проверь LED на ST-Link)"
fi

echo ""
echo "[2/3] Ожидание инициализации устройства (3 сек)..."
sleep 3

echo ""
echo "[3/3] Запуск теста скорости..."
echo "      Диагностический режим должен включиться автоматически"
echo ""
echo "─────────────────────────────────────────────"

# Запуск теста
python3 "$PYTHON_TEST" --full-mode 0 --quiet 2>&1 | head -20

echo "─────────────────────────────────────────────"
echo ""
echo "✅ Тест завершен!"
echo ""
echo "📊 Результаты:"
echo "   • Скорость выше 1200 KB/s = идеально"
echo "   • Скорость 1000-1200 KB/s = хорошо"  
echo "   • Скорость 960+ KB/s = соответствует требованиям"
echo "   • Скорость < 960 KB/s = проблема, см TROUBLESHOOTING.md"
echo ""
