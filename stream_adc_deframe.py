import sys
import time
import struct
import argparse
import usb.core
import usb.util

MAGIC = b"\x5A\xA5\x01"


def claim(dev, intf):
    try:
        if dev.is_kernel_driver_active(0):
            try:
                dev.detach_kernel_driver(0)
            except Exception:
                pass
    except Exception:
        pass
    try:
        if dev.is_kernel_driver_active(intf):
            try:
                dev.detach_kernel_driver(intf)
            except Exception:
                pass
    except Exception:
        pass
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        if getattr(e, "errno", None) != 16:
            raise
    usb.util.claim_interface(dev, intf)


def send_cmd(dev, ep_out, cmd, payload=b""):
    data = bytes([cmd]) + payload
    return dev.write(ep_out, data, timeout=500)


def parse_frames(buf, out):
    consumed = 0
    frames = []
    i = 0
    n = len(buf)
    while i + 32 <= n:
        # STAT at head
        if buf[i:i+4] == b"STAT" and (i + 64) <= n:
            out.append(("STAT", bytes(buf[i:i+64])))
            i += 64
            continue
        # Align to next magic
        if buf[i:i+3] != MAGIC:
            j = buf.find(MAGIC, i+1)
            if j == -1:
                break
            i = j
            continue
        # header present
        flags = buf[i+3]
        seq = struct.unpack_from("<I", buf, i+4)[0]
        ts = struct.unpack_from("<I", buf, i+8)[0]
        total = struct.unpack_from("<H", buf, i+12)[0]
        frame_len = 32 + total * 2
        if i + frame_len > n:
            break
        fr = bytes(buf[i:i+frame_len])
        kind = (
            "TEST" if (flags & 0x80) else
            ("A" if (flags & 0x01) else ("B" if (flags & 0x02) else f"F{flags:02X}"))
        )
        out.append((kind, fr, seq, ts, total))
        i += frame_len
    consumed = i
    return consumed


def main():
    ap = argparse.ArgumentParser(description="USB Vendor stream deframer (PyUSB)")
    ap.add_argument("--vid", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--pid", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--intf", type=int, default=2)
    ap.add_argument("--ep-in", type=lambda x: int(x, 0), default=0x83)
    ap.add_argument("--ep-out", type=lambda x: int(x, 0), default=0x03)
    ap.add_argument("--pairs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()

    dev = usb.core.find(idVendor=args.vid, idProduct=args.pid)
    if not dev:
        print("Device not found")
        sys.exit(1)

    claim(dev, args.intf)

    # Pre control GET_STATUS (optional)
    try:
        for idx in (0, 1, args.intf):
            try:
                dev.ctrl_transfer(0xC1, 0x30, 0, idx, 64, timeout=300)
                break
            except Exception:
                pass
    except Exception:
        pass

    # Basic opts (harmless if ignored)
    try:
        dev.write(args.ep_out, struct.pack("<B4H", 0x10, 100, 300, 700, 300), timeout=300)
        dev.write(args.ep_out, struct.pack("<BH", 0x11, 100), timeout=300)
        dev.write(args.ep_out, struct.pack("<BB", 0x13, 1), timeout=300)
        dev.write(args.ep_out, struct.pack("<BB", 0x14, 2), timeout=300)
    except Exception:
        pass

    # START
    dev.write(args.ep_out, bytes([0x20]), timeout=300)

    buf = bytearray()
    seenA = seenB = 0

    try:
        # small reads to grab STAT/TEST quickly
        for _ in range(6):
            try:
                chunk = dev.read(args.ep_in, 64, timeout=args.timeout).tobytes()
                buf.extend(chunk)
            except usb.core.USBError as e:
                if (getattr(e, "errno", None) is None) and ("timed out" in str(e).lower()):
                    continue
                break
            out = []
            used = parse_frames(buf, out)
            if used:
                del buf[:used]
            for item in out:
                if item[0] == "STAT":
                    print("[IN] STAT 64B")
                elif item[0] == "TEST":
                    _, fr, seq, ts, total = item
                    print(f"[IN] TEST seq={seq} ts={ts} total={total}")
                else:
                    kind, fr, seq, ts, total = item
                    print(f"[IN] {kind} seq={seq} ts={ts} total={total} size={len(fr)}")
                    if kind == "A":
                        seenA += 1
                    elif kind == "B":
                        seenB += 1

        # switch to larger reads
        while True:
            try:
                chunk = dev.read(args.ep_in, 1024, timeout=args.timeout).tobytes()
                buf.extend(chunk)
            except usb.core.USBError as e:
                if (getattr(e, "errno", None) is None) and ("timed out" in str(e).lower()):
                    continue
                print("USB read error:", e)
                break
            out = []
            used = parse_frames(buf, out)
            if used:
                del buf[:used]
            for item in out:
                if item[0] == "STAT":
                    print("[IN] STAT 64B")
                elif item[0] == "TEST":
                    _, fr, seq, ts, total = item
                    print(f"[IN] TEST seq={seq} ts={ts} total={total}")
                else:
                    kind, fr, seq, ts, total = item
                    print(f"[IN] {kind} seq={seq} ts={ts} total={total} size={len(fr)}")
                    if kind == "A":
                        seenA += 1
                    elif kind == "B":
                        seenB += 1
            if args.pairs > 0 and min(seenA, seenB) >= args.pairs:
                break
    finally:
        try:
            dev.write(args.ep_out, bytes([0x21]), timeout=300)
        except Exception:
            pass
        try:
            usb.util.release_interface(dev, args.intf)
        except Exception:
            pass
        try:
            dev.attach_kernel_driver(args.intf)
        except Exception:
            pass

if __name__ == "__main__":
    main()
