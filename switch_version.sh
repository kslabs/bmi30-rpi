#!/bin/bash
# Скрипт для быстрого переключения между версиями BMI30.200.py

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
HOST_DIR="$SCRIPT_DIR/host"

resolve_python() {
    if [[ -x "$SCRIPT_DIR/.usbvenv/bin/python" ]]; then
        printf '%s\n' "$SCRIPT_DIR/.usbvenv/bin/python"
        return 0
    fi

    if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
        printf '%s\n' "$SCRIPT_DIR/.venv/bin/python"
        return 0
    fi

    return 1
}

PYTHON_BIN="$(resolve_python || true)"

run_version() {
    local version_file="$1"

    if [[ -z "$PYTHON_BIN" ]]; then
        echo "Ошибка: не найден Python в .usbvenv/bin/python или .venv/bin/python"
        echo "Проверьте копию системы: каталог .usbvenv у вас сейчас пустой."
        exit 1
    fi

    if [[ ! -f "$HOST_DIR/$version_file" ]]; then
        echo "Ошибка: не найден файл версии $HOST_DIR/$version_file"
        exit 1
    fi

    pkill -f BMI30.200.py
    sleep 0.5
    cd "$SCRIPT_DIR" || exit 1
    exec "$PYTHON_BIN" "$HOST_DIR/$version_file"
}

# Очистка буфера ввода
while read -t 0; do read -n 1; done

echo "=========================================="
echo "   Переключение версий BMI30.200.py"
echo "=========================================="
echo ""

PS3="Введите номер (или 0 для выхода): "
options=(
    "2026-02-07 (29d4cb5) - Update UI and PWM controls"
    "2026-02-07 + AUTORESET - Со встроенным сбросом STM32 (2 сек)"
    "2026-02-11 (35e2110) - ROI: обновление start/len"
    "2026-02-12 (5f33318) - Настроить смещение метки Б"
    "2026-02-15 (b2aba85) - Стабилизация детекции"
    "2026-02-16 - С оптимизированными фильтрами (быстрые avg7/9/11)"
    "ТЕКУЩАЯ - Последняя разработка"
    "Выход"
)

select opt in "${options[@]}"; do
    case $REPLY in
        1)
            echo "Запускаю версию от 2026-02-07..."
            run_version "BMI30.200.py.2026-02-07"
            break
            ;;
        2)
            echo "Запускаю версию 2026-02-07 + AUTORESET (автосброс через 2 сек)..."
            run_version "BMI30.200.py.2026-02-07-autoreset"
            break
            ;;
        3)
            echo "Запускаю версию от 2026-02-11..."
            run_version "BMI30.200.py.old"
            break
            ;;
        4)
            echo "Запускаю версию от 2026-02-12..."
            run_version "BMI30.200.py.2026-02-12"
            break
            ;;
        5)
            echo "Запускаю версию от 2026-02-15..."
            run_version "BMI30.200.py.2026-02-15"
            break
            ;;
        6)
            echo "Запускаю версию от 2026-02-16 (с оптимизированными фильтрами)..."
            run_version "BMI30.200.py.2026-02-16"
            break
            ;;
        7)
            echo "Запускаю текущую версию..."
            run_version "BMI30.200.py"
            break
            ;;
        8|0)
            echo "Выход."
            exit 0
            ;;
        *)
            echo "Неверный выбор! Попробуйте снова."
            ;;
    esac
done
