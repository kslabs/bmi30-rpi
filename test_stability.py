#!/usr/bin/env python3
"""
Тест стабильности запуска - без GUI, только данные
"""
import sys
import time
import os
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream

def test_profile(profile, duration_sec=5, test_params=None):
    """Тестировать профиль с параметрами"""
    
    params = {
        'profile': profile,
        'full': True,
        'fast_mode': True,
        'test_as_data': False,
        'frame_samples': 912
    }
    if test_params:
        params.update(test_params)
    
    name = f"PROFILE={profile} ({'200Hz' if profile == 1 else '300Hz'})"
    print(f"\n{'='*70}")
    print(f"Тест: {name}")
    print(f"Параметры: {params}")
    print(f"{'='*70}")
    
    try:
        stream = USBStream(**params)
        print(f"✓ USBStream создан")
        
        # START_STREAM
        stream.send_cmd(0x20, b'')
        print(f"✓ START_STREAM отправлен")
        
        frames_received = 0
        errors = 0
        start_t = time.time()
        
        while time.time() - start_t < duration_sec:
            try:
                got = stream.get_stereo(timeout=1.0)
                if got and got[0] is not None:
                    frames_received += 1
                    a, b, ch0, ch1 = got
                    if frames_received == 1:
                        print(f"✓ Первый кадр получен: {len(ch0)} семплов")
                    if frames_received % 50 == 0:
                        print(f"  → кадр #{frames_received}")
            except Exception as e:
                errors += 1
                print(f"✗ Ошибка получения данных: {e}")
                if errors > 3:
                    print(f"  Слишком много ошибок, прерываем")
                    break
        
        elapsed = time.time() - start_t
        print(f"\n✓ Получено {frames_received} кадров за {elapsed:.1f}сек")
        
        if frames_received > 0:
            print(f"✓ Частота: {frames_received/elapsed:.1f} кадров/сек")
            print(f"✓ СТАБИЛЬНОСТЬ: {'✅ ХОРОША' if errors == 0 else f'⚠️ {errors} ошибок'}")
            return True
        else:
            print(f"✗ Не получено ни одного кадра")
            return False
            
    except Exception as e:
        print(f"✗ Ошибка инициализации: {e}")
        return False
    finally:
        try:
            stream.send_cmd(0x21, b'')  # STOP_STREAM
            stream.close()
        except:
            pass

if __name__ == '__main__':
    print("\n🧪 ТЕСТ СТАБИЛЬНОСТИ ЗАПУСКА\n")
    
    # Тест 1: Profile 1, стандартные параметры
    test_profile(1, duration_sec=3)
    
    # Пауза между тестами
    time.sleep(1)
    
    # Тест 2: Profile 2, стандартные параметры
    test_profile(2, duration_sec=3)
    
    print("\n" + "="*70)
    print("✓ Все тесты завершены")
