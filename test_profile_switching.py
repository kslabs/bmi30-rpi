#!/usr/bin/env python3
"""
Тест получения данных при переключении между профилями 200/300 Hz
"""
import sys
import time
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream

def test_profile(profile, duration_sec=3, description=""):
    """Тестировать один профиль"""
    freq = "200 Hz (PROFILE=1)" if profile == 1 else "300 Hz (PROFILE=2)"
    print(f"\n{'='*70}")
    print(f"🧪 Тест: {freq} {description}")
    print(f"{'='*70}")
    
    try:
        print(f"[1] Создаем USBStream(profile={profile})...")
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        print(f"    ✓ Создан\n")
        
        print(f"[2] Отправляем START_STREAM...")
        stream.send_cmd(0x20, b'')
        print(f"    ✓ Отправлено\n")
        
        print(f"[3] Получаем данные {duration_sec} сек...")
        start_t = time.time()
        frames = 0
        errors = 0
        
        while time.time() - start_t < duration_sec:
            try:
                pair = stream.get_stereo(timeout=0.5)
                if pair and pair[0] is not None:
                    frames += 1
                    a, b = pair
                    if frames <= 3:
                        print(f"    Кадр {frames}: A={len(a.payload)} B={len(b.payload)} байт")
                    elif frames % 20 == 0:
                        print(f"    ... Кадр {frames}")
            except Exception as e:
                errors += 1
        
        elapsed = time.time() - start_t
        print(f"\n[РЕЗУЛЬТАТ]")
        print(f"    Время: {elapsed:.1f}сек")
        print(f"    Кадров получено: {frames}")
        print(f"    Ошибок: {errors}")
        
        if frames > 0:
            fps = frames / elapsed
            print(f"    FPS: {fps:.1f}")
            print(f"    ✅ ПРОФИЛЬ РАБОТАЕТ")
            return True
        else:
            print(f"    ❌ ДАННЫЕ НЕ ПОЛУЧЕНЫ")
            return False
            
    except Exception as e:
        print(f"    ❌ ОШИБКА: {e}")
        return False
    finally:
        try:
            stream.send_cmd(0x21, b'')  # STOP_STREAM
            stream.close()
        except:
            pass

if __name__ == '__main__':
    print("\n" + "="*70)
    print("📊 ТЕСТ ПОЛУЧЕНИЯ ДАННЫХ ПРИ ПЕРЕКЛЮЧЕНИИ 200/300 Hz")
    print("="*70)
    
    results = {}
    
    # Тест 1: 200 Hz
    results['200'] = test_profile(1, duration_sec=3, description="(первый запуск)")
    time.sleep(1)
    
    # Тест 2: 300 Hz
    results['300'] = test_profile(2, duration_sec=3, description="(переключение)")
    time.sleep(1)
    
    # Тест 3: 200 Hz снова
    results['200_2'] = test_profile(1, duration_sec=3, description="(переключение обратно)")
    time.sleep(1)
    
    # Тест 4: 300 Hz снова
    results['300_2'] = test_profile(2, duration_sec=3, description="(переключение опять)")
    
    # Итоги
    print(f"\n{'='*70}")
    print("📈 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*70}")
    print(f"200 Hz (попытка 1): {'✅ OK' if results['200'] else '❌ FAIL'}")
    print(f"300 Hz (попытка 1): {'✅ OK' if results['300'] else '❌ FAIL'}")
    print(f"200 Hz (попытка 2): {'✅ OK' if results['200_2'] else '❌ FAIL'}")
    print(f"300 Hz (попытка 2): {'✅ OK' if results['300_2'] else '❌ FAIL'}")
    
    success_count = sum(1 for v in results.values() if v)
    print(f"\n✅ Успешно: {success_count}/4")
    print(f"❌ Ошибок: {4-success_count}/4")
    
    if success_count == 4:
        print(f"\n🎉 ОБОРУДОВАНИЕ РАБОТАЕТ НОРМАЛЬНО!")
    elif success_count >= 2:
        print(f"\n⚠️  ЧАСТИЧНАЯ РАБОТА - нестабильность")
    else:
        print(f"\n❌ ОБОРУДОВАНИЕ НЕ РАБОТАЕТ")
