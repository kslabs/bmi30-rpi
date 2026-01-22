#!/usr/bin/env python3
"""
ПРОВЕРОЧНЫЙ ТЕСТ - 5 минут
Прогресс каждые 10 секунд - чтобы видеть что работает
"""

import sys
import os
import time
import subprocess
from datetime import datetime
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector

print("=" * 70)
print("ПРОВЕРОЧНЫЙ ТЕСТ - 5 МИНУТ")
print("=" * 70)
print("⏱️  Длительность: 5 минут")
print("📊 Прогресс: КАЖДЫЕ 10 СЕКУНД")
print("🔍 Проверяем что всё работает правильно\n")

# Сброс USB
print("1️⃣ Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("   ✓ Сброс выполнен\n")
    time.sleep(2)
except:
    print("   ⚠️  Сброс не выполнен\n")

# Детектор
print("2️⃣ Создание детектора...")
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    data_dir='./test_5min_data'
)
print("   ✓ Создан\n")

# USB
print("3️⃣ Подключение к USB...")
try:
    from usb_vendor.usb_stream import USBStream
    stream = USBStream(profile=1, full=True)
    print(f"   ✓ Подключено\n")
except Exception as e:
    print(f"   ❌ Ошибка: {e}\n")
    sys.exit(1)

# Калибровка 1 минута
print("4️⃣ КАЛИБРОВКА (1 минута) - уберите метки!\n")
detector.start_calibration_session(60)

start = time.time()
frames = 0
errors = 0
last_print = start

while time.time() - start < 60:
    try:
        # Получаем фреймы
        f0 = stream.get_frame(0, timeout=0.2)
        f1 = stream.get_frame(1, timeout=0.2)
        
        # Проверка что фреймы валидны
        if f0 is None or f1 is None:
            errors += 1
            time.sleep(0.01)
            continue
        
        if not hasattr(f0, 'data') or not hasattr(f1, 'data'):
            errors += 1
            time.sleep(0.01)
            continue
        
        # Извлекаем данные
        d0 = np.frombuffer(f0.data, dtype=np.uint16)
        d1 = np.frombuffer(f1.data, dtype=np.uint16)
        
        if len(d0) < 64 or len(d1) < 64:
            errors += 1
            time.sleep(0.01)
            continue
        
        # Вычисляем параметры
        level0 = float(np.abs(d0.astype(float) - 32768).max())
        level1 = float(np.abs(d1.astype(float) - 32768).max())
        corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
        prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
        
        # Обработка
        detector.process_frame(level0, level1, corr, prod)
        frames += 1
        
        # Прогресс КАЖДЫЕ 10 СЕКУНД
        current = time.time()
        if current - last_print >= 10:
            elapsed = current - start
            speed = frames / elapsed if elapsed > 0 else 0
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            
            print(f"   {elapsed:.0f}с | Фреймов: {frames:6d} | Ошибок: {errors:4d} | Скорость: {speed:.1f} к/с")
            print(f"        CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}")
            print(f"        CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}")
            last_print = current
            
    except Exception as e:
        errors += 1
        if errors % 100 == 0:
            print(f"   ⚠️  Ошибка #{errors}: {e}")
        time.sleep(0.01)

print(f"\n   ✓ Калибровка завершена: {frames} фреймов, {errors} ошибок\n")

# Основной тест 4 минуты
print("5️⃣ ОСНОВНОЙ ТЕСТ (4 минуты)\n")

start = time.time()
frames_total = 0
detections = 0
errors_main = 0
last_print = start

while time.time() - start < 240:  # 4 минуты
    try:
        f0 = stream.get_frame(0, timeout=0.2)
        f1 = stream.get_frame(1, timeout=0.2)
        
        if f0 is None or f1 is None:
            errors_main += 1
            time.sleep(0.01)
            continue
        
        if not hasattr(f0, 'data') or not hasattr(f1, 'data'):
            errors_main += 1
            time.sleep(0.01)
            continue
        
        d0 = np.frombuffer(f0.data, dtype=np.uint16)
        d1 = np.frombuffer(f1.data, dtype=np.uint16)
        
        if len(d0) < 64 or len(d1) < 64:
            errors_main += 1
            time.sleep(0.01)
            continue
        
        level0 = float(np.abs(d0.astype(float) - 32768).max())
        level1 = float(np.abs(d1.astype(float) - 32768).max())
        corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
        prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
        
        det0, det1, c0, c1 = detector.process_frame(level0, level1, corr, prod)
        frames_total += 1
        
        if det0 or det1:
            detections += 1
        
        # Прогресс КАЖДЫЕ 10 СЕКУНД
        current = time.time()
        if current - last_print >= 10:
            elapsed = current - start
            speed = frames_total / elapsed if elapsed > 0 else 0
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            buf = stats['buffer_averaging']
            
            print(f"   {elapsed:.0f}с | Фреймов: {frames_total:6d} | Детекций: {detections:4d} | Ошибок: {errors_main:4d} | {speed:.1f} к/с")
            print(f"        CH0: порог={nc['ch0']['threshold']:.0f} | CH1: порог={nc['ch1']['threshold']:.0f} | Буферы: {buf['current_buffers']}")
            last_print = current
            
    except Exception as e:
        errors_main += 1
        if errors_main % 100 == 0:
            print(f"   ⚠️  Ошибка #{errors_main}: {e}")
        time.sleep(0.01)

# Итог
print(f"\n{'='*70}")
print("✅ ТЕСТ ЗАВЕРШЕН")
print(f"{'='*70}\n")

total_time = (time.time() - start) / 60
total_frames = frames + frames_total
total_errors = errors + errors_main
stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']

print(f"⏱️  Время: {total_time:.1f} минут")
print(f"📊 Всего фреймов: {total_frames}")
print(f"📊 Калибровка: {frames} | Тест: {frames_total}")
print(f"📡 Детекций: {detections}")
print(f"❌ Ошибок: {total_errors}")
print(f"⚡ Средняя скорость: {total_frames/(total_time*60):.1f} кадр/сек")

print(f"\n📏 Калибровка:")
print(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
print(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")

if total_errors > total_frames * 0.1:
    print(f"\n⚠️  ВНИМАНИЕ: Много ошибок ({total_errors})! Проверьте USB.")
else:
    print(f"\n✅ Всё работает нормально!")

detector.save_calibration('./test_5min_calibration.json')
print(f"\n💾 Данные сохранены: {detector.data_store.data_dir}")

try:
    stream.send_cmd(0x21, b'')
except:
    pass

print(f"\n{'='*70}\n")
