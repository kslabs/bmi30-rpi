#!/usr/bin/env python3
"""Супер-простой тест 1 минута - проверка что вообще работает"""
import sys, os, time, subprocess
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'host'))
from adaptive_realtime_detector import AdaptiveRealtimeDetector

print("\n=== ТЕСТ 1 МИНУТА ===\n")

subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, capture_output=True)
print("✓ USB сброшен")
time.sleep(2)

detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64, data_dir='./test1min')
print("✓ Детектор создан")

from usb_vendor.usb_stream import USBStream
stream = USBStream()
print("✓ USB подключен\n")

print("Работа 60 секунд, прогресс каждые 5 сек:\n")
detector.start_calibration_session(60)

start = time.time()
frames = 0
last = start

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
        if time.time() - last >= 5:
            elapsed = time.time() - start
            print(f"{elapsed:.0f}с: {frames} фреймов, {frames/elapsed:.1f} к/с")
            last = time.time()
    except:
        time.sleep(0.01)

print(f"\n✅ ЗАВЕРШЕНО: {frames} фреймов за 60 сек = {frames/60:.1f} к/с")

stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']
print(f"CH0 порог: {nc['ch0']['threshold']:.0f}")
print(f"CH1 порог: {nc['ch1']['threshold']:.0f}\n")
