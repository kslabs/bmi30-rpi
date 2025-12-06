#!/usr/bin/env python3
"""
Simple USB streaming test - receive 512-byte packets
Tests basic USB transmission before scaling up
"""

import usb.core
import usb.util
import sys
import time
import struct

# Device info
VID = 0xCAFE
PID = 0x4001
ENDPOINT_IN = 0x83
TIMEOUT = 5000  # 5 seconds

def find_device():
    """Find and open BMI30 device"""
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("[!] Device not found")
        return None
    
    print(f"[✓] Found device: {VID:04X}:{PID:04X}")
    
    # Set configuration
    dev.set_configuration()
    return dev

def read_packet(dev):
    """Read 512-byte packet from endpoint"""
    try:
        data = dev.read(ENDPOINT_IN, 512, timeout=TIMEOUT)
        return bytes(data)
    except usb.core.USBError as e:
        print(f"[!] USB Error: {e}")
        return None

def parse_packet(data):
    """Parse simple packet"""
    if len(data) < 8:
        print(f"[!] Packet too short: {len(data)} bytes")
        return None
    
    packet_id = struct.unpack('<I', data[0:4])[0]
    timestamp = struct.unpack('<I', data[4:8])[0]
    payload = data[8:512]
    
    return {
        'packet_id': packet_id,
        'timestamp': timestamp,
        'payload_len': len(payload)
    }

def main():
    print("=" * 60)
    print("Simple USB Streaming Test - 512 bytes")
    print("=" * 60)
    
    dev = find_device()
    if dev is None:
        sys.exit(1)
    
    print("\n[*] Waiting for packets (press Ctrl+C to stop)...\n")
    
    packet_count = 0
    start_time = time.time()
    
    try:
        while True:
            data = read_packet(dev)
            if data is None:
                continue
            
            pkt = parse_packet(data)
            if pkt is None:
                continue
            
            packet_count += 1
            elapsed = time.time() - start_time
            
            # Display packet info
            print(f"[RX] Packet #{pkt['packet_id']:04d} | "
                  f"T={pkt['timestamp']:8d}ms | "
                  f"Payload={pkt['payload_len']} bytes | "
                  f"Total: {packet_count} packets in {elapsed:.1f}s")
            
            # Check data integrity
            payload = data[8:512]
            if payload[0] != 0xFF:
                print(f"[!] Data corruption detected!")
                print(f"    Expected first byte: 0xFF, got: 0x{payload[0]:02X}")
    
    except KeyboardInterrupt:
        print(f"\n\n[*] Test stopped by user")
    except Exception as e:
        print(f"[!] Error: {e}")
    
    print("\n" + "=" * 60)
    print(f"Total packets received: {packet_count}")
    elapsed = time.time() - start_time
    print(f"Elapsed time: {elapsed:.1f}s")
    if elapsed > 0:
        print(f"Average rate: {packet_count / elapsed:.2f} pkt/s")
        print(f"Average throughput: {packet_count * 512 / elapsed / 1024:.2f} KB/s")
    print("=" * 60)

if __name__ == "__main__":
    main()
