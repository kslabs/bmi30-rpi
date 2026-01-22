#!/usr/bin/env python3
"""
ДЛИТЕЛЬНОЕ ОБУЧЕНИЕ АДАПТИВНОГО ДЕТЕКТОРА
Работает несколько суток, накапливает статистику шума
Автосохранение каждый час
"""

import sys
import os
import time
import signal
import subprocess
from datetime import datetime, timedelta
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector

# Глобальные переменные для корректной остановки
running = True
detector = None
stream = None

def signal_handler(sig, frame):
    """Обработка Ctrl+C - корректное завершение"""
    global running
    print("\n\n⚠️  Получен сигнал остановки...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def log_message(msg, logfile='adaptive_learning.log'):
    """Логирование в файл и на экран"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(logfile, 'a') as f:
            f.write(line + '\n')
    except:
        pass


def hardware_reset_usb():
    """Аппаратный сброс USB устройства"""
    try:
        result = subprocess.run(
            ['sudo', 'usbreset', 'cafe:4001'], 
            timeout=5, 
            check=False, 
            capture_output=True
        )
        if result.returncode == 0:
            log_message("✓ USB сброшен")
            time.sleep(2)
            return True
    except:
        pass
    
    log_message("⚠️  Сброс USB не выполнен")
    return False


def print_statistics(detector, duration_hours, frames_total, detections_total):
    """Вывод статистики обучения"""
    stats = detector.get_comprehensive_stats()
    
    print("\n" + "=" * 70)
    print("📊 СТАТИСТИКА ОБУЧЕНИЯ")
    print("=" * 70)
    
    print(f"\n⏱️  Время работы: {duration_hours:.1f} часов")
    print(f"📊 Всего фреймов: {frames_total}")
    print(f"📡 Обнаружено меток: {detections_total}")
    print(f"⚡ Скорость: {frames_total / (duration_hours * 3600):.1f} кадр/сек")
    
    nc = stats['noise_calibration']
    print(f"\n📏 Калибровка шума:")
    print(f"   Образцов: {nc['samples_collected']}")
    print(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}, макс={nc['ch0']['max']:.0f}")
    print(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}, макс={nc['ch1']['max']:.0f}")
    
    det = stats['detection']
    print(f"\n🔍 Детекция:")
    print(f"   Шум: {det['noise_frames']}")
    print(f"   Метки: {det['marker_frames']}")
    print(f"   Ложные: {det['false_positives']}")
    
    buf = stats['buffer_averaging']
    print(f"\n⚡ Буферы:")
    print(f"   Текущие: {buf['current_buffers']}")
    print(f"   Оптимальные: {buf['optimal_buffers']}")
    
    ap = stats['adaptive_params']
    print(f"\n🎯 Адаптивные параметры:")
    print(f"   Sigma CH0: {ap['sigma_ch0']:.2f}")
    print(f"   Sigma CH1: {ap['sigma_ch1']:.2f}")
    print(f"   Калибровка завершена: {ap['calibration_complete']}")
    
    print("=" * 70 + "\n")


def main():
    global running, detector, stream
    
    print("=" * 70)
    print("ДЛИТЕЛЬНОЕ ОБУЧЕНИЕ АДАПТИВНОГО ДЕТЕКТОРА")
    print("=" * 70)
    print("🎯 Цель: Максимально быстрая детекция с минимумом ложных срабатываний")
    print("⏱️  Длительность: Несколько суток (Ctrl+C для остановки)")
    print("💾 Автосохранение: Каждый час")
    print("📊 Статистика: Каждые 15 минут")
    print("\nℹ️  Система будет:")
    print("   1. Калиброваться по шуму (без меток)")
    print("   2. Автоматически оптимизировать буферы")
    print("   3. Адаптироваться к изменениям среды")
    print("   4. Сохранять данные каждый час\n")
    
    log_message("=" * 70)
    log_message("ЗАПУСК ДЛИТЕЛЬНОГО ОБУЧЕНИЯ")
    log_message("=" * 70)
    
    # === Сброс USB ===
    log_message("🔌 Аппаратный сброс USB...")
    hardware_reset_usb()
    
    # === Создание детектора ===
    log_message("📊 Создание адаптивного детектора...")
    detector = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=64,
        data_dir='./adaptive_data_continuous'
    )
    log_message("✓ Детектор создан")
    
    # Проверяем есть ли сохраненные данные
    if detector.data_store.metadata_file.exists():
        log_message("📂 Найдены сохраненные данные - продолжаем обучение")
    else:
        log_message("📂 Новое обучение - нет старых данных")
    
    # === Подключение USB ===
    log_message("📡 Подключение к USB устройству...")
    try:
        from usb_vendor.usb_stream import USBStream
        stream = USBStream(profile=1, full=True)
        log_message(f"✓ USB подключен: {stream.dev.idVendor:04x}:{stream.dev.idProduct:04x}")
    except Exception as e:
        log_message(f"❌ Ошибка подключения USB: {e}")
        return 1
    
    # === Начальная калибровка (5 минут) ===
    log_message("🔧 Начальная калибровка шума (5 минут)...")
    log_message("⚠️  ВАЖНО: Уберите все метки из зоны детекции!")
    
    calibration_duration = 300  # 5 минут
    detector.start_calibration_session(calibration_duration)
    
    start_time = time.time()
    frames = 0
    
    try:
        while (time.time() - start_time < calibration_duration) and running:
            try:
                frame0 = stream.get_frame(0, timeout=0.2)
                frame1 = stream.get_frame(1, timeout=0.2)
                
                if frame0 is not None and frame1 is not None:
                    # Извлекаем данные из фреймов
                    data0 = np.frombuffer(frame0.data, dtype=np.uint16) if hasattr(frame0, 'data') else np.zeros(64, dtype=np.uint16)
                    data1 = np.frombuffer(frame1.data, dtype=np.uint16) if hasattr(frame1, 'data') else np.zeros(64, dtype=np.uint16)
                    
                    level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
                    level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(data0 - 32768, data1 - 32768, 'same')).max())
                    prod = float(np.abs((data0 - 32768) * (data1 - 32768)).max())
                    
                    detector.process_frame(level_ch0, level_ch1, corr, prod)
                    frames += 1
                    
                    # Прогресс каждые 30 секунд
                    elapsed = time.time() - start_time
                    if frames % 5000 == 0:
                        progress = elapsed / calibration_duration * 100
                        log_message(f"   Калибровка: {progress:.0f}% | Фреймов: {frames}")
            except Exception as e:
                time.sleep(0.01)
                continue
    except KeyboardInterrupt:
        log_message("⚠️  Калибровка прервана пользователем")
        running = False
    
    if not running:
        log_message("❌ Обучение остановлено")
        return 0
    
    log_message(f"✓ Начальная калибровка завершена: {frames} фреймов")
    
    # === Основной цикл обучения ===
    log_message("\n🎓 НАЧАЛО ОСНОВНОГО ОБУЧЕНИЯ")
    log_message("   Система адаптируется к реальным условиям")
    log_message("   Статистика каждые 15 минут\n")
    
    start_time = time.time()
    last_stats_time = start_time
    last_save_time = start_time
    stats_interval = 900  # 15 минут
    save_interval = 3600  # 1 час
    
    frames_total = 0
    detections_total = 0
    
    try:
        while running:
            try:
                frame0 = stream.get_frame(0, timeout=0.2)
                frame1 = stream.get_frame(1, timeout=0.2)
                
                if frame0 is not None and frame1 is not None:
                    # Извлекаем данные
                    data0 = np.frombuffer(frame0.data, dtype=np.uint16) if hasattr(frame0, 'data') else np.zeros(64, dtype=np.uint16)
                    data1 = np.frombuffer(frame1.data, dtype=np.uint16) if hasattr(frame1, 'data') else np.zeros(64, dtype=np.uint16)
                    
                    level_ch0 = float(np.abs(data0.astype(float) - 32768).max())
                    level_ch1 = float(np.abs(data1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(data0 - 32768, data1 - 32768, 'same')).max())
                    prod = float(np.abs((data0 - 32768) * (data1 - 32768)).max())
                    
                    # Обработка
                    det0, det1, conf0, conf1 = detector.process_frame(level_ch0, level_ch1, corr, prod)
                    frames_total += 1
                    
                    if det0 or det1:
                        detections_total += 1
                    
                    # Статистика каждые 15 минут
                    current_time = time.time()
                    if current_time - last_stats_time >= stats_interval:
                        duration_hours = (current_time - start_time) / 3600
                        print_statistics(detector, duration_hours, frames_total, detections_total)
                        
                        # Сохраняем калибровку
                        detector.save_calibration('./adaptive_calibration_continuous.json')
                        log_message("💾 Калибровка сохранена в файл")
                        
                        last_stats_time = current_time
                    
                    # Принудительное сохранение каждый час (на случай если автосохранение не сработало)
                    if current_time - last_save_time >= save_interval:
                        log_message("💾 Принудительное сохранение...")
                        detector.data_store.save_all(detector)
                        detector.save_calibration('./adaptive_calibration_continuous.json')
                        last_save_time = current_time
                        
            except Exception as e:
                # Логируем ошибки но продолжаем работу
                if frames_total % 10000 == 0:
                    log_message(f"⚠️  Ошибка обработки: {e}")
                time.sleep(0.01)
                continue
                
    except KeyboardInterrupt:
        log_message("\n⚠️  Получен сигнал остановки от пользователя")
    
    # === Финальная статистика ===
    log_message("\n" + "=" * 70)
    log_message("ЗАВЕРШЕНИЕ ОБУЧЕНИЯ")
    log_message("=" * 70)
    
    duration_hours = (time.time() - start_time) / 3600
    print_statistics(detector, duration_hours, frames_total, detections_total)
    
    # Финальное сохранение
    log_message("💾 Финальное сохранение всех данных...")
    detector.data_store.save_all(detector)
    detector.save_calibration('./adaptive_calibration_continuous.json')
    
    log_message(f"✅ Обучение завершено!")
    log_message(f"   Время работы: {duration_hours:.2f} часов")
    log_message(f"   Обработано фреймов: {frames_total}")
    log_message(f"   Данные сохранены в: {detector.data_store.data_dir}")
    log_message("=" * 70)
    
    # Остановка stream
    if stream:
        try:
            stream.send_cmd(0x21, b'')  # STOP_STREAM
        except:
            pass
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        log_message(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        log_message(traceback.format_exc())
        sys.exit(1)
