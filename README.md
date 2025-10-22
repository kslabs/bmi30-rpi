# BMI30 Streamer - Multi-Platform Project

Полнофункциональная платформа для потоковой передачи данных с помощью BMI30 (6-осевой акселерометр/гироскоп) через USB.

**Проект включает:**
- 🎛️ STM32H723 микроконтроллер (USB Device, ADC streaming)
- 🍓 Raspberry Pi хост приложение (Python)
- 🔌 Поддержка двух USB интерфейсов (Vendor Bulk + CDC Serial)
- 📊 Потоковая передача данных в реальном времени

## 📁 Структура проекта

```
bmi30-rpi/
├── firmware/                    # STM32H723 микроконтроллер
│   ├── stm32h723/              # STM32CubeIDE проект (symlink)
│   │   ├── Core/               # Основной код
│   │   ├── Drivers/            # HAL драйверы
│   │   ├── USB_DEVICE/         # USB конфигурация
│   │   ├── build.py            # Python builder
│   │   ├── program.sh          # Скрипт программирования
│   │   └── BUILD.md            # Инструкция по сборке
│   └── README.md
│
├── host/                        # Raspberry Pi хост код (Python)
│   ├── README.md               # Хост документация
│   ├── QUICKSTART.md           # Быстрый старт
│   ├── USB_receiver.py         # Приложение приёма данных
│   ├── USB_proto.py            # Протокол USB
│   ├── USB_io.py               # USB I/O
│   ├── USB_frame.py            # Обработка фреймов
│   ├── usb_vendor/             # USB vendor интерфейс
│   ├── tools/                  # Утилиты
│   └── scripts/                # Скрипты
│
├── README.md                    # Этот файл
├── QUICKSTART.md                # Общий быстрый старт
└── docs/                        # Документация

```

## 🚀 Быстрый старт

### На Raspberry Pi (хост)

```bash
cd host

# Установить зависимости
pip install pyusb numpy matplotlib

# Запустить приложение приёма данных
python3 USB_receiver.py
```

### На компьютере с STM32 (прошивка)

```bash
cd firmware/stm32h723

# Собрать прошивку (требует arm-none-eabi-gcc)
python3 build.py

# Прошить микроконтроллер (требует ST-Link)
./program.sh
```

## 📋 Требования

### Для хост части (RPi):
- Python 3.7+
- PyUSB
- numpy, matplotlib (опционально для визуализации)

### Для прошивки (микроконтроллер):
- arm-none-eabi-gcc
- openocd
- ST-Link v2 или совместимый программатор

## 🔧 Установка

### Шаг 1: Клонировать репозиторий

```bash
git clone https://github.com/kslabs/bmi30-rpi.git
cd bmi30-rpi
```

### Шаг 2: Установить зависимости хоста

```bash
cd host
pip install -r requirements.txt
cd ..
```

### Шаг 3: Собрать и прошить микроконтроллер

```bash
cd firmware/stm32h723
python3 build.py
./program.sh
cd ../..
```

### Шаг 4: Запустить хост приложение

```bash
cd host
python3 USB_receiver.py
```

## 📚 Документация

- [**host/README.md**](host/README.md) - Документация хост приложения
- [**host/QUICKSTART.md**](host/QUICKSTART.md) - Быстрый старт для RPi
- [**firmware/README.md**](firmware/README.md) - Документация прошивки
- [**firmware/stm32h723/BUILD.md**](firmware/stm32h723/BUILD.md) - Инструкция по сборке микроконтроллера

## 🐛 Известные проблемы и решения

### EP0 GET_STATUS timeout (errno 110)
- **Статус:** ✅ ИСПРАВЛЕНО в прошивке от Oct 22 2025
- **Решение:** Обновлены обработчики USB в Core/Src

### Потеря прошивки после reset
- **Статус:** ✅ ИСПРАВЛЕНО
- **Решение:** Убедитесь что используется FLASH адрес (0x08000000), не RAM

Смотрите [**host/ISSUES.md**](host/ISSUES.md) для подробного списка известных проблем.

## 📊 Возможности

- ✅ Потоковая передача данных в реальном времени
- ✅ Двойной USB интерфейс (Vendor Bulk для данных + CDC для отладки)
- ✅ Веб-интерфейс для визуализации данных
- ✅ Поддержка Linux, macOS, Raspberry Pi
- ✅ Компиляция на Linux с помощью arm-none-eabi-gcc
- ✅ Программирование через openocd + ST-Link

## 👥 Контрибьютинг

Если вы нашли баг или хотите добавить функцию:

1. Форкните репозиторий
2. Создайте ветку для вашей фичи (`git checkout -b feature/AmazingFeature`)
3. Закоммитьте ваши изменения (`git commit -m 'Add some AmazingFeature'`)
4. Запушьте в ветку (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

## 📝 Лицензия

Проект распространяется под лицензией MIT. Смотрите файл `LICENSE` для подробностей.

## 📞 Поддержка

- 🐛 Найденные баги - создайте Issue
- 💡 Вопросы и предложения - Discussion
- 📧 Email: support@example.com

---

**Последнее обновление:** October 22, 2025  
**Версия:** 2.0 (Multi-Platform)
