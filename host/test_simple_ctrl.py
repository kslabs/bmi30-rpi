#!/usr/bin/env python3
"""
Ultra-simple streaming test -send just one control request to trigger data
"""

import usb.core
import usb.util
import time

VID, PID = 0xCAFE, 0x4001

dev = usb.core.find(idVendor=VID, idProduct=PID)
if not dev:
    print(f"✗ Device not found")
    exit(1)

dev.set_configuration()

# Try control transfer to trigger stream
print("→ Attempting to enable streaming via control transfer...")

try:
    # Send VENDOR_OUT request to start stream
    # bmRequestType=0xC0 (vendor, device-to-host)
    # bRequest=0xA0 (custom)
    # wValue=0x0001 (enable)
    # wIndex=0 
    # wLength=0
    result = dev.ctrl_transfer(
        bmRequestType=0x40,  # Vendor, Host-to-Device
        bRequest=0xA0,  # Custom request
        wValue=0x0001,  # Enable
        wIndex=0,
        data_or_wLength=None
    )
    print(f"✓ Control transfer sent")
except Exception as e:
    print(f"✗ Control transfer failed: {e}")
    exit(1)

# Wait and try to read
print("\n→ Waiting 2 seconds...")
time.sleep(2)

print("→ Attempting bulk read...")
try:
    data = dev.read(0x83, 64, timeout=5000)
    print(f"✓ Received {len(data)} bytes")
    print(f"  First 32 bytes: {data[:32].hex()}")
except Exception as e:
    print(f"✗ Bulk read failed: {e}")
