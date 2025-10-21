# 🚀 BMI30 на Raspberry Pi — НАЧНИ ОТСЮДА

**Дата**: 21 октября 2025  
**Статус**: Все готово к развёртыванию на RPi  

---

## 📋 Краткий план (5 минут)

1. ✅ **Копируешь папку `RPI_DEPLOY` на RPi** (один раз — это всё!)
2. ✅ **Подключаешь ST-Link к GPIO RPi** (см. схему ниже)
3. ✅ **Запускаешь `run_setup.sh`** — установит всё необходимое
4. ✅ **Запускаешь `run_test.sh`** — флешит и тестирует

**Готово!** Результат будет на экране.

---

## 🔌 Схема подключения ST-Link к RPi GPIO

```
┌─────────────────────────────────────┐
│   Raspberry Pi GPIO (вид сверху)    │
├─────────────────────────────────────┤
│  1  GND      │  2  5V               │
│  3  GPIO2    │  4  5V               │
│  5  GPIO3    │  6  GND              │
│  7  GPIO4    │  8  GPIO14 (TX)      │
│  9  GND      │  10 GPIO15 (RX)      │
│ 11  GPIO17 ◄─── SWDIO (ST-Link Pin 4)
│ 12  GPIO18   │ 13  GPIO27 ◄─── SWDCLK (ST-Link Pin 9)
│ 15  GPIO22   │ 16  GPIO23           │
│ 17  3.3V     │ 18  GPIO24           │
│ 19  GPIO10   │ 20  GND              │
│ 21  GPIO9    │ 22  GPIO25           │
│ 23  GPIO11   │ 24  GPIO8            │
│ 25  GND ◄─── GND (ST-Link Pin 3)
│ 27  GPIO0    │ 28  GPIO1            │
└─────────────────────────────────────┘

ГЛАВНОЕ:
├─ GPIO 17 (Pin 11) ──→ ST-Link SWDIO (Pin 4)
├─ GPIO 27 (Pin 13) ──→ ST-Link SWDCLK (Pin 9)
└─ GND (Pin 9 или 25) ──→ ST-Link GND (Pin 3)
```

---

## 📁 Что в этой папке

```
RPI_DEPLOY/
├── START_HERE.md              ← ТЫ ЗДЕСЬ
├── run_setup.sh               ← Установка (запусти первый раз)
├── run_test.sh                ← Тестирование (запусти после setup)
├── firmware/
│   └── BMI30.stm32h7.elf      ← Прошивка (готова к флешу)
├── scripts/
│   ├── vendor_stream_read.py  ← Основной тест скорости
│   ├── vendor_quick_status.py ← Быстрая проверка
│   └── openocd_flash.sh       ← Флеш через OpenOCD
└── docs/
    ├── SETUP.md               ← Детальная инструкция setup
    ├── FLASHING.md            ← Как флешить вручную
    └── TROUBLESHOOTING.md     ← Если что-то не работает
```

---

## 🔧 БЫСТРЫЙ СТАРТ (копируй-вставляй)

### Шаг 1: На RPi, в папке RPI_DEPLOY

```bash
# Дай права на выполнение
chmod +x run_setup.sh run_test.sh

# Установи зависимости (один раз)
./run_setup.sh
```

**Ожидай**: ~3-5 минут (apt-get, pip установка)

### Шаг 2: Подключи ST-Link к RPi GPIO

См. схему выше:
- Pin 11 (GPIO 17) → ST-Link SWDIO
- Pin 13 (GPIO 27) → ST-Link SWDCLK  
- Pin 9 или 25 (GND) → ST-Link GND

### Шаг 3: Флеш + Тест

```bash
# Флешит прошивку и запускает тест
./run_test.sh
```

**Ожидай результат**:
```
[INFO] Flashing firmware...
[OK] Flash successful
[INFO] Running speed test...
Streaming speed: 1250 KB/s
[OK] Test passed (target: 960 KB/s)
```

---

## 📊 Ожидаемые результаты

| Что должно произойти | Что видишь |
|------|---------|
| **setup** | `[OK] All dependencies installed` |
| **flash** | `Trying to flash...` → `[OK] Flash successful` |
| **test** | Цифры скорости (KB/s) растут, потом стабилизируются |
| **Финал** | `[OK] Test passed (target: 960 KB/s)` |

**Минимум**: 960 КБ/сек  
**Ожидается**: 1000-1200 КБ/сек  

---

## ⚠️ Если что-то не работает

### ❌ "Device not found"
```bash
# Проверь GPIO подключение:
gpio readall
# Должны светиться GPIO 17 и 27

# Проверь питание на ST-Link (красный LED)
```

### ❌ "LIBUSB_ERROR_ACCESS"
```bash
sudo usermod -a -G plugdev $(whoami)
# Перезагрузись
sudo reboot
```

### ❌ "No target found / Flash timeout"
- Проверь GPIO кабели (особенно SWDCLK)
- Убедись, что питание есть на STM32H723
- Попробуй перезагрузить: `sudo systemctl restart openocd`

### ❌ Скорость < 500 КБ/сек
```bash
# Проверь диагностический режим
python3 scripts/vendor_quick_status.py

# Должно быть:
# diag_mode_active: 1
# diag_samples: 80
```

---

## 📞 Детальная помощь

Если нужны подробности, смотри:
- **Установка**: `docs/SETUP.md`
- **Флеширование вручную**: `docs/FLASHING.md`
- **Решение проблем**: `docs/TROUBLESHOOTING.md`

---

## ✅ Чек-лист перед стартом

- [ ] Папка `RPI_DEPLOY` скопирована на RPi
- [ ] SSH доступ к RPi работает
- [ ] ST-Link v2 подключен к GPIO (Pin 11, 13, GND)
- [ ] Питание есть (LED красный на ST-Link)
- [ ] STM32H723 видна в разъёме ST-Link

**Готово? Запускай `run_setup.sh`! 🚀**
