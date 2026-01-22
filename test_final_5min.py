#!/usr/bin/env python3
"""
РАБОЧАЯ ВЕРСИЯ - взята из test_simple_stream.py + обучение
5 МИНУТ С ПРОГРЕССОМ
"""
import sys
import os
import time
import subprocess
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

print("="*70, flush=True)
print("РАБОЧИЙ ТЕСТ ОБУЧЕНИЯ - 5 МИНУТ", flush=True)
print("="*70, flush=True)
print("⏱️  Длительность: 5 минут", flush=True)
print("📊 Прогресс каждые 15 секунд\n", flush=True)

# Сброс USB
print("Сброс USB...", flush=True)
try:
    result = subprocess.run(['sudo', 'usbreset', 'cafe:4001'], 
                          timeout=5, check=False, capture_output=True)
    print("✓ USB сброшен", flush=True)
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен", flush=True)

# Детектор
print("Создание детектора...", flush=True)
from adaptive_realtime_detector import AdaptiveRealtimeDetector
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    data_dir='./learn_test_final'
)
print("✓ Детектор создан\n", flush=True)

# USB - ТОЧНО КАК В РАБОЧЕМ test_simple_stream.py
print("📡 Создание USBStream...", flush=True)
from usb_vendor.usb_stream import USBStream
stream = USBStream(profile=1, full=True)
print("✓ USB подключен", flush=True)
print(f"✓ Устройство: {stream.dev}\n", flush=True)

# === КАЛИБРОВКА 1 МИНУТА ===
print("КАЛИБРОВКА ШУМА (60 секунд)", flush=True)
print("Уберите метки!\n", flush=True)

detector.start_calibration_session(60)

start_time = time.time()
duration = 60.0
frames = 0
last_progress = 0

while time.time() - start_time < duration:
    try:
        # ЧИТАЕМ ТОЧНО КАК В РАБОЧЕМ test_simple_stream.py
        frame0 = stream.get_frame(0, timeout=0.1)
        frame1 = stream.get_frame(1, timeout=0.1)
        
        if frame0 is not None and frame1 is not None:
            # Извлекаем данные
            if hasattr(frame0, 'data'):
                data0 = np.frombuffer(frame0.data, dtype=np.uint16)
            else:
                continue
            
            if hasattr(frame1, 'data'):
                data1 = np.frombuffer(frame1.data, dtype=np.uint16)
            else:
                continue
            
            if len(data0) >= 64 and len(data1) >= 64:
                # Вычисляем параметры
                level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
                level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
                corr_arr = np.correlate(data0.astype(float) - 32768, data1.astype(float) - 32768, 'same')
                correlation = float(np.abs(corr_arr).max())
                prod_arr = (data0.astype(float) - 32768) * (data1.astype(float) - 32768)
                product = float(np.abs(prod_arr).max())
                
                # Обучение
                detector.process_frame(level_ch0, level_ch1, correlation, product)
                frames += 1
        
        # Прогресс каждые 15 секунд
        elapsed = time.time() - start_time
        current_progress = int(elapsed / 15)
        if current_progress > last_progress:
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            print(f"{elapsed:.0f}с: {frames} фреймов | {frames/elapsed:.1f} к/с", flush=True)
            print(f"     CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}", flush=True)
            print(f"     CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}", flush=True)
            last_progress = current_progress
            
    except Exception as e:
        time.sleep(0.01)

print(f"\n✓ Калибровка: {frames} фреймов за 60с = {frames/60:.1f} к/с\n", flush=True)

# === ТЕСТ 4 МИНУТЫ ===
print("ОСНОВНОЙ ТЕСТ (240 секунд)\n", flush=True)

start_time = time.time()
duration = 240.0
frames_total = 0
detections = 0
last_progress = 0

while time.time() - start_time < duration:
    try:
        frame0 = stream.get_frame(0, timeout=0.1)
        frame1 = stream.get_frame(1, timeout=0.1)
        
        if frame0 is not None and frame1 is not None:
            if hasattr(frame0, 'data'):
                data0 = np.frombuffer(frame0.data, dtype=np.uint16)
            else:
                continue
            
            if hasattr(frame1, 'data'):
                data1 = np.frombuffer(frame1.data, dtype=np.uint16)
            else:
                continue
            
            if len(data0) >= 64 and len(data1) >= 64:
                level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
                level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
                corr_arr = np.correlate(data0.astype(float) - 32768, data1.astype(float) - 32768, 'same')
                correlation = float(np.abs(corr_arr).max())
                prod_arr = (data0.astype(float) - 32768) * (data1.astype(float) - 32768)
                product = float(np.abs(prod_arr).max())
                
                detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
                    level_ch0, level_ch1, correlation, product
                )
                frames_total += 1
                
                if detected_ch0 or detected_ch1:
                    detections += 1
        
        # Прогресс каждые 30 секунд
        elapsed = time.time() - start_time
        current_progress = int(elapsed / 30)
        if current_progress > last_progress:
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            buf = stats['buffer_averaging']
            print(f"{elapsed:.0f}с: {frames_total} фреймов | {detections} детекций | {frames_total/elapsed:.1f} к/с", flush=True)
            print(f"     CH0: {nc['ch0']['threshold']:.0f} | CH1: {nc['ch1']['threshold']:.0f} | Буферы: {buf['current_buffers']}", flush=True)
            last_progress = current_progress
            
    except Exception as e:
        time.sleep(0.01)

# === РЕЗУЛЬТАТ ===
print(f"\n{'='*70}", flush=True)
print("✅ ЗАВЕРШЕНО", flush=True)
print(f"{'='*70}\n", flush=True)

total_frames = frames + frames_total
stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']
det = stats['detection']
buf = stats['buffer_averaging']

print(f"Время: 5 минут (300 сек)", flush=True)
print(f"Калибровка: {frames} фреймов", flush=True)
print(f"Тест: {frames_total} фреймов, {detections} детекций", flush=True)
print(f"ВСЕГО: {total_frames} фреймов = {total_frames/300:.1f} кадр/сек\n", flush=True)

print(f"Калибровка шума:", flush=True)
print(f"  Образцов: {nc['samples_collected']}", flush=True)
print(f"  CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}", flush=True)
print(f"  CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}\n", flush=True)

print(f"Детекция:", flush=True)
print(f"  Шум: {det['noise_frames']}", flush=True)
print(f"  Метки: {det['marker_frames']}", flush=True)
print(f"  Ложные: {det['false_positives']}\n", flush=True)

print(f"Буферы: {buf['current_buffers']} (оптимум: {buf['optimal_buffers']})\n", flush=True)

# Проверка
if total_frames < 45000:
    print(f"⚠️  МАЛО ФРЕЙМОВ: {total_frames} (ожидалось ~54000)", flush=True)
    print("Проверьте USB\n", flush=True)
else:
    print(f"✅ ВСЁ РАБОТАЕТ ОТЛИЧНО!", flush=True)
    print("Поток стабильный, обучение происходит", flush=True)
    print("ГОТОВО ДЛЯ ЗАПУСКА НА 2 СУТОК\n", flush=True)

detector.save_calibration('./learn_test_final.json')
print(f"💾 Данные: {detector.data_store.data_dir}", flush=True)
print(f"💾 Калибровка: ./learn_test_final.json\n", flush=True)

# Остановка
try:
    stream.send_cmd(0x21, b'')
except:
    pass

print(f"{'='*70}\n", flush=True)
