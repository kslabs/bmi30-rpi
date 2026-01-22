#!/usr/bin/env python3
"""
РАБОЧИЙ ТЕСТ - 5 МИНУТ обучения
Правильный порядок инициализации:
1. USB ПЕРЕД детектором
2. Multiprocessing ОТКЛЮЧЕН
"""

import sys
import os
import time
import subprocess
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from usb_vendor.usb_stream import USBStream
from adaptive_realtime_detector import AdaptiveRealtimeDetector

print("=" * 70)
print("РАБОЧИЙ ТЕСТ - 5 МИНУТ ОБУЧЕНИЯ")
print("=" * 70)
print("⏱️  Длительность: 5 минут (300 секунд)")
print("📊 Калибровка шума: 60 секунд")
print("🔬 Тестирование: 240 секунд")
print()

# 1. Сброс USB
print("1️⃣  Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("✓ USB сброшен")
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен")

# 2. Создание USBStream (СНАЧАЛА!)
print("\n2️⃣  Создание USBStream...")
stream = USBStream(profile=1, full=True)
print(f"✓ USB подключен")
print(f"✓ Устройство: {stream.dev}")

# 3. Создание детектора (ПОСЛЕ USB!)
print("\n3️⃣  Создание детектора...")
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    use_multiprocessing=False,  # ВАЖНО: отключить!
    auto_save_interval=None
)
print("✓ Детектор создан")

# 4. Калибровка шума (60 секунд)
print("\n" + "=" * 70)
print("КАЛИБРОВКА ШУМА (60 секунд)")
print("=" * 70)
print("⚠️  УБЕРИТЕ ВСЕ МЕТКИ!")
print()

calibration_start = time.time()
calibration_frames = 0

while time.time() - calibration_start < 60:
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        # Извлечение данных - ПРАВИЛЬНО!
        n_samples = min(frame0.samples, frame1.samples, 128)
        data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
        data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
        
        # Извлечение параметров (как в BMI30.200.py)
        level_ch0 = np.max(data0)
        level_ch1 = np.max(data1)
        
        corr = np.correlate(data0.astype(float), data1.astype(float), mode='valid')
        correlation = float(np.abs(corr[0]))
        
        product = float(np.abs(int(data0[0]) * int(data1[0])))
        
        # Калибровка
        detector.noise_calibrator.add_sample(level_ch0, level_ch1, correlation, product)
        calibration_frames += 1
        
        # Прогресс каждые 15 секунд
        elapsed = time.time() - calibration_start
        if calibration_frames % 2700 == 0:  # ~15 сек при 180 fps
            print(f"   {elapsed:.0f}с | Фреймов: {calibration_frames}")

detector.calibration_complete = True
detector.auto_calibration_mode = False

print(f"\n✅ Калибровка завершена")
print(f"   Фреймов: {calibration_frames}")
print(f"   Калибратор готов к работе")

# 5. Тестирование (240 секунд = 4 минуты)
print("\n" + "=" * 70)
print("ТЕСТИРОВАНИЕ (240 секунд)")
print("=" * 70)
print("📡 Детектор работает, можно подносить метки")
print()

test_start = time.time()
test_frames = 0
detections_ch0 = 0
detections_ch1 = 0

while time.time() - test_start < 240:
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        # Извлечение данных - ПРАВИЛЬНО!
        n_samples = min(frame0.samples, frame1.samples, 128)
        data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
        data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
        
        level_ch0 = np.max(data0)
        level_ch1 = np.max(data1)
        
        corr = np.correlate(data0.astype(float), data1.astype(float), mode='valid')
        correlation = float(np.abs(corr[0]))
        
        product = float(np.abs(int(data0[0]) * int(data1[0])))
        
        # Детекция
        detected_ch0, detected_ch1, conf_ch0, conf_ch1 = detector.process_frame(
            level_ch0, level_ch1, correlation, product
        )
        test_frames += 1
        
        if detected_ch0:
            detections_ch0 += 1
        if detected_ch1:
            detections_ch1 += 1
        
        # Прогресс каждые 30 секунд
        elapsed = time.time() - test_start
        if test_frames % 5400 == 0:  # ~30 сек при 180 fps
            print(f"   {elapsed:.0f}с | Фреймов: {test_frames} | Детекций CH0: {detections_ch0} | CH1: {detections_ch1}")

print(f"\n✅ Тест завершен")
print(f"   Фреймов: {test_frames}")
print(f"   Детекций CH0: {detections_ch0}")
print(f"   Детекций CH1: {detections_ch1}")

# Итоговая статистика
print("\n" + "=" * 70)
print("ИТОГОВАЯ СТАТИСТИКА")
print("=" * 70)
total_frames = calibration_frames + test_frames
total_time = 300
print(f"   Всего фреймов: {total_frames}")
print(f"   Средняя скорость: {total_frames/total_time:.1f} кадр/сек")
print(f"   Детекций CH0: {detections_ch0}")
print(f"   Детекций CH1: {detections_ch1}")
print()

print("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО!")
