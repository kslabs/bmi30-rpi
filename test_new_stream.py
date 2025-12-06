#!/usr/bin/env python3
"""
Test new streaming interface (0x81) vs current implementation
"""
import usb.core
import usb.util
import struct
import time

VID, PID = 0xCAFE, 0x4001

def test_endpoint_81():
    """Test if endpoint 0x81 responds"""
    print("=== Testing Endpoint 0x81 (New Stream) ===")
    
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if not dev:
        print("✗ Device not found")
        return False
    
    try:
        # Detach kernel driver if attached
        for cfg in dev:
            for intf in cfg:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                        print(f"✓ Detached kernel driver from interface {intf.bInterfaceNumber}")
                    except:
                        pass
        
        dev.set_configuration()
        print("✓ Device configured")
        
        # Try reading from 0x81
        print("→ Attempting read from 0x81...")
        data = dev.read(0x81, 64, timeout=1000)
        print(f"✓ Got {len(data)} bytes from 0x81")
        print(f"  Data: {data[:16].hex()}")
        return True
        
    except usb.core.USBTimeoutError:
        print("✗ Timeout on 0x81 - endpoint not streaming")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_endpoint_83():
    """Test if endpoint 0x83 responds (current implementation)"""
    print("\n=== Testing Endpoint 0x83 (Current Vendor) ===")
    
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if not dev:
        print("✗ Device not found")
        return False
    
    try:
        # Detach kernel driver if attached
        for cfg in dev:
            for intf in cfg:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                    except:
                        pass
        
        dev.set_configuration()
        
        # Send START command on 0x03
        CMD_START_STREAM = 0x20
        dev.write(0x03, bytes([CMD_START_STREAM, 0]))
        time.sleep(0.1)
        
        print("→ Sent START_STREAM command")
        print("→ Attempting read from 0x83...")
        
        data = dev.read(0x83, 512, timeout=1000)
        print(f"✓ Got {len(data)} bytes from 0x83")
        print(f"  Data: {data[:16].hex()}")
        return True
        
    except usb.core.USBTimeoutError:
        print("✗ Timeout on 0x83")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == '__main__':
    print("BMI30 Endpoint Test\n")
    
    ep81_works = test_endpoint_81()
    ep83_works = test_endpoint_83()
    
    print("\n=== Summary ===")
    print(f"Endpoint 0x81 (new stream): {'✓ Working' if ep81_works else '✗ Not working'}")
    print(f"Endpoint 0x83 (current):     {'✓ Working' if ep83_works else '✗ Not working'}")
    
    if ep81_works:
        print("\n→ Device supports new streaming! Use USB_stream_receiver.py")
    elif ep83_works:
        print("\n→ Device uses current vendor protocol. Use BMI30.200.py")
    else:
        print("\n→ Device not responding on either endpoint")
