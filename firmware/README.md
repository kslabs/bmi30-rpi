# STM32H723 Firmware

STM32CubeIDE проект для микроконтроллера STM32H723VGTx.

## Структура

- `Core/` - Основной код приложения
- `Drivers/` - HAL драйверы STM32
- `Middlewares/` - USB Device Library
- `USB_DEVICE/` - USB конфигурация и обработчики
- `build.py` - Python builder для Linux/macOS
- `program.sh` - Скрипт программирования через ST-Link
- `BUILD.md` - Подробная инструкция по сборке

## Быстрый старт

```bash
cd firmware

# Собрать прошивку
python3 build.py

# Прошить микроконтроллер
./program.sh
```

## Требования

- arm-none-eabi-gcc
- openocd
- ST-Link v2 или совместимый программатор

## Подробнее

Смотрите `BUILD.md` в этой папке.
