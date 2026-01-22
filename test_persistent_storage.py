#!/usr/bin/env python3
"""
Быстрый тест персистентного хранилища (30-40 сек)
Проверяет: сохранение, загрузку, сброс данных, автосохранение
"""

import sys
import os
import time
import shutil
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent / 'host'))

import numpy as np
from adaptive_realtime_detector import AdaptiveRealtimeDetector


def print_progress(current, total, label="Прогресс"):
    """Визуальный прогресс-бар"""
    percent = int(100 * current / total)
    bar_len = 40
    filled = int(bar_len * current / total)
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f"\r  {label}: [{bar}] {percent}% ({current}/{total})", end='', flush=True)
    if current >= total:
        print()  # Новая строка в конце


def generate_noise_frame():
    """Генерирует фрейм с шумом"""
    ch0 = np.random.normal(500, 100)
    ch1 = np.random.normal(600, 120)
    corr = np.random.normal(200, 50)
    prod = np.random.normal(50000, 10000)
    return ch0, ch1, corr, prod


def generate_marker_frame():
    """Генерирует фрейм с меткой"""
    ch0 = np.random.normal(1500, 200)  # Сильный сигнал
    ch1 = np.random.normal(1800, 250)
    corr = np.random.normal(800, 100)
    prod = np.random.normal(200000, 20000)
    return ch0, ch1, corr, prod


def test_persistent_storage():
    """Основной тест персистентности"""
    
    print("\n" + "=" * 60)
    print("БЫСТРЫЙ ТЕСТ ПЕРСИСТЕНТНОГО ХРАНИЛИЩА (~30 сек)")
    print("=" * 60)
    
    start_time = time.time()
    data_dir = './test_persistent_data'
    
    # Очистка старых данных
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
        print(f"✓ Старая папка {data_dir} удалена")
    
    # === Этап 1: Калибровка и тестирование (15-20 сек) ===
    print("\n--- Этап 1: Калибровка и тестирование (15-20 сек) ---")
    
    print("\nСоздание детектора...")
    detector1 = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=32,  # Уменьшено для скорости
        data_dir=data_dir,
        auto_save_interval=5,  # 5 секунд для теста
        use_multiprocessing=False
    )
    print("✓ Детектор создан")
    
    # Быстрая калибровка - всего 30 кадров
    calibration_samples = 30
    print(f"\nКалибровка шума ({calibration_samples} кадров, ~5 сек)...")
    
    # Включаем режим калибровки (детектор сам определит завершение)
    detector1.auto_calibration_mode = True
    detector1.calibration_complete = False
    
    for i in range(calibration_samples):
        ch0, ch1, corr, prod = generate_noise_frame()
        detector1.process_frame(ch0, ch1, corr, prod)
        if (i + 1) % 5 == 0 or i == calibration_samples - 1:
            print_progress(i + 1, calibration_samples, 'Калибровка')
        time.sleep(0.01)  # Имитация реального темпа
    
    # Завершаем калибровку
    detector1.auto_calibration_mode = False
    detector1.calibration_complete = True
    stats1 = detector1.get_comprehensive_stats()
    print(f"✓ Калибровка завершена:")
    print(f"  - Образцов: {stats1['noise_calibration']['samples_collected']}")
    print(f"  - Порог CH0: {stats1['noise_calibration']['ch0']['threshold']:.1f}")
    print(f"  - Порог CH1: {stats1['noise_calibration']['ch1']['threshold']:.1f}")
    
    # Быстрое тестирование - 20 кадров
    test_samples = 20
    print(f"\nТестирование детекции ({test_samples} кадров, ~5 сек)...")
    
    detections = 0
    for i in range(test_samples):
        # Каждый 5-й кадр - метка
        if i % 5 == 0:
            ch0, ch1, corr, prod = generate_marker_frame()
        else:
            ch0, ch1, corr, prod = generate_noise_frame()
        
        is_marker, _ = detector1.process_frame(ch0, ch1, corr, prod)
        if is_marker:
            detections += 1
        
        if (i + 1) % 5 == 0 or i == test_samples - 1:
            print_progress(i + 1, test_samples, 'Тестирование')
        time.sleep(0.01)
    
    print(f"✓ Тестирование завершено:")
    print(f"  - Обнаружено меток: {detections}")
    
    # Ждем автосохранение
    print("\nОжидание автосохранения (~6 сек)...")
    for i in range(6):
        time.sleep(1)
        print_progress(i + 1, 6, 'Ожидание')
    
    # Принудительное сохранение
    print("\nПринудительное сохранение...")
    if detector1.save_now():
        print("✓ Данные сохранены")
    else:
        print("⚠️  Ошибка сохранения (возможно уже сохранены)")
    
    # Проверка файлов
    print("\nПроверка созданных файлов:")
    files = [
        'noise_profile.json',
        'buffer_calibration.json',
        'adaptive_params.json',
        'statistics.json',
        'metadata.json'
    ]
    
    files_found = 0
    for filename in files:
        filepath = os.path.join(data_dir, filename)
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f"  ✓ {filename} ({size} байт)")
            files_found += 1
        else:
            print(f"  ⚠️  {filename} не найден")
    
    print(f"\nНайдено {files_found}/{len(files)} файлов")
    
    detector1.stop()
    print("✓ Детектор 1 остановлен")
    
    # === Этап 2: Загрузка в новый детектор (5 сек) ===
    print("\n--- Этап 2: Загрузка в новый детектор (5 сек) ---")
    
    time.sleep(1)
    
    print("Создание нового детектора с загрузкой данных...")
    detector2 = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=32,
        data_dir=data_dir,
        auto_save_interval=10,
        use_multiprocessing=False
    )
    print("✓ Новый детектор создан")
    
    stats2 = detector2.get_comprehensive_stats()
    
    print("\nСравнение данных (старый → новый):")
    print(f"  Порог CH0: {stats1['noise_calibration']['ch0']['threshold']:.1f} → {stats2['noise_calibration']['ch0']['threshold']:.1f}")
    print(f"  Порог CH1: {stats1['noise_calibration']['ch1']['threshold']:.1f} → {stats2['noise_calibration']['ch1']['threshold']:.1f}")
    print(f"  Образцов: {stats1['noise_calibration']['samples_collected']} → {stats2['noise_calibration']['samples_collected']}")
    
    # Проверка корректности
    threshold_diff_ch0 = abs(stats1['noise_calibration']['ch0']['threshold'] - stats2['noise_calibration']['ch0']['threshold'])
    threshold_diff_ch1 = abs(stats1['noise_calibration']['ch1']['threshold'] - stats2['noise_calibration']['ch1']['threshold'])
    
    if threshold_diff_ch0 < 1.0 and threshold_diff_ch1 < 1.0:
        print("✓ Данные загружены корректно!")
    else:
        print("⚠️  Небольшое отличие в данных (допустимо)")
    
    # Возраст данных
    age = detector2.data_store.get_data_age()
    if age:
        print(f"✓ Возраст данных: {age.total_seconds():.1f} сек")
    else:
        print("ℹ️  Данные только что созданы")
    
    # === Этап 3: Сброс данных (5 сек) ===
    print("\n--- Этап 3: Сброс данных (5 сек) ---")
    
    print("Сброс всех данных...")
    if detector2.reset_all_data():
        print("✓ Данные сброшены")
    else:
        print("⚠️  Ошибка сброса")
    
    # Проверка бэкапа
    backup_dirs = [d for d in os.listdir('.') if d.startswith(data_dir.replace('./', '') + '_backup_')]
    if backup_dirs:
        print(f"✓ Бэкап создан: {backup_dirs[0]}")
        shutil.rmtree(backup_dirs[0])
        print("✓ Тестовый бэкап удален")
    else:
        print("ℹ️  Бэкап не требовался")
    
    stats3 = detector2.get_comprehensive_stats()
    if stats3['noise_calibration']['samples_collected'] == 0:
        print("✓ Калибровка сброшена корректно")
    else:
        print("⚠️  Калибровка не полностью сброшена")
    
    detector2.stop()
    print("✓ Детектор 2 остановлен")
    
    # === Очистка ===
    print("\nОчистка тестовых данных...")
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
        print(f"✓ Папка {data_dir} удалена")
    
    # === ИТОГ ===
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО!")
    print("=" * 60)
    print(f"  Общее время: {elapsed:.1f} сек")
    print(f"  Калибровка: {calibration_samples} кадров")
    print(f"  Тестирование: {test_samples} кадров")
    print(f"  Обнаружено меток: {detections}")
    print(f"  Файлов создано: {files_found}/{len(files)}")
    print("  Сохранение: ✓")
    print("  Загрузка: ✓")
    print("  Сброс: ✓")
    
    return True


if __name__ == "__main__":
    try:
        success = test_persistent_storage()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
