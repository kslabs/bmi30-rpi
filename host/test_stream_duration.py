#!/usr/bin/env python3
import os, sys, time
from usb_vendor.usb_stream import USBStream, CMD_SET_PROFILE, CMD_START_STREAM, CMD_STOP_STREAM  # type: ignore

def run_test(duration_sec=60, profile=2, frame_samples=912):
    os.environ['BMI30_SEND_BLOCK_RATE'] = '1'
    print(f"[TEST] Opening USBStream(profile={profile}, frame_samples={frame_samples}, fast_mode=True)")
    us = USBStream(profile=profile, full=True, frame_samples=frame_samples, fast_mode=True)
    print("[TEST] Stream opened. Collecting...")
    start = time.monotonic()
    last_rx = start
    pairs = 0
    stalls = 0
    max_stall = 0.0
    while True:
        now = time.monotonic()
        if now - start >= duration_sec:
            break
        pair = us.get_stereo(timeout=0.2)
        if pair is None:
            # timeout
            stall = time.monotonic() - last_rx
            if stall > 1.0:
                stalls += 1
                max_stall = max(max_stall, stall)
            continue
        last_rx = time.monotonic()
        pairs += 1
        if pairs % 200 == 0:
            elapsed = now - start
            rate = pairs / elapsed if elapsed > 0 else 0.0
            print(f"[TEST] t={elapsed:.1f}s pairs={pairs} rate={rate:.1f}pps queue_ok")
    total = time.monotonic() - start
    rate = pairs / total if total > 0 else 0.0
    print(f"[TEST] DONE: duration={total:.1f}s pairs={pairs} avg_rate={rate:.1f}pps stalls={stalls} max_stall={max_stall:.2f}s")
    us.close()
    # Return success if we had a meaningful rate
    return 0 if pairs > 10 and max_stall < 3.0 else 1

if __name__ == '__main__':
    prof = int(os.getenv('TEST_PROFILE', '2'))
    dur = int(os.getenv('TEST_DURATION', '60'))
    fs = int(os.getenv('TEST_FRAME_SAMPLES', '912'))
    rc = run_test(duration_sec=dur, profile=prof, frame_samples=fs)
    sys.exit(rc)
