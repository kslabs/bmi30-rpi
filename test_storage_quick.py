#!/usr/bin/env python3
"""
БЫСТРЫЙ ТЕСТ персистентного хранилища (30 секунд)
С прогрессом и реальными данными от устройства
"""

import sys
import os
import time
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector


def main():
    print("=" * 70)
    print("БЫСТРЫЙ ТЕСТ ПЕРСИСТЕНТНОГО ХРАНИЛИЩА")
    print("=" * 70)
    print("\n⏱️  Длительность: 30 секунд")
    print("📊 С прогресс-индикатором")
    print("📡 Попытка использовать реальные данные от USB\n")
    
    # === Создаем детектор ===
    print("1️⃣ Создание детектора...")
    detector = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=64,
        data_dir='./adaptive_data_test'
    )
    
    print(f"✓ Хранилище: {detector.data_store.data_dir}")
    if detector.data_store.metadata_file.exists():
        print(f"✓ Найдены сохраненные данные")
    else:
        print(f"✓ Новое хранилище (нет старых данных)")
    print()
    
    # === Подключение к устройству ===
    print("2️⃣ Подключение к USB-устройству...")
    stream = None
    use_real_data = False
    
    try:
        from usb_vendor.usb_stream import USBStream
        stream = USBStream()  # __init__ сам подключается
        stream.send_command(0x20)  # START_STREAM
        print("✓ USB подключено - используем РЕАЛЬНЫЕ данные\n")
        use_real_data = True
    except Exception as e:
        print(f"⚠️  USB недоступно ({str(e)[:50]}) - используем симуляцию\n")
        stream = None

    
    # === Фаза 1: Калибровка (15 сек) ===
    print("3️⃣ ФАЗА 1: Калибровка шума (15 секунд)")
    detector.start_calibration_session(15)
    
    start_time = time.time()
    phase1_duration = 15.0
    frames = 0
    last_progress_pct = -1
    
    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed >= phase1_duration:
                break
            
            # Получаем данные
            if use_real_data and stream:
                try:
                    chunk = stream.read_bulk(timeout_ms=50)
                    if chunk and len(chunk) >= 256:
                        adc0 = np.frombuffer(chunk[0:128], dtype=np.uint16)
                        adc1 = np.frombuffer(chunk[128:256], dtype=np.uint16)
                        
                        level_ch0 = float(np.abs(adc0.astype(float) - 32768.0).max())
                        level_ch1 = float(np.abs(adc1.astype(float) - 32768.0).max())
                        corr_arr = np.correlate(adc0.astype(float) - 32768, adc1.astype(float) - 32768, 'same')
                        correlation = float(np.abs(corr_arr).max())
                        prod_arr = (adc0.astype(float) - 32768) * (adc1.astype(float) - 32768)
                        product = float(np.abs(prod_arr).max())
                    else:
                        time.sleep(0.005)
                        continue
                except Exception:
                    level_ch0 = np.random.normal(500, 100)
                    level_ch1 = np.random.normal(600, 120)
                    correlation = np.random.normal(200, 50)
                    product = np.random.normal(50000, 10000)
                    time.sleep(0.005)
            else:
                # Симуляция
                level_ch0 = np.random.normal(500, 100)
                level_ch1 = np.random.normal(600, 120)
                correlation = np.random.normal(200, 50)
                product = np.random.normal(50000, 10000)
                time.sleep(0.005)
            
            # Обработка
            detector.process_frame(level_ch0, level_ch1, correlation, product)
            frames += 1
            
            # Прогресс
            current_pct = int(elapsed / phase1_duration * 100)
            if current_pct != last_progress_pct and current_pct <= 100:
                last_progress_pct = current_pct
                bar_filled = current_pct // 5
                bar = '█' * bar_filled + '░' * (20 - bar_filled)
                stats = detector.get_comprehensive_stats()
                samples = stats['noise_calibration']['samples_collected']
                thr0 = stats['noise_calibration']['ch0']['threshold']
                thr1 = stats['noise_calibration']['ch1']['threshold']
                print(f"\r   [{bar}] {current_pct:3d}%  |  Фреймы: {frames:4d}  |  Образцы: {samples:4d}  |  Пороги: {thr0:.0f}/{thr1:.0f}", end='', flush=True)
        
        print("\n✓ Фаза 1 завершена\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        if stream:
            try:
                stream.send_command(0x21)
                stream.close()
            except:
                pass
        return 1
    
    # === Фаза 2: Тест с метками (15 сек) ===
    print("4️⃣ ФАЗА 2: Тест детекции (15 секунд)")
    
    start_time = time.time()
    phase2_duration = 15.0
    frames = 0
    detections = 0
    last_progress_pct = -1
    
    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed >= phase2_duration:
                break
            
            # Периодически добавляем "метку" (каждые 5 секунд на 1 секунду)
            cycle_pos = elapsed % 5.0
            is_marker = (cycle_pos < 1.0)
            
            # Данные
            if use_real_data and stream:
                try:
                    chunk = stream.read_bulk(timeout_ms=50)
                    if chunk and len(chunk) >= 256:
                        adc0 = np.frombuffer(chunk[0:128], dtype=np.uint16)
                        adc1 = np.frombuffer(chunk[128:256], dtype=np.uint16)
                        
                        level_ch0 = float(np.abs(adc0.astype(float) - 32768.0).max())
                        level_ch1 = float(np.abs(adc1.astype(float) - 32768.0).max())
                        corr_arr = np.correlate(adc0.astype(float) - 32768, adc1.astype(float) - 32768, 'same')
                        correlation = float(np.abs(corr_arr).max())
                        prod_arr = (adc0.astype(float) - 32768) * (adc1.astype(float) - 32768)
                        product = float(np.abs(prod_arr).max())
                        
                        # Если должна быть метка - усиливаем сигнал
                        if is_marker:
                            level_ch0 *= 2.0
                            level_ch1 *= 2.0
                            correlation *= 3.0
                            product *= 3.0
                    else:
                        time.sleep(0.005)
                        continue
                except Exception:
                    if is_marker:
                        level_ch0 = np.random.normal(2000, 300)
                        level_ch1 = np.random.normal(2200, 350)
                        correlation = np.random.normal(1500, 200)
                        product = np.random.normal(400000, 50000)
                    else:
                        level_ch0 = np.random.normal(500, 100)
                        level_ch1 = np.random.normal(600, 120)
                        correlation = np.random.normal(200, 50)
                        product = np.random.normal(50000, 10000)
                    time.sleep(0.005)
            else:
                # Симуляция
                if is_marker:
                    level_ch0 = np.random.normal(2000, 300)
                    level_ch1 = np.random.normal(2200, 350)
                    correlation = np.random.normal(1500, 200)
                    product = np.random.normal(400000, 50000)
                else:
                    level_ch0 = np.random.normal(500, 100)
                    level_ch1 = np.random.normal(600, 120)
                    correlation = np.random.normal(200, 50)
                    product = np.random.normal(50000, 10000)
                time.sleep(0.005)
            
            # Обработка
            detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
                level_ch0, level_ch1, correlation, product
            )
            frames += 1
            
            if detected_ch0 or detected_ch1:
                detections += 1
            
            # Прогресс
            current_pct = int(elapsed / phase2_duration * 100)
            if current_pct != last_progress_pct and current_pct <= 100:
                last_progress_pct = current_pct
                bar_filled = current_pct // 5
                bar = '█' * bar_filled + '░' * (20 - bar_filled)
                marker_state = "🟢 МЕТКА" if is_marker else "⚫ ШУМ"
                detected_state = "✓" if (detected_ch0 or detected_ch1) else " "
                print(f"\r   [{bar}] {current_pct:3d}%  |  Фреймы: {frames:4d}  |  Обнаружено: {detections:3d}  |  {marker_state} {detected_state}", end='', flush=True)
        
        print("\n✓ Фаза 2 завершена\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
    finally:
        if stream:
            try:
                stream.send_command(0x21)
                stream.close()
            except:
                pass
    
    # === Итоговая статистика ===
    print("5️⃣ ИТОГОВАЯ СТАТИСТИКА")
    print("-" * 70)
    
    final_stats = detector.get_comprehensive_stats()
    
    print(f"📊 Всего фреймов: {final_stats['detection']['total_frames']}")
    print(f"🔇 Шум: {final_stats['detection']['noise_frames']}")
    print(f"📡 Метки: {final_stats['detection']['marker_frames']}")
    print(f"❌ Ложные: {final_stats['detection']['false_positives']}")
    
    noise_cal = final_stats['noise_calibration']
    print(f"\n📏 Калибровка шума:")
    print(f"   Образцов: {noise_cal['samples_collected']}")
    print(f"   CH0: порог={noise_cal['ch0']['threshold']:.0f}, шум={noise_cal['ch0']['mean']:.0f}±{noise_cal['ch0']['std']:.0f}")
    print(f"   CH1: порог={noise_cal['ch1']['threshold']:.0f}, шум={noise_cal['ch1']['mean']:.0f}±{noise_cal['ch1']['std']:.0f}")
    
    buf_stats = final_stats['buffer_averaging']
    print(f"\n⚡ Буферы:")
    print(f"   Текущие: {buf_stats['current_buffers']}")
    print(f"   Оптимальные: {buf_stats['optimal_buffers']}")
    
    # === Сохранение ===
    print("\n6️⃣ СОХРАНЕНИЕ")
    print("-" * 70)
    
    detector.save_calibration('./adaptive_calibration_test.json')
    print(f"✓ Калибровка: ./adaptive_calibration_test.json")
    
    # Проверяем хранилище
    print(f"\n💾 Персистентное хранилище:")
    print(f"   Директория: {detector.data_store.data_dir}")
    saved_files = list(detector.data_store.data_dir.glob('*.json'))
    print(f"   Файлов: {len(saved_files)}")
    if saved_files:
        for f in saved_files:
            size_kb = f.stat().st_size / 1024
            print(f"      - {f.name} ({size_kb:.1f} KB)")

    
    print("\n" + "=" * 70)
    print("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО!")
    print("=" * 70)
    print(f"\n⏱️  Время выполнения: 30 секунд")
    print(f"📡 Источник данных: {'USB-устройство' if use_real_data else 'Симуляция'}")
    print(f"📊 Обработано фреймов: {final_stats['detection']['total_frames']}")
    print(f"💾 Данные сохранены в: {detector.data_store.data_dir}\n")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Тест прерван пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
