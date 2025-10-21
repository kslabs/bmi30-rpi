import sys, time, struct
import usb.core, usb.util

VID, PID = 0xCAFE, 0x4001
INTF = 2
EP_OUT = 0x03
EP_IN  = 0x83

MAGIC = b"\x5A\xA5\x01"


def parse_frames(buf):
    out = []
    i = 0
    n = len(buf)
    while i + 32 <= n:
        if buf[i:i+4] == b"STAT" and i + 64 <= n:
            out.append(("STAT", 64, None, None, None))
            i += 64
            continue
        if buf[i:i+3] != MAGIC:
            j = buf.find(MAGIC, i+1)
            if j == -1:
                break
            i = j
            continue
        flags = buf[i+3]
        seq   = struct.unpack_from("<I", buf, i+4)[0]
        ts    = struct.unpack_from("<I", buf, i+8)[0]
        total = struct.unpack_from("<H", buf, i+12)[0]
        frame_len = 32 + total*2
        if i + frame_len > n:
            break
        kind = 'TEST' if (flags & 0x80) else ('A' if (flags & 0x01) else ('B' if (flags & 0x02) else 'F'))
        out.append((kind, frame_len, seq, ts, total))
        i += frame_len
    return i, out


def main(duration_s=60):
    d = usb.core.find(idVendor=VID, idProduct=PID)
    if not d:
        print('Device not found')
        sys.exit(1)
    # detach IF0 (CDC Comm) quietly
    try:
        if d.is_kernel_driver_active(0):
            d.detach_kernel_driver(0)
    except Exception:
        pass
    # detach/claim vendor IF2
    try:
        if d.is_kernel_driver_active(INTF):
            d.detach_kernel_driver(INTF)
    except Exception:
        pass
    try:
        d.set_configuration()
    except usb.core.USBError as e:
        if getattr(e, 'errno', None) != 16:
            raise
    usb.util.claim_interface(d, INTF)

    # set profile 1 (200 Hz), full mode, and START
    try:
        d.write(EP_OUT, struct.pack('<BB', 0x14, 1), timeout=300)
        d.write(EP_OUT, struct.pack('<BB', 0x13, 1), timeout=300)
    except Exception:
        pass
    d.write(EP_OUT, bytes([0x20]), timeout=300)

    buf = bytearray()
    t0 = time.time()
    last_stat = t0
    last_report = t0
    cnt_A = cnt_B = cnt_TEST = cnt_STAT = 0
    gaps = 0
    last_seq = None

    try:
        while True:
            now = time.time()
            if now - t0 > duration_s:
                break
            try:
                chunk = d.read(EP_IN, 1024, timeout=1500).tobytes()
                buf.extend(chunk)
            except usb.core.USBError as e:
                s = str(e).lower()
                if 'timed out' in s:
                    continue
                print('USB read error:', e)
                break
            used, frames = parse_frames(buf)
            if used:
                del buf[:used]
            for kind, size, seq, ts, total in frames:
                if kind == 'STAT':
                    cnt_STAT += 1
                    last_stat = now
                elif kind == 'TEST':
                    cnt_TEST += 1
                elif kind == 'A':
                    cnt_A += 1
                    if last_seq is not None and seq != ((last_seq + 1) & 0xFFFFFFFF):
                        gaps += 1
                    last_seq = seq
                elif kind == 'B':
                    cnt_B += 1
                # ignore F*
            if now - last_report >= 5.0:
                rate_pairs = min(cnt_A, cnt_B) / max(1e-6, now - t0)
                print(f"[burn-in] t={int(now-t0)}s pairs={min(cnt_A,cnt_B)} A={cnt_A} B={cnt_B} TEST={cnt_TEST} STAT={cnt_STAT} gaps={gaps} r={rate_pairs:.1f}/s")
                last_report = now
    finally:
        try:
            d.write(EP_OUT, bytes([0x21]), timeout=300)
        except Exception:
            pass
        try:
            usb.util.release_interface(d, INTF)
        except Exception:
            pass
    print(f"DONE: pairs={min(cnt_A,cnt_B)} A={cnt_A} B={cnt_B} TEST={cnt_TEST} STAT={cnt_STAT} gaps={gaps}")


if __name__ == '__main__':
    dur = 60
    if len(sys.argv) > 1:
        try:
            dur = int(sys.argv[1])
        except Exception:
            pass
    main(dur)
