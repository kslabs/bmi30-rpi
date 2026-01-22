#!/usr/bin/env python3
"""
КАЛИБРОВКА ШУМА - НЕПРЕРЫВНАЯ
Только калибровка шума, БЕЗ детекции меток!
С полной кросс-канальной обработкой и автосохранением
"""
import sys
import os
import time
import subprocess
import numpy as np
import json
from pathlib import Path
from datetime import datetime

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from usb_vendor.usb_stream import USBStream

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
SAVE_INTERVAL_SECONDS = 3600  # Сохранять каждый час
PROGRESS_INTERVAL = 60  # Показывать прогресс каждую минуту
STATS_INTERVAL = 900  # Детальная статистика каждые 15 минут
DATA_DIR = './noise_calibration_data'

print("=" * 70)
print("КАЛИБРОВКА ШУМА - НЕПРЕРЫВНАЯ")
print("=" * 70)
print(f"⏱️  Длительность: БЕСКОНЕЧНО (до Ctrl+C)")
print(f"💾 Автосохранение каждые {SAVE_INTERVAL_SECONDS//60} минут")
print(f"📊 Прогресс каждые {PROGRESS_INTERVAL} секунд")
print(f"📁 Папка: {DATA_DIR}")
print()

# =====================================================================
# КЛАССЫ ДЛЯ СТАТИСТИКИ
# =====================================================================

class OnlineStats:
    """Онлайн-вычисление mean и std по алгоритму Велфорда"""
    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.M2 = 0.0
        self.min_val = float('inf')
        self.max_val = float('-inf')
        self.sum_val = 0.0  # Для вычисления среднего
    
    def update(self, value):
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        delta2 = value - self.mean
        self.M2 += delta * delta2
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)
        self.sum_val += value
    
    @property
    def variance(self):
        return self.M2 / self.n if self.n > 1 else 0.0
    
    @property
    def std(self):
        return np.sqrt(self.variance)
    
    def to_dict(self):
        return {
            'samples': self.n,
            'mean': float(self.mean),
            'std': float(self.std),
            'min': float(self.min_val) if self.min_val != float('inf') else 0.0,
            'max': float(self.max_val) if self.max_val != float('-inf') else 0.0
        }

class NoiseCalibrator:
    """Калибровка шума с полной кросс-канальной обработкой + EVEN/ODD + МОЩНОСТЬ"""
    def __init__(self):
        # Индивидуальные каналы - ПОЛНАЯ статистика (амплитудная)
        self.ch0_max = OnlineStats()
        self.ch0_mean = OnlineStats()
        self.ch0_rms = OnlineStats()
        self.ch0_p2p = OnlineStats()
        
        self.ch1_max = OnlineStats()
        self.ch1_mean = OnlineStats()
        self.ch1_rms = OnlineStats()
        self.ch1_p2p = OnlineStats()
        
        # НОВОЕ: Мощностные/энергетические параметры
        self.ch0_energy = OnlineStats()         # Сумма квадратов (энергия)
        self.ch0_power = OnlineStats()          # Средняя мощность = RMS^2
        self.ch0_integral = OnlineStats()       # Интеграл (площадь) = sum(|data|)
        self.ch0_mav = OnlineStats()            # Mean Absolute Value
        
        self.ch1_energy = OnlineStats()
        self.ch1_power = OnlineStats()
        self.ch1_integral = OnlineStats()
        self.ch1_mav = OnlineStats()
        
        # НОВОЕ: Even/Odd разделение для КАЖДОГО канала
        self.ch0_even_max = OnlineStats()
        self.ch0_odd_max = OnlineStats()
        self.ch1_even_max = OnlineStats()
        self.ch1_odd_max = OnlineStats()
        
        # НОВОЕ: Мощностные параметры для Even/Odd
        self.ch0_even_energy = OnlineStats()
        self.ch0_odd_energy = OnlineStats()
        self.ch1_even_energy = OnlineStats()
        self.ch1_odd_energy = OnlineStats()
        
        # Корреляция и произведение
        self.correlation = OnlineStats()
        self.product = OnlineStats()
        
        # Кросс-канальная обработка (CH0 vs CH1)
        self.sum_channels = OnlineStats()
        self.diff_channels = OnlineStats()
        self.ratio_channels = OnlineStats()
        self.phase_shift = OnlineStats()
        
        # НОВОЕ: Even vs Odd обработка (для детекции противофазности)
        self.ch0_even_odd_sum = OnlineStats()      # CH0_even + CH0_odd
        self.ch0_even_odd_diff = OnlineStats()     # |CH0_even - CH0_odd|
        self.ch1_even_odd_sum = OnlineStats()
        self.ch1_even_odd_diff = OnlineStats()
        
        # Кросс Even/Odd между каналами
        self.cross_even_sum = OnlineStats()        # CH0_even + CH1_even
        self.cross_even_diff = OnlineStats()       # |CH0_even - CH1_even|
        self.cross_odd_sum = OnlineStats()         # CH0_odd + CH1_odd
        self.cross_odd_diff = OnlineStats()        # |CH0_odd - CH1_odd|
        
        # Для корреляции между каналами
        self.cross_corr_sum = 0.0
        self.cross_corr_n = 0
        
        # История для анализа трендов
        self.history_ch0_max = []
        self.history_ch1_max = []
        self.history_sum = []
        self.history_diff = []
        self.max_history = 10000
    
    def add_sample(self, data0, data1):
        """Добавить новый семпл для калибровки - ПОЛНАЯ обработка + EVEN/ODD"""
        
        # Разделение на even/odd (четные и нечетные индексы)
        data0_even = data0[::2]   # 0, 2, 4, 6...
        data0_odd = data0[1::2]   # 1, 3, 5, 7...
        data1_even = data1[::2]
        data1_odd = data1[1::2]
        
        # Вычисление всех параметров для CH0 (полный массив)
        max_ch0 = float(np.max(data0))
        mean_ch0 = float(np.mean(data0))
        rms_ch0 = float(np.sqrt(np.mean(data0.astype(float)**2)))
        p2p_ch0 = float(np.max(data0) - np.min(data0))
        
        # НОВОЕ: Мощностные параметры для CH0
        energy_ch0 = float(np.sum(data0.astype(float)**2))     # Энергия = сумма квадратов
        power_ch0 = float(np.mean(data0.astype(float)**2))     # Мощность = среднее квадратов
        integral_ch0 = float(np.sum(np.abs(data0)))            # Интеграл = площадь
        mav_ch0 = float(np.mean(np.abs(data0)))                # MAV = средний модуль
        
        # Вычисление всех параметров для CH1 (полный массив)
        max_ch1 = float(np.max(data1))
        mean_ch1 = float(np.mean(data1))
        rms_ch1 = float(np.sqrt(np.mean(data1.astype(float)**2)))
        p2p_ch1 = float(np.max(data1) - np.min(data1))
        
        # НОВОЕ: Мощностные параметры для CH1
        energy_ch1 = float(np.sum(data1.astype(float)**2))
        power_ch1 = float(np.mean(data1.astype(float)**2))
        integral_ch1 = float(np.sum(np.abs(data1)))
        mav_ch1 = float(np.mean(np.abs(data1)))
        
        # НОВОЕ: Параметры для even/odd отдельно
        max_ch0_even = float(np.max(data0_even))
        max_ch0_odd = float(np.max(data0_odd))
        max_ch1_even = float(np.max(data1_even))
        max_ch1_odd = float(np.max(data1_odd))
        
        # НОВОЕ: Энергия для even/odd
        energy_ch0_even = float(np.sum(data0_even.astype(float)**2))
        energy_ch0_odd = float(np.sum(data0_odd.astype(float)**2))
        energy_ch1_even = float(np.sum(data1_even.astype(float)**2))
        energy_ch1_odd = float(np.sum(data1_odd.astype(float)**2))
        
        # Обновление статистики CH0 (амплитудная)
        self.ch0_max.update(max_ch0)
        self.ch0_mean.update(mean_ch0)
        self.ch0_rms.update(rms_ch0)
        self.ch0_p2p.update(p2p_ch0)
        
        # НОВОЕ: Обновление мощностных статистик CH0
        self.ch0_energy.update(energy_ch0)
        self.ch0_power.update(power_ch0)
        self.ch0_integral.update(integral_ch0)
        self.ch0_mav.update(mav_ch0)
        
        # Обновление статистики CH1 (амплитудная)
        self.ch1_max.update(max_ch1)
        self.ch1_mean.update(mean_ch1)
        self.ch1_rms.update(rms_ch1)
        self.ch1_p2p.update(p2p_ch1)
        
        # НОВОЕ: Обновление мощностных статистик CH1
        self.ch1_energy.update(energy_ch1)
        self.ch1_power.update(power_ch1)
        self.ch1_integral.update(integral_ch1)
        self.ch1_mav.update(mav_ch1)
        
        # НОВОЕ: Обновление Even/Odd статистики (амплитуда)
        self.ch0_even_max.update(max_ch0_even)
        self.ch0_odd_max.update(max_ch0_odd)
        self.ch1_even_max.update(max_ch1_even)
        self.ch1_odd_max.update(max_ch1_odd)
        
        # НОВОЕ: Обновление Even/Odd энергии
        self.ch0_even_energy.update(energy_ch0_even)
        self.ch0_odd_energy.update(energy_ch0_odd)
        self.ch1_even_energy.update(energy_ch1_even)
        self.ch1_odd_energy.update(energy_ch1_odd)
        
        # Корреляция между каналами
        corr = np.correlate(data0.astype(float), data1.astype(float), mode='valid')
        correlation_val = float(np.abs(corr[0]))
        self.correlation.update(correlation_val)
        
        # Произведение
        product_val = float(np.abs(int(data0[0]) * int(data1[0])))
        self.product.update(product_val)
        
        # Кросс-канальная обработка - ИСПРАВЛЕНО!
        # Используем MEAN вместо MAX для более стабильной метрики
        # Приводим к int32 для избежания переполнения
        data0_i32 = data0.astype(np.int32)
        data1_i32 = data1.astype(np.int32)
        
        sum_val = float(np.mean(data0_i32 + data1_i32))
        diff_val = float(np.mean(np.abs(data0_i32 - data1_i32)))
        ratio_val = mean_ch0 / max(mean_ch1, 1.0)
        
        self.sum_channels.update(sum_val)
        self.diff_channels.update(diff_val)
        self.ratio_channels.update(ratio_val)
        
        # Фазовый сдвиг (через кросс-корреляцию)
        full_corr = np.correlate(data0.astype(float), data1.astype(float), mode='full')
        phase_idx = float(np.argmax(full_corr) - len(data0) + 1)
        self.phase_shift.update(phase_idx)
        
        # НОВОЕ: Even vs Odd анализ внутри каналов - ИСПРАВЛЕНО!
        # Используем ПОСЕМПЛОВУЮ разницу, а не разницу максимумов
        # Для ШУМА: even и odd близки (diff малый)
        # Для СИГНАЛА: even и odd различны (diff большой)
        
        # Приводим к int32 чтобы избежать переполнения uint16 (быстрее float)
        ch0_even_i32 = data0_even.astype(np.int32)
        ch0_odd_i32 = data0_odd.astype(np.int32)
        ch1_even_i32 = data1_even.astype(np.int32)
        ch1_odd_i32 = data1_odd.astype(np.int32)
        
        # Посемпловая разница (правильная метрика противофазности)
        ch0_pointwise_diff = np.abs(ch0_even_i32 - ch0_odd_i32)
        ch1_pointwise_diff = np.abs(ch1_even_i32 - ch1_odd_i32)
        
        ch0_even_odd_diff_val = float(np.mean(ch0_pointwise_diff))  # Средняя разница
        ch0_even_odd_sum_val = float(np.mean(ch0_even_i32 + ch0_odd_i32))  # Средняя сумма
        ch1_even_odd_diff_val = float(np.mean(ch1_pointwise_diff))
        ch1_even_odd_sum_val = float(np.mean(ch1_even_i32 + ch1_odd_i32))
        
        self.ch0_even_odd_sum.update(ch0_even_odd_sum_val)
        self.ch0_even_odd_diff.update(ch0_even_odd_diff_val)
        self.ch1_even_odd_sum.update(ch1_even_odd_sum_val)
        self.ch1_even_odd_diff.update(ch1_even_odd_diff_val)
        
        # НОВОЕ: Кросс Even/Odd между каналами - ИСПРАВЛЕНО!
        # Посемпловая разница между каналами для even и odd отдельно
        cross_even_diff_pointwise = np.abs(ch0_even_i32 - ch1_even_i32)
        cross_odd_diff_pointwise = np.abs(ch0_odd_i32 - ch1_odd_i32)
        
        cross_even_sum_val = float(np.mean(ch0_even_i32 + ch1_even_i32))
        cross_even_diff_val = float(np.mean(cross_even_diff_pointwise))
        cross_odd_sum_val = float(np.mean(ch0_odd_i32 + ch1_odd_i32))
        cross_odd_diff_val = float(np.mean(cross_odd_diff_pointwise))
        
        self.cross_even_sum.update(cross_even_sum_val)
        self.cross_even_diff.update(cross_even_diff_val)
        self.cross_odd_sum.update(cross_odd_sum_val)
        self.cross_odd_diff.update(cross_odd_diff_val)
        
        # Кросс-корреляция (коэффициент Пирсона)
        if self.ch0_max.n > 1:
            delta0 = max_ch0 - self.ch0_max.mean
            delta1 = max_ch1 - self.ch1_max.mean
            self.cross_corr_sum += delta0 * delta1
            self.cross_corr_n += 1
        
        # История
        self.history_ch0_max.append(max_ch0)
        self.history_ch1_max.append(max_ch1)
        self.history_sum.append(sum_val)
        self.history_diff.append(diff_val)
        
        if len(self.history_ch0_max) > self.max_history:
            self.history_ch0_max.pop(0)
            self.history_ch1_max.pop(0)
            self.history_sum.pop(0)
            self.history_diff.pop(0)
    
    def get_cross_correlation_coefficient(self):
        """Коэффициент корреляции между каналами"""
        if self.cross_corr_n < 2:
            return 0.0
        
        denom = self.ch0_max.std * self.ch1_max.std * self.cross_corr_n
        if denom == 0:
            return 0.0
        
        return self.cross_corr_sum / denom
    
    def get_stats(self):
        """Получить полную статистику (амплитуды + мощности + even/odd)"""
        return {
            'timestamp': datetime.now().isoformat(),
            'total_samples': self.ch0_max.n,
            'channels': {
                'ch0': {
                    'amplitude': {
                        'max': self.ch0_max.to_dict(),
                        'mean': self.ch0_mean.to_dict(),
                        'rms': self.ch0_rms.to_dict(),
                        'peak_to_peak': self.ch0_p2p.to_dict()
                    },
                    'power': {
                        'energy': self.ch0_energy.to_dict(),
                        'power': self.ch0_power.to_dict(),
                        'integral': self.ch0_integral.to_dict(),
                        'mav': self.ch0_mav.to_dict()
                    }
                },
                'ch1': {
                    'amplitude': {
                        'max': self.ch1_max.to_dict(),
                        'mean': self.ch1_mean.to_dict(),
                        'rms': self.ch1_rms.to_dict(),
                        'peak_to_peak': self.ch1_p2p.to_dict()
                    },
                    'power': {
                        'energy': self.ch1_energy.to_dict(),
                        'power': self.ch1_power.to_dict(),
                        'integral': self.ch1_integral.to_dict(),
                        'mav': self.ch1_mav.to_dict()
                    }
                }
            },
            'cross_channel': {
                'sum': self.sum_channels.to_dict(),
                'diff': self.diff_channels.to_dict(),
                'ratio': self.ratio_channels.to_dict(),
                'phase_shift': self.phase_shift.to_dict(),
                'correlation_coefficient': float(self.get_cross_correlation_coefficient())
            },
            'signal_metrics': {
                'correlation': self.correlation.to_dict(),
                'product': self.product.to_dict()
            },
            'even_odd_analysis': {
                'ch0': {
                    'even_max': self.ch0_even_max.to_dict(),
                    'odd_max': self.ch0_odd_max.to_dict(),
                    'even_energy': self.ch0_even_energy.to_dict(),
                    'odd_energy': self.ch0_odd_energy.to_dict(),
                    'even_odd_sum': self.ch0_even_odd_sum.to_dict(),
                    'even_odd_diff': self.ch0_even_odd_diff.to_dict()
                },
                'ch1': {
                    'even_max': self.ch1_even_max.to_dict(),
                    'odd_max': self.ch1_odd_max.to_dict(),
                    'even_energy': self.ch1_even_energy.to_dict(),
                    'odd_energy': self.ch1_odd_energy.to_dict(),
                    'even_odd_sum': self.ch1_even_odd_sum.to_dict(),
                    'even_odd_diff': self.ch1_even_odd_diff.to_dict()
                },
                'cross_channel': {
                    'even_sum': self.cross_even_sum.to_dict(),
                    'even_diff': self.cross_even_diff.to_dict(),
                    'odd_sum': self.cross_odd_sum.to_dict(),
                    'odd_diff': self.cross_odd_diff.to_dict()
                }
            }
        }
    
    def save_to_file(self, filepath):
        """Сохранить в JSON"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        stats = self.get_stats()
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2)
        print(f"💾 Сохранено: {filepath}")

# =====================================================================
# ОСНОВНАЯ ПРОГРАММА
# =====================================================================

# Создать папку для данных
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

# Сброс USB
print("1️⃣  Сброс USB...")
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("✓ USB сброшен")
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен")

# Создание USBStream
print("\n2️⃣  Создание USBStream...")
stream = USBStream(profile=1, full=True)
print(f"✓ USB подключен")

# Создание калибратора
print("\n3️⃣  Создание калибратора...")
calibrator = NoiseCalibrator()
print("✓ Калибратор создан")

# Параметры работы
start_time = time.time()
last_save_time = start_time
last_progress_time = start_time
last_stats_time = start_time
frame_count = 0

print("\n" + "=" * 70)
print("КАЛИБРОВКА ШУМА ЗАПУЩЕНА")
print("=" * 70)
print(f"🕐 Начало: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"\n⚠️  Метки НЕ требуются - калибруется только ШУМ!")
print("📊 Статистика сохраняется автоматически каждый час")
print("⏹️  Для остановки нажмите Ctrl+C")
print("\n🔄 Начинаю чтение фреймов...")
sys.stdout.flush()

try:
    while True:  # БЕСКОНЕЧНЫЙ ЦИКЛ!
        current_time = time.time()
        
        # Чтение фреймов
        frame0 = stream.get_frame(0, timeout=0.1)
        frame1 = stream.get_frame(1, timeout=0.1)
        
        if frame0 and frame1:
            # Извлечение данных - ПОЛНЫЙ массив
            n_samples = min(frame0.samples, frame1.samples, 128)
            data0 = np.frombuffer(frame0.payload, dtype=np.uint16, count=n_samples)
            data1 = np.frombuffer(frame1.payload, dtype=np.uint16, count=n_samples)
            
            # Добавление в калибратор (передаем массивы, не скаляры!)
            calibrator.add_sample(data0, data1)
            frame_count += 1
        
        # Прогресс каждую минуту
        if current_time - last_progress_time >= PROGRESS_INTERVAL:
            elapsed = current_time - start_time
            elapsed_hours = elapsed / 3600
            elapsed_days = elapsed / 86400
            fps = frame_count / elapsed if elapsed > 0 else 0
            
            print(f"\n⏱️ {elapsed_hours:.1f}ч ({elapsed_days:.2f} дней) | Фреймов: {frame_count} | FPS: {fps:.1f}")
            sys.stdout.flush()
            last_progress_time = current_time
        
        # Детальная статистика каждые 15 минут
        if current_time - last_stats_time >= STATS_INTERVAL:
            stats = calibrator.get_stats()
            print("\n" + "=" * 70)
            print("ДЕТАЛЬНАЯ СТАТИСТИКА ШУМА")
            print("=" * 70)
            print(f"Семплов: {stats['total_samples']}")
            print(f"\nCH0 (АМПЛИТУДА):")
            print(f"  MAX:  mean={stats['channels']['ch0']['amplitude']['max']['mean']:.1f}, "
                  f"std={stats['channels']['ch0']['amplitude']['max']['std']:.1f}")
            print(f"  RMS:  mean={stats['channels']['ch0']['amplitude']['rms']['mean']:.1f}, "
                  f"std={stats['channels']['ch0']['amplitude']['rms']['std']:.1f}")
            print(f"\nCH0 (МОЩНОСТЬ):")
            print(f"  ЭНЕРГИЯ:  mean={stats['channels']['ch0']['power']['energy']['mean']:.1f}")
            print(f"  ИНТЕГРАЛ: mean={stats['channels']['ch0']['power']['integral']['mean']:.1f}")
            
            print(f"\nCH1 (АМПЛИТУДА):")
            print(f"  MAX:  mean={stats['channels']['ch1']['amplitude']['max']['mean']:.1f}, "
                  f"std={stats['channels']['ch1']['amplitude']['max']['std']:.1f}")
            print(f"  RMS:  mean={stats['channels']['ch1']['amplitude']['rms']['mean']:.1f}, "
                  f"std={stats['channels']['ch1']['amplitude']['rms']['std']:.1f}")
            print(f"\nCH1 (МОЩНОСТЬ):")
            print(f"  ЭНЕРГИЯ:  mean={stats['channels']['ch1']['power']['energy']['mean']:.1f}")
            print(f"  ИНТЕГРАЛ: mean={stats['channels']['ch1']['power']['integral']['mean']:.1f}")
            
            print(f"\nEVEN/ODD (CH0):")
            print(f"  EVEN энергия: mean={stats['even_odd_analysis']['ch0']['even_energy']['mean']:.1f}")
            print(f"  ODD энергия:  mean={stats['even_odd_analysis']['ch0']['odd_energy']['mean']:.1f}")
            print(f"  Diff (противофазность): mean={stats['even_odd_analysis']['ch0']['even_odd_diff']['mean']:.1f}")
            
            print(f"\nКРОСС-КАНАЛЬНАЯ ОБРАБОТКА:")
            print(f"  SUM (CH0+CH1):   mean={stats['cross_channel']['sum']['mean']:.1f}")
            print(f"  DIFF (|CH0-CH1|): mean={stats['cross_channel']['diff']['mean']:.1f}")
            print("=" * 70 + "\n")
            sys.stdout.flush()
            last_stats_time = current_time
            
            last_stats_time = current_time
        
        # Автосохранение каждый час
        if current_time - last_save_time >= SAVE_INTERVAL_SECONDS:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = os.path.join(DATA_DIR, f'noise_stats_{timestamp}.json')
            calibrator.save_to_file(save_path)
            last_save_time = current_time

except KeyboardInterrupt:
    print("\n\n⚠️  Прервано пользователем (Ctrl+C)")

finally:
    # Финальное сохранение
    print("\n" + "=" * 70)
    print("КАЛИБРОВКА ЗАВЕРШЕНА")
    print("=" * 70)
    
    final_stats = calibrator.get_stats()
    
    # Сохранение финальной статистики
    final_path = os.path.join(DATA_DIR, 'noise_stats_FINAL.json')
    calibrator.save_to_file(final_path)
    
    # Вывод итогов
    elapsed_total = time.time() - start_time
    print(f"\n⏱️  Общее время: {elapsed_total/3600:.2f} часов ({elapsed_total/86400:.2f} дней)")
    print(f"📊 Всего фреймов: {frame_count}")
    print(f"📊 Всего семплов: {final_stats['total_samples']}")
    print(f"📊 Средняя скорость: {frame_count/(elapsed_total):.1f} FPS")
    
    print(f"\n📊 ФИНАЛЬНАЯ СТАТИСТИКА ШУМА:")
    print(f"   CH0 MAX: {final_stats['channels']['ch0']['max']['mean']:.1f} ± {final_stats['channels']['ch0']['max']['std']:.1f}")
    print(f"   CH1 MAX: {final_stats['channels']['ch1']['max']['mean']:.1f} ± {final_stats['channels']['ch1']['max']['std']:.1f}")
    print(f"   CH0 RMS: {final_stats['channels']['ch0']['rms']['mean']:.1f} ± {final_stats['channels']['ch0']['rms']['std']:.1f}")
    print(f"   CH1 RMS: {final_stats['channels']['ch1']['rms']['mean']:.1f} ± {final_stats['channels']['ch1']['rms']['std']:.1f}")
    print(f"   SUM: {final_stats['cross_channel']['sum']['mean']:.1f} ± {final_stats['cross_channel']['sum']['std']:.1f}")
    print(f"   DIFF: {final_stats['cross_channel']['diff']['mean']:.1f} ± {final_stats['cross_channel']['diff']['std']:.1f}")
    print(f"   PHASE: {final_stats['cross_channel']['phase_shift']['mean']:.1f} ± {final_stats['cross_channel']['phase_shift']['std']:.1f}")
    print(f"   Корреляция: {final_stats['cross_channel']['correlation_coefficient']:.3f}")
    
    print(f"\n💾 Все данные сохранены в: {DATA_DIR}/")
    print("\n✅ ГОТОВО!")
