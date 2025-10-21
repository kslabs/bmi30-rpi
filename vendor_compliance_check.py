#!/usr/bin/env python3
from __future__ import annotations
import sys, time, struct
from typing import Optional, Dict, Set

try:
    import usb.core, usb.util  # type: ignore
except Exception as e:
    print(f"[ERR] PyUSB not installed: {e}")
    sys.exit(2)

VID = 0xCAFE
PID = 0x4001
EP_IN_EXPECT = 0x83
EP_OUT_EXPECT = 0x03

CMD_START = 0x20
CMD_STOP = 0x21
CMD_GET_STATUS = 0x30
CMD_SET_FULL_MODE = 0x13
CMD_SET_PROFILE = 0x14
CMD_SET_BLOCK_HZ = 0x11

MAGIC = 0xA55A
HDR_FMT = '<H B B I I H H I I I H H'
HDR_SIZE = 32

class USBVend:
    def __init__(self, vid=VID, pid=PID):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise SystemExit(f"Device {vid:04X}:{pid:04X} not found")
        self._pick_interface()

    def _pick_interface(self):
        # detach kernel drivers quickly
        for i in range(0, 8):
            try:
                if self.dev.is_kernel_driver_active(i):
                    try:
                        self.dev.detach_kernel_driver(i)
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            cfg = self.dev.get_active_configuration()
        except usb.core.USBError:
            self.dev.set_configuration()
            cfg = self.dev.get_active_configuration()
        self.intf = None
        self.ep_in = None
        self.ep_out = None
        # prefer expected endpoint numbers
        for intf in cfg:
            cls = getattr(intf, 'bInterfaceClass', None)
            if cls == 0xFF:
                eps = list(intf.endpoints())
                addrs = [e.bEndpointAddress for e in eps]
                if EP_IN_EXPECT in addrs and EP_OUT_EXPECT in addrs:
                    self.intf = intf
                    for e in eps:
                        if e.bEndpointAddress == EP_IN_EXPECT:
                            self.ep_in = e.bEndpointAddress
                        if e.bEndpointAddress == EP_OUT_EXPECT:
                            self.ep_out = e.bEndpointAddress
                    break
        if self.intf is None:
            # fallback: any vendor interface with bulk in/out
            for intf in cfg:
                cls = getattr(intf, 'bInterfaceClass', None)
                if cls != 0xFF:
                    continue
                eps = list(intf.endpoints())
                in_bulk = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) and (e.bmAttributes & 0x03) == 2]
                out_bulk = [e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2]
                if in_bulk and out_bulk:
                    self.intf = intf
                    self.ep_in = in_bulk[0]
                    self.ep_out = out_bulk[0]
                    break
        if self.intf is None or self.ep_in is None or self.ep_out is None:
            raise SystemExit("No suitable vendor bulk interface found")
        try:
            if self.dev.is_kernel_driver_active(self.intf.bInterfaceNumber):
                try:
                    self.dev.detach_kernel_driver(self.intf.bInterfaceNumber)
                except Exception:
                    pass
        except Exception:
            pass
        usb.util.claim_interface(self.dev, self.intf.bInterfaceNumber)

    def close(self):
        try:
            usb.util.release_interface(self.dev, self.intf.bInterfaceNumber)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass

    def write_cmd(self, cmd: int, payload: bytes = b'') -> int:
        pkt = bytes([cmd]) + payload
        return int(self.dev.write(self.ep_out, pkt, timeout=1000))

    def read_in(self, nbytes: int = 4096, timeout_ms: int = 1000) -> bytes:
        return bytes(self.dev.read(self.ep_in, nbytes, timeout=timeout_ms))


def parse_hdr(b: bytes):
    return struct.unpack(HDR_FMT, b)

def hexb(b: bytes, n: int = 32) -> str:
    return ' '.join(f"{x:02X}" for x in b[:n]) + (" …" if len(b) > n else '')


def main() -> int:
    us = None
    fails = []
    notes = []
    try:
        us = USBVend()
        print(f"[info] opened {VID:04X}:{PID:04X} IF={us.intf.bInterfaceNumber} EPs IN={us.ep_in:#x} OUT={us.ep_out:#x}")

        # state vars
        test_seen = False
        size_locked: Optional[int] = None
        seq_pairs: Dict[int, Set[int]] = {}
        last_pair_seq: Optional[int] = None
        monotonic_ok = True
        only_work_flags_ok = True
        frames_collected = 0
        pairs_collected = 0
        buf = bytearray()
        MAGIC_LE = b"\x5A\xA5"

        def drain_buf():
            nonlocal test_seen, size_locked, seq_pairs, last_pair_seq, monotonic_ok, only_work_flags_ok, frames_collected, pairs_collected, buf
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
                payload_len = int(total_samples) * 2
                frame_total = HDR_SIZE + payload_len
                if len(buf) < frame_total:
                    break
                # optional test frame
                if (flags & 0x80) and total_samples == 8 and not test_seen:
                    print(f"[ok] test frame: flags=0x81 total=8 ver={ver}")
                    test_seen = True
                    del buf[:frame_total]
                    continue
                # working flag
                if flags & 0x01:
                    adc_id = 0
                elif flags & 0x02:
                    adc_id = 1
                else:
                    only_work_flags_ok = False
                    notes.append(f"unexpected flags 0x{flags:02X} seq={seq}")
                    del buf[:frame_total]
                    continue
                if size_locked is None:
                    size_locked = int(total_samples)
                    print(f"[lock] total_samples={size_locked}")
                elif int(total_samples) != int(size_locked):
                    fails.append(f"total_samples changed {size_locked}→{total_samples}")
                s16 = seq & 0xFFFF
                present = seq_pairs.setdefault(s16, set())
                if adc_id in present:
                    # duplicate same channel; ignore silently
                    del buf[:frame_total]
                    continue
                present.add(adc_id)
                if present == {0,1}:
                    pairs_collected += 1
                    if last_pair_seq is not None:
                        gap = (s16 - last_pair_seq) & 0xFFFF
                        if gap != 1:
                            monotonic_ok = False
                            notes.append(f"pair seq gap {last_pair_seq}->{s16}")
                    last_pair_seq = s16
                frames_collected += 1
                del buf[:frame_total]

        def consume_pairs(deadline: float, want_pairs: int):
            nonlocal buf
            # main loop
            while time.time() < deadline and pairs_collected < want_pairs:
                # read chunk
                try:
                    data = us.read_in(4096, timeout_ms=500)
                except usb.core.USBError as e:
                    if getattr(e, 'errno', None) == 110:  # timeout
                        drain_buf()
                        continue
                    raise
                if not data:
                    drain_buf()
                    continue
                # If STAT and data coalesced, strip exactly 64 bytes of STAT and keep the rest
                if data[:4] == b'STAT':
                    notes.append("STAT mid-stream")
                    if len(data) > 64:
                        data = data[64:]
                    else:
                        drain_buf()
                        continue
                notes.append(f"chunk len={len(data)} head={hexb(data,8)}")
                buf.extend(data)
                drain_buf()

        # Helpers
        def wait_for_stat(total_timeout_s: float) -> bytes:
            deadline = time.time() + total_timeout_s
            while time.time() < deadline:
                try:
                    data = us.read_in(4096, timeout_ms=400)
                except usb.core.USBError as e:  # type: ignore
                    if getattr(e, 'errno', None) == 110:
                        continue
                    else:
                        break
                if not data:
                    continue
                if data[:4] == b'STAT':
                    return data
                # else: keep data for later deframing; also handle case STAT+data coalesced
                if data[:4] == b'STAT' and len(data) > 64:
                    data = data[64:]
                buf.extend(data)
            return b''

        # ensure device is responsive and set mode before START
        try:
            # poke status once (some FW gates STAT by permit_once)
            us.write_cmd(CMD_GET_STATUS)
            _ = wait_for_stat(0.4)
            # 1 = 200 Hz, 2 = 300 Hz (per spec)
            us.write_cmd(CMD_SET_PROFILE, bytes([2]))
            time.sleep(0.05)
            us.write_cmd(CMD_SET_FULL_MODE, bytes([1]))
            time.sleep(0.05)
        except Exception:
            pass
        # start stream
        us.write_cmd(CMD_START)
        # try to catch immediate STAT ACK (optional)
        _ = wait_for_stat(0.9)
        # process anything accumulated
        drain_buf()

        # Immediately start consuming to get TEST and first A/B
        consume_pairs(time.time() + 6.0, want_pairs=1)
        if pairs_collected == 0 and size_locked is None:
            # retry START once more in case device missed it
            us.write_cmd(CMD_START)
            _ = wait_for_stat(0.6)
            consume_pairs(time.time() + 4.0, want_pairs=1)

        # Now collect at least one A/B pair and lock total_samples
        consume_pairs(time.time() + 8.0, want_pairs=1)
        if size_locked is None:
            # one more attempt window
            consume_pairs(time.time() + 8.0, want_pairs=1)
        # debug gate
        print(f"[dbg] gate: size_locked={size_locked} pairs_collected={pairs_collected}")
        if size_locked is None:
            fails.append("no working frames to lock total_samples (pre-GET_STATUS)")
        else:
            # GET_STATUS: wait up to 2.0s for STAT between pairs
            us.write_cmd(CMD_GET_STATUS)
            stat = wait_for_stat(2.0)
            if stat[:4] == b'STAT':
                print(f"[ok] GET_STATUS len={len(stat)} head={hexb(stat,16)}")
            else:
                fails.append("GET_STATUS: no 'STAT'")
            # keep collecting some frames after GET_STATUS
            consume_pairs(time.time() + 3.0, want_pairs=3)
            # STOP → wait up to 2.0s for STAT
            us.write_cmd(CMD_STOP)
            stat2 = wait_for_stat(2.0)
            if stat2[:4] == b'STAT':
                print(f"[ok] STOP→STAT len={len(stat2)} head={hexb(stat2,16)}")
            else:
                fails.append("STOP: no 'STAT'")
        # optional extra collection window
        consume_pairs(time.time() + 1.5, want_pairs=pairs_collected + 2)
        # summary
        if not test_seen:
            # Variant 2: отсутствие тестового кадра не приводит к FAIL, только предупреждение
            notes.append("warning: test frame (flags=0x81,total=8) not observed; treating as optional")
        if size_locked is None:
            fails.append("no working frames to lock total_samples")
        if not only_work_flags_ok:
            fails.append("non-working flags seen")
        if not monotonic_ok:
            fails.append("non-monotonic pair sequence")
        if fails:
            print("\nRESULT: FAIL")
            for f in fails:
                print(" -", f)
            if notes:
                print("Notes:")
                for n in notes:
                    print(" *", n)
            return 1
        else:
            print("\nRESULT: PASS")
            if size_locked is not None:
                print(f"locked total_samples={size_locked}")
            return 0
    finally:
        try:
            if us:
                us.close()
        except Exception:
            pass

if __name__ == '__main__':
    sys.exit(main())
