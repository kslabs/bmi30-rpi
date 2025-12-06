#!/usr/bin/env python3
"""
Быстрая проверка: работает ли устройство и передает ли данные
"""
import sys
import time
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream

def check_device_working(profile=1, timeout_sec=3):
    """Быстро проверить что устройство передает данные"""
    print(f"\n🔍 Проверка устройства (PROFILE={profile}, {timeout_sec}сек)...")
    
    try:
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        print(f"   ✓ USBStream создан")
        
        stream.send_cmd(0x20, b'')  # START_STREAM
        print(f"   ✓ START_STREAM отправлен")
        
        # Подождём чтобы устройство начало передавать
        time.sleep(1)
        print(f"   ⏳ Ждём 1сек после START_STREAM...")
        
        start_t = time.time()
        got_data = False
        
        while time.time() - start_t < timeout_sec:
            try:
                pair = stream.get_stereo(timeout=0.5)
                if pair and pair[0] is not None:
                    got_data = True
                    a, b = pair
                    print(f"   ✓ Получены данные: {len(a.payload)} + {len(b.payload)} байт")
                    break
            except Exception as e:
                pass
        
        try:
            stream.send_cmd(0x21, b'')  # STOP_STREAM
            stream.close()
        except:
            pass
        
        if got_data:
            print(f"   ✅ УСТРОЙСТВО РАБОТАЕТ")
            return True
        else:
            print(f"   ❌ УСТРОЙСТВО НЕ ПЕРЕДАЕТ ДАННЫЕ")
            return False
            
    except Exception as e:
        print(f"   ❌ ОШИБКА: {e}")
        return False

if __name__ == '__main__':
    result = check_device_working(profile=1, timeout_sec=3)
    sys.exit(0 if result else 1)
