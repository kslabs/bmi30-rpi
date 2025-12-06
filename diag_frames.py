#!/usr/bin/env python3
"""
Diagnostic: print raw frames to see adc_id and seq patterns
"""
from usb_vendor.usb_stream import USBStream
import time
import sys

stream = USBStream(profile=1, full=True, frame_samples=912, fast_mode=True)
print("✓ Stream opened")

# Raw reader - bypass StereoAssembler
frames_seen = []
start = time.time()

for _ in range(200):  # Collect 200 frames
    try:
        f = stream.rx_queue.get(timeout=0.1)
        frames_seen.append((f.seq, f.adc_id, len(f.payload), f.timestamp))
    except:
        continue

print(f"\nCollected {len(frames_seen)} frames in {time.time() - start:.1f}s")
print("\nseq  adc_id  payload_bytes  timestamp")
print("=" * 50)
for seq, adc_id, payload_len, ts in frames_seen[:40]:  # Show first 40
    print(f"{seq:3d}  {adc_id}       {payload_len:5d}        {ts}")

# Analyze pattern
adc0_seqs = [seq for seq, adc, _, _ in frames_seen if adc == 0]
adc1_seqs = [seq for seq, adc, _, _ in frames_seen if adc == 1]

print(f"\n=== Analysis ===")
print(f"ADC0 frames: {len(adc0_seqs)}")
print(f"ADC1 frames: {len(adc1_seqs)}")
if adc0_seqs:
    print(f"ADC0 seq range: {min(adc0_seqs)} - {max(adc0_seqs)}")
if adc1_seqs:
    print(f"ADC1 seq range: {min(adc1_seqs)} - {max(adc1_seqs)}")

print(f"\nFirst 10 ADC0 seqs: {adc0_seqs[:10]}")
print(f"First 10 ADC1 seqs: {adc1_seqs[:10]}")

stream.close()
