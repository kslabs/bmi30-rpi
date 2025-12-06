#!/usr/bin/env python3
"""
Диагностика: проверить что USBStream вообще работает
"""
import sys
sys.path.insert(0, '/home/techaid/Documents/host')

print("[1] Импортируем USBStream...")
try:
    from usb_vendor.usb_stream import USBStream
    print("    ✓ Импорт успешен")
except Exception as e:
    print(f"    ✗ Ошибка импорта: {e}")
    sys.exit(1)

print("\n[2] Проверяем USB устройства...")
import usb.core
devices = usb.core.find(find_all=True)
device_list = list(devices)
print(f"    Найдено {len(device_list)} USB устройств")
for dev in device_list:
    print(f"      {dev.idVendor:04x}:{dev.idProduct:04x}")

print("\n[3] Ищем CAFE:4001...")
dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001)
if dev:
    print(f"    ✓ Найдено устройство: {dev}")
else:
    print(f"    ✗ Устройство CAFE:4001 НЕ найдено")
    print("\n    Пробуем альтернативный поиск с allow_any=True...")
    try:
        stream = USBStream(profile=1, allow_any=True)
        print(f"    ✓ USBStream создан с allow_any=True")
        print(f"    Порт: {stream.port_info}")
    except Exception as e:
        print(f"    ✗ Ошибка: {e}")
    sys.exit(1)

print("\n[4] Создаем USBStream(profile=1)...")
try:
    stream = USBStream(profile=1, full=True, fast_mode=True)
    print(f"    ✓ USBStream создан")
    print(f"    Порт: {stream.port_info}")
except Exception as e:
    print(f"    ✗ Ошибка создания: {e}")
    sys.exit(1)

print("\n[5] Отправляем START_STREAM...")
try:
    stream.send_cmd(0x20, b'')
    print(f"    ✓ START_STREAM отправлен")
except Exception as e:
    print(f"    ✗ Ошибка: {e}")
    stream.close()
    sys.exit(1)

print("\n[6] Пытаемся получить данные...")
import time
start_t = time.time()
got_first = False
while time.time() - start_t < 5:
    try:
        pair = stream.get_stereo(timeout=0.5)
        if pair:
            a, b = pair
            print(f"    ✓ Получен кадр: A({len(a.payload)} байт), B({len(b.payload)} байт)")
            got_first = True
            break
    except Exception as e:
        print(f"    ! Ошибка: {e}")

if got_first:
    print("\n✅ УСПЕХ: USBStream работает!")
else:
    print("\n❌ ОШИБКА: Не получены данные за 5 секунд")

print("\n[7] Закрываем поток...")
try:
    stream.send_cmd(0x21, b'')  # STOP_STREAM
    stream.close()
    print("    ✓ Поток закрыт")
except Exception as e:
    print(f"    ! Ошибка: {e}")
