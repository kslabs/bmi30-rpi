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


def find_and_claim(vid: int, pid: int, ep_out: int | None, ep_in: int | None):
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
    for intf in cfg:  # type: ignore
        eps = list(intf.endpoints())
        addrs = [e.bEndpointAddress for e in eps]
        if ep_out is not None and ep_in is not None and ep_out in addrs and ep_in in addrs:
            chosen = (intf, ep_out, ep_in)
            break
        cls = getattr(intf, 'bInterfaceClass', None)
        if cls == 0xFF:
            outs = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2]
            ins  = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) != 0 and (e.bmAttributes & 0x03) == 2]
            if outs and ins:
                out_addr = ep_out if ep_out in outs else (0x03 if 0x03 in outs else outs[0])
                in_addr  = ep_in  if ep_in  in ins  else (0x83 if 0x83 in ins  else ins[0])
                chosen = (intf, out_addr, in_addr)
                break
    if chosen is None:
        raise SystemExit("no vendor bulk interface found")
    intf, out_addr, in_addr = chosen
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


def run(vid: int, pid: int, ep_out: int | None, ep_in: int | None, read_timeout_ms: int, wait_pairs_s: float, wait_stop_stat_s: float) -> int:
    dev, intf, EP_OUT, EP_IN = find_and_claim(vid, pid, ep_out, ep_in)
    print(f"[open] {vid:04X}:{pid:04X} IF#{intf.bInterfaceNumber} OUT=0x{EP_OUT:02X} IN=0x{EP_IN:02X}")

    def read_n(max_bytes: int, timeout_ms: int) -> bytes:
        return bytes(dev.read(EP_IN, max_bytes, timeout=timeout_ms))

    def write_cmd(cmd: int):
        return dev.write(EP_OUT, bytes([cmd]), timeout=500)

    try:
        # START
        write_cmd(CMD_START)
        print(f"[TX] START (0x{CMD_START:02X})")
        # Try to observe some traffic briefly
        t_end = time.time() + max(1.5, wait_pairs_s)
        saw_any = False
        while time.time() < t_end:
            try:
                data = read_n(4096, read_timeout_ms)
            except usb.core.USBError as e:
                if getattr(e, 'errno', None) == 110:
                    continue
                raise
            if not data:
                continue
            if data[:4] == b'STAT':
                print(f"[RX] STAT len={len(data)} head={hexb(data,16)}")
                saw_any = True
                continue
            # Frame-like
            if len(data) >= HDR_SIZE and data[0]==0x5A and data[1]==0xA5:
                try:
                    (magic, ver, flags, seq, ts, total_samples, *_rest) = parse_hdr(data[:HDR_SIZE])
                except struct.error:
                    total_samples = 0
                    flags = 0
                ch = 'A' if (flags & 0x01) else ('B' if (flags & 0x02) else '?')
                print(f"[RX] FRM ch={ch} total={total_samples} head={hexb(data,16)}")
                saw_any = True
            else:
                print(f"[RX] IN len={len(data)} head={hexb(data,16)}")
                saw_any = True
        # STOP
        write_cmd(CMD_STOP)
        print(f"[TX] STOP (0x{CMD_STOP:02X})")
        # Expect STAT quickly (no ZLP variant)
        t_stop = time.time() + wait_stop_stat_s
        got_stop_stat = False
        while time.time() < t_stop and not got_stop_stat:
            try:
                st = read_n(64, 400)
            except usb.core.USBError as e:
                if getattr(e, 'errno', None) == 110:
                    continue
                else:
                    break
            if st[:4] == b'STAT':
                print(f"[RX] STAT (STOP) len={len(st)} head={hexb(st,16)}")
                got_stop_stat = True
                break
        if not got_stop_stat:
            print("[FAIL] STOP: no STAT within timeout")
            return 1
        if not saw_any:
            print("[WARN] no frames observed before STOP")
        print("[OK] STOP acknowledged and stream ended")
        return 0
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
    p = argparse.ArgumentParser(description="Start stream briefly, then STOP and expect one STAT ack (no ZLP build)")
    p.add_argument('--vid', type=lambda x: int(x, 0), default=DEF_VID)
    p.add_argument('--pid', type=lambda x: int(x, 0), default=DEF_PID)
    p.add_argument('--ep-in', type=lambda x: int(x, 0), default=None)
    p.add_argument('--ep-out', type=lambda x: int(x, 0), default=None)
    p.add_argument('--read-timeout-ms', type=int, default=600)
    p.add_argument('--wait-pairs-s', type=float, default=2.0, help='How long to sniff before STOP')
    p.add_argument('--wait-stop-stat-s', type=float, default=2.0, help='Time window to wait for STOP STAT')
    return p.parse_args(argv)


if __name__ == '__main__':
    a = _parse_args(sys.argv[1:])
    sys.exit(run(a.vid, a.pid, a.ep_out, a.ep_in, a.read_timeout_ms, a.wait_pairs_s, a.wait_stop_stat_s))
