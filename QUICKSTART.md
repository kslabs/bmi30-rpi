# ⚡ Быстрый Старт BMI30 Oscilloscope

## 🎯 Суть Проекта
Получить и отобразить живую осциллограмму ADC потока от BMI30 через USB Vendor Bulk с ~200 FPS.

---

## ✅ Текущее Состояние

**Устройство BMI30**: Поддерживает ДВА режима
- **Режим 1: Vendor Bulk (IF#2)** ⭐ Рекомендуется
  - Interface 2 (class 255)
  - Endpoints: OUT 0x03, IN 0x83  
  - STAT v1 протокол
  - ~200 FPS для осциллограммы
  - Статус: READY FOR PRODUCTION
  
- **Режим 2: CDC (IF#0 + IF#1)** (legacy fallback)
  - Interface 0 (CDC Control) + Interface 1 (CDC Data)
  - Для отладки, медленнее
  - Текущий статус устройства: **❓ Неизвестно**

**Компьютер (RPi)**: ✅ **ГОТОВ**
- Python окружение установлено
- Все зависимости готовы (PyUSB, PyQt5, numpy)
- GUI код готов (BMI30.200.py) - работает с Vendor Bulk
- USB транспорт готов (usb_vendor/usb_stream.py)

---

## 🚀 Что Нужно Сделать

### Вариант А: Если устройство в режиме Vendor Bulk (IF#2) ⭐ РЕКОМЕНДУЕТСЯ
```bash
cd /home/techaid/Documents
python3 BMI30.200.py
```

**Ожидаемый результат**:
- GUI откроется с двумя пустыми графиками
- Кнопки управления активны
- При подключённом устройстве с IF#2 должны появиться две осциллограммы
- ~200 FPS обновления

### Вариант B: Если устройство в режиме CDC (IF#0 + IF#1) (legacy fallback)
```bash
cd /home/techaid/Documents
# Использовать стандартный USB_receiver (медленнее, без GUI осциллографа)
python3 USB_receiver.py --plot-fast
```

**Ожидаемый результат**:
- Окно PyQtGraph с меньшей частотой обновления
- Данные поступают через CDC последовательный порт

### Как Проверить Какой Режим Устройства
```bash
# Проверить, что видит операционная система
lsusb -d cafe:4001 -v | grep "bNumInterfaces\|Interface"

# Ищите:
# bNumInterfaces 3 → Vendor Bulk режим ✅ (Вариант А)
# bNumInterfaces 2 → CDC режим (Вариант B)
```

---

## 📊 После Запуска GUI

### Если Всё Работает ✅ (Vendor Bulk режим)
- На экране две синхронизированные осциллограммы (ADC0 зелёный, ADC1 синий)
- Данные обновляются ~200 FPS
- Статус показывает "BUF=1360 FREQ=200Hz"
- X-ось: индексы семплов
- Y-ось: амплитуда (-32768..32767)

### Если Нет Данных ❌
- Проверьте какой режим устройства: `lsusb -d cafe:4001 -v | grep bNumInterfaces`
- Нажмите кнопку 🩺 (диагностика) в GUI
- Посмотрите консоль на ошибки

### Проблема: Устройство в режиме CDC (bNumInterfaces=2)
- Используйте `python3 USB_receiver.py --plot-fast` вместо `BMI30.200.py`
- ИЛИ потребуйте от разработчика перепрошить устройство в Vendor Bulk режим

---

## 🩺 Диагностика

### Проверить Подключение Устройства
```bash
lsusb | grep cafe:4001
# Output: Bus 001 Device XXX: ID cafe:4001 WeAct BMI30 Streamer
```

### Запустить Диагностику USB
```bash
lsusb -d cafe:4001 -v | head -50
# Проверить: Interface 2, EP 0x03, EP 0x83
```

### Проверить Python Зависимости
```bash
python3 -c "import usb, pyqtgraph, PyQt5; print('✓ All dependencies OK')"
```

### Протестировать USB Транспорт Напрямую
```bash
python3 << 'EOF'
from usb_vendor.usb_stream import USBStream

try:
    stream = USBStream(profile=1, full=True)
    print("✓ Device opened successfully")
    
    for i in range(5):
        pairs = stream.get_stereo(timeout=0.1)
        if pairs:
            print(f"✓ Pair {i}: {len(pairs)} frames received")
    
    stream.close()
    print("✓ USB transport working!")
except Exception as e:
    print(f"✗ Error: {e}")
EOF
```

---

## 🆘 Если Не Работает

### Ошибка: "Device not found"
```
Решение: Проверить подключение USB кабеля
lsusb | grep cafe:4001
```

### Ошибка: "No suitable interface"
```
Решение: Это может быть транспортная проблема. 
Создать GitHub Issue с текстом ошибки.
```

### Ошибка: "Permission denied"
```bash
# Дать права
sudo tee /etc/udev/rules.d/99-bmi30.rules << 'EOF'
SUBSYSTEMS=="usb", ATTRS{idVendor}=="cafe", ATTRS{idProduct}=="4001", MODE="0666"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Нет данных на графике
1. Нажать кнопку 🩺 (Diagnose) в GUI
2. Посмотреть на вывод в консоль
3. Если статус не показывает alt=1/out_armed - создать Issue

---

## 📝 Как Создать GitHub Issue

Если устройство не работает правильно:

1. Откройте: https://github.com/kslabs/bmi30-rpi/issues
2. Нажмите "New Issue"
3. Заполните:

```
**Название**: [Device Problem] Brief description

**Описание проблемы**:
- Что вы делали
- Что произошло
- Что вы ожидали

**Вывод консоли**:
[Вставить весь текст ошибки из консоли]

**Команда проверки**:
lsusb -d cafe:4001 -v output
[Вставить полный вывод]

**Окружение**:
- Python версия: 3.11
- ОС: Linux (RPi OS)
```

Разработчик устройства увидит Issue и:
- Изменит прошивку если нужно
- Перепрошит устройство
- Обновит инструкции

---

## 📚 Основные Файлы

- `BMI30.200.py` — GUI (1113 строк)
- `usb_vendor/usb_stream.py` — USB транспорт (~850 строк)
- `LAUNCH.md` — Полное руководство
- `README_INSTRUCTIONS.md` — Навигация

---

## ✨ Главное

**Просто запусти**:
```bash
python3 BMI30.200.py
```

**Если не работает**:
1. Посмотри ошибку в консоли
2. Создай GitHub Issue с ошибкой
3. Разработчик исправит

**Успеха!** 🚀
