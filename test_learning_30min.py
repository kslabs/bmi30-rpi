#!/usr/bin/env python3
"""
БЫСТРЫЙ ТЕСТ обучения - 30 минут
Проверяет что система работает перед длительным запуском
"""

import sys
import os
import time
import signal
import subprocess
from datetime import datetime
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector

running = True

def signal_handler(sig, frame):
    global running
    print("\n\n⚠️  Остановка...")
    running = False

signal.signal(signal.SIGINT, signal_handler)

print("=" * 70)
print("БЫСТРЫЙ ТЕСТ ОБУЧЕНИЯ (30 минут)")
print("=" * 70)
print("⏱️  Длительность: 30 минут")
print("📊 Статистика: Каждые 5 минут")
print("💾 Автосохранение включено\n")

# Сброс USB
print("🔌 Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("✓ Сброс выполнен")
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен")

# Создание детектора
print("\n📊 Создание детектора...")
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    data_dir='./adaptive_data_test_30min'
)
print("✓ Детектор создан\n")

# Подключение USB
print("📡 Подключение к USB...")
try:
    from usb_vendor.usb_stream import USBStream
    stream = USBStream(profile=1, full=True)
    print(f"✓ USB подключен\n")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    sys.exit(1)

# Калибровка 2 минуты
print("🔧 Калибровка шума (2 минуты)...")
print("⚠️  Уберите метки из зоны!\n")

detector.start_calibration_session(120)
start = time.time()
frames = 0

while (time.time() - start < 120) and running:
    try:
        frame0 = stream.get_frame(0, timeout=0.2)
        frame1 = stream.get_frame(1, timeout=0.2)
        
        if frame0 and frame1:
            data0 = np.frombuffer(frame0.data, dtype=np.uint16) if hasattr(frame0, 'data') else np.zeros(64, dtype=np.uint16)
            data1 = np.frombuffer(frame1.data, dtype=np.uint16) if hasattr(frame1, 'data') else np.zeros(64, dtype=np.uint16)
            
            level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
            level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
            corr = float(np.abs(np.correlate(data0 - 32768, data1 - 32768, 'same')).max())
            prod = float(np.abs((data0 - 32768) * (data1 - 32768)).max())
            
            detector.process_frame(level_ch0, level_ch1, corr, prod)
            frames += 1
            
            if frames % 5000 == 0:
                elapsed = time.time() - start
                print(f"   {elapsed:.0f}с | Фреймов: {frames} | {frames/elapsed:.1f} кадр/сек")
    except:
        time.sleep(0.01)

print(f"\n✓ Калибровка завершена: {frames} фреймов\n")

# Основной тест 28 минут
print("🎓 ОСНОВНОЕ ОБУЧЕНИЕ (28 минут)\n")

start = time.time()
last_stats = start
frames_total = 0
detections = 0

try:
    while (time.time() - start < 1680) and running:  # 28 минут
        try:
            frame0 = stream.get_frame(0, timeout=0.2)
            frame1 = stream.get_frame(1, timeout=0.2)
            
            if frame0 and frame1:
                data0 = np.frombuffer(frame0.data, dtype=np.uint16) if hasattr(frame0, 'data') else np.zeros(64, dtype=np.uint16)
                data1 = np.frombuffer(frame1.data, dtype=np.uint16) if hasattr(frame1, 'data') else np.zeros(64, dtype=np.uint16)
                
                level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
                level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
                corr = float(np.abs(np.correlate(data0 - 32768, data1 - 32768, 'same')).max())
                prod = float(np.abs((data0 - 32768) * (data1 - 32768)).max())
                
                det0, det1, c0, c1 = detector.process_frame(level_ch0, level_ch1, corr, prod)
                frames_total += 1
                
                if det0 or det1:
                    detections += 1
                
                # Статистика каждые 5 минут
                current = time.time()
                if current - last_stats >= 300:
                    elapsed_min = (current - start) / 60
                    stats = detector.get_comprehensive_stats()
                    nc = stats['noise_calibration']
                    
                    print(f"\n{'='*70}")
                    print(f"⏱️  {elapsed_min:.1f} минут | Фреймов: {frames_total} | Детекций: {detections}")
                    print(f"📏 CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
                    print(f"📏 CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")
                    print(f"⚡ Буферы: {stats['buffer_averaging']['current_buffers']}")
                    print(f"🎯 Sigma CH0: {stats['adaptive_params']['sigma_ch0']:.2f}, CH1: {stats['adaptive_params']['sigma_ch1']:.2f}")
                    print(f"{'='*70}\n")
                    
                    last_stats = current
        except:
            time.sleep(0.01)
except KeyboardInterrupt:
    print("\n⚠️  Остановлено пользователем")

# Финальная статистика
print(f"\n{'='*70}")
print("✅ ТЕСТ ЗАВЕРШЕН")
print(f"{'='*70}")

duration_min = (time.time() - start) / 60
stats = detector.get_comprehensive_stats()

print(f"\n⏱️  Время: {duration_min:.1f} минут")
print(f"📊 Фреймов: {frames_total}")
print(f"📡 Детекций: {detections}")
print(f"⚡ Скорость: {frames_total/(duration_min*60):.1f} кадр/сек")

nc = stats['noise_calibration']
print(f"\n📏 Калибровка:")
print(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
print(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")

print(f"\n💾 Данные сохранены: {detector.data_store.data_dir}")
detector.save_calibration('./adaptive_calibration_test30.json')
print(f"💾 Калибровка: ./adaptive_calibration_test30.json")

print(f"\n{'='*70}\n")

try:
    stream.send_cmd(0x21, b'')
except:
    pass
