# Исправление: Реальные частоты профилей BMI30

## Проблема
Документация и код указывали неправильные частоты:
- ❌ PROFILE=1 = 200 Гц (реально: 176 Гц)
- ❌ PROFILE=2 = 300 Гц (реально: 280 Гц)

## Решение (24.10.2025)

### ✅ Обновлена документация (6 файлов)
- `docs/FIRMWARE_CONTRACT.md` - таблица параметров
- `docs/QUICKSTART_200HZ.md` - примеры и таблицы
- `docs/200HZ_IMPLEMENTATION_TEST.md` - параметры
- `docs/IMPLEMENTATION_SUMMARY.md` - описание профилей
- `docs/FINAL_CHECKLIST.md` - селектор и производительность
- `docs/LAUNCH.md` - селектор частот

### ✅ Обновлен код Python (2 файла)
- `host/BMI30.200.py` (10 мест)
  - Комбобокс: "176 Hz" / "280 Hz"
  - Все сообщения статуса обновлены
  - Команды SET_BLOCK_RATE: 176/280

- `host/vendor_compliance_check.py` (1 место)
  - Комментарий в коде

### ✅ Проведено тестирование
```bash
# PROFILE=1: 175.8 Hz ≈ 176 Hz ✓
python3 host/diag_block_rate.py --profile 1 --duration 3
# → Frames: 1056, rate≈175.8Hz

# PROFILE=2: 280.4 Hz ≈ 280 Hz ✓
python3 host/diag_block_rate.py --profile 2 --duration 3
# → Frames: 1682, rate≈280.4Hz
```

## Статус
✅ **ЗАВЕРШЕНО** - Все файлы синхронизированы
✅ **ПРОТЕСТИРОВАНО** - Частоты подтверждены
✅ **ГОТОВО К ИСПОЛЬЗОВАНИЮ** - Документация и код согласованы

## Использование
```python
# 176 Гц
stream = usb_stream.BMI30(profile=1, full=True)

# 280 Гц
stream = usb_stream.BMI30(profile=2, full=True)
```

## Примечание
Эти частоты - характеристика прошивки STM32H723.
Если требуются точно 200/300 Гц - необходимо обновление прошивки.
