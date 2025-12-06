# 🚀 Быстрый старт: 200 Гц на BMI30

## Что нужно знать

✅ **PROFILE=1 (200 Гц) - Работает стабильно**
- Команда: SET_PROFILE(1) = задаём 200 Гц
- Реально получаем: ≈176 Гц (измерено)
- total_samples=912 на каждый кадр

✅ **PROFILE=2 (300 Гц) - Работает стабильно**
- Команда: SET_PROFILE(2) = задаём 300 Гц
- Реально получаем: ≈280 Гц (измерено)
- total_samples=912 на каждый кадр

---

## Использование в коде

### 1. Диагностика (низкоуровневый тест)

```bash
cd /home/techaid/Documents

# Тест профилей
python3 host/diag_block_rate.py --profile 1 --duration 10

# Тест 280 Гц (профиль 2)
python3 host/diag_block_rate.py --profile 2 --duration 10
```

### 2. Использование в Python коде

```python
from usb_vendor import usb_stream

# Инициализация на 176 Гц
```python
from usb_vendor import usb_stream

# Инициализация на 176 Гц
stream = usb_stream.BMI30(
    profile=1,      # 1 = 176 Гц, 2 = 280 Гц
    full=True,
    fast_mode=True  # Всегда включен (рекомендуется)
)

# Получить пару кадров (A+B)
while True:
    try:
        frame_a, frame_b = stream.get_stereo(timeout=1.0)
        # frame_a, frame_b имеют структуру Frame(seq, timestamp, adc_id, flags, samples, payload)
        print(f"A: {frame_a.samples} samples, B: {frame_b.samples} samples")
    except Exception as e:
        print(f"Ошибка: {e}")
        break
```

# Переключение профилей

```python
# Переключиться на 280 Гц
stream.profile = 2
stream.start()  # Переинициализировать

# ... или на 176 Гц
stream.profile = 1
stream.start()
```

---

## Важные детали

### ✅ Поддерживаемые профили

| Профиль | Частота | total_samples | Период | Статус |
|---------|---------|---------------|--------|--------|
| PROFILE=1 | ~176 Гц | 912 | ~5.7 мс | ✅ Работает |
| PROFILE=2 | ~280 Гц | 912 | ~3.6 мс | ✅ Работает |

### ⚠️ Ограничения

1. **SET_FRAME_SAMPLES ломает PROFILE=1**
   - Решение: хост-код автоматически не отправляет эту команду для PROFILE=1.
   - ✅ Уже исправлено в `host/usb_vendor/usb_stream.py`.

2. **Требуется пауза между переключениями**
   - После смены профиля подождите ≥3 сек перед новым START.
   - Это ограничение прошивки/USB, не хоста.

3. **total_samples=912, не 1360**
   - Текущая прошивка обоих профилей использует 912 семплов.
   - Если требуется 1360 — нужно обновить прошивку (запросить у разработчика).

---

## Рекомендации

### Для GPIO-приложений

```python
stream = usb_stream.BMI30(
    profile=1,      # 176 Гц для гладкого потока
    fast_mode=True,
    frame_samples=None  # Автоматическое определение (912)
)
```

### Для высокой точности

```python
stream = usb_stream.BMI30(
    profile=2,      # 300 Гц для большей частоты дискретизации
    fast_mode=True
)
```

### Для долгих сессий

```python
# Убедитесь, что среда установлена корректно
import os
os.environ['BMI30_KEEPALIVE_SEC'] = '2.0'  # Каждые 2 сек проверка соединения
os.environ['BMI30_RESTART_AFTER'] = '2.5'   # Рестарт при необходимости
```

---

## Тестирование

### 1. Проверка синтаксиса

```bash
python3 -m py_compile host/usb_vendor/usb_stream.py host/diag_block_rate.py
```

### 2. Базовая функциональность

```bash
# Оба профиля должны выдать кадры
python3 host/diag_block_rate.py --profile 1 --duration 5
python3 host/diag_block_rate.py --profile 2 --duration 5
```

### 3. Переключение (требует паузы!)

```bash
python3 host/diag_block_rate.py --profile 1 --duration 3 && \
sleep 3 && \
python3 host/diag_block_rate.py --profile 2 --duration 3
```

---

## Решение проблем

### Проблема: 0 кадров после обновления прошивки

**Решение:**
1. Убедитесь, что обновили `host/usb_vendor/usb_stream.py` (SET_FRAME_SAMPLES удалён для PROFILE=1).
2. Перезагрузите устройство (отсоедините USB на 5 сек).
3. Повторите тест.

### Проблема: частота не ~202 Гц

**Решение:**
1. Проверьте, что PROFILE=1 установлен (а не PROFILE=2).
2. Используйте `diag_block_rate.py` для диагностики.
3. Контактируйте разработчика прошивки.

### Проблема: кадры пропадают после переключения профилей

**Решение:**
1. Добавьте паузу ≥3 сек между переключениями.
2. Используйте `time.sleep(3)` после смены профиля.
3. (Опционально) добавьте STOP перед сменой профиля.

---

## Контакты и документация

- **Контракт:** `FIRMWARE_CONTRACT.md` — полное описание USB протокола.
- **Результаты тестирования:** `200HZ_IMPLEMENTATION_TEST.md`.
- **Сводка изменений:** `CHANGES_SUMMARY.md`.
- **Чек-лист:** `FINAL_VERIFICATION_CHECKLIST.md`.

---

## ✅ Готово к использованию!

176 Гц (PROFILE=1) и 280 Гц (PROFILE=2) — стабильно работающие профили на диагностическом уровне.
Для полного использования требуется:
1. Проверить на целевом оборудовании (RPi).
2. Тестирование GUI осциллографа.
3. Долгосрочная проверка стабильности (24+ часов).

**Текущий статус:** 🟢 **Функционально готово** (требуется финальная валидация)

---

**Версия:** 1.1 (обновлено с реальными частотами)  
**Дата:** 24.10.2025
