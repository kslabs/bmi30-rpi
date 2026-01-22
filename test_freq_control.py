#!/usr/bin/env python3
"""
Тест управления частотой буферов 200-210 Гц
"""
import sys
import os
import time

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from usb_vendor.usb_stream import USBStream

print("=" * 70)
print("ТЕСТ УПРАВЛЕНИЯ ЧАСТОТОЙ БУФЕРОВ (200-210 Гц)")
print("=" * 70)

# Подключение
stream = USBStream(profile=1, full=True)
print("✓ USB подключен\n")

# Тест установки частоты
test_freqs = [200, 203, 205, 207, 210]

for freq in test_freqs:
    print(f"Установка {freq} Гц...", end=" ", flush=True)
    try:
        stream.set_buf_rate_fine(freq)
        print("✓")
        time.sleep(0.5)  # Пауза для стабилизации
    except Exception as e:
        print(f"✗ {e}")

print("\nТест за пределами диапазона:")
for freq in [199, 211]:
    print(f"Попытка установить {freq} Гц...", end=" ", flush=True)
    try:
        stream.set_buf_rate_fine(freq)
        print("✗ Должно было вернуть ошибку!")
    except ValueError as e:
        print(f"✓ Корректная ошибка: {e}")
    except Exception as e:
        print(f"? Неожиданная ошибка: {e}")

# Возврат к 200 Гц
print(f"\nВозврат к 200 Гц...", end=" ", flush=True)
stream.set_buf_rate_fine(200)
print("✓")

stream.close()
print("\n" + "=" * 70)
print("Тест завершен!")
