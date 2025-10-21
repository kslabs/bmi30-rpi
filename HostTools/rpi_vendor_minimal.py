#!/usr/bin/env python3
import usb.core, usb.util, time, sys

VID, PID = 0xCAFE, 0x4001
OUT_EP, IN_EP = 0x03, 0x83
READ_COUNT, READ_TIMEOUT_MS = 6, 1000

def find_iface_with_eps(dev, out_ep, in_ep):
    for cfg in dev:
        for intf in cfg:
            eps = [ep.bEndpointAddress for ep in intf]
            if out_ep in eps and in_ep in eps:
                return cfg, intf
    return None, None

dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    print(f"[ERR] Device not found VID=0x{VID:04X} PID=0x{PID:04X}")
    sys.exit(1)

try:
    dev.set_configuration()
except usb.core.USBError:
    pass

cfg, intf = find_iface_with_eps(dev, OUT_EP, IN_EP)
if cfg is None:
    print("[ERR] Vendor interface (0x03/0x83) not found")
    sys.exit(2)

try:
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        dev.detach_kernel_driver(intf.bInterfaceNumber)
except Exception:
    pass
usb.util.claim_interface(dev, intf.bInterfaceNumber)

def frame_type(ba):
    if len(ba) >= 4 and ba[0:4] == b'STAT':
        return 'STAT'
    if len(ba) >= 4 and ba[0]==0x5A and ba[1]==0xA5 and ba[2]==0x01:
        flags = ba[3]
        if flags & 0x80: return 'TEST'
        if flags == 0x01: return 'A'
        if flags == 0x02: return 'B'
    return 'UNK'

# START
dev.write(OUT_EP, bytes([0x20]), timeout=1000)
print("[HOST] START sent")

# Пример: запросить mid-stream статус сразу после START:
# dev.write(OUT_EP, bytes([0x30]), timeout=1000)

got, t0 = 0, time.time()
while got < READ_COUNT and (time.time() - t0) < 10:
    try:
        buf = dev.read(IN_EP, 512, timeout=READ_TIMEOUT_MS)
        ba = bytes(buf)
        print(f"[HOST_RX] len={len(ba)} type={frame_type(ba)} head={' '.join(f'{b:02X}' for b in ba[:4])}")
        got += 1
    except usb.core.USBError as e:
        if 'timed out' in str(e).lower():
            print("[HOST_RX] timeout")
            continue
        print(f"[HOST_RX][ERR] {e}")
        break

# STOP
try:
    dev.write(OUT_EP, bytes([0x21]), timeout=1000)
    print("[HOST] STOP sent")
except Exception as e:
    print(f"[HOST] STOP error: {e}")

try:
    usb.util.release_interface(dev, intf.bInterfaceNumber)
    usb.util.dispose_resources(dev)
except Exception:
    pass
