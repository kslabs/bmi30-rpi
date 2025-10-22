# USB_proto.py — команды и протокол CDC
from __future__ import annotations
import struct
import time
import zlib
from typing import Optional, Tuple
import serial  # type: ignore[import-not-found]

# Команды
CMD_PING         = 0x01
CMD_SET_WINDOWS  = 0x10  # payload: start0(uint16), len0(uint16), start1(uint16), len1(uint16), LE
CMD_SET_BLOCK_HZ = 0x11  # payload: block_hz(uint16), LE
CMD_START        = 0x20
CMD_STOP         = 0x21
CMD_GET_STATUS   = 0x30

# Ответы
RSP_ACK    = 0x80
RSP_NACK   = 0x81
RSP_STATUS = 0x82

# MAGIC кадра
MAGIC = b"\x5A\xA5"
ALT_MAGIC = b"\xA5\x5A"

# CRC стратегии
def crc32_incl(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF

def crc32_ieee(data: bytes) -> int:
    return (zlib.crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF) & 0xFFFFFFFF

# Базовые команды

def send_cmd(
    ser: serial.Serial,
    cmd: int,
    payload: bytes = b"",
    expect_ack: bool = True,
    *,
    stream_aware: bool = False,
    timeout: float = 1.0,
):
    ser.write(bytes([cmd]) + payload)
    ser.flush()
    if not expect_ack:
        return None

    if not stream_aware:
        b = ser.read(1)
        if not b:
            raise TimeoutError("Timeout while reading rsp id")
        if b[0] == RSP_ACK:
            echo = ser.read(1)
            if not echo:
                raise TimeoutError("Timeout while reading ack echo")
            if echo[0] != cmd:
                raise RuntimeError(f"ACK echo mismatch: got 0x{echo[0]:02X}, expected 0x{cmd:02X}")
            return ("ACK", None)
        elif b[0] == RSP_NACK:
            echo = ser.read(1)
            code = ser.read(1)
            if not echo or not code:
                raise TimeoutError("Timeout while reading nack body")
            return ("NACK", code[0])
        elif b[0] == RSP_STATUS:
            ser.timeout, t_old = 0.02, ser.timeout
            try:
                rest = ser.read(256)
            finally:
                ser.timeout = t_old
            return ("STATUS", bytes(rest))
        else:
            raise RuntimeError(f"Unknown response id: 0x{b[0]:02X}")
    else:
        # stream-aware: читаем с короткими таймаутами, не валим сессию на таймауте
        t_old = ser.timeout
        try:
            ser.timeout = timeout
            b = ser.read(1)
            if not b:
                raise TimeoutError("Timeout while reading rsp id")
            if b[0] == RSP_ACK:
                echo = ser.read(1)
                if not echo:
                    raise TimeoutError("Timeout while reading ack echo")
                return ("ACK", None)
            elif b[0] == RSP_NACK:
                echo = ser.read(1); code = ser.read(1)
                if not echo or not code:
                    raise TimeoutError("Timeout while reading nack body")
                return ("NACK", code[0])
            elif b[0] == RSP_STATUS:
                rest = ser.read(256)
                return ("STATUS", bytes(rest))
            else:
                return ("UNKNOWN", b[0])
        finally:
            ser.timeout = t_old


def send_cmd_no_ack(ser: serial.Serial, cmd: int, payload: bytes = b""):
    ser.write(bytes([cmd]) + payload)
    ser.flush()


def set_windows(ser: serial.Serial, start0: int, len0: int, start1: int, len1: int):
    payload = struct.pack('<HHHH', start0 & 0xFFFF, len0 & 0xFFFF, start1 & 0xFFFF, len1 & 0xFFFF)
    return send_cmd(ser, CMD_SET_WINDOWS, payload)


def set_block_rate(ser: serial.Serial, hz: int):
    payload = struct.pack('<H', max(0, hz) & 0xFFFF)
    return send_cmd(ser, CMD_SET_BLOCK_HZ, payload)


def start_stream(ser: serial.Serial):
    return send_cmd(ser, CMD_START)


def stop_stream(ser: serial.Serial):
    return send_cmd(ser, CMD_STOP)
