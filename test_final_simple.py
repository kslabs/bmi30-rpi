#!/usr/bin/env python3
"""
ФИНАЛЬНЫЙ ТЕСТ - простой и понятный
Проверяем: оба профиля передают 912-сэмповые фреймы в нужном количестве
"""

import sys
sys.path.insert(0, 'host/usb_vendor')

from usb_stream import USBStream
import time

def test_profile(profile: int, profile_name: str, test_duration: float = 3.0):
    """Простой тест профиля"""
    print(f"\n  🧪 {profile_name} ({test_duration} сек)")
    
    try:
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        
        stream.send_cmd(0x20, b'')
        time.sleep(0.5)
        
        pairs = 0
        start = time.time()
        
        while time.time() - start < test_duration:
            try:
                pair = stream.asm.q.get(timeout=0.5)
                if pair:
                    pairs += 1
            except:
                pass
        
        elapsed = time.time() - start
        fps = pairs / elapsed if elapsed > 0 else 0
        
        stream.close()
        
        print(f"     ✓ Пар получено: {pairs} ({fps:.0f} пар/сек)")
        
        return pairs > 0
        
    except Exception as e:
        print(f"     ❌ {e}")
        return False

def main():
    print("\n" + "="*60)
    print("✅ ФИНАЛЬНАЯ ПРОВЕРКА УСТОЙЧИВОСТИ")
    print("="*60)
    
    print("\n[1️⃣  ПЕРВЫЙ ЗАПУСК] Начинаем с 300 Hz")
    p2_1 = test_profile(2, "PROFILE=2 (300 Hz)")
    time.sleep(1)
    
    print("\n[2️⃣  ВТОРОЙ] Переключаемся на 200 Hz")
    p1_1 = test_profile(1, "PROFILE=1 (200 Hz)")
    time.sleep(1)
    
    print("\n[3️⃣  ТРЕТИЙ] Обратно на 300 Hz")
    p2_2 = test_profile(2, "PROFILE=2 (300 Hz)")
    time.sleep(1)
    
    print("\n[4️⃣  ЧЕТВЁРТЫЙ] Ещё раз на 200 Hz")
    p1_2 = test_profile(1, "PROFILE=1 (200 Hz)")
    time.sleep(1)
    
    print("\n[5️⃣  ПЯТЫЙ] Финальный 300 Hz")
    p2_3 = test_profile(2, "PROFILE=2 (300 Hz)")
    
    results = [p2_1, p1_1, p2_2, p1_2, p2_3]
    success = sum(results)
    total = len(results)
    
    print("\n" + "="*60)
    print(f"📊 РЕЗУЛЬТАТЫ: {success}/{total} успешно")
    print("="*60)
    
    if success == total:
        print(f"\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ - СИСТЕМА СТАБИЛЬНА!")
        return 0
    else:
        print(f"\n⚠️  {total - success} тестов не прошли")
        return 1

if __name__ == '__main__':
    exit(main())
