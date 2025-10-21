#!/usr/bin/env python3
from __future__ import annotations
import sys, time, struct, argparse

try:
    import usb.core, usb.util  # type: ignore
except Exception as e:
    print(f"[ERR] PyUSB not installed: {e}\n  pip install pyusb")
    sys.exit(2)

DEF_VID = 0xCAFE
DEF_PID = 0x4001
DEF_EP_OUT = 0x03
DEF_EP_IN  = 0x83

CMD_START = 0x20
CMD_STOP = 0x21
CMD_GET_STATUS = 0x30

MAGIC = 0xA55A
HDR_FMT = '<H B B I I H H I I I H H'
HDR_SIZE = 32
MAGIC_LE = b"\x5A\xA5"


def hexb(b: bytes, n: int = 32) -> str:
    return ' '.join(f"{x:02X}" for x in b[:n]) + (" …" if len(b) > n else '')


def parse_hdr(b: bytes):
    return struct.unpack(HDR_FMT, b)


def find_and_claim(vid: int, pid: int, force_intf: int | None, ep_out: int | None, ep_in: int | None):
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise SystemExit(f"device {vid:04X}:{pid:04X} not found")
    # ensure configured
    try:
        _ = dev.get_active_configuration()
    except usb.core.USBError:
        dev.set_configuration()
    cfg = dev.get_active_configuration()
    chosen = None
    # prefer vendor interface with desired EPs
    for intf in cfg:  # type: ignore
        if force_intf is not None and intf.bInterfaceNumber != force_intf:
            continue
        eps = list(intf.endpoints())
        if ep_out is not None and ep_in is not None:
            addrs = [e.bEndpointAddress for e in eps]
            if ep_out in addrs and ep_in in addrs:
                chosen = (intf, ep_out, ep_in)
                break
        # fallback: any vendor bulk in/out
        cls = getattr(intf, 'bInterfaceClass', None)
        if cls == 0xFF:
            outs = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2]
            ins  = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) != 0 and (e.bmAttributes & 0x03) == 2]
            if outs and ins:
                # prefer the canonical 0x03/0x83 if present
                out_addr = ep_out if ep_out in outs else (0x03 if 0x03 in outs else outs[0])
                in_addr  = ep_in  if ep_in  in ins  else (0x83 if 0x83 in ins  else ins[0])
                chosen = (intf, out_addr, in_addr)
                break
    if chosen is None:
        raise SystemExit("no vendor bulk interface found")
    intf, out_addr, in_addr = chosen
    # detach kernel driver if needed
    try:
        if dev.is_kernel_driver_active(intf.bInterfaceNumber):
            try:
                dev.detach_kernel_driver(intf.bInterfaceNumber)
            except Exception:
                pass
    except Exception:
        pass
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    return dev, intf, out_addr, in_addr


def run(vid: int, pid: int, force_intf: int | None, ep_out: int | None, ep_in: int | None, want_pairs: int, read_timeout_ms: int):
    dev, intf, EP_OUT, EP_IN = find_and_claim(vid, pid, force_intf, ep_out, ep_in)
    print(f"[open] {vid:04X}:{pid:04X} IF#{intf.bInterfaceNumber} OUT=0x{EP_OUT:02X} IN=0x{EP_IN:02X}")
    buf = bytearray()
    got_test = False
    pairs_seen = 0
    waiting_get_status = False

    def read_n(max_bytes: int, timeout_ms: int) -> bytes:
        return bytes(dev.read(EP_IN, max_bytes, timeout=timeout_ms))

    def write_cmd(cmd: int):
        return dev.write(EP_OUT, bytes([cmd]), timeout=500)

    try:
        # START
        write_cmd(CMD_START)
        print(f"[TX] START (0x{CMD_START:02X})")
        # First expect STAT ACK
        try:
            st = read_n(64, 800)
            if st[:4] == b'STAT':
                print(f"[RX] STAT len={len(st)} head={hexb(st,32)}")
            else:
                print(f"[RX] first IN len={len(st)} head={hexb(st,32)}")
                buf.extend(st)
        except usb.core.USBError as e:
            print(f"[..] no immediate STAT: {e}")

        t_end = time.time() + max(4.0, 2.0 + 0.5 * want_pairs)
        while time.time() < t_end and pairs_seen < want_pairs:
            # pump IN
            try:
                data = read_n(2048, read_timeout_ms)
            except usb.core.USBError as e:
                if getattr(e, 'errno', None) == 110:
                    continue
                raise
            if not data:
                continue
            if data[:4] == b'STAT':
                tag = "(GET_STATUS)" if waiting_get_status else "(mid)"
                print(f"[RX] STAT {tag} len={len(data)} head={hexb(data,32)}")
                if waiting_get_status:
                    waiting_get_status = False
                continue
            buf.extend(data)
            # deframe
            while True:
                if len(buf) < HDR_SIZE:
                    break
                if not (buf[0] == 0x5A and buf[1] == 0xA5):
                    idx = buf.find(MAGIC_LE)
                    if idx == -1:
                        del buf[:max(0, len(buf)-1)]
                        break
                    else:
                        del buf[:idx]
                        if len(buf) < HDR_SIZE:
                            break
                hdr = bytes(buf[:HDR_SIZE])
                try:
                    (magic, ver, flags, seq, ts, total_samples, zone_count, z1_off, z1_len, rsv, rsv2, crc16v) = parse_hdr(hdr)
                except struct.error:
                    break
                if magic != MAGIC:
                    del buf[0]
                    continue
                frame_len = HDR_SIZE + int(total_samples) * 2
                if len(buf) < frame_len:
                    break
                if (flags & 0x80) and total_samples == 8 and not got_test:
                    # TEST кадр: выведем первые байты payload как контроль
                    payload = bytes(buf[HDR_SIZE:frame_len])
                    n = min(16, len(payload)//2)
                    ival = struct.unpack('<'+'h'*n, payload[:n*2]) if n>0 else []
                    print(f"[RX] TEST len={frame_len} ver={ver} flags=0x{flags:02X} seq={seq} payload[0:32]={' '.join(f'{x:02X}' for x in payload[:32])}")
                    if n:
                        print(f"     int16[0:{n}]={list(ival)}")
                    got_test = True
                    del buf[:frame_len]
                    continue
                # working frames
                ch = None
                if flags & 0x01:
                    ch = 'A'
                elif flags & 0x02:
                    ch = 'B'
                else:
                    print(f"[RX] non-working flags=0x{flags:02X} seq={seq} total={total_samples}")
                    del buf[:frame_len]
                    continue
                # Выведем первые 32 байта payload в hex и первые 16 значений int16
                payload = bytes(buf[HDR_SIZE:frame_len])
                n = min(16, len(payload)//2)
                ival = struct.unpack('<'+'h'*n, payload[:n*2]) if n>0 else []
                print(f"[RX] {ch} len={frame_len} seq={seq & 0xFFFF} total={total_samples} payload[0:32]={' '.join(f'{x:02X}' for x in payload[:32])}")
                if n:
                    print(f"     int16[0:{n}]={list(ival)}")
                if ch == 'B':
                    pairs_seen += 1
                del buf[:frame_len]
                # issue GET_STATUS once after first pair
                if pairs_seen == 1 and not waiting_get_status:
                    write_cmd(CMD_GET_STATUS)
                    waiting_get_status = True
                    print(f"[TX] GET_STATUS (0x{CMD_GET_STATUS:02X})")
        # If we requested GET_STATUS but didn't see STAT yet, wait briefly
        if waiting_get_status:
            t_wait = time.time() + 1.5
            while time.time() < t_wait and waiting_get_status:
                try:
                    stg = read_n(64, 400)
                except usb.core.USBError as e:
                    if getattr(e, 'errno', None) == 110:
                        continue
                    else:
                        break
                if stg[:4] == b'STAT':
                    print(f"[RX] STAT (GET_STATUS late) len={len(stg)} head={hexb(stg,32)}")
                    waiting_get_status = False
                    break

        # STOP
        write_cmd(CMD_STOP)
        print(f"[TX] STOP (0x{CMD_STOP:02X})")
        # Expect STAT soon
        try:
            st2 = read_n(64, 1000)
            if st2[:4] == b'STAT':
                print(f"[RX] STAT (STOP) len={len(st2)} head={hexb(st2,32)}")
            else:
                print(f"[RX] after STOP head={hexb(st2,32)}")
        except Exception as e:
            print(f"[..] STOP STAT wait: {e}")
    finally:
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Start vendor stream, read STAT/TEST/A/B, GET_STATUS mid-stream, STOP")
    p.add_argument('--vid', type=lambda x: int(x, 0), default=DEF_VID, help='USB VID (e.g. 0xCAFE)')
    p.add_argument('--pid', type=lambda x: int(x, 0), default=DEF_PID, help='USB PID (e.g. 0x4001)')
    p.add_argument('--intf', type=int, default=None, help='Force interface number (e.g. 2)')
    p.add_argument('--ep-in', type=lambda x: int(x, 0), default=None, help='Force EP IN (e.g. 0x83)')
    p.add_argument('--ep-out', type=lambda x: int(x, 0), default=None, help='Force EP OUT (e.g. 0x03)')
    p.add_argument('--pairs', type=int, default=4, help='How many A/B pairs to read before STOP')
    p.add_argument('--read-timeout-ms', type=int, default=600, help='Bulk IN timeout per read')
    return p.parse_args(argv)


if __name__ == '__main__':
    args = _parse_args(sys.argv[1:])
    run(args.vid, args.pid, args.intf, args.ep_out, args.ep_in, args.pairs, args.read_timeout_ms)
