#!/usr/bin/env python3
"""
Прямой тест Bulk IN эндпоинта на низком уровне
"""
import sys
import time
import usb.core
import usb.util

print("🔍 Прямой тест USB Bulk IN эндпоинта\n")

# Найдем устройство
dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001)
if not dev:
    print("❌ Устройство не найдено!")
    sys.exit(1)

print(f"✓ Найдено: {dev}")

# Попытаемся открыть конфигурацию
try:
    # Конфигурация может быть уже установлена
    cfg = dev.get_active_configuration()
    print(f"✓ Конфигурация уже установлена")
except Exception as e:
    print(f"! Конфигурация не установлена: {e}")
    try:
        dev.set_configuration()
        print(f"✓ Конфигурация установлена")
        cfg = dev.get_active_configuration()
    except Exception as e2:
        print(f"! Невозможно установить конфигурацию: {e2}")
        sys.exit(1)

# Найдем Bulk IN эндпоинт (0x83)
ep_in = None
try:
    intf = cfg[(2, 1)]  # Interface 2, Alternate Setting 1
except:
    try:
        intf = cfg[2]
    except:
        print("❌ Интерфейс 2 не найден!")
        sys.exit(1)

for ep in intf:
    if ep.bEndpointAddress == 0x83:  # Ищем ровно EP 0x83
        ep_in = ep
        print(f"✓ Найден Bulk IN эндпоинт: 0x{ep.bEndpointAddress:02x}")
        break

if not ep_in:
    print("❌ Bulk IN эндпоинт не найден!")
    sys.exit(1)

# Отправим START_STREAM через контрольный эндпоинт
print(f"\n[CTRL] Отправляем START_STREAM через EP0...")
try:
    dev.ctrl_transfer(0xC0, 0x20, 0, 0, 0, timeout=1000)  # Или можно 0x40 для OUT
    print(f"✓ Отправлено")
except Exception as e:
    print(f"! Ошибка: {e}")

time.sleep(0.5)

# Пробуем читать данные с Bulk IN
print(f"\n[BULK] Читаем с Bulk IN эндпоинта 0x{ep_in.bEndpointAddress:02x}...")
print(f"  Max packet size: {ep_in.wMaxPacketSize}")
print(f"  Timeout: 5000ms")

start_t = time.time()
frames_got = 0
errors = 0

while time.time() - start_t < 5:
    try:
        # Читаем с таймаутом 1 сек
        data = dev.read(ep_in, ep_in.wMaxPacketSize, timeout=1000)
        if data and len(data) > 0:
            frames_got += 1
            elapsed = time.time() - start_t
            print(f"  [{elapsed:.1f}s] ✓ Получено {len(data)} байт: {bytes(data[:16]).hex()}...")
    except usb.core.USBTimeoutError:
        # Timeout - нормально, пробуем снова
        pass
    except usb.core.USBError as e:
        errors += 1
        print(f"  ! USB Error: {e}")
        if errors > 3:
            break
    except Exception as e:
        errors += 1
        print(f"  ! Error: {e}")

elapsed = time.time() - start_t
print(f"\n📊 Результаты за {elapsed:.1f}сек:")
print(f"  Получено пакетов: {frames_got}")
print(f"  Ошибок: {errors}")

if frames_got > 0:
    print(f"  ✅ ЭНДПОИНТ РАБОТАЕТ!")
else:
    print(f"  ❌ ЭНДПОИНТ НЕ ОТПРАВЛЯЕТ ДАННЫЕ")

# Отправим STOP_STREAM
print(f"\n[CTRL] Отправляем STOP_STREAM...")
try:
    dev.ctrl_transfer(0xC0, 0x21, 0, 0, 0, timeout=1000)
    print(f"✓ Отправлено")
except Exception as e:
    print(f"! Ошибка: {e}")
