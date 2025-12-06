#!/usr/bin/env python3
"""
Test current vendor protocol (0x83)
"""
import usb.core
import time

VID, PID = 0xCAFE, 0x4001

dev = usb.core.find(idVendor=VID, idProduct=PID)
if not dev:
    print("✗ Device not found")
    exit(1)

# Detach all kernel drivers
for cfg in dev:
    for intf in cfg:
        if dev.is_kernel_driver_active(intf.bInterfaceNumber):
            try:
                dev.detach_kernel_driver(intf.bInterfaceNumber)
                print(f"✓ Detached kernel driver from IF{intf.bInterfaceNumber}")
            except:
                pass

dev.set_configuration()
print("✓ Device configured")

# Claim vendor interface (IF#2)
usb.util.claim_interface(dev, 2)
print("✓ Claimed interface 2")

# Send START command
CMD_START_STREAM = 0x20
dev.write(0x03, bytes([CMD_START_STREAM, 0]))
print("→ Sent START_STREAM command")

time.sleep(0.2)

# Try reading
try:
    data = dev.read(0x83, 512, timeout=2000)
    print(f"✓ Got {len(data)} bytes from 0x83")
    print(f"  Header: {data[:32].hex()}")
    print("\n✓ Current vendor protocol (0x83) is WORKING!")
    print("→ Use BMI30.200.py for GUI")
except Exception as e:
    print(f"✗ Error reading: {e}")

# Release
usb.util.release_interface(dev, 2)
usb.util.dispose_resources(dev)
