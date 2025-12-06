#!/usr/bin/env python3
"""
Проверить статус устройства
"""
import sys
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream
import time

print("[STAT] Проверяем статус устройства\n")

try:
    stream = USBStream(profile=1, full=True, fast_mode=True)
    print(f"✓ USBStream создан\n")
    
    # Отправляем GET_STATUS (0x30)
    print("[STAT] Отправляем GET_STATUS...")
    stream.send_cmd(0x30, b'')
    time.sleep(0.2)
    
    # Смотрим на последний статус
    print(f"[STAT] last_stat: {stream.last_stat}\n")
    
    # Пробуем еще раз
    stream.send_cmd(0x30, b'')
    time.sleep(0.2)
    print(f"[STAT] last_stat (попытка 2): {stream.last_stat}\n")
    
    # Смотрим что приходит по EP0
    print("[STAT] Читаем EP0...")
    try:
        data = stream.dev.ctrl_transfer(0xC0, 0x30, 0, 0, 64, timeout=1000)
        print(f"[STAT] EP0 ответ: {data.hex()}\n")
    except Exception as e:
        print(f"[STAT] EP0 ошибка: {e}\n")
    
    # Смотрим на фоновый поток состояние
    print(f"[STAT] Stream stats:")
    print(f"  frames: {stream.frames}")
    print(f"  bytes: {stream.bytes}")
    print(f"  _working_seen: {stream._working_seen}")
    print(f"  test_seen: {stream.test_seen}")
    
    stream.close()
    
except Exception as e:
    import traceback
    print(f"[ERROR] {e}")
    traceback.print_exc()
