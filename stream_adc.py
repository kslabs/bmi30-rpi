import sys
import time
import struct
import argparse
import usb.core
import usb.util


def find_endpoints(dev, intf_num, ep_in, ep_out):
    cfg = dev.get_active_configuration()
    try:
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=intf_num) or cfg[(intf_num, 0)]
    except Exception:
        # Fallback: first interface
        intf = cfg[(0, 0)]
    e_in = usb.util.find_descriptor(intf, bEndpointAddress=ep_in)
    e_out = usb.util.find_descriptor(intf, bEndpointAddress=ep_out)
    if not e_in or not e_out:
        raise RuntimeError("Endpoint(s) not found: IN=0x%02X OUT=0x%02X" % (ep_in, ep_out))
    return intf, e_in, e_out


def send_cmd(ep_out, cmd, payload=b""):
    data = bytes([cmd]) + payload
    return ep_out.write(data)


def parse_and_log(pkt: bytes):
    if not pkt:
        return ("EMPTY", None)
    # STAT marker (device-specific 64B)
    if len(pkt) >= 4 and pkt[:4] == b"STAT":
        ver = pkt[4] if len(pkt) >= 5 else 0
        print(f"[IN] STAT len={len(pkt)} ver={ver}")
        return ("STAT", None)
    # Header: 0xA55A 0x01 [flags] [seq:u32] [ts:u32] [total:u16] ...
    if len(pkt) >= 16 and pkt[0:2] == b"\x5A\xA5" and pkt[2] == 0x01:
        flags = pkt[3]
        seq = struct.unpack_from("<I", pkt, 4)[0]
        ts = struct.unpack_from("<I", pkt, 8)[0]
        total = struct.unpack_from("<H", pkt, 12)[0]
        kind = (
            "TEST"
            if (flags & 0x80)
            else ("A" if (flags & 0x01) else ("B" if (flags & 0x02) else f"F{flags:02X}"))
        )
        print(f"[IN] {kind} len={len(pkt)} seq={seq} ts={ts} ns={total}")
        return (kind, seq)
    print(f"[IN] RAW len={len(pkt)} head={pkt[:8].hex(' ')}")
    return ("RAW", None)


def main():
    ap = argparse.ArgumentParser(description="Мини-ридер USB Vendor потока (PyUSB)")
    ap.add_argument("--vid", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--pid", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--intf", type=int, default=2)
    ap.add_argument("--ep-in", type=lambda x: int(x, 0), default=0x83)
    ap.add_argument("--ep-out", type=lambda x: int(x, 0), default=0x03)
    ap.add_argument("--pairs", type=int, default=8, help="Сколько A/B пар прочитать (примерно)")
    ap.add_argument("--read-timeout-ms", type=int, default=1000)
    ap.add_argument("--no-opts", action="store_true", help="Не отправлять SET_* перед START")
    args = ap.parse_args()

    dev = usb.core.find(idVendor=args.vid, idProduct=args.pid)
    if not dev:
        print("Device not found")
        sys.exit(1)

    # Prepare device / interface
    try:
        # Detach CDC Comm (IF0) to avoid EBUSY on some stacks
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except Exception:
            pass
        if dev.is_kernel_driver_active(args.intf):
            try:
                dev.detach_kernel_driver(args.intf)
            except Exception:
                pass
    except (NotImplementedError, usb.core.USBError):
        pass

    # On Linux composite devices, other interfaces may be busy (CDC-ACM bound),
    # so setting configuration can raise EBUSY even though config is already set.
    # Use active configuration if available; otherwise, try to set and ignore EBUSY.
    try:
        _ = dev.get_active_configuration()
        if _ is None:
            try:
                dev.set_configuration()
            except usb.core.USBError as e:
                # Ignore EBUSY if kernel already set configuration
                if getattr(e, "errno", None) != 16:
                    raise
    except usb.core.USBError:
        # Fallback: attempt to set, ignore EBUSY
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            if getattr(e, "errno", None) != 16:
                raise
    intf, ep_in, ep_out = find_endpoints(dev, args.intf, args.__dict__["ep_in"], args.ep_out)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)

    # Optional settings (windows, hz, mode, profile)
    if not args.no_opts:
        # SET_WINDOWS (0x10): start0,len0,start1,len1 (u16 LE)
        w = struct.pack("<B4H", 0x10, 100, 300, 700, 300)
        ep_out.write(w)
        # SET_BLOCK_HZ (0x11): hz (u16)
        ep_out.write(struct.pack("<BH", 0x11, 100))
        # SET_FULL_MODE (0x13): 1 = рабочий режим (ADC stream)
        ep_out.write(struct.pack("<BB", 0x13, 1))
        # SET_PROFILE (0x14): профиль (например, 2)
        ep_out.write(struct.pack("<BB", 0x14, 2))

    # Control GET_STATUS (vendor-specific IN) as a quick liveness check (some fw handle it on IF0)
    try:
        for idx in (0, 1, args.intf):
            try:
                data = dev.ctrl_transfer(0xC1, 0x30, 0, idx, 64, timeout=300)
                if data and len(data) == 64:
                    print("[CTRL] GET_STATUS ok idx=", idx)
                    break
            except Exception:
                continue
    except Exception:
        pass

    # START (0x20)
    send_cmd(ep_out, 0x20)

    read_sz = 2048
    timeout = args.read_timeout_ms
    seen_A = 0
    seen_B = 0
    t_end = time.time() + 10

    try:
        # First, try a few short reads (64B) to quickly catch STAT/TEST
        short_reads = 6
        while short_reads > 0:
            short_reads -= 1
            try:
                pkt = ep_in.read(64, timeout=timeout).tobytes()
            except usb.core.USBError as e:
                if (getattr(e, "errno", None) is None) and ("timed out" in str(e).lower()):
                    continue
                break
            kind, seq = parse_and_log(pkt)
            if kind == "A":
                seen_A += 1
            if kind == "B":
                seen_B += 1
        # Then switch to normal sized reads
        while True:
            try:
                pkt = ep_in.read(read_sz, timeout=timeout).tobytes()
            except usb.core.USBError as e:
                if (getattr(e, "errno", None) is None) and ("timed out" in str(e).lower()):
                    continue
                print("USB read error:", e)
                break
            kind, seq = parse_and_log(pkt)
            if kind == "A":
                seen_A += 1
            if kind == "B":
                seen_B += 1
            if args.pairs > 0 and min(seen_A, seen_B) >= args.pairs:
                break
            if time.time() > t_end and (seen_A + seen_B) == 0:
                print("No data within 10s, exiting")
                break
    finally:
        # STOP (0x21)
        try:
            send_cmd(ep_out, 0x21)
        except Exception:
            pass
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
        except Exception:
            pass
        try:
            dev.attach_kernel_driver(args.intf)
        except Exception:
            pass


if __name__ == "__main__":
    main()
