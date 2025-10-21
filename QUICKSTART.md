# ⚡ Быстрый Старт BMI30 Oscilloscope

## 🎯 Суть Проекта в Одной Фразе
Живая осциллограмма стерео ADC потока от BMI30 через USB Vendor Bulk с ~200 FPS.

---

## ⚠️ КРИТИЧНАЯ ПРОБЛЕМА

**На устройстве установлена CDC конфигурация, а требуется Vendor Bulk!**

### Текущее состояние:
```
lsusb -d cafe:4001 -v
→ Interface 0 (CDC Control), Interface 1 (CDC Data)
❌ Нет Interface 2 с EP 0x03/0x83
```

### Требуемое состояние:
```
Interface 2 (Vendor Bulk Stereo)
├─ EP 0x03 (Bulk OUT)
└─ EP 0x83 (Bulk IN)
```

---

## 🛠️ Решение: Перепрошить Устройство

### Требуется:
- ✅ ST-Link v2 программатор
- ✅ Подключить ST-Link к RPi GPIO (3 провода)
- ✅ Прошивка уже готова: `firmware/BMI30.stm32h7.elf`

### Схема подключения:
```
RPi GPIO         →  ST-Link
Pin 11 (GPIO17)  →  Pin 4 (SWDIO)
Pin 13 (GPIO27)  →  Pin 9 (SWDCLK)
Pin 9/25 (GND)   →  Pin 3 (GND)
```

### Команда:
```bash
cd /home/techaid/Documents

# Автоматический скрипт
./flash_firmware.sh

# Или вручную
openocd -f /usr/share/openocd/scripts/interface/stlink.cfg \
        -f /usr/share/openocd/scripts/target/stm32h7x.cfg \
        -c "init" -c "halt" \
        -c "stm32h7x mass_erase 0" \
        -c "program firmware/BMI30.stm32h7.elf 0x08000000 verify" \
        -c "reset run" -c "exit"
```

### После прошивания:
```bash
# Проверить (должны быть новые endpoints)
lsusb -d cafe:4001 -v | grep -A 10 "Interface 2"

# Запустить GUI
python3 BMI30.200.py
```

---

## 📊 После Успешного Прошивания

GUI покажет:
```
┌─────────────────────────────────────┐
│ BUF=1360 FREQ=200Hz  ↻  ⚡  🩺      │
├─────────────────────────────────────┤
│         ADC0 (зелёный)              │ ≈ 200 FPS
│         ADC1 (синий)                │ Синхронно
├─────────────────────────────────────┤
│ X: Индексы семплов (0, 1, 2, ...)  │
│ Y: Амплитуда (-32768..32767)        │
└─────────────────────────────────────┘
```

---

## 📚 Полная Документация

| Файл | Назначение |
|------|-----------|
| `DEVICE_STATUS.md` | Детальный анализ текущего состояния |
| `LAUNCH.md` | Полное руководство по запуску |
| `README.md` | Архитектура проекта |
| `BMI30.200.py` | Основной GUI (1113 строк) |
| `usb_vendor/usb_stream.py` | USB транспорт (~850 строк) |

---

## ✅ Контрольный Список

- [ ] ST-Link приобретён и подключен к RPi GPIO
- [ ] Прошивка загружена на устройство
- [ ] Проверено: `lsusb` показывает IF#2 с EP 0x03/0x83
- [ ] GUI запущен: `python3 BMI30.200.py`
- [ ] На экране две осциллограммы с данными
- [ ] FPS ≥ 200

---

## 🆘 Помощь

```bash
# Если что-то не так, запустить диагностику
cd /home/techaid/Documents

# Проверить текущее состояние устройства
lsusb -d cafe:4001 -v

# Проверить логи
dmesg | tail -20

# GitHub репозиторий
git log --oneline | head -10
```

---

**Главный Интернет Адрес**: https://github.com/kslabs/bmi30-rpi  
**Версия**: 200 (STAT v1 compliance)  
**Дата**: 21 октября 2025
