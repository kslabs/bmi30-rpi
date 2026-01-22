#!/usr/bin/env python3
"""РАБОЧИЙ ТЕСТ 5 МИНУТ - на основе test_simple_stream.py который работал"""
import sys, os, time, subprocess, numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'host'))

print("\n=== РАБОЧИЙ ТЕСТ 5 МИНУТ ===\n", flush=True)

# Сброс
subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, capture_output=True)
print("✓ USB сброшен", flush=True)
time.sleep(2)

# Детектор
from adaptive_realtime_detector import AdaptiveRealtimeDetector
detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64, data_dir='./learn_test')
print("✓ Детектор создан", flush=True)

# USB - КАК В РАБОЧЕМ test_simple_stream.py
from usb_vendor.usb_stream import USBStream
stream = USBStream(profile=1, full=True)
print(f"✓ USB: {stream.dev}", flush=True)
print("\nКАЛИБРОВКА 60 сек:\n", flush=True)

# Калибровка
detector.start_calibration_session(60)
start = time.time()
frames = 0
last = start

while time.time() - start < 60:
    try:
        # ЧИТАЕМ ТАКЖЕ КАК В РАБОЧЕМ test_simple_stream.py
        f0 = stream.get_frame(0, timeout=0.1)
        f1 = stream.get_frame(1, timeout=0.1)
        
        # Проверяем что получили
        if f0 is not None and f1 is not None:
            if hasattr(f0, 'data') and hasattr(f1, 'data'):
                d0 = np.frombuffer(f0.data, dtype=np.uint16)
                d1 = np.frombuffer(f1.data, dtype=np.uint16)
                
                if len(d0) >= 64 and len(d1) >= 64:
                    # Обработка
                    l0 = float(np.abs(d0.astype(float) - 32768).max())
                    l1 = float(np.abs(d1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                    prod = float(np.abs((d0.astype(float) - 32768) * (d1.astype(float) - 32768)).max())
                    
                    detector.process_frame(l0, l1, corr, prod)
                    frames += 1
        
        # Прогресс каждые 10 сек
        if time.time() - last >= 10:
            elapsed = time.time() - start
            print(f"{int(elapsed):2d}с: {frames:5d} фреймов | {frames/elapsed:.1f} к/с", flush=True)
            last = time.time()
    except Exception as e:
        if frames % 1000 == 0 and frames > 0:
            print(f"Ошибка: {e}", flush=True)
        time.sleep(0.01)

print(f"\n✓ Калибровка: {frames} фреймов | {frames/60:.1f} к/с\n", flush=True)

# Тест 4 минуты
print("ТЕСТ 240 сек:\n", flush=True)

start = time.time()
test_frames = 0
dets = 0
last = start

while time.time() - start < 240:
    try:
        f0 = stream.get_frame(0, timeout=0.1)
        f1 = stream.get_frame(1, timeout=0.1)
        
        if f0 is not None and f1 is not None:
            if hasattr(f0, 'data') and hasattr(f1, 'data'):
                d0 = np.frombuffer(f0.data, dtype=np.uint16)
                d1 = np.frombuffer(f1.data, dtype=np.uint16)
                
                if len(d0) >= 64 and len(d1) >= 64:
                    l0 = float(np.abs(d0.astype(float) - 32768).max())
                    l1 = float(np.abs(d1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                    prod = float(np.abs((d0.astype(float) - 32768) * (d1.astype(float) - 32768)).max())
                    
                    det0, det1, _, _ = detector.process_frame(l0, l1, corr, prod)
                    test_frames += 1
                    
                    if det0 or det1:
                        dets += 1
        
        # Прогресс каждые 15 сек
        if time.time() - last >= 15:
            elapsed = time.time() - start
            print(f"{int(elapsed):3d}с: {test_frames:6d} фреймов | {dets:4d} детекций | {test_frames/elapsed:.1f} к/с", flush=True)
            last = time.time()
    except Exception as e:
        if test_frames % 1000 == 0 and test_frames > 0:
            print(f"Ошибка: {e}", flush=True)
        time.sleep(0.01)

# Результат
total = frames + test_frames
print(f"\n{'='*70}", flush=True)
print(f"ЗАВЕРШЕНО", flush=True)
print(f"{'='*70}\n", flush=True)

print(f"Калибровка: {frames} фреймов", flush=True)
print(f"Тест: {test_frames} фреймов, {dets} детекций", flush=True)
print(f"Всего: {total} фреймов = {total/300:.1f} к/с\n", flush=True)

stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']

print(f"Калибровка:", flush=True)
print(f"  CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}", flush=True)
print(f"  CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}\n", flush=True)

# Проверка
if total < 45000:
    print(f"⚠️  Мало фреймов ({total} < 45000)", flush=True)
    print(f"Проверьте USB\n", flush=True)
else:
    print(f"✅ ВСЁ РАБОТАЕТ!", flush=True)
    print(f"Поток стабильный, обучение идёт", flush=True)
    print(f"МОЖНО ЗАПУСКАТЬ НА 2 СУТОК\n", flush=True)

detector.save_calibration('./learn_test.json')
print(f"💾 Сохранено: ./learn_test.json\n", flush=True)

try:
    stream.send_cmd(0x21, b'')
except:
    pass
