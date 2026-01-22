#!/usr/bin/env python3
"""Тест отправки команды частоты на устройство"""

import sys
import os
import time

# Проверим что можем подключиться к устройству и отправить команду частоты
try:
    sys.path.insert(0, 'host')
    from usb_vendor.usb_stream import USBStream
    
    print("="*60)
    print("ТЕСТ: Отправка команды частоты на устройство")
    print("="*60)
    
    # Список частот для теста
    test_freqs = [200, 210, 220, 250]
    
    print("\n📡 Подключаемся к устройству...")
    stream = USBStream(profile=1, full=True, fast_mode=True)
    print("✅ Устройство подключено\n")
    
    for freq in test_freqs:
        print(f"⚡ Устанавливаем частоту {freq} Hz...")
        try:
            if hasattr(stream, 'set_block_rate'):
                stream.set_block_rate(freq)
                print(f"   ✅ Команда отправлена через set_block_rate()")
            else:
                import struct
                stream.send_cmd(0x11, struct.pack('<H', freq))
                print(f"   ✅ Команда отправлена через send_cmd(0x11)")
            time.sleep(0.5)
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
    
    print("\n✅ Тест завершен!")
    print("="*60)
    
    # Закрываем соединение
    try:
        stream.close()
    except:
        pass
    
except ImportError as e:
    print(f"❌ Не удалось импортировать USBStream: {e}")
    print("Убедитесь что модуль usb_vendor установлен")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
