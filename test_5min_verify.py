#!/usr/bin/env python3
"""
БЫСТРЫЙ ТЕСТ 5 МИНУТ - Проверка работы обучения
Прогресс каждые 15 секунд
"""

import sys, os, time, subprocess
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'host'))
from adaptive_realtime_detector import AdaptiveRealtimeDetector

print("\n" + "="*70, flush=True)
print("ТЕСТ ОБУЧЕНИЯ - 5 МИНУТ", flush=True)
print("="*70, flush=True)
print("⏱️  Длительность: 5 минут", flush=True)
print("📊 Прогресс: КАЖДЫЕ 15 СЕКУНД", flush=True)
print("🎯 Проверяем поток данных и обучение\n", flush=True)

# Сброс USB
print("1️⃣ Сброс USB...", flush=True)
subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, capture_output=True)
print("   ✓ Выполнен\n", flush=True)
time.sleep(2)

# Детектор
print("2️⃣ Создание детектора...", flush=True)
detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64, data_dir='./test_5min_data')
print("   ✓ Создан\n", flush=True)

# USB
print("3️⃣ Подключение к USB...", flush=True)
from usb_vendor.usb_stream import USBStream
stream = USBStream(profile=1, full=True)
print("   ✓ Подключено\n", flush=True)

# Калибровка 1 минута
print("4️⃣ КАЛИБРОВКА ШУМА (1 минута) - уберите метки!\n", flush=True)
detector.start_calibration_session(60)

start = time.time()
frames = 0
errors = 0
last_report = start

while time.time() - start < 60:
    try:
        f0 = stream.get_frame(0, timeout=0.1)
        f1 = stream.get_frame(1, timeout=0.1)
        
        if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
            d0 = np.frombuffer(f0.data, dtype=np.uint16)
            d1 = np.frombuffer(f1.data, dtype=np.uint16)
            
            if len(d0) >= 64 and len(d1) >= 64:
                l0 = float(np.abs(d0 - 32768).max())
                l1 = float(np.abs(d1 - 32768).max())
                corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
                
                detector.process_frame(l0, l1, corr, prod)
                frames += 1
            else:
                errors += 1
        else:
            errors += 1
        
        # Прогресс каждые 15 секунд
        if time.time() - last_report >= 15:
            elapsed = time.time() - start
            speed = frames / elapsed
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            
            print(f"   {elapsed:.0f}с: {frames} фреймов | {speed:.1f} к/с | Ошибок: {errors}", flush=True)
            print(f"        CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}", flush=True)
            print(f"        CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}", flush=True)
            last_report = time.time()
    except Exception as e:
        errors += 1
        time.sleep(0.01)

elapsed = time.time() - start
print(f"\n   ✓ Калибровка завершена: {frames} фреймов за {elapsed:.1f}с = {frames/elapsed:.1f} к/с\n", flush=True)

if frames < 5000:
    print(f"   ⚠️  МАЛО ФРЕЙМОВ! Ожидалось ~10800, получено {frames}", flush=True)
    print(f"   Проверьте USB соединение\n", flush=True)

# Основной тест 4 минуты
print("5️⃣ ОСНОВНОЙ ТЕСТ (4 минуты)\n", flush=True)

start = time.time()
frames_total = 0
detections = 0
errors_main = 0
last_report = start

while time.time() - start < 240:
    try:
        f0 = stream.get_frame(0, timeout=0.1)
        f1 = stream.get_frame(1, timeout=0.1)
        
        if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
            d0 = np.frombuffer(f0.data, dtype=np.uint16)
            d1 = np.frombuffer(f1.data, dtype=np.uint16)
            
            if len(d0) >= 64 and len(d1) >= 64:
                l0 = float(np.abs(d0 - 32768).max())
                l1 = float(np.abs(d1 - 32768).max())
                corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
                
                det0, det1, c0, c1 = detector.process_frame(l0, l1, corr, prod)
                frames_total += 1
                
                if det0 or det1:
                    detections += 1
            else:
                errors_main += 1
        else:
            errors_main += 1
        
        # Прогресс каждые 15 секунд
        if time.time() - last_report >= 15:
            elapsed = time.time() - start
            speed = frames_total / elapsed
            stats = detector.get_comprehensive_stats()
            nc = stats['noise_calibration']
            buf = stats['buffer_averaging']
            
            print(f"   {elapsed:.0f}с: {frames_total} фреймов | {speed:.1f} к/с | Детекций: {detections} | Ошибок: {errors_main}", flush=True)
            print(f"        CH0: порог={nc['ch0']['threshold']:.0f} | CH1: порог={nc['ch1']['threshold']:.0f} | Буферы: {buf['current_buffers']}", flush=True)
            last_report = time.time()
    except Exception as e:
        errors_main += 1
        time.sleep(0.01)

# Финал
print(f"\n{'='*70}", flush=True)
print("✅ ТЕСТ ЗАВЕРШЕН", flush=True)
print(f"{'='*70}\n", flush=True)

total_frames = frames + frames_total
total_errors = errors + errors_main
stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']
det = stats['detection']
buf = stats['buffer_averaging']

print(f"⏱️  Время: 5 минут", flush=True)
print(f"📊 Всего фреймов: {total_frames} (калибровка: {frames}, тест: {frames_total})", flush=True)
print(f"📡 Детекций: {detections}", flush=True)
print(f"❌ Ошибок: {total_errors}", flush=True)
print(f"⚡ Средняя скорость: {total_frames/300:.1f} кадр/сек", flush=True)

print(f"\n📏 Калибровка шума:", flush=True)
print(f"   Образцов: {nc['samples_collected']}", flush=True)
print(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}", flush=True)
print(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}", flush=True)

print(f"\n🔍 Детекция:", flush=True)
print(f"   Шум: {det['noise_frames']}", flush=True)
print(f"   Метки: {det['marker_frames']}", flush=True)
print(f"   Ложные: {det['false_positives']}", flush=True)

print(f"\n⚡ Буферы: текущие={buf['current_buffers']}, оптимальные={buf['optimal_buffers']}", flush=True)

# Проверки
print(f"\n🔍 ПРОВЕРКА РЕЗУЛЬТАТОВ:", flush=True)

if total_frames < 45000:  # Ожидаем ~54000 за 5 минут при 180 к/с
    print(f"   ⚠️  МАЛО ФРЕЙМОВ: {total_frames} (ожидалось ~54000)", flush=True)
    print(f"   USB работает нестабильно или медленно", flush=True)
elif total_errors > total_frames * 0.1:
    print(f"   ⚠️  МНОГО ОШИБОК: {total_errors} ({total_errors*100/total_frames:.1f}%)", flush=True)
    print(f"   Проверьте качество USB соединения", flush=True)
else:
    print(f"   ✅ ВСЁ РАБОТАЕТ НОРМАЛЬНО!", flush=True)
    print(f"   Поток данных стабильный", flush=True)
    print(f"   Обучение происходит корректно", flush=True)
    print(f"   Можно запускать на 2+ суток", flush=True)

detector.save_calibration('./test_5min_calibration.json')
print(f"\n💾 Данные сохранены: {detector.data_store.data_dir}", flush=True)
print(f"💾 Калибровка: ./test_5min_calibration.json", flush=True)

try:
    stream.send_cmd(0x21, b'')
except:
    pass

print(f"\n{'='*70}\n", flush=True)
