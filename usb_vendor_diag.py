#!/usr/bin/env python3
from __future__ import annotations
import sys, time
import usb.core, usb.util
import glob
import serial  # type: ignore

def to_hex(b: bytes, max_len: int = 64) -> str:
    if not b:
        return ''
    head = b[:max_len]
    s = ' '.join(f"{x:02X}" for x in head)
    if len(b) > max_len:
        s += f" …(+{len(b)-max_len})"
    return s

def find_dev(vid=0xCAFE, pid=0x4001):
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise SystemExit('device not found')
    return dev

# Vendor IF2, EP OUT=0x03, IN=0x83 per description
V_IF = 2
EP_OUT = 0x03
EP_IN  = 0x83

# Simple commands
CMD_START = 0x20
CMD_STOP  = 0x21
CMD_GET_STATUS = 0x30


def claim_vendor(dev):
    if dev.is_kernel_driver_active(V_IF):
        dev.detach_kernel_driver(V_IF)
    usb.util.claim_interface(dev, V_IF)


def bulk_write(dev, data: bytes, timeout=500):
    return dev.write(EP_OUT, data, timeout)


def bulk_read(dev, size=64, timeout=500):
    return bytes(dev.read(EP_IN, size, timeout))


def main():
    dev = find_dev()
    print('[usb] found device')
    # Устройство уже сконфигурировано ОС; не трогаем конфигурацию, чтобы не получить EBUSY
    try:
        _ = dev.get_active_configuration()
    except Exception:
        pass
    claim_vendor(dev)
    # Try read immediate DIAG64 'STAT' once after configuration
    for i in range(3):
        try:
            data = bulk_read(dev, 64, timeout=300)
            print(f"[usb] IN{i} len={len(data)}: {to_hex(data,64)}")
        except usb.core.USBError as e:
            print(f"[usb] IN timeout {i}: {e}")
            break
    # GET_STATUS (bulk)
    try:
        bulk_write(dev, bytes([CMD_GET_STATUS]))
        st = bulk_read(dev, 64, timeout=500)
        print(f"[usb] GET_STATUS len={len(st)}: {to_hex(st,64)}")
    except Exception as e:
        print(f"[usb] GET_STATUS err: {e}")
    # GET_STATUS (control transfer, bmReqType=0xC1, bRequest=0x30, wIndex=2)
    try:
        data = dev.ctrl_transfer(0xC1, CMD_GET_STATUS, 0, 2, 64, timeout=500)
        print(f"[usb] CTRL GET_STATUS len={len(bytes(data))}: {to_hex(bytes(data),64)}")
    except Exception as e:
        print(f"[usb] CTRL GET_STATUS err: {e}")
    # START
    try:
        bulk_write(dev, bytes([CMD_START]))
        print('[usb] START sent')
    except Exception as e:
        print(f"[usb] START err: {e}")
    # Read a few IN packets (not frames, just raw 64B chunks)
    for i in range(10):
        try:
            data = bulk_read(dev, 64, timeout=800)
            print(f"[usb] IN{i} len={len(data)}: {to_hex(data,64)}")
        except usb.core.USBError as e:
            print(f"[usb] IN timeout {i}: {e}")
            break

    # CDC bridge test: send commands via /dev/ttyACM*
    try:
        acms = sorted(glob.glob('/dev/ttyACM*'))
        if acms:
            com = acms[0]
            print(f"[cdc] sending commands via {com}")
            s = serial.Serial(com, baudrate=2000000, timeout=0.2)
            try:
                s.write(bytes([CMD_GET_STATUS])); s.flush()
                time.sleep(0.1)
                # Try to read from vendor after CDC GET_STATUS
                try:
                    data = bulk_read(dev, 64, timeout=500)
                    print(f"[usb] after-CDC GET_STATUS IN len={len(data)}: {to_hex(data,64)}")
                except Exception as e:
                    print(f"[usb] after-CDC GET_STATUS IN err: {e}")
                s.write(bytes([CMD_START])); s.flush()
                print('[cdc] START sent via CDC')
                time.sleep(0.1)
                for i in range(6):
                    try:
                        data = bulk_read(dev, 64, timeout=800)
                        print(f"[usb] after-CDC START IN{i} len={len(data)}: {to_hex(data,64)}")
                    except Exception as e:
                        print(f"[usb] after-CDC START IN timeout {i}: {e}")
                        break
            finally:
                s.close()
        else:
            print('[cdc] no /dev/ttyACM* ports found')
    except Exception as e:
        print(f"[cdc] err: {e}")

    try:
        bulk_write(dev, bytes([CMD_STOP]))
        print('[usb] STOP sent')
    except Exception as e:
        print(f"[usb] STOP err: {e}")

if __name__ == '__main__':
    main()
