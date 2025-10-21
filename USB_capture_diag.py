#!/usr/bin/env python3
"""USB_capture_diag.py
Диагностический сбор:
 1. Авто-подбор CDC порта.
 2. Отправка START (0x20) — игнорирует отсутствие ACK.
 3. Захват до 5 кадров (использует USB_frame.read_frame) или таймаут.
 4. Поиск 32-байтного статусного блока ('STAT' v2) в сыром байтовом потоке.
 5. Вывод сводки и расшифровка статуса.

Не претендует на точные USB packet boundary — работает на уровне потока ttyACM.
Для настоящих USB пакетов используйте usbmon / Wireshark (инструкции см. основной ответ).
"""
from __future__ import annotations
import time
import argparse
import USB_io
import USB_proto
import USB_frame

def to_hex(b: bytes, max_len: int = 64) -> str:
    if not b:
        return ''
    v = b[:max_len]
    s = ' '.join(f"{x:02X}" for x in v)
    if len(b) > max_len:
        s += f" …(+{len(b)-max_len})"
    return s

def parse_status32(block: bytes) -> dict:
    if not (block.startswith(b'STAT') and len(block) >= 32):
        return {}
    def u16(le: bytes) -> int: return int.from_bytes(le, 'little')
    return {
        'version': block[4],
        'flags': block[5],
        'channels': block[6],
        'last_sent_seq': u16(block[8:10]),
        'produced_seq': u16(block[10:12]),
        'sent_ch0': u16(block[12:14]),
        'sent_ch1': u16(block[14:16]),
        'uptime_ms': int.from_bytes(block[16:20], 'little'),
        'errors': u16(block[20:22]),
        'debug0': u16(block[22:24]),
        'debug1': u16(block[24:26]),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='auto')
    ap.add_argument('--baudrate', type=int, default=2_000_000)
    ap.add_argument('--frames', type=int, default=5, help='Макс. число кадров для захвата')
    ap.add_argument('--frame-timeout', type=float, default=1.0)
    ap.add_argument('--overall', type=float, default=8.0, help='Глобальный лимит секунд на фазу кадров')
    ap.add_argument('--status-wait', type=float, default=3.0, help='Время ожидания первого статуса после кадров')
    args = ap.parse_args()

    port = USB_io.wait_for_cdc_port(args.port)
    ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
    print(f"[diag] Открыт порт {port} @ {args.baudrate}")
    try:
        # START
        try:
            rsp = USB_proto.start_stream(ser)
            print(f"[diag] START rsp={rsp}")
        except Exception as e:
            print(f"[diag] START no ACK: {e}")

        frames = []
        t_dead = time.time() + args.overall
        while len(frames) < args.frames and time.time() < t_dead:
            try:
                fr = USB_frame.read_frame(
                    ser,
                    crc_strategy='none',
                    sync_wait_s=0.8,
                    io_timeout_s=0.4,
                    frame_timeout_s=args.frame_timeout,
                    max_retries=1,
                    fast_drop=True,
                )
                raw = fr.get('raw', b'')
                frames.append(fr)
                print(f"[diag] frame#{len(frames)} seq={fr['seq']} raw_len={len(raw)} total={fr['total_samples']} ch={fr['channels']} fmt=0x{fr['fmt']:04X}")
            except TimeoutError:
                continue
            except Exception as e:
                print(f"[diag] frame err: {e}")
                continue

        if not frames:
            print('[diag] Кадры не получены — переход к поиску статуса (вдруг только STAT идёт).')

        # Сбор сырых байт для статуса
        status_block = b''
        buf = b''
        t_stat = time.time() + args.status_wait
        while time.time() < t_stat and not status_block:
            chunk = ser.read(64)
            if chunk:
                buf += chunk
                pos = buf.find(b'STAT')
                if pos >= 0 and len(buf) >= pos + 32:
                    status_block = buf[pos:pos+32]
                    break
            else:
                time.sleep(0.02)
            if len(buf) > 512:
                buf = buf[-256:]

        print('===== SUMMARY =====')
        if frames:
            lens = [len(fr['raw']) for fr in frames]
            print(f"[diag] frames_count={len(frames)} lens={lens}")
            # покажем первые 16 байт каждого
            for i, fr in enumerate(frames[:5]):
                raw = fr['raw']
                print(f"[diag] frame{i+1} head16: {to_hex(raw[:16],16)}")
        else:
            print('[diag] frames_count=0')

        if status_block:
            parsed = parse_status32(status_block)
            print(f"[diag] status32 raw={to_hex(status_block,64)} parsed={parsed}")
        else:
            print('[diag] status32 НЕ найден')

    finally:
        try:
            ser.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
