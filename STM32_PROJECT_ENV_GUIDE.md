# Инструкция: как сохранить проект STM32 и окружение

Цель: чтобы проект можно было воспроизвести на другом ПК/Raspberry (сборка + прошивка) без ручной «магии».

## 1) Что обязательно сохранить в репозитории
- Исходники приложения и драйверов: `Core/`, `Drivers/`, `Middlewares/`, `USB/` (если есть).
- Файлы сборки:
  - **Make**: `Makefile` и все `.mk`.
  - **CMake**: `CMakeLists.txt` и все `.cmake`.
  - **CubeIDE**: `.project`, `.cproject`, `.settings/`.
- Скрипты прошивки/отладки:
  - OpenOCD `.cfg`, скрипты `flash.sh`/`flash.bat`.
- Конфигурацию линковщика: `*.ld`.
- Конфиги генератора, если используете CubeMX: `*.ioc`.
- README с командами сборки/прошивки (см. шаблон ниже).

## 2) Что НЕ хранить в репозитории
- Папки сборки: `build/`, `Debug/`, `Release/`, `.metadata/`.
- Локальные артефакты IDE.

## 3) Зафиксируйте версии окружения
В корне проекта добавить файл `ENVIRONMENT.md`:
- Версия MCU: **STM32H723**.
- Компилятор: `arm-none-eabi-gcc` (версия).
- Система сборки: Make/CMake/CubeIDE (конкретно).
- Прошивка: `openocd` или `stlink` (версия).
- ОС: Windows/Linux (минимум).

Пример содержимого `ENVIRONMENT.md`:
```
MCU: STM32H723
Toolchain: arm-none-eabi-gcc 12.2.1
Build system: CMake 3.25 + Ninja 1.11
Flashing: OpenOCD 0.12.0 (STLINK)
OS: Windows 11 / Raspberry Pi OS Bookworm
```

## 4) Минимальный README (шаблон)
Добавьте в `README.md`:
```
# Сборка
mkdir -p build
cd build
cmake -DCMAKE_TOOLCHAIN_FILE=../cmake/arm-none-eabi.cmake ..
cmake --build .

# Прошивка (OpenOCD)
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg -c "program build/firmware.elf verify reset exit"

# Прошивка (st-flash)
st-flash write build/firmware.bin 0x08000000
```

## 5) Рекомендовано: GitHub
- Хранить проект в GitHub.
- Все изменения через PR/commit.
- На Raspberry: `git clone` и `git pull` для синхронизации.

## 6) Проверка воспроизводимости
На «чистой» машине:
1) Установить toolchain + openocd/stlink.
2) Склонировать репозиторий.
3) Собрать по README.
4) Прошить по README.

Если эти 4 шага работают без ручных правок — проект сохранён правильно.
