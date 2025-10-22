#!/usr/bin/env python3
"""
Простой триггер START_STREAM по USB Vendor (Bulk OUT 0x03), без COM.
Использование:
  python vendor_usb_start_only.py 0xCAFE 0x4001
Аргументы VID/PID принимаются в hex (0x....) или десятичном виде.
Требования: PyUSB + libusb (Windows: WinUSB через Zadig для Vendor-интерфейса).
"""
from __future__ import annotations
import sys, time

try:
    import usb.core, usb.util  # type: ignore
except Exception as e:
    print(f"[ERR] PyUSB not installed: {e}\n  pip install pyusb")
    sys.exit(2)

EP_OUT_EXPECT = 0x03
EP_IN_EXPECT = 0x83

CMD_START = 0x20


def parse_vid_pid(argv):
    def p(x: str) -> int:
        x = x.strip().lower()
        if x.startswith('0x'):
            return int(x, 16)
        return int(x)
    if len(argv) >= 3:
        return p(argv[1]), p(argv[2])
    return 0xCAFE, 0x4001


def find_iface_with_eps(dev, want_out=EP_OUT_EXPECT, want_in=EP_IN_EXPECT):
    cfg = dev.get_active_configuration()
    best = None
    for intf in cfg:  # type: ignore
        eps = list(intf.endpoints())
        addrs = [e.bEndpointAddress for e in eps]
        if want_out in addrs and want_in in addrs:
            best = (intf, want_out, want_in)
            break
    if best is None:
        # fallback: любой vendor intf с bulk in/out
        for intf in cfg:  # type: ignore
            cls = getattr(intf, 'bInterfaceClass', None)
            if cls != 0xFF:
                continue
            eps = list(intf.endpoints())
            outs = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2]
            ins  = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) != 0 and (e.bmAttributes & 0x03) == 2]
            if outs and ins:
                best = (intf, outs[0], ins[0])
                break
    return best


def detach_if_needed(dev, intf_num: int):
    # На Linux может быть привязан драйвер — мягко отцепим
    try:
        if dev.is_kernel_driver_active(intf_num):
            try:
                dev.detach_kernel_driver(intf_num)
            except Exception:
                pass
    except Exception:
        pass


def main(argv):
    vid, pid = parse_vid_pid(argv)
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        print(f"[ERR] device {vid:04X}:{pid:04X} not found")
        return 2
    # set configuration if needed
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError:
        dev.set_configuration()
        cfg = dev.get_active_configuration()
    info = find_iface_with_eps(dev)
    if info is None:
        print(f"[ERR] no vendor interface with EPs OUT 0x{EP_OUT_EXPECT:02X} / IN 0x{EP_IN_EXPECT:02X}")
        return 3
    intf, ep_out, ep_in = info
    detach_if_needed(dev, intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    try:
        # START
        n = dev.write(ep_out, bytes([CMD_START]), timeout=1000)
        print(f"[START] sent 0x{CMD_START:02X} to EP 0x{ep_out:02X}, n={n}")
        # Небольшая пауза, чтобы устройство успело отправить тест/первые кадры
        time.sleep(0.05)
        print("[OK] START triggered. Смотрите лог устройства на первые [VND_TX] строки.")
        return 0
    except usb.core.USBError as e:
        print(f"[ERR] bulk write failed: {e}")
        return 4
    finally:
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main(sys.argv))
