#!/usr/bin/env python3
"""
Тест логики even/odd обработки для детекции противофазности
"""
import numpy as np
import sys
import os

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from usb_vendor.usb_stream import USBStream
import time

# Получить несколько фреймов
stream = USBStream(profile=1, full=True)
time.sleep(0.5)

print("Тестирование Even/Odd логики...")
print("=" * 70)

for i in range(5):
    frame0 = stream.get_frame(0, timeout=0.1)
    frame1 = stream.get_frame(1, timeout=0.1)
    
    if frame0 and frame1:
        n_samples = min(frame0.samples, frame1.samples, 128)
        data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
        data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
        
        print(f"\nФрейм {i+1}:")
        print(f"  Длина: {len(data0)}")
        print(f"  CH0: min={np.min(data0)}, max={np.max(data0)}, mean={np.mean(data0):.1f}")
        print(f"  CH1: min={np.min(data1)}, max={np.max(data1)}, mean={np.mean(data1):.1f}")
        print(f"  CH0≈CH1? diff={abs(np.mean(data0) - np.mean(data1)):.1f}")
        
        # Even/Odd разделение
        data0_even = data0[::2]
        data0_odd = data0[1::2]
        
        print(f"\n  Even/Odd CH0:")
        print(f"    EVEN: len={len(data0_even)}, max={np.max(data0_even)}, mean={np.mean(data0_even):.1f}")
        print(f"    ODD:  len={len(data0_odd)}, max={np.max(data0_odd)}, mean={np.mean(data0_odd):.1f}")
        
        # СТАРАЯ логика (НЕПРАВИЛЬНАЯ)
        old_diff = abs(np.max(data0_even) - np.max(data0_odd))
        print(f"    СТАРАЯ diff (max_even - max_odd): {old_diff}")
        
        # НОВАЯ логика (ПРАВИЛЬНАЯ): посемпловая разница
        pointwise_diff = np.abs(data0_even - data0_odd)
        new_diff_mean = np.mean(pointwise_diff)
        new_diff_std = np.std(pointwise_diff)
        
        print(f"    НОВАЯ diff (mean |even[i] - odd[i]|): {new_diff_mean:.1f} ± {new_diff_std:.1f}")
        
        # Для противофазного сигнала new_diff должно быть БОЛЬШИМ
        # Для синфазного шума new_diff будет МАЛЫМ
        
        # Первые 10 точек для наглядности
        print(f"\n  Первые 10 точек CH0:")
        print(f"    Индексы even: {data0_even[:10]}")
        print(f"    Индексы odd:  {data0_odd[:10]}")
        print(f"    Diff:         {pointwise_diff[:10]}")

print("\n" + "=" * 70)
print("ВЫВОД:")
print("• СТАРАЯ логика: abs(max_even - max_odd) ≈ 0 (оба ~65535)")
print("• НОВАЯ логика: mean(|even[i] - odd[i]|) показывает фазовые отношения")
print("• Для шума: diff малый (even и odd близки)")
print("• Для сигнала: diff большой (even и odd отличаются)")
