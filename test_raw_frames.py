#!/usr/bin/env python3
"""
Тест СЫРЫХ фреймов без стерео-сборки
Смотрим, что реально приходит по USB, не через StereoAssembler
"""

import sys
sys.path.insert(0, 'host/usb_vendor')

from usb_stream import USBStream, Frame, MAGIC
import time

def test_profile_raw(profile: int, expected_fps: int, test_duration: float = 3.0):
    """Тест профиля - смотрим СЫРЫЕ фреймы"""
    print(f"\n{'='*70}")
    print(f"🧪 Профиль {profile} ({expected_fps} Hz) - СЫРЫЕ ФРЕЙМЫ")
    print(f"{'='*70}")
    
    try:
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        print(f"  ✓ Stream создан")
        
        stream.send_cmd(0x20, b'')
        print(f"  ✓ START_STREAM отправлен")
        
        time.sleep(0.5)
        
        raw_frames = 0
        adc0_frames = 0
        adc1_frames = 0
        start_time = time.time()
        frame_samples_list = []
        
        print(f"\n  Получаем фреймы по мере прихода...")
        
        # Будем читать напрямую из очереди Assembler (после парсинга, но ДО стерео-сборки)
        # Нам нужно подсмотреть в _rx_loop где создаются Frame объекты
        
        # Так как сборка происходит в asm.push(frame), давайте просто подсчитаем 
        # что попадает в bufA и bufB
        while time.time() - start_time < test_duration:
            try:
                # Просто смотрим на статистику приема
                pair = stream.asm.q.get(timeout=0.5)
                if pair:
                    frameA, frameB = pair
                    raw_frames += 2
                    
                    print(f"    Пара {raw_frames//2}:")
                    print(f"      A: seq={frameA.seq}, samples={frameA.samples}, adc_id={frameA.adc_id}, flags=0x{frameA.flags:02x}")
                    print(f"      B: seq={frameB.seq}, samples={frameB.samples}, adc_id={frameB.adc_id}, flags=0x{frameB.flags:02x}")
                    
                    if frameA.adc_id == 0:
                        adc0_frames += 1
                    else:
                        adc1_frames += 1
                    
                    if frameB.adc_id == 0:
                        adc0_frames += 1
                    else:
                        adc1_frames += 1
                    
                    frame_samples_list.append(frameA.samples)
                    frame_samples_list.append(frameB.samples)
            except:
                pass
        
        elapsed = time.time() - start_time
        fps = raw_frames / elapsed if elapsed > 0 else 0
        
        print(f"\n  📊 СТАТИСТИКА:")
        print(f"     Время: {elapsed:.2f} сек")
        print(f"     Фреймов получено: {raw_frames}")
        print(f"     ADC0 фреймов: {adc0_frames}")
        print(f"     ADC1 фреймов: {adc1_frames}")
        print(f"     FPS (фреймов в сек): {fps:.1f} (ожидалось ~{expected_fps*2})")
        
        if frame_samples_list:
            print(f"     Размеры фреймов (уникальные): {set(frame_samples_list)}")
            if all(s == 912 for s in frame_samples_list):
                print(f"  ✅ ВСЕ ФРЕЙМЫ ПО 912 СЭМПЛОВ")
            else:
                print(f"  ❌ НЕОДНОРОДНЫЕ РАЗМЕРЫ")
        
        if raw_frames > 0:
            print(f"  ✅ ДАННЫЕ ПОЛУЧЕНЫ")
            success = True
        else:
            print(f"  ❌ НЕ ПОЛУЧЕНЫ ДАННЫЕ")
            success = False
        
        stream.close()
        return success
        
    except Exception as e:
        print(f"  ❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "="*70)
    print("🔬 АНАЛИЗ СЫРЫХ ФРЕЙМОВ")
    print("="*70)
    
    # НАЧИНАЕМ С 300 Hz!
    print(f"\n[ТЕСТ 1] Начинаем с PROFILE=2 (300 Hz)")
    p2_ok = test_profile_raw(profile=2, expected_fps=280, test_duration=3.0)
    
    time.sleep(2)
    
    print(f"\n[ТЕСТ 2] Переключаемся на PROFILE=1 (200 Hz)")
    p1_ok = test_profile_raw(profile=1, expected_fps=176, test_duration=3.0)
    
    time.sleep(2)
    
    print(f"\n[ТЕСТ 3] Обратно на PROFILE=2 (300 Hz)")
    p2_ok_2 = test_profile_raw(profile=2, expected_fps=280, test_duration=3.0)
    
    print(f"\n" + "="*70)
    print(f"📈 ИТОГИ")
    print(f"="*70)
    print(f"P2 (первый): {'✅ OK' if p2_ok else '❌ FAIL'}")
    print(f"P1 (второй): {'✅ OK' if p1_ok else '❌ FAIL'}")
    print(f"P2 (третий): {'✅ OK' if p2_ok_2 else '❌ FAIL'}")
    
    return 0 if (p2_ok and p1_ok and p2_ok_2) else 1

if __name__ == '__main__':
    exit(main())
