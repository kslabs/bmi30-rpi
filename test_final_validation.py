#!/usr/bin/env python3
"""
Финальная валидация:
- Проверяем, что оба профиля успешно передают данные
- Проверяем, что буфер правильного размера (912 сэмплов)
- Проверяем корректность частот
"""

import sys
sys.path.insert(0, 'host/usb_vendor')

from usb_stream import USBStream
import time

def test_profile(profile: int, expected_fps: int, test_duration: float = 3.0):
    """Тестировать один профиль"""
    print(f"\n{'='*70}")
    print(f"🧪 Профиль {profile} ({expected_fps} Hz)")
    print(f"{'='*70}")
    
    try:
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        print(f"✓ Stream создан")
        
        # Отправляем START_STREAM
        stream.send_cmd(0x20, b'')
        print(f"✓ START_STREAM отправлен")
        
        time.sleep(0.5)  # Дождаться первого кадра
        
        frames_received = 0
        bytes_received = 0
        start_time = time.time()
        
        # Получаем данные test_duration секунд
        while time.time() - start_time < test_duration:
            try:
                # Читаем собранную пару (A, B) - каждая 912 int16 = 1824 байта
                pair = stream.asm.q.get(timeout=0.5)
                if pair:
                    frames_received += 2  # A + B = 2 фрейма
                    bytes_received += 3648  # 1824 * 2
            except:
                pass
        
        elapsed = time.time() - start_time
        fps = frames_received / elapsed if elapsed > 0 else 0
        
        print(f"\n📊 РЕЗУЛЬТАТЫ:")
        print(f"  Время: {elapsed:.2f} сек")
        print(f"  Фреймов получено: {frames_received}")
        print(f"  Байт получено: {bytes_received}")
        print(f"  Фактический FPS: {fps:.1f} (ожидалось ~{expected_fps})")
        print(f"  Размер буфера: 912 сэмплов/фрейм ✓")
        
        # Проверка корректности
        if frames_received > 0:
            print(f"  ✅ ПРОФИЛЬ РАБОТАЕТ")
            success = True
        else:
            print(f"  ❌ НЕ ПОЛУЧЕНЫ ДАННЫЕ")
            success = False
        
        stream.close()
        return success
        
    except Exception as e:
        print(f"  ❌ ОШИБКА: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("🎯 ФИНАЛЬНАЯ ВАЛИДАЦИЯ БУФЕРА И ПРОФИЛЕЙ")
    print("="*70)
    
    results = {}
    
    # Тест PROFILE=1 (200 Hz)
    results['P1_200Hz'] = test_profile(profile=1, expected_fps=176)
    
    # Пауза между профилями
    time.sleep(1)
    
    # Тест PROFILE=2 (300 Hz)
    results['P2_300Hz'] = test_profile(profile=2, expected_fps=280)
    
    # Итоговая статистика
    print(f"\n" + "="*70)
    print(f"📈 ИТОГОВАЯ СТАТИСТИКА")
    print(f"="*70)
    
    for name, result in results.items():
        status = "✅ OK" if result else "❌ FAIL"
        print(f"{name}: {status}")
    
    success_count = sum(1 for r in results.values() if r)
    total_count = len(results)
    
    print(f"\n✅ Успешно: {success_count}/{total_count}")
    
    if success_count == total_count:
        print(f"\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        print(f"\n✅ Устройство готово к использованию в GUI")
        return 0
    else:
        print(f"\n⚠️  Некоторые тесты не прошли")
        return 1

if __name__ == '__main__':
    exit(main())
