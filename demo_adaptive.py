#!/usr/bin/env python3
"""
Демо-тест адаптивного детектора в реальном времени
Симулирует работу системы с калибровкой и оптимизацией
"""

import sys
import os
import time
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector


def simulate_noise_frame():
    """Симулировать фрейм с шумом"""
    return {
        'level_ch0': np.random.normal(500, 100),
        'level_ch1': np.random.normal(600, 120),
        'correlation': np.random.normal(200, 50),
        'product': np.random.normal(50000, 10000)
    }


def simulate_marker_frame(strength=1.0):
    """Симулировать фрейм с меткой"""
    base_signal = 1500 * strength
    return {
        'level_ch0': np.random.normal(base_signal + 500, 200),
        'level_ch1': np.random.normal(base_signal + 600, 220),
        'correlation': np.random.normal(1000 * strength, 150),
        'product': np.random.normal(300000 * strength, 50000)
    }


def phase1_noise_calibration(detector, duration_frames=500):
    """Фаза 1: Калибровка шума"""
    print("\n" + "=" * 70)
    print("ФАЗА 1: КАЛИБРОВКА ШУМА (симуляция ночной работы)")
    print("=" * 70)
    print(f"Собираем {duration_frames} фреймов ТОЛЬКО шума...")
    print("(В реальности: оставьте систему на ночь БЕЗ меток)\n")
    
    for i in range(duration_frames):
        frame = simulate_noise_frame()
        
        detector.process_frame(
            frame['level_ch0'],
            frame['level_ch1'],
            frame['correlation'],
            frame['product']
        )
        
        if (i + 1) % 100 == 0:
            stats = detector.get_comprehensive_stats()
            noise_stats = stats['noise_calibration']
            
            print(f"[{i+1:4d}] Образцов: {noise_stats['samples_collected']:4d} | "
                  f"CH0 порог: {noise_stats['ch0']['threshold']:7.1f} | "
                  f"CH1 порог: {noise_stats['ch1']['threshold']:7.1f} | "
                  f"Готовность: {'✓' if noise_stats['ready'] else '...'}")
    
    stats = detector.get_comprehensive_stats()
    print(f"\n✓ Калибровка шума завершена!")
    print(f"  Собрано образцов: {stats['noise_calibration']['samples_collected']}")
    print(f"  Порог CH0: {stats['noise_calibration']['ch0']['threshold']:.1f}")
    print(f"  Порог CH1: {stats['noise_calibration']['ch1']['threshold']:.1f}")
    
    return stats


def phase2_buffer_optimization(detector, cycles=10):
    """Фаза 2: Оптимизация буферов"""
    print("\n" + "=" * 70)
    print("ФАЗА 2: ОПТИМИЗАЦИЯ БУФЕРОВ")
    print("=" * 70)
    print(f"Тестируем разные количества буферов с периодическими метками...")
    print("(В реальности: подносите и убирайте метку ~30 раз)\n")
    
    buffer_counts = [8, 16, 24, 32, 48, 64]
    
    for cycle in range(cycles):
        # Каждый цикл: шум -> метка -> шум
        
        # 1. Шум (5 фреймов)
        for _ in range(5):
            frame = simulate_noise_frame()
            detector.process_frame(
                frame['level_ch0'], frame['level_ch1'],
                frame['correlation'], frame['product']
            )
        
        # 2. Метка (3 фрейма)
        marker_present = True
        for _ in range(3):
            frame = simulate_marker_frame(strength=np.random.uniform(0.8, 1.2))
            
            detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
                frame['level_ch0'], frame['level_ch1'],
                frame['correlation'], frame['product'],
                user_feedback='marker' if marker_present else None
            )
            
            if detected_ch0 or detected_ch1:
                # Тестируем текущее количество буферов
                current_buffers = detector.buffer_averager.get_current_buffers()
                
                # Симуляция SNR и времени
                snr = np.random.normal(5 + current_buffers / 10, 1.0)
                detection_time_ms = current_buffers * 5  # ~5 мс на буфер
                
                detector.buffer_averager.test_buffer_count(
                    current_buffers, snr, detection_time_ms
                )
        
        # 3. Переключаем на следующее количество буферов
        next_buffers = buffer_counts[cycle % len(buffer_counts)]
        detector.buffer_averager.current_buffers = next_buffers
        
        if (cycle + 1) % 2 == 0:
            stats = detector.buffer_averager.get_stats()
            print(f"[Цикл {cycle+1:2d}] Текущие буферы: {stats['current_buffers']:2d} | "
                  f"Оптимальные: {stats['optimal_buffers']:2d} | "
                  f"Образцов собрано: {sum(stats['calibration_samples'].values())}")
    
    # Финализация оптимизации
    optimal_buffers = detector.buffer_averager.find_optimal_buffers()
    detector.buffer_averager.current_buffers = optimal_buffers
    
    print(f"\n✓ Оптимизация завершена!")
    print(f"  Оптимальное количество буферов: {optimal_buffers}")
    print(f"  Ожидаемое время детекции: {optimal_buffers * 5:.0f} мс")
    
    return optimal_buffers


def phase3_realtime_operation(detector, duration_frames=200):
    """Фаза 3: Реальная работа с адаптацией"""
    print("\n" + "=" * 70)
    print("ФАЗА 3: РАБОТА В РЕАЛЬНОМ ВРЕМЕНИ")
    print("=" * 70)
    print(f"Симуляция реальной работы с периодическими метками и обратной связью...\n")
    
    detections = {'correct': 0, 'false_positive': 0, 'missed': 0}
    
    for i in range(duration_frames):
        # Генерируем фрейм: 20% вероятность метки
        has_marker = np.random.random() < 0.2
        
        if has_marker:
            frame = simulate_marker_frame(strength=np.random.uniform(0.7, 1.3))
        else:
            frame = simulate_noise_frame()
        
        # Обработка
        detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
            frame['level_ch0'], frame['level_ch1'],
            frame['correlation'], frame['product']
        )
        
        detected = detected_ch0 or detected_ch1
        
        # Симуляция обратной связи (90% правильная)
        feedback = None
        if detected and has_marker and np.random.random() < 0.9:
            # Правильное обнаружение
            feedback = 'marker'
            detections['correct'] += 1
        elif detected and not has_marker:
            # Ложное срабатывание
            feedback = 'false_positive'
            detections['false_positive'] += 1
        elif not detected and has_marker:
            # Пропущена метка
            detections['missed'] += 1
        
        # Отправляем обратную связь
        if feedback and np.random.random() < 0.1:  # 10% вероятность дать обратную связь
            detector.process_frame(
                frame['level_ch0'], frame['level_ch1'],
                frame['correlation'], frame['product'],
                user_feedback=feedback
            )
        
        # Периодический вывод
        if (i + 1) % 50 == 0:
            stats = detector.get_comprehensive_stats()
            adaptive = stats['adaptive_params']
            
            print(f"[{i+1:3d}] σ={adaptive['threshold_sigma']:.1f} | "
                  f"FP_rate={adaptive['false_positive_rate']:.1f}% | "
                  f"Правильно: {detections['correct']:2d} | "
                  f"Ложные: {detections['false_positive']:2d} | "
                  f"Пропущено: {detections['missed']:2d}")
    
    print(f"\n✓ Тестирование завершено!")
    print(f"  Правильных обнаружений: {detections['correct']}")
    print(f"  Ложных срабатываний: {detections['false_positive']}")
    print(f"  Пропущено меток: {detections['missed']}")
    
    if detections['correct'] + detections['false_positive'] > 0:
        accuracy = detections['correct'] / (detections['correct'] + detections['false_positive']) * 100
        print(f"  Точность: {accuracy:.1f}%")
    
    return detections


def main():
    print("\n" + "=" * 70)
    print("ДЕМО: АДАПТИВНЫЙ ДЕТЕКТОР В РЕАЛЬНОМ ВРЕМЕНИ")
    print("=" * 70)
    print("\nЭта демонстрация симулирует 3 фазы работы системы:")
    print("1. Калибровка шума (на ночь)")
    print("2. Оптимизация буферов (интерактивно)")
    print("3. Реальная работа с адаптацией")
    print("\nВ реальной системе фазы 1 и 2 выполняются один раз,")
    print("а фаза 3 работает постоянно с онлайн-обучением.\n")
    
    input("Нажмите Enter для начала...")
    
    # Создаем детектор
    detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64)
    
    # Фаза 1: Калибровка
    phase1_noise_calibration(detector, duration_frames=500)
    time.sleep(1)
    
    # Фаза 2: Оптимизация
    optimal_buffers = phase2_buffer_optimization(detector, cycles=10)
    time.sleep(1)
    
    # Фаза 3: Работа
    detections = phase3_realtime_operation(detector, duration_frames=200)
    time.sleep(1)
    
    # Итоговая статистика
    print("\n" + "=" * 70)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 70)
    
    final_stats = detector.get_comprehensive_stats()
    
    print("\n📊 Общая статистика:")
    print(f"  Всего фреймов обработано: {final_stats['detection']['total_frames']}")
    print(f"  Фреймов с шумом: {final_stats['detection']['noise_frames']}")
    print(f"  Фреймов с метками: {final_stats['detection']['marker_frames']}")
    
    print("\n🎯 Калибровка шума:")
    noise_stats = final_stats['noise_calibration']
    print(f"  Образцов собрано: {noise_stats['samples_collected']}")
    print(f"  Порог CH0: {noise_stats['ch0']['threshold']:.1f} "
          f"(шум: {noise_stats['ch0']['mean']:.1f} ± {noise_stats['ch0']['std']:.1f})")
    print(f"  Порог CH1: {noise_stats['ch1']['threshold']:.1f} "
          f"(шум: {noise_stats['ch1']['mean']:.1f} ± {noise_stats['ch1']['std']:.1f})")
    
    print("\n⚡ Оптимизация буферов:")
    buf_stats = final_stats['buffer_averaging']
    print(f"  Оптимальное количество: {buf_stats['optimal_buffers']} буферов")
    print(f"  Ожидаемая скорость: {buf_stats['optimal_buffers'] * 5:.0f} мс")
    
    print("\n🔧 Адаптивные параметры:")
    adaptive = final_stats['adaptive_params']
    print(f"  σ-множитель: {adaptive['threshold_sigma']:.2f}")
    print(f"  Частота ложных срабатываний: {adaptive['false_positive_rate']:.1f}%")
    print(f"  Калибровка: {'✓ завершена' if adaptive['calibration_complete'] else '⏳ в процессе'}")
    
    # Сохранение
    print("\n💾 Сохранение калибровки...")
    detector.save_calibration('./adaptive_calibration_demo.json')
    print("  ✓ Сохранено: ./adaptive_calibration_demo.json")
    
    print("\n" + "=" * 70)
    print("✅ ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 70)
    print("\nДля реальной интеграции:")
    print("1. Запустите калибровку на ночь (4-8 часов)")
    print("2. Оптимизируйте буферы (5-10 минут с метками)")
    print("3. Используйте систему с онлайн-обучением")
    print("\nПодробности в ADAPTIVE_README.md\n")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
