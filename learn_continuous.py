#!/usr/bin/env python3
"""
ДЛИТЕЛЬНОЕ ОБУЧЕНИЕ НА 2+ СУТОК
Прогресс каждую минуту - видно что работает
Статистика каждые 15 минут
Автосохранение каждый час
"""

import sys
import os
import time
import signal
import subprocess
from datetime import datetime
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector

# Глобальные для корректной остановки
running = True
detector = None
stream = None

def signal_handler(sig, frame):
    global running
    print("\n\n⚠️  Получен сигнал остановки...", flush=True)
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(msg):
    """Лог с временем и принудительным flush"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open('learning.log', 'a') as f:
            f.write(line + '\n')
            f.flush()
    except:
        pass

print("=" * 70, flush=True)
print("ДЛИТЕЛЬНОЕ ОБУЧЕНИЕ АДАПТИВНОГО ДЕТЕКТОРА", flush=True)
print("=" * 70, flush=True)
print("⏱️  Длительность: 2+ суток (Ctrl+C для остановки)", flush=True)
print("📊 Прогресс: КАЖДУЮ МИНУТУ", flush=True)
print("📈 Статистика: Каждые 15 минут", flush=True)
print("💾 Автосохранение: Каждый час", flush=True)
print("📝 Лог: learning.log\n", flush=True)

log("="*70)
log("СТАРТ ДЛИТЕЛЬНОГО ОБУЧЕНИЯ")
log("="*70)

# Сброс USB
log("Сброс USB устройства...")
try:
    result = subprocess.run(['sudo', 'usbreset', 'cafe:4001'], 
                          timeout=5, check=False, capture_output=True)
    if result.returncode == 0:
        log("✓ USB сброшен успешно")
    else:
        log("⚠️  Сброс USB вернул код: " + str(result.returncode))
    time.sleep(2)
except Exception as e:
    log(f"⚠️  Ошибка сброса USB: {e}")

# Детектор
log("Создание адаптивного детектора...")
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    data_dir='./learning_data'
)

if detector.data_store.metadata_file.exists():
    log("📂 Найдены сохраненные данные - продолжаем обучение")
else:
    log("📂 Новое обучение - начинаем с нуля")

log("✓ Детектор создан")

# Подключение USB
log("Подключение к USB устройству...")
try:
    from usb_vendor.usb_stream import USBStream
    stream = USBStream(profile=1, full=True)
    log(f"✓ USB подключен: {stream.dev.idVendor:04x}:{stream.dev.idProduct:04x}")
except Exception as e:
    log(f"❌ КРИТИЧЕСКАЯ ОШИБКА подключения USB: {e}")
    sys.exit(1)

# === КАЛИБРОВКА 5 МИНУТ ===
log("")
log("="*70)
log("ФАЗА 1: КАЛИБРОВКА ШУМА (5 МИНУТ)")
log("⚠️  ВАЖНО: Уберите все метки из зоны детекции!")
log("="*70)
log("")

calibration_duration = 300  # 5 минут
detector.start_calibration_session(calibration_duration)

start_time = time.time()
cal_frames = 0
cal_errors = 0
last_minute = 0

try:
    while (time.time() - start_time < calibration_duration) and running:
        try:
            f0 = stream.get_frame(0, timeout=0.2)
            f1 = stream.get_frame(1, timeout=0.2)
            
            if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
                d0 = np.frombuffer(f0.data, dtype=np.uint16)
                d1 = np.frombuffer(f1.data, dtype=np.uint16)
                
                if len(d0) >= 64 and len(d1) >= 64:
                    level0 = float(np.abs(d0.astype(float) - 32768).max())
                    level1 = float(np.abs(d1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                    prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
                    
                    detector.process_frame(level0, level1, corr, prod)
                    cal_frames += 1
                else:
                    cal_errors += 1
            else:
                cal_errors += 1
            
            # Прогресс КАЖДУЮ МИНУТУ
            elapsed_min = int((time.time() - start_time) / 60)
            if elapsed_min > last_minute:
                speed = cal_frames / (time.time() - start_time)
                stats = detector.get_comprehensive_stats()
                nc = stats['noise_calibration']
                
                log(f"Калибровка {elapsed_min}/5 мин | Фреймов: {cal_frames} | Ошибок: {cal_errors} | {speed:.1f} к/с")
                log(f"  CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
                log(f"  CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")
                
                last_minute = elapsed_min
                
        except Exception as e:
            cal_errors += 1
            if cal_errors % 1000 == 0:
                log(f"  ⚠️  Ошибка обработки #{cal_errors}: {str(e)[:80]}")
            time.sleep(0.01)
            
except KeyboardInterrupt:
    log("⚠️  Калибровка прервана пользователем")
    running = False

if not running:
    log("Обучение остановлено")
    sys.exit(0)

log("")
log(f"✓ Калибровка завершена: {cal_frames} фреймов, {cal_errors} ошибок")
log("")

# === ОСНОВНОЕ ОБУЧЕНИЕ ===
log("="*70)
log("ФАЗА 2: ОСНОВНОЕ ОБУЧЕНИЕ (НЕПРЕРЫВНО)")
log("Система адаптируется к реальным условиям")
log("Можно вносить/убирать метки - система будет учиться")
log("="*70)
log("")

start_learning = time.time()
last_minute_log = start_learning
last_stats_time = start_learning
last_save_time = start_learning

frames_total = 0
detections_total = 0
errors_total = 0

minute_counter = 0
stats_interval = 900  # 15 минут
save_interval = 3600  # 1 час

try:
    while running:
        try:
            f0 = stream.get_frame(0, timeout=0.2)
            f1 = stream.get_frame(1, timeout=0.2)
            
            if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
                d0 = np.frombuffer(f0.data, dtype=np.uint16)
                d1 = np.frombuffer(f1.data, dtype=np.uint16)
                
                if len(d0) >= 64 and len(d1) >= 64:
                    level0 = float(np.abs(d0.astype(float) - 32768).max())
                    level1 = float(np.abs(d1.astype(float) - 32768).max())
                    corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                    prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
                    
                    det0, det1, c0, c1 = detector.process_frame(level0, level1, corr, prod)
                    frames_total += 1
                    
                    if det0 or det1:
                        detections_total += 1
                else:
                    errors_total += 1
            else:
                errors_total += 1
            
            current_time = time.time()
            
            # Прогресс КАЖДУЮ МИНУТУ
            if current_time - last_minute_log >= 60:
                elapsed_hours = (current_time - start_learning) / 3600
                speed = frames_total / (current_time - start_learning) if frames_total > 0 else 0
                minute_counter += 1
                
                log(f"Мин {minute_counter:4d} | {elapsed_hours:.2f}ч | Фреймов: {frames_total:8d} | Детекций: {detections_total:5d} | Ошибок: {errors_total:5d} | {speed:.1f} к/с")
                
                last_minute_log = current_time
            
            # Подробная статистика каждые 15 минут
            if current_time - last_stats_time >= stats_interval:
                elapsed_hours = (current_time - start_learning) / 3600
                stats = detector.get_comprehensive_stats()
                nc = stats['noise_calibration']
                buf = stats['buffer_averaging']
                ap = stats['adaptive_params']
                det = stats['detection']
                
                log("")
                log("="*70)
                log(f"📊 СТАТИСТИКА ОБУЧЕНИЯ")
                log("="*70)
                log(f"⏱️  Время работы: {elapsed_hours:.2f} часов")
                log(f"📊 Всего фреймов: {frames_total}")
                log(f"📡 Обнаружено меток: {detections_total}")
                log(f"❌ Ошибок: {errors_total}")
                log(f"⚡ Скорость: {frames_total/(elapsed_hours*3600):.1f} кадр/сек")
                log("")
                log(f"📏 Калибровка шума:")
                log(f"   Образцов: {nc['samples_collected']}")
                log(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}, макс={nc['ch0']['max']:.0f}")
                log(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}, макс={nc['ch1']['max']:.0f}")
                log("")
                log(f"🔍 Детекция:")
                log(f"   Шум: {det['noise_frames']}")
                log(f"   Метки: {det['marker_frames']}")
                log(f"   Ложные: {det['false_positives']}")
                log("")
                log(f"⚡ Буферы: текущие={buf['current_buffers']}, оптимальные={buf['optimal_buffers']}")
                log(f"🎯 Sigma: CH0={ap['sigma_ch0']:.2f}, CH1={ap['sigma_ch1']:.2f}")
                log(f"✓ Калибровка: {ap['calibration_complete']}")
                log("="*70)
                log("")
                
                # Сохраняем калибровку
                detector.save_calibration('./learning_calibration.json')
                log("💾 Калибровка сохранена в файл")
                
                last_stats_time = current_time
            
            # Принудительное сохранение каждый час
            if current_time - last_save_time >= save_interval:
                log("💾 Авт осохранение...")
                detector.data_store.save_all(detector)
                detector.save_calibration('./learning_calibration.json')
                log("✓ Данные сохранены")
                last_save_time = current_time
                
        except Exception as e:
            errors_total += 1
            if errors_total % 1000 == 0:
                log(f"⚠️  Ошибка обработки #{errors_total}: {str(e)[:80]}")
            time.sleep(0.01)
            
except KeyboardInterrupt:
    log("")
    log("⚠️  Получен сигнал остановки от пользователя")

# === ФИНАЛЬНАЯ СТАТИСТИКА ===
log("")
log("="*70)
log("ЗАВЕРШЕНИЕ ОБУЧЕНИЯ")
log("="*70)

total_hours = (time.time() - start_learning) / 3600
stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']

log(f"⏱️  Время работы: {total_hours:.2f} часов")
log(f"📊 Всего фреймов: {frames_total}")
log(f"📡 Обнаружено меток: {detections_total}")
log(f"❌ Ошибок: {errors_total}")
log(f"⚡ Средняя скорость: {frames_total/(total_hours*3600):.1f} кадр/сек")
log("")
log(f"📏 Финальные пороги:")
log(f"   CH0: {nc['ch0']['threshold']:.0f}")
log(f"   CH1: {nc['ch1']['threshold']:.0f}")

# Финальное сохранение
log("")
log("💾 Финальное сохранение всех данных...")
detector.data_store.save_all(detector)
detector.save_calibration('./learning_calibration.json')
log(f"✓ Данные сохранены в: {detector.data_store.data_dir}")
log("="*70)

# Остановка stream
if stream:
    try:
        stream.send_cmd(0x21, b'')
        log("✓ USB stream остановлен")
    except:
        pass

log("")
log("✅ ОБУЧЕНИЕ ЗАВЕРШЕНО УСПЕШНО!")
log("")
