#!/usr/bin/env python3
"""
Попытка запустить устройство с разными командами
"""
import sys
sys.path.insert(0, '/home/techaid/Documents/host')

import usb.core
import time

print("🧪 Отладка команд для запуска устройства\n")

dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001)
if not dev:
    print("❌ Устройство не найдено!")
    sys.exit(1)

print(f"✓ Найдено устройство\n")

# Команды из usb_stream.py
commands = [
    (0x14, b'\x01', "SET_PROFILE (0x14) = 1"),
    (0x13, b'\x00\x00', "SET_FULL_MODE (0x13) = 0"),
    (0x20, b'', "START_STREAM (0x20)"),
]

print("[1] Отправляем команды последовательно:\n")

for cmd_num, cmd_data, desc in commands:
    try:
        print(f"  • {desc}...")
        # Отправляем как OUT команду на EP0
        dev.ctrl_transfer(0x40, cmd_num, 0, 0, cmd_data, timeout=1000)
        print(f"    ✓ Отправлено")
        time.sleep(0.1)
    except Exception as e:
        print(f"    ✗ Ошибка: {e}")

print("\n[2] Пытаемся читать данные с Bulk IN (5 сек)...\n")

cfg = dev.get_active_configuration()
intf = cfg[(2, 1)]
ep_in = None
for ep in intf:
    if ep.bEndpointAddress == 0x83:
        ep_in = ep
        break

if not ep_in:
    print("❌ EP 0x83 не найден!")
    sys.exit(1)

start_t = time.time()
got = 0

while time.time() - start_t < 5:
    try:
        data = dev.read(ep_in, 2048, timeout=500)
        if data and len(data) > 0:
            got += 1
            elapsed = time.time() - start_t
            print(f"  [{elapsed:.1f}s] ✓ Получено {len(data)} байт")
            if got == 1:
                print(f"         Первые 32 байта: {bytes(data[:32]).hex()}")
    except usb.core.USBTimeoutError:
        pass
    except Exception as e:
        print(f"  ✗ Error: {e}")
        break

print(f"\n📊 Получено пакетов: {got}")

if got > 0:
    print("✅ ЭНДПОИНТ РАБОТАЕТ!")
else:
    print("❌ Нет данных с эндпоинта")
    print("\n⚠️  Возможно:")
    print("  1. Микроконтроллер не инициализирован правильно")
    print("  2. Нужны дополнительные команды инициализации")
    print("  3. Прошивка требует перепрограммирования")

# Попытаемся остановить
print("\n[3] Отправляем STOP_STREAM...")
try:
    dev.ctrl_transfer(0x40, 0x21, 0, 0, b'', timeout=1000)
    print("  ✓ Отправлено")
except Exception as e:
    print(f"  ✗ Ошибка: {e}")
