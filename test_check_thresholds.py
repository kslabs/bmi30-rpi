#!/usr/bin/env python3
"""
Проверка порогов детектора
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
print("ПРОВЕРКА ПОРОГОВ ДЕТЕКТОРА")
print("=" * 70)

# Сброс USB
subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
time.sleep(2)

# USB
stream = USBStream(profile=1, full=True)
print(f"✓ USB подключен")

# Детектор
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    use_multiprocessing=False,
    auto_save_interval=None
)
print(f"✓ Детектор создан\n")

# Калибровка 30 секунд
print("КАЛИБРОВКА 30 СЕКУНД (без меток)")
print("-" * 70)
start = time.time()
cal_frames = 0

while time.time() - start < 30:
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        # Правильное извлечение данных
        n_samples = min(frame0.samples, frame1.samples, 128)  # используем первые 128 семплов
        data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
        data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
        
        level_ch0 = float(np.max(data0))
        level_ch1 = float(np.max(data1))
        corr = np.correlate(data0.astype(float), data1.astype(float), mode='valid')
        correlation = float(np.abs(corr[0]))
        product = float(np.abs(int(data0[0]) * int(data1[0])))
        
        detector.noise_calibrator.add_sample(level_ch0, level_ch1, correlation, product)
        cal_frames += 1

print(f"✓ Калибровано {cal_frames} фреймов\n")

# Получить статистику БЕЗ блокировки
detector.calibration_complete = True
detector.auto_calibration_mode = False

# Вывести статистику шума
print("СТАТИСТИКА ШУМА:")
print("-" * 70)
print(f"CH0 mean: {detector.noise_calibrator.noise_ch0.mean_level:.1f}")
print(f"CH0 std:  {detector.noise_calibrator.noise_ch0.std_level:.1f}")
print(f"CH0 max:  {detector.noise_calibrator.noise_ch0.max_level:.1f}")
print(f"CH1 mean: {detector.noise_calibrator.noise_ch1.mean_level:.1f}")
print(f"CH1 std:  {detector.noise_calibrator.noise_ch1.std_level:.1f}")
print(f"CH1 max:  {detector.noise_calibrator.noise_ch1.max_level:.1f}")
print(f"Corr mean: {detector.noise_calibrator.noise_combined.correlation_mean:.1f}")
print(f"Corr std:  {detector.noise_calibrator.noise_combined.correlation_std:.1f}")
print(f"Prod mean: {detector.noise_calibrator.noise_combined.product_mean:.1f}")
print(f"Prod std:  {detector.noise_calibrator.noise_combined.product_std:.1f}")

# Вычислить пороги
sigma = 3.0
thresh_ch0 = detector.noise_calibrator.get_adaptive_threshold(0, sigma)
thresh_ch1 = detector.noise_calibrator.get_adaptive_threshold(1, sigma)
thresh_corr = detector.noise_calibrator.get_correlation_threshold(sigma)
thresh_prod = detector.noise_calibrator.get_product_threshold(sigma)

print(f"\nПОРОГИ (σ={sigma}):")
print("-" * 70)
print(f"CH0 threshold:  {thresh_ch0:.1f}")
print(f"CH1 threshold:  {thresh_ch1:.1f}")
print(f"Corr threshold: {thresh_corr:.1f}")
print(f"Prod threshold: {thresh_prod:.1f}")

# Тест 10 секунд
print(f"\nТЕСТ 10 СЕКУНД:")
print("-" * 70)
start = time.time()
test_frames = 0
detections = 0
levels_ch0 = []
levels_ch1 = []

while time.time() - start < 10:
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        # Правильное извлечение данных
        n_samples = min(frame0.samples, frame1.samples, 128)
        data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
        data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
        
        level_ch0 = float(np.max(data0))
        level_ch1 = float(np.max(data1))
        corr = np.correlate(data0.astype(float), data1.astype(float), mode='valid')
        correlation = float(np.abs(corr[0]))
        product = float(np.abs(int(data0[0]) * int(data1[0])))
        
        levels_ch0.append(level_ch0)
        levels_ch1.append(level_ch1)
        
        detected_ch0, detected_ch1, conf_ch0, conf_ch1 = detector.process_frame(
            level_ch0, level_ch1, correlation, product
        )
        test_frames += 1
        
        if detected_ch0 or detected_ch1:
            detections += 1

print(f"✓ Тестировано {test_frames} фреймов")
print(f"✓ Детекций: {detections} ({100*detections/test_frames:.1f}%)")
print(f"\nУРОВНИ В ТЕСТЕ:")
print(f"CH0: min={min(levels_ch0):.0f}, max={max(levels_ch0):.0f}, mean={np.mean(levels_ch0):.0f}")
print(f"CH1: min={min(levels_ch1):.0f}, max={max(levels_ch1):.0f}, mean={np.mean(levels_ch1):.0f}")

print("\n" + "=" * 70)
if detections == test_frames:
    print("❌ ПРОБЛЕМА: Все фреймы детектированы как метки!")
    print("   Пороги слишком низкие или калибровка некорректна")
elif detections == 0:
    print("✓ ХОРОШО: Нет ложных срабатываний")
else:
    print(f"⚠️  Частичные детекции: {detections}/{test_frames}")
