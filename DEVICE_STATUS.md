# 📊 Состояние Устройства BMI30 и Требуемые Действия

**Дата**: 21 октября 2025  
**Статус**: ⚠️ Требуется действие  

---

## 🔍 Текущее Состояние

### Что Имеется

✅ **На компьютере (Linux)**:
- Python окружение с pyusb, PyQt5, numpy
- Исходный код GUI (`BMI30.200.py`)
- USB транспорт (`usb_vendor/usb_stream.py`)
- Скомпилированная прошивка (`firmware/BMI30.stm32h7.elf`)
- Вся документация и примеры
- Git репозиторий синхронизирован с GitHub

✅ **Физическое подключение**:
- Устройство BMI30 подключено к USB (VID:PID = 0xCAFE:0x4001)
- Устройство распознаётся ОС: `lsusb | grep cafe:4001`

❌ **Проблема с устройством**:
- На устройстве установлена **CDC конфигурация** (интерфейсы IF#0 и IF#1)
- Требуется **Vendor Bulk конфигурация** (интерфейс IF#2 с endpoints 0x03/0x83)
- **GUI не может подключиться** из-за отсутствия нужных endpoints

### Детальное Сравнение

#### Текущее состояние устройства (CDC):
```
Configuration 1:
  ├─ Interface 0 (CDC Control)
  │  └─ EP 0x82 (Interrupt IN)
  │
  └─ Interface 1 (CDC Data)
     ├─ EP 0x01 (Bulk OUT)
     └─ EP 0x81 (Bulk IN)
```

#### Требуемое состояние (Vendor Bulk):
```
Configuration 1:
  ├─ Interface 0 (CDC Control) - опционально
  ├─ Interface 1 (CDC Data) - опционально
  │
  └─ Interface 2 (Vendor Bulk Stereo) ← ТРЕБУЕТСЯ
     ├─ EP 0x03 (Bulk OUT)
     └─ EP 0x83 (Bulk IN)
```

---

## 🛠️ Что Нужно Сделать

### Вариант 1️⃣: Перепрошить Устройство (РЕКОМЕНДУЕТСЯ)

Прошивка нужна **новая версия** с поддержкой Vendor Bulk (IF#2).

**Требования**:
- ST-Link v2 программатор (подключить к RPi GPIO)
- OpenOCD (уже установлен: `/usr/bin/openocd`)
- Права доступа к USB

**Схема подключения ST-Link к RPi GPIO**:
```
Raspberry Pi GPIO (вид сверху)
Pin 11 (GPIO 17) ──→ ST-Link SWDIO (Pin 4)
Pin 13 (GPIO 27) ──→ ST-Link SWDCLK (Pin 9)
Pin 9 или 25 (GND) ──→ ST-Link GND (Pin 3)
```

**Команда прошивания** (когда ST-Link подключен):
```bash
cd /home/techaid/Documents
chmod +x flash_firmware.sh
./flash_firmware.sh
```

**Или вручную через OpenOCD**:
```bash
openocd -f /usr/share/openocd/scripts/interface/stlink.cfg \
        -f /usr/share/openocd/scripts/target/stm32h7x.cfg \
        -c "init" \
        -c "halt" \
        -c "stm32h7x mass_erase 0" \
        -c "program /home/techaid/Documents/firmware/BMI30.stm32h7.elf 0x08000000 verify" \
        -c "reset run" \
        -c "exit"
```

**После прошивания**:
1. Устройство переподключится в Vendor Bulk режиме
2. Проверить: `lsusb -d cafe:4001 -v` должен показать IF#2 с EP 0x03/0x83
3. Запустить GUI: `python3 BMI30.200.py`

---

### Вариант 2️⃣: Использовать CDC Режим (АЛЬТЕРНАТИВА)

Если нет возможности перепрошить, можно использовать CDC режим через serial:

```bash
# Использовать существующий CDC стек (serial порт)
python3 /home/techaid/Documents/HostTools/rpi_cdc_client.py
```

**Минусы**:
- Медленнее (~200 FPS вместо потенциальных 300+)
- Требует отдельной реализации GUI для CDC
- Текущий GUI (`BMI30.200.py`) не совместим с CDC

---

## 📋 Пошаговая Инструкция Прошивания

### Шаг 1: Подготовка
```bash
# Убедиться, что OpenOCD установлен
openocd --version

# Убедиться, что прошивка на месте
ls -lh /home/techaid/Documents/firmware/BMI30.stm32h7.elf
```

### Шаг 2: Подключение ST-Link
```
1. Отключить USB кабель от устройства BMI30 (оставить на месте!)
2. Подключить ST-Link к RPi GPIO:
   - Pin 11 (GPIO 17) → ST-Link SWDIO
   - Pin 13 (GPIO 27) → ST-Link SWDCLK
   - Pin 9/25 (GND) → ST-Link GND
3. Подключить ST-Link к компьютеру через USB
4. Убедиться, что ST-Link виден: lsusb | grep -i stlink
```

### Шаг 3: Запуск Прошивания
```bash
cd /home/techaid/Documents

# Способ A: Через скрипт (автоматический)
chmod +x flash_firmware.sh
./flash_firmware.sh

# Способ B: Вручную через OpenOCD
openocd -f /usr/share/openocd/scripts/interface/stlink.cfg \
        -f /usr/share/openocd/scripts/target/stm32h7x.cfg \
        -c "init" \
        -c "halt" \
        -c "stm32h7x mass_erase 0" \
        -c "program firmware/BMI30.stm32h7.elf 0x08000000 verify" \
        -c "reset run" \
        -c "exit"
```

### Шаг 4: Проверка
```bash
# Дождаться переподключения (обычно 2-3 сек)
sleep 3

# Проверить конфигурацию
lsusb -d cafe:4001 -v | grep -A 20 "Interface"

# Должны увидеть:
# Interface 2, Alternate setting 0 (or 1)
#   Endpoints:
#     EP 0x03 (Bulk OUT)
#     EP 0x83 (Bulk IN)
```

### Шаг 5: Запуск GUI
```bash
cd /home/techaid/Documents
python3 BMI30.200.py
```

---

## 🎯 Критерии Успеха

После прошивания GUI должен показать:
```
✅ Device found: 0xCAFE:0x4001
✅ Interface 2 with EP 0x03/0x83 located
✅ SET_INTERFACE alt=1 successful
✅ alt1=1, out_armed=1 (STAT ready)
✅ Two synchronized oscillograms (ADC0 green, ADC1 blue)
✅ ~200 FPS frame rate
✅ Sample index on X-axis
✅ BUF=XXXX FREQ=200Hz in legend
```

---

## ❓ FAQ

### Q: Что если ST-Link не подключен?
**A**: Нужно его подключить к RPi GPIO. Это только способ прошить STM32H7. Без него не получится перейти на Vendor Bulk режим.

### Q: Могу ли я использовать другой программатор?
**A**: Да, подойдёт любой STM32H7 программатор (J-Link, Segger, OpenSDA). Нужно изменить интерфейс OpenOCD.

### Q: Что если прошивка не загружается?
**A**: Возможные причины:
- ST-Link неправильно подключен (проверить пины)
- Питание не доходит до устройства
- Неправильный путь к прошивке
- Проверить: `openocd ... -c "init"` должен найти STM32H7

### Q: Как откатиться на CDC?
**A**: Нужна CDC версия прошивки (обычно поставляется отдельно). Повторить прошивание с CDC ELF файлом.

### Q: Потеряются ли данные при прошивании?
**A**: Нет, прошивка хранится во flash памяти. Данные (если есть) в SRAM сотрутся, но это нормально.

---

## 📞 Поддержка

Если возникли проблемы:

1. **Проверить логи**:
   ```bash
   dmesg | tail -20  # Логи ядра Linux
   ```

2. **Диагностика USB**:
   ```bash
   lsusb -d cafe:4001 -v
   ```

3. **Проверить права**:
   ```bash
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

4. **Проверить в GitHub**:
   ```bash
   cd /home/techaid/Documents
   git status
   git log --oneline | head -10
   ```

---

## 📝 Файлы Проекта

```
/home/techaid/Documents/
├── BMI30.200.py                    # GUI (требует Vendor Bulk режима)
├── usb_vendor/
│   └── usb_stream.py              # USB транспорт
├── firmware/
│   └── BMI30.stm32h7.elf          # Прошивка (требуется прошивание)
├── HostTools/
│   ├── rpi_vendor_minimal.py       # Пример Vendor Bulk
│   ├── rpi_cdc_client.py           # Пример CDC (альтернатива)
│   └── vendor_stream_read.py       # Тестирование потока
├── flash_firmware.sh               # Скрипт автоматического прошивания
├── DEVICE_STATUS.md                # Этот файл
├── LAUNCH.md                       # Инструкция запуска
└── README.md                       # Главная страница
```

---

**Следующий шаг**: Подключить ST-Link и запустить прошивание! 🚀
