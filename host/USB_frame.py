# USB_frame.py — разбор кадра и CRC
from typing import Dict
import struct
import zlib
import numpy as np
import USB_io
import USB_proto
import serial


def hex_bytes(b: bytes, n: int | None = None) -> str:
    try:
        view = b if n is None else b[:n]
        return ' '.join(f'{x:02X}' for x in view)
    except Exception:
        return ''
def read_frame(
    ser: serial.Serial,
    crc_strategy: str = 'auto',
    sync_wait_s: float = 3.0,
    io_timeout_s: float = 1.0,
    frame_timeout_s: float | None = None,
    max_retries: int = 5,
    fast_drop: bool = False,
) -> Dict:
    import time as _t
    deadline = _t.time() + frame_timeout_s if (frame_timeout_s and frame_timeout_s > 0) else None

    def _remain(default: float) -> float:
        if deadline is None:
            return default
        left = deadline - _t.time()
        if left <= 0:
            raise TimeoutError('Frame timeout')
        return min(default, left)

    last_err: Exception | None = None
    for _ in range(max(1, max_retries)):
        USB_io.sync_to_magic(ser, max_wait_s=_remain(sync_wait_s))
        hdr = USB_io.read_exact(ser, 16, 'header', timeout_s=_remain(io_timeout_s))
        if len(hdr) < 16:
            last_err = ValueError('Header too short')
            continue
        ver = struct.unpack_from('<H', hdr, 0)[0]
        a_total = struct.unpack_from('<H', hdr, 2)[0]
        msec = struct.unpack_from('>I', hdr, 4)[0]
        seq = struct.unpack_from('<H', hdr, 8)[0]
        fmt = struct.unpack_from('<H', hdr, 10)[0]
        channels_orig = struct.unpack_from('<H', hdr, 12)[0]
        a_table = struct.unpack_from('<H', hdr, 14)[0]
        b_total = a_table
        b_table = a_total
        def _plausible(table_val: int) -> bool:
            return (table_val == 0) or (table_val % 4 == 0 and 0 < table_val <= 4096)
        if _plausible(a_table) and not _plausible(b_table):
            total_samples_hdr, table_bytes = a_total, a_table
        elif _plausible(b_table) and not _plausible(a_table):
            total_samples_hdr, table_bytes = b_total, b_table
        else:
            total_samples_hdr, table_bytes = a_total, a_table

        # Диагностический фейковый формат: fmt&0x0080 и channels==0 => 2ch, 128 samples, без CRC
        diag_fake = ((fmt & 0x0080) != 0) and (channels_orig == 0)
        channels = (2 if diag_fake else channels_orig)
        if not (1 <= channels <= 8):
            last_err = ValueError(f'Bad channels: {channels}')
            continue

        # Общие переменные
        win_lengths: list[tuple[int, int]] = []
        tbl = b''
        payload = b''
        tail_crc = b''
        sum_len = 0
        win_count = 0
        table_bytes_eff = table_bytes
        variant = 'auto'

        per_ch_len_hdr = ((fmt & 0x0004) != 0)
        special_fmt = ((fmt & 0x1000) != 0) and (not per_ch_len_hdr)

        if diag_fake:
            sum_len = 128
            win_count = 1
            win_lengths = [(0, sum_len)]
            table_bytes_eff = 0
            # читаем фиксированный payload, CRC отсутствует
            try:
                bps = float(getattr(ser, 'baudrate', 115200.0))
                bytes_per_sec = max(1.0, bps / 10.0)
            except Exception:
                bytes_per_sec = 11520.0
            payload_len = sum_len * channels * 2
            est = payload_len / bytes_per_sec + 0.5
            dyn_timeout = max(io_timeout_s, est)
            payload = USB_io.read_exact(ser, payload_len, 'payload(diag)', timeout_s=_remain(dyn_timeout))
            tail_crc = b''
            variant = 'none'
        elif special_fmt:
            try:
                tbl = USB_io.read_exact(ser, 4, 'prelude', timeout_s=_remain(io_timeout_s))
            except Exception as e:
                last_err = e
                continue
            win_count = 1
            s, v = struct.unpack_from('<HH', tbl, 0)
            cand_len: list[int] = []
            if v > 0:
                cand_len.append(v)
            if v >= s:
                cand_len.append(v - s)
            for l in cand_len:
                if 0 < l <= 32768:
                    sum_len = l
                    break
            if sum_len <= 0:
                if fast_drop:
                    last_err = ValueError('fast_drop: skip fallback (special fmt)')
                    continue
                max_payload = 65536
                step = 32
                while True:
                    if len(payload) >= max_payload:
                        last_err = ValueError('Payload too large without CRC match (special fmt)')
                        break
                    try:
                        more = USB_io.read_exact(ser, step, 'payload(step)', timeout_s=_remain(io_timeout_s))
                    except Exception as e:
                        last_err = e
                        break
                    payload += more
                    try:
                        crc_cand = USB_io.read_exact(ser, 4, 'crc32?', timeout_s=_remain(io_timeout_s))
                    except Exception as e:
                        last_err = e
                        break
                    bodies = [
                        ('incl+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0, False),
                        ('incl-ff+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0xFFFFFFFF, True),
                        ('excl+tbl', hdr + tbl + payload, 0, False),
                        ('excl-ff+tbl', hdr + tbl + payload, 0xFFFFFFFF, True),
                        ('incl', USB_proto.MAGIC + hdr + payload, 0, False),
                        ('incl-ff', USB_proto.MAGIC + hdr + payload, 0xFFFFFFFF, True),
                        ('excl', hdr + payload, 0, False),
                        ('excl-ff', hdr + payload, 0xFFFFFFFF, True),
                        ('payload', payload, 0, False),
                        ('payload-ff', payload, 0xFFFFFFFF, True),
                        ('tbl+payload', tbl + payload, 0, False),
                        ('tbl+payload-ff', tbl + payload, 0xFFFFFFFF, True),
                    ]
                    matched = False
                    for name, body, init, do_xor in bodies:
                        c = zlib.crc32(body, init) & 0xFFFFFFFF
                        if do_xor:
                            c = (c ^ 0xFFFFFFFF) & 0xFFFFFFFF
                        cand_le = int.from_bytes(crc_cand, 'little') & 0xFFFFFFFF
                        cand_be = int.from_bytes(crc_cand, 'big') & 0xFFFFFFFF
                        if c == cand_le or c == cand_be:
                            tail_crc = crc_cand
                            variant = name
                            matched = True
                            break
                    if matched:
                        break
                    payload += crc_cand
                if not payload or not tail_crc:
                    continue
                total_i16 = len(payload) // 2
                samples_per_ch = max(0, total_i16 // max(1, channels))
                sum_len = samples_per_ch
                if sum_len <= 0:
                    last_err = ValueError('Zero samples after CRC delimitation (special fmt)')
                    continue
                win_lengths = [(0, sum_len)]
            else:
                payload_len = sum_len * channels * 2
                try:
                    bps = float(getattr(ser, 'baudrate', 115200.0))
                    bytes_per_sec = max(1.0, bps / 10.0)
                except Exception:
                    bytes_per_sec = 11520.0
                est = payload_len / bytes_per_sec + 0.5
                dyn_timeout = max(io_timeout_s, est)
                payload = USB_io.read_exact(ser, payload_len, 'payload', timeout_s=_remain(dyn_timeout))
                tail_crc = b''
        elif per_ch_len_hdr:
            samples_per_ch = int(total_samples_hdr)
            if samples_per_ch <= 0 or samples_per_ch > 32768:
                last_err = ValueError(f'Bad samples_per_ch in header: {samples_per_ch}')
                continue
            sum_len = samples_per_ch
            win_count = channels
            starts: list[int] = []
            if table_bytes_eff:
                if table_bytes_eff not in (channels * 2, channels * 4):
                    last_err = ValueError(f'Unexpected table_bytes for per-ch starts: {table_bytes_eff}, ch={channels}')
                    continue
                tbl = USB_io.read_exact(ser, table_bytes_eff, 'per-ch starts/len', timeout_s=_remain(io_timeout_s))
                if table_bytes_eff == channels * 2:
                    for i in range(channels):
                        s = struct.unpack_from('<H', tbl, i * 2)[0]
                        starts.append(s)
                    win_lengths = [(s, samples_per_ch) for s in starts]
                else:
                    lens: list[int] = []
                    for i in range(channels):
                        s, l = struct.unpack_from('<HH', tbl, i * 4)
                        starts.append(s)
                        lens.append(l)
                    if all(l == lens[0] for l in lens):
                        sum_len = int(lens[0])
                    win_lengths = [(starts[i], sum_len) for i in range(channels)]
            else:
                win_lengths = [(0, samples_per_ch) for _ in range(channels)]
            payload_len = sum_len * channels * 2
            try:
                bps = float(getattr(ser, 'baudrate', 115200.0))
                bytes_per_sec = max(1.0, bps / 10.0)
            except Exception:
                bytes_per_sec = 11520.0
            est = payload_len / bytes_per_sec + 0.5
            dyn_timeout = max(io_timeout_s, est)
            payload = USB_io.read_exact(ser, payload_len, 'payload', timeout_s=_remain(dyn_timeout))
            tail_crc = USB_io.read_exact(ser, 4, 'crc32', timeout_s=_remain(io_timeout_s))
        else:
            if table_bytes_eff == 0:
                win_count = 1
                sum_len = int(total_samples_hdr) // max(1, channels)
            else:
                if (table_bytes_eff % 4) != 0 or table_bytes_eff > 4096:
                    last_err = ValueError(f'Bad table_bytes: {table_bytes_eff}')
                    continue
                win_count = table_bytes_eff // 4
                tbl = USB_io.read_exact(ser, table_bytes_eff, 'window table', timeout_s=_remain(io_timeout_s))
                sum_len = 0
                sum_len_alt = 0
                win_lengths.clear()
                for i in range(win_count):
                    s, v = struct.unpack_from('<HH', tbl, i * 4)
                    win_lengths.append((s, v))
                    sum_len += v
                    if v >= s:
                        sum_len_alt += (v - s)
                def _reasonable(x: int) -> bool:
                    return 0 < x <= 32768
                if not _reasonable(sum_len) and _reasonable(sum_len_alt):
                    sum_len = sum_len_alt

            if table_bytes_eff == 0:
                payload_len = int(total_samples_hdr) * 2
                try:
                    bps = float(getattr(ser, 'baudrate', 115200.0))
                    bytes_per_sec = max(1.0, bps / 10.0)
                except Exception:
                    bytes_per_sec = 11520.0
                est = payload_len / bytes_per_sec + 0.5
                dyn_timeout = max(io_timeout_s, est)
                payload = USB_io.read_exact(ser, payload_len, 'payload', timeout_s=_remain(dyn_timeout))
                tail_crc = USB_io.read_exact(ser, 4, 'crc32', timeout_s=_remain(io_timeout_s))
            else:
                payload_len = sum_len * channels * 2
                if 0 < sum_len <= 32768:
                    try:
                        bps = float(getattr(ser, 'baudrate', 115200.0))
                        bytes_per_sec = max(1.0, bps / 10.0)
                    except Exception:
                        bytes_per_sec = 11520.0
                    est = payload_len / bytes_per_sec + 0.5
                    dyn_timeout = max(io_timeout_s, est)
                    payload = USB_io.read_exact(ser, payload_len, 'payload', timeout_s=_remain(dyn_timeout))
                    tail_crc = USB_io.read_exact(ser, 4, 'crc32', timeout_s=_remain(io_timeout_s))
                else:
                    if fast_drop:
                        last_err = ValueError('fast_drop: skip CRC search fallback')
                        continue
                    max_payload = 65536
                    step = 32
                    while True:
                        if len(payload) >= max_payload:
                            last_err = ValueError('Payload too large without CRC match (fallback)')
                            break
                        try:
                            more = USB_io.read_exact(ser, step, 'payload(step)', timeout_s=_remain(io_timeout_s))
                        except Exception as e:
                            last_err = e
                            break
                        payload += more
                        try:
                            crc_cand = USB_io.read_exact(ser, 4, 'crc32?', timeout_s=_remain(io_timeout_s))
                        except Exception as e:
                            last_err = e
                            break
                        bodies = [
                            ('incl+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0, False),
                            ('incl-ff+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0xFFFFFFFF, True),
                            ('excl+tbl', hdr + tbl + payload, 0, False),
                            ('excl-ff+tbl', hdr + tbl + payload, 0xFFFFFFFF, True),
                        ]
                        matched = False
                        for name, body, init, do_xor in bodies:
                            c = zlib.crc32(body, init) & 0xFFFFFFFF
                            if do_xor:
                                c = (c ^ 0xFFFFFFFF) & 0xFFFFFFFF
                            cand_le = int.from_bytes(crc_cand, 'little') & 0xFFFFFFFF
                            cand_be = int.from_bytes(crc_cand, 'big') & 0xFFFFFFFF
                            if c == cand_le or c == cand_be:
                                tail_crc = crc_cand
                                variant = name
                                matched = True
                                break
                        if matched:
                            break
                        payload += crc_cand
                    if not payload or not tail_crc:
                        continue

        # 5) CRC
        if diag_fake:
            crc_ok = True
            variant = 'none'
            crc_val = 0
        elif special_fmt and len(tail_crc) == 0:
            crc_ok = True
            variant = 'none'
            crc_val = 0
        else:
            crc_val = int.from_bytes(tail_crc, 'little') & 0xFFFFFFFF
            crc_ok = False
            variant = 'auto'
        if crc_strategy == 'none' and not (special_fmt or diag_fake):
            crc_ok = True
            variant = 'none'
        else:
            bodies = (
                [
                    ('incl+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0, False),
                    ('incl-ff+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0xFFFFFFFF, True),
                    ('excl+tbl', hdr + tbl + payload, 0, False),
                    ('excl-ff+tbl', hdr + tbl + payload, 0xFFFFFFFF, True),
                ] if (special_fmt and not diag_fake) else []
            ) + [
                ('incl', USB_proto.MAGIC + hdr + (payload if special_fmt else (tbl + payload)), 0, False),
                ('incl-ff', USB_proto.MAGIC + hdr + (payload if special_fmt else (tbl + payload)), 0xFFFFFFFF, True),
                ('excl', hdr + (payload if special_fmt else (tbl + payload)), 0, False),
                ('excl-ff', hdr + (payload if special_fmt else (tbl + payload)), 0xFFFFFFFF, True),
                ('payload', payload, 0, False),
                ('payload-ff', payload, 0xFFFFFFFF, True),
                ('tbl+payload', tbl + payload, 0, False),
                ('tbl+payload-ff', tbl + payload, 0xFFFFFFFF, True),
            ]
            for name, body, init, do_xor in bodies:
                c = zlib.crc32(body, init) & 0xFFFFFFFF
                if do_xor:
                    c = (c ^ 0xFFFFFFFF) & 0xFFFFFFFF
                if c == crc_val or c == int.from_bytes(tail_crc, 'big'):
                    crc_ok = True
                    variant = name
                    break
        if not crc_ok:
            bodies = (
                [
                    ('incl+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0, False),
                    ('incl-ff+tbl', USB_proto.MAGIC + hdr + tbl + payload, 0xFFFFFFFF, True),
                    ('excl+tbl', hdr + tbl + payload, 0, False),
                    ('excl-ff+tbl', hdr + tbl + payload, 0xFFFFFFFF, True),
                ] if (special_fmt and not diag_fake) else []
            ) + [
                ('incl', USB_proto.MAGIC + hdr + (payload if special_fmt else (tbl + payload)), 0, False),
                ('incl-ff', USB_proto.MAGIC + hdr + (payload if special_fmt else (tbl + payload)), 0xFFFFFFFF, True),
                ('excl', hdr + (payload if special_fmt else (tbl + payload)), 0, False),
                ('excl-ff', hdr + (payload if special_fmt else (tbl + payload)), 0xFFFFFFFF, True),
                ('payload', payload, 0, False),
                ('payload-ff', payload, 0xFFFFFFFF, True),
                ('tbl+payload', tbl + payload, 0, False),
                ('tbl+payload-ff', tbl + payload, 0xFFFFFFFF, True),
            ]
            cand = []
            for name, body, init, do_xor in bodies:
                c = zlib.crc32(body, init) & 0xFFFFFFFF
                if do_xor:
                    c = (c ^ 0xFFFFFFFF) & 0xFFFFFFFF
                cand.append(f"{name}={c:08x}")
            try:
                total_samples_for_crc = (sum_len if (table_bytes_eff != 0 and not special_fmt and not diag_fake) else int(len(payload)//2//max(1,channels)))
            except Exception:
                total_samples_for_crc = 0
            last_err = ValueError(
                'CRC mismatch: '
                f"seq={seq}, wins={win_count}, msec={msec}, total={total_samples_for_crc}, "
                f"hdr16={hex_bytes(hdr, 16)}, tbl_head={hex_bytes(tbl, 16)}, "
                f"payload_head={hex_bytes(payload, 16)}, crc_le={crc_val:08x}, cand={'/'.join(cand)}"
            )
            continue

        data = np.frombuffer(payload, dtype='<i2')
        if special_fmt or diag_fake:
            try:
                data = data[:sum_len*channels].reshape(-1, channels)
            except Exception:
                n = (data.size // max(1, channels)) * channels
                data = data[:n].reshape(-1, channels)
        elif table_bytes_eff == 0:
            total_i16 = data.size
            samples_per_ch = max(0, total_i16 // max(1, channels))
            if samples_per_ch <= 0:
                last_err = ValueError('Empty table: zero samples per channel after payload read')
                continue
            n = samples_per_ch * channels
            data = data[:n].reshape(-1, channels)
            sum_len = samples_per_ch
            win_lengths = [(0, sum_len)]
        else:
            try:
                data = data.reshape(-1, channels)
            except Exception:
                n = (data.size // max(1, channels)) * channels
                data = data[:n].reshape(-1, channels)

        return {
            'magic': USB_proto.MAGIC,
            'seq': seq,
            'win_count': win_count,
            'msec': msec,
            'total_samples': sum_len,
            'total_samples_hdr': total_samples_hdr,
            'channels': channels,
            'fmt': fmt,
            'ver': ver,
            'wins': win_lengths,
            'data': data,
            'crc_variant': variant,
            'raw': USB_proto.MAGIC + hdr + tbl + payload + tail_crc,
        }

    if last_err:
        raise last_err
    raise TimeoutError('Frame read failed without specific error')
