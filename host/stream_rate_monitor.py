#!/usr/bin/env python3
"""
Measure vendor USB stream throughput without GUI.
- Starts streaming (START 0x20)
- Deframes headers (MAGIC 0xA55A, 32-byte header), counts ADC0/ADC1 samples
- Prints stats every --interval seconds: samples, frames, bytes, rates
- Sends STOP on exit

Usage:
  python3 host/stream_rate_monitor.py --interval 10 --duration 60
"""
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

MAGIC = 0xA55A
HDR_FMT = '<H B B I I H H I I I H H'
HDR_SIZE = 32
MAGIC_LE = b"\x5A\xA5"

VF_ADC0 = 0x01
VF_ADC1 = 0x02
VF_TEST = 0x80


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
    # prefer vendor bulk interface with desired EPs
    for intf in cfg:  # type: ignore
        if force_intf is not None and intf.bInterfaceNumber != force_intf:
            continue
        eps = list(intf.endpoints())
        addrs = [e.bEndpointAddress for e in eps]
        # exact match first
        if ep_out in addrs and ep_in in addrs:
            chosen = (intf, ep_out, ep_in)
            break
        # fallback: any vendor bulk in/out
        cls = getattr(intf, 'bInterfaceClass', None)
        if cls == 0xFF:
            outs = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2]
            ins  = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) != 0 and (e.bmAttributes & 0x03) == 2]
            if outs and ins:
                out_addr = ep_out if ep_out in outs else outs[0]
                in_addr  = ep_in  if ep_in  in ins  else ins[0]
                chosen = (intf, out_addr, in_addr)
                break
    if chosen is None:
        raise SystemExit("no vendor bulk interface found")
    intf, out_addr, in_addr = chosen
    # detach kernel driver if needed and claim
    try:
        if dev.is_kernel_driver_active(intf.bInterfaceNumber):
            try:
                dev.detach_kernel_driver(intf.bInterfaceNumber)
            except Exception:
                pass
    except Exception:
        pass
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    # Try to switch alt=1 gently (not fatal if fails)
    try:
        dev.set_interface_altsetting(interface=intf.bInterfaceNumber, alternate_setting=1)
    except Exception:
        pass
    return dev, intf, out_addr, in_addr


def run(vid: int, pid: int, force_intf: int | None, ep_out: int, ep_in: int,
    interval_sec: float, duration_sec: float | None, read_timeout_ms: int,
    send_full: bool, profile: int | None, ns: int | None,
    keepalive_sec: float, restart_after_sec: float, restart_mode: str, keepalive_mode: str):
    dev, intf, EP_OUT, EP_IN = find_and_claim(vid, pid, force_intf, ep_out, ep_in)
    print(f"[open] {vid:04X}:{pid:04X} IF#{intf.bInterfaceNumber} OUT=0x{EP_OUT:02X} IN=0x{EP_IN:02X}")

    def write_cmd(cmd: int):
        return dev.write(EP_OUT, bytes([cmd]), timeout=500)

    # optional pre-configuration
    if send_full:
        try:
            dev.write(EP_OUT, bytes([0x13, 0x01]), timeout=500)
            print("[TX] SET_FULL_MODE(1)")
        except Exception as e:
            print("[TX] SET_FULL_MODE err:", e)
    if profile is not None:
        try:
            dev.write(EP_OUT, bytes([0x14, int(profile) & 0xFF]), timeout=500)
            print(f"[TX] SET_PROFILE({profile})")
        except Exception as e:
            print("[TX] SET_PROFILE err:", e)
    if ns is not None:
        try:
            ns16 = max(1, int(ns)) & 0xFFFF
            dev.write(EP_OUT, bytes([0x17, ns16 & 0xFF, (ns16 >> 8) & 0xFF]), timeout=500)
            print(f"[TX] SET_FRAME_SAMPLES({ns16})")
        except Exception as e:
            print("[TX] SET_FRAME_SAMPLES err:", e)
    # start streaming
    write_cmd(CMD_START)
    print(f"[TX] START (0x{CMD_START:02X})")

    buf = bytearray()
    t0 = time.time()
    last = t0
    total_samples = 0
    total_bytes = 0
    total_frames = 0
    total_frames_a = 0
    total_frames_b = 0
    int_samples_last = 0
    int_bytes_last = 0

    try:
        last_rx_t = time.time()
        while True:
            # stop by duration
            if duration_sec is not None and (time.time() - t0) >= duration_sec:
                break
            # pump IN
            try:
                data = bytes(dev.read(EP_IN, 4096, timeout=read_timeout_ms))
            except usb.core.USBError as e:
                if getattr(e, 'errno', None) == 110:  # timeout
                    data = b''
                else:
                    raise
            if data:
                # strip leading STAT frames (64 bytes each)
                mv = memoryview(data)
                pos = 0
                n = len(mv)
                while pos + 4 <= n and mv[pos:pos+4] == b'STAT':
                    if pos + 64 <= n:
                        pos += 64
                        continue
                    break
                if pos < n:
                    buf.extend(mv[pos:].tobytes())
                last_rx_t = time.time()
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
                    (magic, ver, flags, seq, ts, total_s, zone_count, z1_off, z1_len, rsv, rsv2, crc16v) = parse_hdr(hdr)
                except struct.error:
                    break
                if magic != MAGIC:
                    del buf[0]
                    continue
                frame_len = HDR_SIZE + int(total_s) * 2
                if len(buf) < frame_len:
                    break
                # count only working A/B frames (ignore pure TEST frames)
                ch = None
                if flags & VF_ADC0:
                    ch = 0
                elif flags & VF_ADC1:
                    ch = 1
                if ch is not None:
                    total_frames += 1
                    if ch == 0:
                        total_frames_a += 1
                    else:
                        total_frames_b += 1
                    total_samples += int(total_s)
                    total_bytes += int(total_s) * 2
                    int_samples_last += int(total_s)
                    int_bytes_last += int(total_s) * 2
                # drop this frame
                del buf[:frame_len]
                last_rx_t = time.time()
            # keepalive / restart logic
            now = time.time()
            if keepalive_sec and (now - last_rx_t) > keepalive_sec:
                try:
                    if keepalive_mode == 'ctrl':
                        _ = dev.ctrl_transfer(0xC0, 0x30, 0, 0, 64, timeout=200)
                    else:
                        dev.write(EP_OUT, bytes([0x30]), timeout=200)  # queue GET_STATUS via bulk
                    # no print to avoid spam
                except Exception:
                    pass
            if restart_after_sec and (now - last_rx_t) > restart_after_sec:
                try:
                    if restart_mode == 'stop-start':
                        write_cmd(CMD_STOP)
                        time.sleep(0.02)
                    write_cmd(CMD_START)
                    print("[kick] restart sent")
                    last_rx_t = time.time()
                except Exception as e:
                    print("[kick] restart error:", e)
            # interval report
            if now - last >= max(0.5, float(interval_sec)):
                dt = now - last
                sps = int_samples_last / dt if dt > 0 else 0.0
                bps = int_bytes_last / dt if dt > 0 else 0.0
                mbps = (bps * 8) / 1e6
                elapsed = now - t0
                print(f"[t={elapsed:6.1f}s] samples(total)={total_samples:,}  rate={sps:,.0f} sps  bytes={total_bytes:,}  rate={bps:,.0f} B/s ({mbps:.3f} Mbit/s)  frames A/B={total_frames_a}/{total_frames_b}")
                last = now
                int_samples_last = 0
                int_bytes_last = 0
    except KeyboardInterrupt:
        print("\n[exit] interrupted by user")
    finally:
        try:
            write_cmd(CMD_STOP)
            print(f"[TX] STOP (0x{CMD_STOP:02X})")
        except Exception:
            pass
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Measure vendor stream throughput: samples/s and bytes/s")
    p.add_argument('--vid', type=lambda x: int(x, 0), default=DEF_VID, help='USB VID (e.g. 0xCAFE)')
    p.add_argument('--pid', type=lambda x: int(x, 0), default=DEF_PID, help='USB PID (e.g. 0x4001)')
    p.add_argument('--intf', type=int, default=None, help='Force interface number (e.g. 2)')
    p.add_argument('--ep-in', type=lambda x: int(x, 0), default=DEF_EP_IN, help='EP IN (default 0x83)')
    p.add_argument('--ep-out', type=lambda x: int(x, 0), default=DEF_EP_OUT, help='EP OUT (default 0x03)')
    p.add_argument('--interval', type=float, default=10.0, help='Report interval seconds (default 10)')
    p.add_argument('--duration', type=float, default=None, help='Total duration seconds (default: run until Ctrl+C)')
    p.add_argument('--read-timeout-ms', type=int, default=600, help='Bulk IN timeout per read (ms)')
    p.add_argument('--send-full', action='store_true', help='Send SET_FULL_MODE(1) before START')
    p.add_argument('--profile', type=int, default=None, choices=[1,2], help='Send SET_PROFILE(1|2) before START')
    p.add_argument('--ns', type=int, default=None, help='Send SET_FRAME_SAMPLES (u16) before START')
    p.add_argument('--keepalive-sec', type=float, default=0.0, help='Send GET_STATUS if no RX for this many seconds (0=off)')
    p.add_argument('--keepalive-mode', type=str, default='ctrl', choices=['ctrl','bulk'], help='Keepalive via EP0 control (ctrl) or bulk command (bulk)')
    p.add_argument('--restart-after', type=float, default=0.0, help='Send START (or STOP+START) if no RX for this many seconds (0=off)')
    p.add_argument('--restart-mode', type=str, default='start', choices=['start','stop-start'], help='How to restart when stalled')
    return p.parse_args(argv)


if __name__ == '__main__':
    args = _parse_args(sys.argv[1:])
    run(args.vid, args.pid, args.intf, args.ep_out, args.ep_in,
        args.interval, args.duration, args.read_timeout_ms,
        args.send_full, args.profile, args.ns,
        args.keepalive_sec, args.restart_after, args.restart_mode, args.keepalive_mode)
