# BMI30 Streamer - Быстрый старт# ⚡ Быстрый Старт BMI30 Oscilloscope



Полная инструкция для запуска проекта с нуля.## 🎯 Суть Проекта

Получить и отобразить живую осциллограмму ADC потока от BMI30 через USB Vendor Bulk с ~200 FPS.

## 📋 Предварительные требования

---

### Оборудование

- STM32H723VGTx микроконтроллер (BMI30 плата)## ✅ Текущее Состояние

- ST-Link v2 программатор (для прошивки)

- Raspberry Pi 4B или 5 (для хост приложения)**Устройство BMI30**: Поддерживает ДВА режима

- Кабель USB (micro-USB для RPi, USB-A для ST-Link)- **Режим 1: Vendor Bulk (IF#2)** ⭐ Рекомендуется

  - Interface 2 (class 255)

### ПО  - Endpoints: OUT 0x03, IN 0x83  

  - STAT v1 протокол

**Для Raspberry Pi:**  - ~200 FPS для осциллограммы

```bash  - Статус: READY FOR PRODUCTION

sudo apt-get install python3 python3-pip libusb-1.0-0  

```- **Режим 2: CDC (IF#0 + IF#1)** (legacy fallback)

  - Interface 0 (CDC Control) + Interface 1 (CDC Data)

**Для компьютера с прошивкой (любой Linux):**  - Для отладки, медленнее

```bash  - Текущий статус устройства: **❓ Неизвестно**

sudo apt-get install gcc-arm-none-eabi openocd

```**Компьютер (RPi)**: ✅ **ГОТОВ**

- Python окружение установлено

## 🔧 Установка- Все зависимости готовы (PyUSB, PyQt5, numpy)

- GUI код готов (BMI30.200.py) - работает с Vendor Bulk

### 1️⃣ Клонировать репозиторий- USB транспорт готов (usb_vendor/usb_stream.py)



```bash---

git clone https://github.com/kslabs/bmi30-rpi.git

cd bmi30-rpi## 🚀 Что Нужно Сделать

```

### Вариант А: Если устройство в режиме Vendor Bulk (IF#2) ⭐ РЕКОМЕНДУЕТСЯ

### 2️⃣ Установить Python зависимости```bash

cd /home/techaid/Documents

```bashpython3 BMI30.200.py

cd host```

pip3 install pyusb numpy matplotlib

cd ..**Ожидаемый результат**:

```- GUI откроется с двумя пустыми графиками

- Кнопки управления активны

### 3️⃣ Собрать прошивку (опционально)- При подключённом устройстве с IF#2 должны появиться две осциллограммы

- ~200 FPS обновления

Если вы хотите пересобрать прошивку:

### Вариант B: Если устройство в режиме CDC (IF#0 + IF#1) (legacy fallback)

```bash```bash

cd firmware/stm32h723cd /home/techaid/Documents

# Использовать стандартный USB_receiver (медленнее, без GUI осциллографа)

# Собратьpython3 USB_receiver.py --plot-fast

python3 build.py```



# Это создаст:**Ожидаемый результат**:

# - Debug/BMI30.stm32h7.elf- Окно PyQtGraph с меньшей частотой обновления

# - Debug/BMI30.stm32h7.bin- Данные поступают через CDC последовательный порт

# - Debug/BMI30.stm32h7.hex

```### Как Проверить Какой Режим Устройства

```bash

### 4️⃣ Прошить микроконтроллер# Проверить, что видит операционная система

lsusb -d cafe:4001 -v | grep "bNumInterfaces\|Interface"

Если вы изменили код прошивки:

# Ищите:

```bash# bNumInterfaces 3 → Vendor Bulk режим ✅ (Вариант А)

cd firmware/stm32h723# bNumInterfaces 2 → CDC режим (Вариант B)

```

# Подключите ST-Link к компьютеру и к STM32H723

./program.sh---



# Вывод:## 📊 После Запуска GUI

# [✓] Programming complete!

```### Если Всё Работает ✅ (Vendor Bulk режим)

- На экране две синхронизированные осциллограммы (ADC0 зелёный, ADC1 синий)

## 🚀 Запуск хост приложения- Данные обновляются ~200 FPS

- Статус показывает "BUF=1360 FREQ=200Hz"

### На Raspberry Pi:- X-ось: индексы семплов

- Y-ось: амплитуда (-32768..32767)

```bash

cd host### Если Нет Данных ❌

- Проверьте какой режим устройства: `lsusb -d cafe:4001 -v | grep bNumInterfaces`

# Запустить основное приложение- Нажмите кнопку 🩺 (диагностика) в GUI

python3 USB_receiver.py- Посмотрите консоль на ошибки



# Вывод:### Проблема: Устройство в режиме CDC (bNumInterfaces=2)

# [*] Waiting for BMI30 device...- Используйте `python3 USB_receiver.py --plot-fast` вместо `BMI30.200.py`

# [✓] Device found: 375C385E3532- ИЛИ потребуйте от разработчика перепрошить устройство в Vendor Bulk режим

# [*] Starting stream...

```---



### На компьютере (для тестирования):## 🩺 Диагностика



```bash### Проверить Подключение Устройства

cd host```bash

lsusb | grep cafe:4001

# Простой тест# Output: Bus 001 Device XXX: ID cafe:4001 WeAct BMI30 Streamer

python3 << 'EOF'```

import usb.core

dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001)### Запустить Диагностику USB

if dev:```bash

    print(f"[✓] Device found: {dev.serial_number}")lsusb -d cafe:4001 -v | head -50

else:# Проверить: Interface 2, EP 0x03, EP 0x83

    print("[!] Device not found")```

EOF

```### Проверить Python Зависимости

```bash

## 📊 Варианты использованияpython3 -c "import usb, pyqtgraph, PyQt5; print('✓ All dependencies OK')"

```

### Вариант 1: Потоковая передача данных

### Протестировать USB Транспорт Напрямую

```bash```bash

cd hostpython3 << 'EOF'

python3 USB_receiver.pyfrom usb_vendor.usb_stream import USBStream

```

try:

Это запустит основное приложение которое:    stream = USBStream(profile=1, full=True)

- Подождет подключения устройства    print("✓ Device opened successfully")

- Инициализирует USB    

- Начнет потоковую передачу данных    for i in range(5):

- Выведет статистику на консоль        pairs = stream.get_stereo(timeout=0.1)

        if pairs:

### Вариант 2: Визуализация в реальном времени            print(f"✓ Pair {i}: {len(pairs)} frames received")

    

```bash    stream.close()

cd host    print("✓ USB transport working!")

python3 USB_plot_fast.pyexcept Exception as e:

```    print(f"✗ Error: {e}")

EOF

Откроет окно с графиком акселерометра/гироскопа в реальном времени.```



### Вариант 3: Сохранение данных---



```bash## 🆘 Если Не Работает

cd host

python3 USB_receiver.py 2>&1 | tee data_$(date +%s).log### Ошибка: "Device not found"

``````

Решение: Проверить подключение USB кабеля

Сохранит все данные в файл для последующего анализа.lsusb | grep cafe:4001

```

## ✅ Проверка работы

### Ошибка: "No suitable interface"

### Тест 1: Устройство видно в системе```

Решение: Это может быть транспортная проблема. 

```bashСоздать GitHub Issue с текстом ошибки.

lsusb | grep -i bmi30```

# Output: Bus 001 Device 013: ID cafe:4001 WeAct BMI30 Streamer

```### Ошибка: "Permission denied"

```bash

### Тест 2: USB команды работают# Дать права

sudo tee /etc/udev/rules.d/99-bmi30.rules << 'EOF'

```bashSUBSYSTEMS=="usb", ATTRS{idVendor}=="cafe", ATTRS{idProduct}=="4001", MODE="0666"

cd hostEOF

python3 << 'EOF'

import usb.coresudo udevadm control --reload-rules

sudo udevadm trigger

dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001)```



# GET_STATUS### Нет данных на графике

status = dev.ctrl_transfer(0x80, 0x00, 0, 0, 2)1. Нажать кнопку 🩺 (Diagnose) в GUI

print(f"[✓] GET_STATUS: {list(status)}")2. Посмотреть на вывод в консоль

3. Если статус не показывает alt=1/out_armed - создать Issue

# GET_DESCRIPTOR  

desc = dev.ctrl_transfer(0x80, 0x06, 0x0100, 0, 18)---

print(f"[✓] GET_DESCRIPTOR: {len(desc)} bytes")

EOF## 📝 Как Создать GitHub Issue

```

Если устройство не работает правильно:

### Тест 3: Потоковая передача работает

1. Откройте: https://github.com/kslabs/bmi30-rpi/issues

```bash2. Нажмите "New Issue"

cd host3. Заполните:

timeout 5 python3 USB_receiver.py 2>&1 | head -20

``````

**Название**: [Device Problem] Brief description

## 🐛 Решение проблем

**Описание проблемы**:

### Проблема: "Device not found"- Что вы делали

- Что произошло

```bash- Что вы ожидали

# Проверьте подключение

lsusb**Вывод консоли**:

[Вставить весь текст ошибки из консоли]

# Если устройство не видно:

# 1. Проверьте питание микроконтроллера**Команда проверки**:

# 2. Проверьте USB кабельlsusb -d cafe:4001 -v output

# 3. Переподключите устройство[Вставить полный вывод]

# 4. Проверьте что прошивка была загружена (последовательный вывод должен быть)

```**Окружение**:

- Python версия: 3.11

### Проблема: "Permission denied"- ОС: Linux (RPi OS)

```

```bash

# Добавьте пользователя в группу dialoutРазработчик устройства увидит Issue и:

sudo usermod -a -G dialout $USER- Изменит прошивку если нужно

- Перепрошит устройство

# Перезагрузитесь или:- Обновит инструкции

newgrp dialout

```---



### Проблема: Данные не поступают## 📚 Основные Файлы



```bash- `BMI30.200.py` — GUI (1113 строк)

# Проверьте логи устройства- `usb_vendor/usb_stream.py` — USB транспорт (~850 строк)

screen /dev/ttyACM0 115200- `LAUNCH.md` — Полное руководство

- `README_INSTRUCTIONS.md` — Навигация

# Или в Python

import serial---

ser = serial.Serial('/dev/ttyACM0', 115200)

print(ser.readline())## ✨ Главное

```

**Просто запусти**:

## 📚 Документация```bash

python3 BMI30.200.py

- [host/README.md](host/README.md) - Полная документация хост приложения```

- [host/QUICKSTART.md](host/QUICKSTART.md) - Быстрый старт для RPi

- [firmware/stm32h723/BUILD.md](firmware/stm32h723/BUILD.md) - Компиляция прошивки**Если не работает**:

- [host/ISSUES.md](host/ISSUES.md) - Известные проблемы и решения1. Посмотри ошибку в консоли

2. Создай GitHub Issue с ошибкой

## 🎯 Что дальше?3. Разработчик исправит



1. **Ознакомьтесь с документацией** в [host/README.md](host/README.md)**Успеха!** 🚀

2. **Измените код** под ваши нужды
3. **Тестируйте на своем оборудовании**
4. **Расскажите нам о проблемах** через Issues

## 💡 Советы

- Используйте `screen` или `minicom` для просмотра логов микроконтроллера
- Сохраняйте данные для анализа (`USB_receiver.py > data.log`)
- Проверяйте напряжение питания (обычно 3.3V для STM32H7)
- Убедитесь что ST-Link имеет правильные подключения (SWCLK, SWDIO, GND)

## 📞 Поддержка

Если что-то не работает:

1. Проверьте [ISSUES.md](host/ISSUES.md)
2. Создайте Issue на GitHub с описанием проблемы
3. Включите логи и выход команд диагностики

---

**Версия:** 2.0  
**Последнее обновление:** October 22, 2025
