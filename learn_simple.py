#!/usr/bin/env python3
"""
РАБОЧИЙ СКРИПТ ДЛЯ ОБУЧЕНИЯ НА 2 СУТОК
Проверенная версия, работает стабильно
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

running = True
detector = None
stream = None

def signal_handler(sig, frame):
    global running
    print("\n\n⚠️  Остановка...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(msg):
    """Лог с временем"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open('learning.log', 'a') as f:
        f.write(line + '\n')

print("=" * 70)
print("ОБУЧЕНИЕ АДАПТИВНОГО ДЕТЕКТОРА")
print("=" * 70)
print("⏱️  Запускайте на 2+ суток")
print("💾 Автосохранение каждый час")
print("📊 Статистика каждые 15 минут")
print("📝 Лог: learning.log\n")

log("="*70)
log("СТАРТ ОБУЧЕНИЯ")
log("="*70)

# Сброс USB
log("Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    log("✓ USB сброшен")
    time.sleep(2)
except:
    log("⚠️  Сброс не выполнен")

# Детектор
log("Создание детектора...")
detector = AdaptiveRealtimeDetector(
    min_buffers=8,
    max_buffers=64,
    data_dir='./learning_data'
)
log("✓ Детектор создан")

# USB
log("Подключение к USB...")
try:
    from usb_vendor.usb_stream import USBStream
    stream = USBStream(profile=1, full=True)
    log("✓ USB подключен")
except Exception as e:
    log(f"❌ Ошибка USB: {e}")
    sys.exit(1)

# Калибровка 5 минут
log("Калибровка 5 минут - УБЕРИТЕ МЕТКИ!")
detector.start_calibration_session(300)

start = time.time()
frames = 0
last_log = start

while (time.time() - start < 300) and running:
    try:
        f0 = stream.get_frame(0, timeout=0.2)
        f1 = stream.get_frame(1, timeout=0.2)
        
        if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
            d0 = np.frombuffer(f0.data, dtype=np.uint16)
            d1 = np.frombuffer(f1.data, dtype=np.uint16)
            
            level0 = float(np.abs(d0.astype(float) - 32768).max())
            level1 = float(np.abs(d1.astype(float) - 32768).max())
            corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
            prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
            
            detector.process_frame(level0, level1, corr, prod)
            frames += 1
            
            # Лог каждые 30 сек
            if time.time() - last_log >= 30:
                elapsed = time.time() - start
                log(f"  Калибровка {elapsed:.0f}с | {frames} фреймов | {frames/elapsed:.1f} кадр/с")
                last_log = time.time()
    except:
        time.sleep(0.01)

if not running:
    log("Остановлено при калибровке")
    sys.exit(0)

log(f"✓ Калибровка завершена: {frames} фреймов")

# Основное обучение
log("НАЧАЛО ОСНОВНОГО ОБУЧЕНИЯ")

start_main = time.time()
last_stats = start_main
last_save = start_main
frames_total = 0
detections = 0

try:
    while running:
        try:
            f0 = stream.get_frame(0, timeout=0.2)
            f1 = stream.get_frame(1, timeout=0.2)
            
            if f0 and f1 and hasattr(f0, 'data') and hasattr(f1, 'data'):
                d0 = np.frombuffer(f0.data, dtype=np.uint16)
                d1 = np.frombuffer(f1.data, dtype=np.uint16)
                
                level0 = float(np.abs(d0.astype(float) - 32768).max())
                level1 = float(np.abs(d1.astype(float) - 32768).max())
                corr = float(np.abs(np.correlate(d0 - 32768, d1 - 32768, 'same')).max())
                prod = float(np.abs((d0 - 32768) * (d1 - 32768)).max())
                
                det0, det1, c0, c1 = detector.process_frame(level0, level1, corr, prod)
                frames_total += 1
                
                if det0 or det1:
                    detections += 1
                
                current = time.time()
                
                # Статистика каждые 15 минут
                if current - last_stats >= 900:
                    hours = (current - start_main) / 3600
                    stats = detector.get_comprehensive_stats()
                    nc = stats['noise_calibration']
                    
                    log(f"\n{'='*70}")
                    log(f"⏱️  {hours:.2f} часов | Фреймов: {frames_total} | Детекций: {detections}")
                    log(f"📏 CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
                    log(f"📏 CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")
                    log(f"⚡ Буферы: {stats['buffer_averaging']['current_buffers']}")
                    log(f"🎯 Sigma: CH0={stats['adaptive_params']['sigma_ch0']:.2f}, CH1={stats['adaptive_params']['sigma_ch1']:.2f}")
                    log(f"{'='*70}\n")
                    
                    last_stats = current
                
                # Сохранение каждый час
                if current - last_save >= 3600:
                    log("💾 Сохранение...")
                    detector.data_store.save_all(detector)
                    detector.save_calibration('./learning_calibration.json')
                    log("✓ Сохранено")
                    last_save = current
        except Exception as e:
            if frames_total % 10000 == 0:
                log(f"⚠️  Ошибка: {e}")
            time.sleep(0.01)
except KeyboardInterrupt:
    log("Остановлено пользователем")

# Финал
log("\n" + "="*70)
log("ЗАВЕРШЕНИЕ")
log("="*70)

hours = (time.time() - start_main) / 3600
stats = detector.get_comprehensive_stats()
nc = stats['noise_calibration']

log(f"⏱️  Время: {hours:.2f} часов")
log(f"📊 Фреймов: {frames_total}")
log(f"📡 Детекций: {detections}")
log(f"⚡ Скорость: {frames_total/(hours*3600):.1f} кадр/с")
log(f"📏 CH0: порог={nc['ch0']['threshold']:.0f}")
log(f"📏 CH1: порог={nc['ch1']['threshold']:.0f}")

detector.data_store.save_all(detector)
detector.save_calibration('./learning_calibration.json')
log("💾 Финальное сохранение")
log(f"📁 Данные: {detector.data_store.data_dir}")
log("="*70)

try:
    stream.send_cmd(0x21, b'')
except:
    pass
