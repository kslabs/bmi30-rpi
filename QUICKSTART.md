# ⚡ Быстрый Старт BMI30 Oscilloscope

## 🎯 Суть Проекта
Получить и отобразить живую осциллограмму ADC потока от BMI30 через USB Vendor Bulk с ~200 FPS.

---

## ✅ Текущее Состояние

**Устройство BMI30**: ✅ **ГОТОВО И ПРОШИТО**
- Поддерживает Vendor Bulk режим
- Endpoints: OUT 0x03, IN 0x83
- IF#2 с STAT v1 протоколом

**Компьютер (RPi)**: ✅ **ГОТОВ**
- Python окружение установлено
- Все зависимости готовы (PyUSB, PyQt5, numpy)
- GUI код готов (BMI30.200.py)
- USB транспорт готов (usb_vendor/usb_stream.py)

---

## 🚀 Что Нужно Сделать

### Вариант 1: Прямой Запуск GUI
```bash
cd /home/techaid/Documents
python3 BMI30.200.py
```

**Ожидаемый результат**:
- GUI откроется с двумя пустыми графиками
- Кнопки управления активны
- При подключённом устройстве должны появиться две осциллограммы

### Вариант 2: Проверить Устройство Перед Запуском
```bash
# Проверить, что устройство видно
lsusb -d cafe:4001 -v

# Должны увидеть:
# Interface 2 (Vendor Bulk)
# EP 0x03 (Bulk OUT)
# EP 0x83 (Bulk IN)
```

---

## 📊 После Запуска GUI

### Если Всё Работает ✅
- На экране две синхронизированные осциллограммы (ADC0 зелёный, ADC1 синий)
- Данные обновляются ~200 FPS
- Статус показывает "BUF=1360 FREQ=200Hz"
- X-ось: индексы семплов
- Y-ось: амплитуда (-32768..32767)

### Если Есть Проблема ❌
- Нет данных на графиках
- GUI не открывается
- Ошибки в консоли

**Решение**: 
1. Посмотри в консоль на ошибку
2. Создай GitHub Issue с описанием проблемы
3. Разработчик устройства исправит прошивку

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
