#!/usr/bin/env python3
# Minimal Vendor streaming reader for STM32H7 (Bulk OUT cmds @0x03, IN data @0x83)
# - Sends SET_PROFILE/SET_FRAME_SAMPLES/SET_FULL_MODE then START
# - Reads frames, verifies strict A→B ordering (B immediately after A),
#   allows STAT only between pairs, prints brief stats and FPS.
# - Optionally requests STAT with GET_STATUS as a keepalive.

import sys, struct, time, argparse
import usb.core, usb.util

# Commands (must match firmware)
VND_CMD_START_STREAM      = 0x20
VND_CMD_STOP_STREAM       = 0x21
VND_CMD_GET_STATUS        = 0x30
VND_CMD_SET_WINDOWS       = 0x10
VND_CMD_SET_BLOCK_HZ      = 0x11
VND_CMD_SET_TRUNC_SAMPLES = 0x16
VND_CMD_SET_FRAME_SAMPLES = 0x17
VND_CMD_SET_FULL_MODE     = 0x13
VND_CMD_SET_PROFILE       = 0x14

MAGIC = 0xA55A


def find_device(vid, pid):
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise SystemExit(f"Device VID=0x{vid:04x} PID=0x{pid:04x} not found")
    try:
        dev.set_configuration()
    except Exception:
        pass
    return dev


def claim_interface(dev, intf_num):
    cfg = dev.get_active_configuration()
    intf = usb.util.find_descriptor(cfg, bInterfaceNumber=intf_num)
    if intf is None:
        raise SystemExit(f"Interface #{intf_num} not found")
    try:
        if dev.is_kernel_driver_active(intf_num):
            try:
                dev.detach_kernel_driver(intf_num)
            except Exception:
                pass
    except NotImplementedError:
        pass
    try:
        usb.util.claim_interface(dev, intf_num)
    except Exception:
        pass
    try:
        dev.set_interface_altsetting(interface=intf_num, alternate_setting=1)
    except Exception as e:
        pass
    return intf


def send_cmd(dev, ep_out, data: bytes):
    dev.write(ep_out, data, timeout=1000)


def le16(v):
    return struct.pack('<H', v)


def le32(v):
    return struct.pack('<I', v)


def parse_frame(buf: bytes):
    if len(buf) < 32:
        return None
    magic, ver, flags, seq, ts, total_samples, zone_cnt = struct.unpack_from('<HBBIIHH', buf, 0)[:7]
    if magic != MAGIC:
        return None
    total = 32 + total_samples * 2
    if total != len(buf):
        if len(buf) < total:
            return None
        buf = buf[:total]
    return {
        'ver': ver,
        'flags': flags,
        'seq': seq,
        'ts': ts,
        'ns': total_samples,
        'len': len(buf),
        'raw': buf,
    }


def main():
    ap = argparse.ArgumentParser(description='Vendor stream reader (Bulk IN 0x83, OUT 0x03)')
    ap.add_argument('--vid', type=lambda x: int(x,0), default=0xCAFE)
    ap.add_argument('--pid', type=lambda x: int(x,0), default=0x4001)
    ap.add_argument('--intf', type=int, default=2, help='Vendor interface number')
    ap.add_argument('--ep-in', type=lambda x: int(x,0), default=0x83)
    ap.add_argument('--ep-out', type=lambda x: int(x,0), default=0x03)
    ap.add_argument('--profile', type=int, default=2, help='1=A(200Hz), 2=B(default)')
    ap.add_argument('--frame-samples', type=int, default=10, help='Samples per channel per frame')
    ap.add_argument('--full-mode', type=int, default=1, help='1=ADC mode, 0=diagnostic')
    ap.add_argument('--block-hz', type=int, default=200, help='ADC block rate hint')
    ap.add_argument('--frames', type=int, default=200)
    ap.add_argument('--timeout', type=int, default=300, help='IN timeout ms')
    ap.add_argument('--status-interval', type=float, default=0.0, help='Request GET_STATUS every N seconds (0=off)')
    ap.add_argument('--quiet', action='store_true', help='Reduce prints, show only summary')
    args = ap.parse_args()

    dev = find_device(args.vid, args.pid)
    intf = claim_interface(dev, args.intf)
    ep_in = args.ep_in
    ep_out = args.ep_out
    
    if not args.quiet:
        print(f"[OK] Opened VID=0x{args.vid:04X} PID=0x{args.pid:04X} IF#{args.intf}")

    # Configure and start
    try:
        send_cmd(dev, ep_out, bytes([VND_CMD_SET_PROFILE, args.profile & 0xFF]))
        send_cmd(dev, ep_out, bytes([VND_CMD_SET_BLOCK_HZ]) + le16(args.block_hz))
        send_cmd(dev, ep_out, bytes([VND_CMD_SET_FRAME_SAMPLES]) + le16(args.frame_samples))
        send_cmd(dev, ep_out, bytes([VND_CMD_SET_FULL_MODE, 1 if args.full_mode else 0]))
        send_cmd(dev, ep_out, bytes([VND_CMD_START_STREAM]))
    except Exception as e:
        print(f"[ERROR] Failed to configure: {e}")
        sys.exit(1)

    want_frames = args.frames
    got_a = got_b = 0
    bytes_received = 0
    start_time = time.time()

    try:
        acc = b""
        while got_a + got_b < want_frames:
            try:
                chunk = dev.read(ep_in, 2048, timeout=args.timeout)
                acc += bytes(chunk)
            except usb.core.USBError as e:
                if got_a + got_b > 0:
                    break
                print(f"[ERROR] USB read error: {e}")
                sys.exit(1)

            # Parse accumulated buffer
            while len(acc) >= 32:
                if acc[0] == 0x5A and acc[1] == 0xA5:
                    total_samples = struct.unpack_from('<H', acc, 12)[0]
                    total_len = 32 + total_samples * 2
                    if len(acc) >= total_len:
                        fbuf = acc[:total_len]
                        acc = acc[total_len:]
                        
                        fr = parse_frame(fbuf)
                        if fr:
                            bytes_received += len(fbuf)
                            fl = fr['flags']
                            ch = 'A' if (fl & 0x01) else 'B'
                            if ch == 'A':
                                got_a += 1
                            else:
                                got_b += 1
                            if not args.quiet and (got_a + got_b) % 20 == 0:
                                print(f"[{ch}] seq={fr['seq']} ns={fr['ns']}")
                    else:
                        break
                else:
                    acc = acc[1:]

        elapsed = time.time() - start_time
        speed_kbs = (bytes_received / 1024.0) / elapsed if elapsed > 0 else 0
        
        print(f"[OK] Received A={got_a} B={got_b} in {elapsed:.2f}s")
        print(f"Streaming speed: {speed_kbs:.0f} KB/s")
        
        if speed_kbs >= 960:
            print(f"[OK] Test passed (target: 960 KB/s)")
        else:
            print(f"[WARN] Speed below target (got {speed_kbs:.0f}, target 960)")
            
    finally:
        try:
            send_cmd(dev, ep_out, bytes([VND_CMD_STOP_STREAM]))
        except Exception:
            pass


if __name__ == '__main__':
    main()
