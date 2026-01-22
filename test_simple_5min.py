#!/usr/bin/env python3
"""СУПЕР-ПРОСТОЙ ТЕСТ - показывает ЧТО происходит"""
import sys, os, time, subprocess, numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'host'))

print("\n=== ТЕСТ 5 МИНУТ ===\n", flush=True)

# Сброс
subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, capture_output=True)
print("✓ USB сброшен\n", flush=True)
time.sleep(2)

# Детектор
from adaptive_realtime_detector import AdaptiveRealtimeDetector
detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64, data_dir='./test5min')
print("✓ Детектор создан\n", flush=True)

# USB
from usb_vendor.usb_stream import USBStream
stream = USBStream()
print("✓ USB подключен\n", flush=True)

# Калибровка 1 минута
print("КАЛИБРОВКА 60 секунд:\n", flush=True)
detector.start_calibration_session(60)

start = time.time()
frames = 0
last_print = start

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
        
        # Прогресс каждые 5 сек
        now = time.time()
        if now - last_print >= 5:
            print(f"{int(now-start):2d}с: {frames:5d} фреймов | {frames/(now-start):.1f} к/с", flush=True)
            last_print = now
    except:
        time.sleep(0.01)

print(f"\n✓ Калибровка: {frames} фреймов\n", flush=True)

# Тест 4 минуты
print("ТЕСТ 240 секунд:\n", flush=True)

start = time.time()
frames_test = 0
dets = 0
last_print = start

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
                det0, det1, _, _ = detector.process_frame(l0, l1, corr, prod)
                frames_test += 1
                if det0 or det1:
                    dets += 1
        
        # Прогресс каждые 10 сек
        now = time.time()
        if now - last_print >= 10:
            print(f"{int(now-start):3d}с: {frames_test:6d} фреймов | {dets:4d} детекций | {frames_test/(now-start):.1f} к/с", flush=True)
            last_print = now
    except:
        time.sleep(0.01)

# Итог
print(f"\n{'='*70}", flush=True)
print(f"✅ ТЕСТ ЗАВЕРШЕН", flush=True)
print(f"{'='*70}", flush=True)
print(f"Калибровка: {frames} фреймов", flush=True)
print(f"Тест: {frames_test} фреймов, {dets} детекций", flush=True)
print(f"Всего: {frames+frames_test} фреймов = {(frames+frames_test)/300:.1f} к/с", flush=True)

stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']
print(f"\nПороги: CH0={nc['ch0']['threshold']:.0f}, CH1={nc['ch1']['threshold']:.0f}", flush=True)

if frames + frames_test > 45000:
    print(f"\n✅ ВСЁ РАБОТАЕТ! Можно запускать на 2 суток", flush=True)
else:
    print(f"\n⚠️  Мало фреймов - проверьте USB", flush=True)

detector.save_calibration('./test5min.json')
print(f"\n💾 Сохранено: ./test5min.json\n", flush=True)
