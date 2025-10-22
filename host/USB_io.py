# USB_io.py — открытие порта и низкоуровневое чтение
from __future__ import annotations
import glob
import os
import time
from typing import Optional
import serial  # type: ignore[import-not-found]

# RX стэш, чтобы не терять байты между пробниками
RX_STASH = bytearray()

MAGIC = b"\x5A\xA5"
ALT_MAGIC = b"\xA5\x5A"
OPEN_RTS_LEVEL = None  # None — не трогаем, True/False — установить


def wait_for_cdc_port(port_arg: str, poll_interval: float = 0.5) -> str:
    if port_arg and port_arg != 'auto':
        return port_arg
    print('Ожидание USB CDC устройства (/dev/ttyACM*), авто-поиск... (Ctrl+C для выхода)')
    last = None
    while True:
        candidates = sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'))
        if candidates:
            if last != candidates:
                print('Найдены порты:', ', '.join(candidates))
                last = candidates
            # Если несколько портов — выберем тот, где есть входящий трафик
            chosen = candidates[0]
            if len(candidates) > 1:
                stats = []
                for p in candidates:
                    try:
                        info = sniff_port_bytes(p, seconds=0.3, sample_limit=0)
                    except Exception:
                        info = {'port': p, 'total': 0}
                    stats.append((p, info.get('total', 0)))
                stats.sort(key=lambda x: x[1], reverse=True)
                if stats and stats[0][1] > 0:
                    chosen = stats[0][0]
                    human = ", ".join(f"{p}:{n}" for p, n in stats)
                    print(f"[auto] Активность по портам за 0.3с: {human}. Выбираю {chosen}")
            print(f'Найден порт: {chosen}')
            return chosen
        time.sleep(poll_interval)


def list_cdc_ports() -> list[str]:
    """Возвращает список доступных CDC-портов /dev/ttyACM* и /dev/ttyUSB*."""
    return sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'))


def sniff_port_bytes(path: str, seconds: float = 1.0, sample_limit: int = 64) -> dict:
    """Пробный захват байтов с порта за отведённое время.
    Возвращает { 'port': path, 'total': N, 'sample': bytes } и гарантированно закрывает порт.
    """
    total = 0
    sample = bytearray()
    ser = None
    try:
        ser = open_serial(path, timeout=0.05)
        try:
            ser.timeout = 0.05
        except Exception:
            pass
        t_end = time.time() + max(0.0, seconds)
        while time.time() < t_end:
            try:
                b = ser.read(256)
            except Exception:
                b = b''
            if b:
                total += len(b)
                if len(sample) < sample_limit:
                    need = sample_limit - len(sample)
                    sample.extend(b[:need])
            else:
                time.sleep(0.02)
    except Exception:
        pass
    finally:
        try:
            if ser:
                ser.close()
        except Exception:
            pass
    return {'port': path, 'total': total, 'sample': bytes(sample)}


def capture_bytes(path: str, count: int, seconds: float = 2.0) -> bytes:
    """Считывает не более count байт с порта за отведённое время и возвращает их."""
    ser = None
    out = bytearray()
    try:
        ser = open_serial(path, timeout=0.1)
        deadline = time.time() + max(0.0, seconds)
        while len(out) < count and time.time() < deadline:
            b = ser.read(min(1024, count - len(out)))
            if b:
                out.extend(b)
            else:
                time.sleep(0.01)
    except Exception:
        pass
    finally:
        try:
            if ser:
                ser.close()
        except Exception:
            pass
    return bytes(out)


def open_serial(port: str, timeout: float = 1.0, baudrate: int | None = None) -> serial.Serial:
    ser = serial.Serial(
        port=port,
        baudrate=(baudrate or 115200),
        timeout=timeout,
        exclusive=True,
        write_timeout=1.0,
    )
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    # DTR: False→True как мягкий триггер, если устройство слушает
    try:
        ser.setDTR(False); time.sleep(0.02); ser.setDTR(True)
    except Exception:
        pass
    if OPEN_RTS_LEVEL is not None:
        try:
            ser.setRTS(bool(OPEN_RTS_LEVEL))
        except Exception:
            pass
    return ser


def read_exact(ser: serial.Serial, n: int, what: str = 'bytes', timeout_s: Optional[float] = None) -> bytes:
    """Читает ровно n байт или кидает TimeoutError.
    Таймаут «скользящий»: дедлайн продлевается при каждом поступлении данных.
    """
    buf = bytearray()
    # Сначала из локального стэша
    global RX_STASH
    if RX_STASH:
        take = min(n, len(RX_STASH))
        buf.extend(RX_STASH[:take])
        del RX_STASH[:take]
        n -= take
        if n <= 0:
            return bytes(buf)
    idle = timeout_s if (timeout_s and timeout_s > 0) else max(ser.timeout or 0, 1.0)
    deadline = time.time() + idle
    while n > 0:
        if time.time() > deadline:
            raise TimeoutError(f'Timeout while reading {what}')
        chunk = ser.read(n)
        if not chunk:
            # маленькая пауза и ещё попытка
            time.sleep(0.001)
            continue
        buf.extend(chunk)
        n -= len(chunk)
        # продлеваем дедлайн при прогрессе
        deadline = time.time() + idle
    return bytes(buf)


def sync_to_magic(ser: serial.Serial, max_wait_s: float = 3.0, *, allow_alt_vendor: bool = False) -> bytes:
    prev = b''
    # Если в стэше уже есть байты, учтём их при поиске MAGIC
    global RX_STASH
    if RX_STASH:
        prev = bytes(RX_STASH)
        RX_STASH.clear()
    deadline = time.time() + (max_wait_s if max_wait_s and max_wait_s > 0 else 2.0)
    while True:
        if time.time() > deadline:
            try:
                avail = getattr(ser, 'in_waiting', 0)
                if avail:
                    peek = ser.read(min(64, avail))
                    print(f"[sync] timeout, in_waiting={avail}, peek[:32]={' '.join(f'{x:02x}' for x in peek[:32])}")
            except Exception:
                pass
            if allow_alt_vendor:
                raise TimeoutError('Timeout while searching magic 0x5A 0xA5/0xA5 0x5A')
            else:
                raise TimeoutError('Timeout while searching magic 0x5A 0xA5')
        try:
            b = ser.read(32)
        except (serial.SerialException, OSError):
            time.sleep(0.002); continue
        if not b:
            continue
        data = prev + b
        idx = data.find(MAGIC)
        if idx >= 0:
            tail = data[idx+2:]
            if tail:
                RX_STASH[:0] = tail
            return MAGIC
        if data.find(ALT_MAGIC) >= 0:
            if allow_alt_vendor:
                tail = data[data.find(ALT_MAGIC)+2:]
                if tail:
                    RX_STASH[:0] = tail
                return ALT_MAGIC
            else:
                print('[sync] Найдена последовательность A5 5A (ALT_MAGIC). Продолжаю поиск 5A A5')
        prev = data[-1:]


def push_rx_front(data: bytes) -> None:
    """Возвращает байты в начало RX_STASH, чтобы их прочитал следующий вызов read_exact/sync."""
    if not data:
        return
    global RX_STASH
    RX_STASH[:0] = data
