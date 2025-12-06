#!/usr/bin/env python3
"""Простой тест: вывести один блок данных из потока"""

import sys
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream

# Профиль 1
print("=" * 60)
print("PROFILE=1 (200 Hz)")
print("=" * 60)

stream1 = USBStream(profile=1, full=True, fast_mode=True)
print("\n[connect] Поток открыт")

# Получим первый блок A и B
try:
    pair = stream1.get_stereo(timeout=2.0)
    if pair:
        frame_a, frame_b = pair
        print(f"\nКадр A:")
        print(f"  seq: {frame_a.seq}")
        print(f"  timestamp: {frame_a.timestamp}")
        print(f"  adc_id: {frame_a.adc_id}")
        print(f"  flags: 0x{frame_a.flags:02x}")
        print(f"  samples (total_samples): {frame_a.samples}")
        print(f"  payload len: {len(frame_a.payload)}")
        
        import numpy as np
        data_a = np.frombuffer(frame_a.payload, dtype='<i2')
        print(f"  data shape: {data_a.shape}")
        print(f"  data[:20]: {data_a[:20]}")
        print(f"  data stats: min={data_a.min()}, max={data_a.max()}, mean={data_a.mean():.1f}")
        
        print(f"\nКадр B:")
        print(f"  seq: {frame_b.seq}")
        print(f"  timestamp: {frame_b.timestamp}")
        print(f"  adc_id: {frame_b.adc_id}")
        print(f"  flags: 0x{frame_b.flags:02x}")
        print(f"  samples (total_samples): {frame_b.samples}")
        print(f"  payload len: {len(frame_b.payload)}")
        
        data_b = np.frombuffer(frame_b.payload, dtype='<i2')
        print(f"  data shape: {data_b.shape}")
        print(f"  data[:20]: {data_b[:20]}")
        print(f"  data stats: min={data_b.min()}, max={data_b.max()}, mean={data_b.mean():.1f}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

stream1.close()

print("\n" + "=" * 60)
print("PROFILE=2 (300 Hz)")
print("=" * 60)

stream2 = USBStream(profile=2, full=True, fast_mode=True)
print("\n[connect] Поток открыт")

# Получим первый блок A и B
try:
    pair = stream2.get_stereo(timeout=2.0)
    if pair:
        frame_a, frame_b = pair
        print(f"\nКадр A:")
        print(f"  seq: {frame_a.seq}")
        print(f"  timestamp: {frame_a.timestamp}")
        print(f"  adc_id: {frame_a.adc_id}")
        print(f"  flags: 0x{frame_a.flags:02x}")
        print(f"  samples (total_samples): {frame_a.samples}")
        print(f"  payload len: {len(frame_a.payload)}")
        
        import numpy as np
        data_a = np.frombuffer(frame_a.payload, dtype='<i2')
        print(f"  data shape: {data_a.shape}")
        print(f"  data[:20]: {data_a[:20]}")
        print(f"  data stats: min={data_a.min()}, max={data_a.max()}, mean={data_a.mean():.1f}")
        
        print(f"\nКадр B:")
        print(f"  seq: {frame_b.seq}")
        print(f"  timestamp: {frame_b.timestamp}")
        print(f"  adc_id: {frame_b.adc_id}")
        print(f"  flags: 0x{frame_b.flags:02x}")
        print(f"  samples (total_samples): {frame_b.samples}")
        print(f"  payload len: {len(frame_b.payload)}")
        
        data_b = np.frombuffer(frame_b.payload, dtype='<i2')
        print(f"  data shape: {data_b.shape}")
        print(f"  data[:20]: {data_b[:20]}")
        print(f"  data stats: min={data_b.min()}, max={data_b.max()}, mean={data_b.mean():.1f}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

stream2.close()

print("\n" + "=" * 60)
print("Данные получены успешно!")
print("=" * 60)
