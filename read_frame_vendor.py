#!/usr/bin/env python3
from __future__ import annotations
import USB_frame
from USB_vnd import open_vendor

def to_hex(b: bytes, n=32):
    b=b[:n]
    return ' '.join(f"{x:02X}" for x in b)

def main():
    ser = open_vendor()
    try:
        # Стартуем поток на вендор-интерфейсе (без ожидания ACK)
        try:
            ser.write(bytes([0x20]))  # CMD_START
        except Exception:
            pass
        # небольшая пауза, чтобы пошли кадры
        import time as _t
        _t.sleep(0.05)
        fr = USB_frame.read_frame(
            ser,
            crc_strategy='none',
            sync_wait_s=2.0,
            io_timeout_s=0.5,
            frame_timeout_s=3.0,
            max_retries=2,
            fast_drop=True,
        )
        raw = fr.get('raw', b'')
        print(f"seq={fr['seq']} total={fr['total_samples']} ch={fr['channels']} fmt=0x{fr['fmt']:04X} raw_len={len(raw)}")
        print(f"hdr16: {to_hex(raw[2:18], 16)}")
        print(f"head32: {to_hex(raw, 32)}")
    finally:
        ser.close()

if __name__ == '__main__':
    main()
