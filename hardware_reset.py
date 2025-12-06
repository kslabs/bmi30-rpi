#!/usr/bin/env python3
"""
Аппаратный сброс USB устройства
"""
import sys
import time
import subprocess

print("🔌 Аппаратный сброс USB устройства CAFE:4001\n")

# Способ 1: Через usb_modeswitch (если установлен)
print("[1] Попытка через usb_modeswitch...")
try:
    result = subprocess.run(['usb_modeswitch', '-v', '0xcafe', '-p', '0x4001', '-R'], 
                          capture_output=True, timeout=5)
    print(f"    Результат: {result.returncode}")
except Exception as e:
    print(f"    ! usb_modeswitch не работает: {e}")

time.sleep(1)

# Способ 2: Через uhubctl (сброс через USB hub)
print("\n[2] Попытка через uhubctl (сброс hub port)...")
try:
    # Найдём информацию об устройстве
    result = subprocess.run(['lsusb', '-t'], capture_output=True, text=True, timeout=5)
    print("    Ищем устройство в USB tree...")
    
    # Попытаемся сбросить порт где устройство подключено (обычно 1-1)
    result = subprocess.run(['uhubctl', '-p', '1-1', '-a', 'cycle'], 
                          capture_output=True, text=True, timeout=10)
    print(f"    uhubctl результат: {result.returncode}")
    if result.stdout:
        print(f"    {result.stdout}")
except Exception as e:
    print(f"    ! uhubctl не работает: {e}")

time.sleep(2)

# Способ 3: Через sysfs - отключить/включить устройство
print("\n[3] Попытка через sysfs (bind/unbind)...")
try:
    # Найдём путь устройства
    result = subprocess.run(['lsusb', '-v', '-d', 'cafe:4001'], 
                          capture_output=True, text=True, timeout=5)
    
    # Получим Bus и Device номер
    import re
    match = re.search(r'Bus\s+(\d+)\s+Device\s+(\d+)', result.stdout)
    if match:
        bus = match.group(1)
        device = match.group(2)
        print(f"    Найдено: Bus {bus}, Device {device}")
        
        # Попытаемся найти sysfs путь
        result = subprocess.run(['find', '/sys/bus/usb/devices', '-name', '*cafe*'], 
                              capture_output=True, text=True, timeout=5)
        if result.stdout:
            device_path = result.stdout.strip().split('\n')[0]
            print(f"    Путь: {device_path}")
            
            # Отключаем
            print(f"    Отключаем...")
            subprocess.run(['sh', '-c', f'echo 0 > {device_path}/power/autosuspend_delay_ms'],
                         capture_output=True, timeout=5)
            time.sleep(0.5)
            subprocess.run(['sh', '-c', f'echo suspend > {device_path}/power/control'],
                         capture_output=True, timeout=5)
            time.sleep(1)
            
            # Включаем
            print(f"    Включаем...")
            subprocess.run(['sh', '-c', f'echo on > {device_path}/power/control'],
                         capture_output=True, timeout=5)
            time.sleep(1)
            print(f"    ✓ Готово")
        else:
            print(f"    ! Не найден sysfs путь")
except Exception as e:
    print(f"    ! Ошибка sysfs: {e}")

time.sleep(2)

# Способ 4: Физический reset через PyUSB
print("\n[4] Попытка через PyUSB...")
try:
    sys.path.insert(0, '/home/techaid/Documents/host')
    import usb.core
    import usb.backend.libusb1
    
    backend = usb.backend.libusb1.get_backend()
    dev = usb.core.find(idVendor=0xcafe, idProduct=0x4001, backend=backend)
    
    if dev:
        print(f"    Выполняем dev.reset()...")
        dev.reset()
        print(f"    ✓ Reset выполнен")
        time.sleep(2)
    else:
        print(f"    ! Устройство не найдено")
except Exception as e:
    print(f"    ! Ошибка PyUSB: {e}")

print("\n✅ Процедура завершена, ждём переподключения устройства...")
time.sleep(3)

# Проверим что устройство снова в системе
print("\n[CHECK] Проверяем наличие устройства...")
result = subprocess.run(['lsusb', '-d', 'cafe:4001'], capture_output=True, text=True)
if result.returncode == 0:
    print(f"✅ Устройство найдено:")
    print(f"   {result.stdout.strip()}")
else:
    print(f"❌ Устройство НЕ найдено!")
