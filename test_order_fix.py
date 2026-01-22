#!/usr/bin/env python3
"""
Тест: создание USBStream ПЕРЕД детектором
"""

import sys
import os
import time
import subprocess
import numpy as np
from pathlib import Path

# Импорт модулей USB
host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from usb_vendor.usb_stream import USBStream

print("=" * 70)
print("ТЕСТ ПОРЯДКА ИНИЦИАЛИЗАЦИИ")
print("=" * 70)
print("📌 USB создается ПЕРЕД детектором")
print()

# 1. СНАЧАЛА сбросить и создать USB
print("1️⃣  Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("✓ USB сброшен")
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен")

print("\n2️⃣  Создание USBStream...")
stream = USBStream(profile=1, full=True)
dev = stream.dev
print(f"✓ USB подключен")
print(f"✓ Устройство: {dev}")

# 2. ПОТОМ создать детектор
print("\n3️⃣  Создание детектора...")
from adaptive_realtime_detector import AdaptiveRealtimeDetector
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    use_multiprocessing=False,  # ОТКЛЮЧИТЬ multiprocessing!
    auto_save_interval=None  # Без автосохранения
)
print("✓ Детектор создан")

# 3. Тест чтения
print("\n4️⃣  Чтение фреймов 10 секунд...")
start = time.time()
count = 0
while time.time() - start < 10:
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        count += 1
        if count % 500 == 0:
            print(f"   Фреймов: {count}")

print(f"\n✅ Получено {count} фреймов за 10 секунд")
print(f"   Скорость: {count/10:.1f} кадр/сек")

stream.stop()
