#!/usr/bin/env python3
"""
Quick test for USB streaming
"""

import usb.core
import usb.util
import struct
import time
import numpy as np

VID, PID = 0xCAFE, 0x4001
ENDPOINT_IN = 0x83  # Bulk IN endpoint
STREAM_PACKET_SIZE = 64  # USB Full-Speed Bulk max packet size (2048/64 = 32 packets per buffer)
STREAM_SAMPLES_PER_CHANNEL = 1000

def crc16_ccitt(data, crc=0xFFFF):
    """Compute CRC16-CCITT checksum"""
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc

def test_stream():
    print("=" * 60)
    print("BMI30 USB Stream Test")
    print("=" * 60)
    
    # Connect
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if not dev:
        print(f"✗ Device not found (VID={VID:04X}, PID={PID:04X})")
        return False
    
    print(f"✓ Device found: {dev}")
    dev.set_configuration()
    print("✓ Configuration set")
    
    # Read packets
    packets_ok = 0
    packets_crc_err = 0
    start_time = time.time()
    last_id = -1
    total_bytes = 0
    
    print("\n[*] Reading packets for 10 seconds...")
    print("-" * 60)
    
    try:
        while time.time() - start_time < 10:
            try:
                # Read packet
                data = dev.read(ENDPOINT_IN, STREAM_PACKET_SIZE, timeout=2000)
                
                if len(data) < 6:
                    print(f"⚠ Packet too short: {len(data)} bytes")
                    continue
                
                # Parse
                buffer_id = struct.unpack_from('<I', data, 0)[0]
                crc_rx = struct.unpack_from('<H', data, 4)[0]
                
                # Compute CRC
                data_crc = bytearray(data)
                struct.pack_into('<H', data_crc, 4, 0)
                crc_computed = crc16_ccitt(data_crc)
                
                total_bytes += len(data)
                
                if crc_rx != crc_computed:
                    packets_crc_err += 1
                    print(f"✗ CRC Error: ID={buffer_id} RX={crc_rx:04X} COM={crc_computed:04X}")
                    continue
                
                packets_ok += 1
                
                # Check sequence
                if last_id >= 0:
                    expected = (last_id + 1) & 0xFFFFFFFF
                    if buffer_id != expected:
                        print(f"⚠ Dropped packets: {expected} -> {buffer_id}")
                
                last_id = buffer_id
                
                # Parse data
                offset = 6
                adc1 = np.zeros(STREAM_SAMPLES_PER_CHANNEL, dtype=np.uint16)
                adc2 = np.zeros(STREAM_SAMPLES_PER_CHANNEL, dtype=np.uint16)
                
                for i in range(STREAM_SAMPLES_PER_CHANNEL):
                    adc1[i] = struct.unpack_from('<H', data, offset + i*4)[0]
                    adc2[i] = struct.unpack_from('<H', data, offset + i*4 + 2)[0]
                
                # Print first packet in detail, then every 10th
                if packets_ok == 1 or packets_ok % 10 == 0:
                    print(f"[{packets_ok:2d}] ID={buffer_id:6d} "
                          f"ADC1: {adc1[0]:4d}-{adc1[-1]:4d}  "
                          f"ADC2: {adc2[0]:4d}-{adc2[-1]:4d}  "
                          f"CRC={crc_rx:04X}✓")
                
            except usb.core.USBTimeoutError:
                pass
            except Exception as e:
                print(f"✗ Read error: {e}")
                break
    
    except KeyboardInterrupt:
        print("\n[Interrupted by user]")
    
    # Stats
    elapsed = time.time() - start_time
    throughput_mbps = (total_bytes * 8) / (elapsed * 1_000_000)
    
    print("-" * 60)
    print(f"\n[RESULTS]")
    print(f"  Packets OK:        {packets_ok}")
    print(f"  CRC Errors:        {packets_crc_err}")
    print(f"  Total bytes:       {total_bytes}")
    print(f"  Time:              {elapsed:.2f} s")
    print(f"  Throughput:        {throughput_mbps:.3f} Mbps")
    print(f"  Packet rate:       {packets_ok/elapsed:.1f} pps")
    print()
    
    return packets_ok > 0

if __name__ == '__main__':
    try:
        success = test_stream()
        exit(0 if success else 1)
    except Exception as e:
        print(f"✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
