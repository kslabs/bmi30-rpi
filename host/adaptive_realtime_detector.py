"""
Адаптивный детектор меток в реальном времени
Автоматически калибрует шум и адаптирует пороги на основе живых данных
"""

import numpy as np
import time
import json
import os
import shutil
from pathlib import Path
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Dict, List
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing as mp
from datetime import datetime, timedelta


@dataclass
class DetectionStats:
    """Статистика детекции"""
    total_frames: int = 0
    noise_frames: int = 0
    marker_frames: int = 0
    false_positives: int = 0
    true_positives: int = 0
    avg_buffers_used: float = 64.0
    optimal_buffers: int = 64
    noise_level: float = 0.0
    marker_level: float = 0.0
    snr: float = 0.0
    detection_speed_ms: float = 0.0


@dataclass
class NoiseProfile:
    """Профиль шума для каждого канала"""
    mean_level: float = 0.0
    std_level: float = 0.0
    max_level: float = 0.0
    correlation_mean: float = 0.0
    correlation_std: float = 0.0
    product_mean: float = 0.0
    product_std: float = 0.0
    samples_count: int = 0


class AdaptiveBufferAverager:
    """
    Адаптивное усреднение буферов
    Автоматически выбирает оптимальное количество буферов (8-64)
    """
    
    def __init__(self, min_buffers=8, max_buffers=64):
        self.min_buffers = min_buffers
        self.max_buffers = max_buffers
        self.current_buffers = max_buffers  # начинаем с максимума
        
        # История для адаптации
        self.snr_history = deque(maxlen=100)  # последние SNR
        self.speed_history = deque(maxlen=100)  # время детекции
        
        # Оптимальные параметры
        self.optimal_buffers = max_buffers
        self.optimal_snr = 0.0
        
        # Режим калибровки
        self.calibration_mode = True
        self.calibration_samples = {}  # {num_buffers: [snr_values]}
        
        self.lock = threading.Lock()
    
    def test_buffer_count(self, num_buffers: int, snr: float, detection_time_ms: float):
        """Тестировать конкретное количество буферов"""
        with self.lock:
            if num_buffers not in self.calibration_samples:
                self.calibration_samples[num_buffers] = []
            
            self.calibration_samples[num_buffers].append({
                'snr': snr,
                'time_ms': detection_time_ms,
                'timestamp': time.time()
            })
    
    def find_optimal_buffers(self) -> int:
        """
        Найти оптимальное количество буферов
        Критерий: минимальное время при SNR > порога
        """
        with self.lock:
            if not self.calibration_samples:
                return self.max_buffers
            
            # Анализируем каждое значение буферов
            best_score = -1e9
            best_buffers = self.max_buffers
            
            for num_buffers, samples in self.calibration_samples.items():
                if not samples:
                    continue
                
                # Средние значения
                avg_snr = np.mean([s['snr'] for s in samples])
                avg_time = np.mean([s['time_ms'] for s in samples])
                
                # Критерий качества: SNR / time
                # Хотим максимальный SNR при минимальном времени
                if avg_snr > 3.0:  # минимально приемлемый SNR
                    score = avg_snr / (avg_time + 1.0)  # чем меньше время, тем лучше
                    
                    if score > best_score:
                        best_score = score
                        best_buffers = num_buffers
                        self.optimal_snr = avg_snr
            
            self.optimal_buffers = best_buffers
            return best_buffers
    
    def get_current_buffers(self) -> int:
        """Получить текущее оптимальное количество буферов"""
        with self.lock:
            return self.current_buffers
    
    def update_adaptive(self, current_snr: float, detection_time_ms: float):
        """Адаптивное обновление на основе текущих условий"""
        with self.lock:
            self.snr_history.append(current_snr)
            self.speed_history.append(detection_time_ms)
            
            if len(self.snr_history) < 10:
                return
            
            # Если SNR слишком низкий - увеличиваем буферы
            avg_snr = np.mean(list(self.snr_history)[-10:])
            if avg_snr < 3.0 and self.current_buffers < self.max_buffers:
                self.current_buffers = min(self.current_buffers + 4, self.max_buffers)
            
            # Если SNR очень высокий - можем уменьшить буферы для скорости
            elif avg_snr > 10.0 and self.current_buffers > self.min_buffers:
                self.current_buffers = max(self.current_buffers - 4, self.min_buffers)
    
    def get_stats(self) -> Dict:
        """Статистика калибровки"""
        with self.lock:
            stats = {
                'current_buffers': self.current_buffers,
                'optimal_buffers': self.optimal_buffers,
                'optimal_snr': self.optimal_snr,
                'calibration_samples': {
                    k: len(v) for k, v in self.calibration_samples.items()
                }
            }
            
            if self.snr_history:
                stats['recent_snr'] = float(np.mean(list(self.snr_history)[-10:]))
            if self.speed_history:
                stats['recent_speed_ms'] = float(np.mean(list(self.speed_history)[-10:]))
            
            return stats


class NoiseCalibrator:
    """
    Калибровка шумового фона
    Работает постоянно в фоновом режиме, собирая статистику шума
    """
    
    def __init__(self, learning_rate=0.05):
        self.learning_rate = learning_rate
        
        # Профили шума для каждого канала
        self.noise_ch0 = NoiseProfile()
        self.noise_ch1 = NoiseProfile()
        self.noise_combined = NoiseProfile()
        
        # Буфер недавних измерений (для быстрой адаптации)
        self.recent_levels_ch0 = deque(maxlen=200)
        self.recent_levels_ch1 = deque(maxlen=200)
        self.recent_correlations = deque(maxlen=200)
        self.recent_products = deque(maxlen=200)
        
        # Детектор выбросов (для исключения меток из калибровки)
        self.outlier_threshold_sigma = 3.0
        
        self.lock = threading.Lock()
        self.calibration_start_time = time.time()
        self.is_calibrating = True
    
    def add_sample(self, level_ch0: float, level_ch1: float, 
                   correlation: float, product: float,
                   is_marker_suspected: bool = False):
        """
        Добавить образец для калибровки шума
        is_marker_suspected: если True, образец может содержать метку (исключаем из статистики шума)
        """
        with self.lock:
            # Если подозреваем метку - не используем для калибровки шума
            if is_marker_suspected:
                return
            
            # Проверка на выбросы
            if self.recent_levels_ch0:
                median_ch0 = np.median(list(self.recent_levels_ch0))
                std_ch0 = np.std(list(self.recent_levels_ch0))
                
                if abs(level_ch0 - median_ch0) > self.outlier_threshold_sigma * std_ch0:
                    return  # выброс, вероятно метка
            
            # Добавляем в буферы
            self.recent_levels_ch0.append(level_ch0)
            self.recent_levels_ch1.append(level_ch1)
            self.recent_correlations.append(correlation)
            self.recent_products.append(product)
            
            # Обновляем профили с экспоненциальным сглаживанием
            alpha = self.learning_rate
            
            # Канал 0
            if self.noise_ch0.samples_count == 0:
                self.noise_ch0.mean_level = level_ch0
                self.noise_ch0.std_level = 1.0
            else:
                old_mean = self.noise_ch0.mean_level
                self.noise_ch0.mean_level = (1 - alpha) * old_mean + alpha * level_ch0
                deviation = abs(level_ch0 - old_mean)
                self.noise_ch0.std_level = (1 - alpha) * self.noise_ch0.std_level + alpha * deviation
            
            self.noise_ch0.max_level = max(self.noise_ch0.max_level, level_ch0)
            self.noise_ch0.samples_count += 1
            
            # Канал 1
            if self.noise_ch1.samples_count == 0:
                self.noise_ch1.mean_level = level_ch1
                self.noise_ch1.std_level = 1.0
            else:
                old_mean = self.noise_ch1.mean_level
                self.noise_ch1.mean_level = (1 - alpha) * old_mean + alpha * level_ch1
                deviation = abs(level_ch1 - old_mean)
                self.noise_ch1.std_level = (1 - alpha) * self.noise_ch1.std_level + alpha * deviation
            
            self.noise_ch1.max_level = max(self.noise_ch1.max_level, level_ch1)
            self.noise_ch1.samples_count += 1
            
            # Комбинированный профиль
            if self.noise_combined.samples_count == 0:
                self.noise_combined.correlation_mean = correlation
                self.noise_combined.correlation_std = 1.0
                self.noise_combined.product_mean = product
                self.noise_combined.product_std = 1.0
            else:
                # Корреляция
                old_corr_mean = self.noise_combined.correlation_mean
                self.noise_combined.correlation_mean = (1 - alpha) * old_corr_mean + alpha * correlation
                corr_dev = abs(correlation - old_corr_mean)
                self.noise_combined.correlation_std = (1 - alpha) * self.noise_combined.correlation_std + alpha * corr_dev
                
                # Продукт
                old_prod_mean = self.noise_combined.product_mean
                self.noise_combined.product_mean = (1 - alpha) * old_prod_mean + alpha * product
                prod_dev = abs(product - old_prod_mean)
                self.noise_combined.product_std = (1 - alpha) * self.noise_combined.product_std + alpha * prod_dev
            
            self.noise_combined.samples_count += 1
    
    def get_adaptive_threshold(self, channel: int, sigma_multiplier: float = 3.0) -> float:
        """
        Получить адаптивный порог для канала
        threshold = mean + sigma_multiplier * std
        """
        with self.lock:
            if channel == 0:
                profile = self.noise_ch0
            elif channel == 1:
                profile = self.noise_ch1
            else:
                return 0.0
            
            if profile.samples_count < 10:
                # Недостаточно данных - используем начальный порог
                return 1000.0
            
            threshold = profile.mean_level + sigma_multiplier * profile.std_level
            return max(threshold, 100.0)  # минимальный порог
    
    def get_correlation_threshold(self, sigma_multiplier: float = 3.0) -> float:
        """Адаптивный порог для корреляции"""
        with self.lock:
            if self.noise_combined.samples_count < 10:
                return 500.0
            
            threshold = self.noise_combined.correlation_mean + sigma_multiplier * self.noise_combined.correlation_std
            return max(threshold, 50.0)
    
    def get_product_threshold(self, sigma_multiplier: float = 3.0) -> float:
        """Адаптивный порог для продукта"""
        with self.lock:
            if self.noise_combined.samples_count < 10:
                return 100000.0
            
            threshold = self.noise_combined.product_mean + sigma_multiplier * self.noise_combined.product_std
            return max(threshold, 10000.0)
    
    def estimate_snr(self, signal_level: float, channel: int) -> float:
        """Оценить SNR для сигнала"""
        with self.lock:
            if channel == 0:
                noise_level = self.noise_ch0.mean_level
            elif channel == 1:
                noise_level = self.noise_ch1.mean_level
            else:
                noise_level = 1.0
            
            if noise_level < 1.0:
                noise_level = 1.0
            
            snr_linear = signal_level / noise_level
            snr_db = 10.0 * np.log10(snr_linear + 1e-10)
            return snr_db
    
    def is_calibration_ready(self, min_samples: int = 100) -> bool:
        """Готова ли калибровка (собрано достаточно образцов шума)"""
        with self.lock:
            return (self.noise_ch0.samples_count >= min_samples and 
                    self.noise_ch1.samples_count >= min_samples)
    
    def get_stats(self) -> Dict:
        """Статистика калибровки"""
        with self.lock:
            calibration_time = time.time() - self.calibration_start_time
            
            return {
                'calibration_time_sec': calibration_time,
                'samples_collected': self.noise_combined.samples_count,
                'ready': self.is_calibration_ready(),
                'ch0': {
                    'mean': self.noise_ch0.mean_level,
                    'std': self.noise_ch0.std_level,
                    'max': self.noise_ch0.max_level,
                    'threshold': self.get_adaptive_threshold(0)
                },
                'ch1': {
                    'mean': self.noise_ch1.mean_level,
                    'std': self.noise_ch1.std_level,
                    'max': self.noise_ch1.max_level,
                    'threshold': self.get_adaptive_threshold(1)
                },
                'correlation': {
                    'mean': self.noise_combined.correlation_mean,
                    'std': self.noise_combined.correlation_std,
                    'threshold': self.get_correlation_threshold()
                },
                'product': {
                    'mean': self.noise_combined.product_mean,
                    'std': self.noise_combined.product_std,
                    'threshold': self.get_product_threshold()
                }
            }


class PersistentDataStore:
    """
    Персистентное хранилище данных адаптивного детектора
    Автоматически сохраняет и загружает данные из папки
    """
    
    def __init__(self, data_dir='./adaptive_data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Файлы данных
        self.noise_profile_file = self.data_dir / 'noise_profile.json'
        self.buffer_calibration_file = self.data_dir / 'buffer_calibration.json'
        self.adaptive_params_file = self.data_dir / 'adaptive_params.json'
        self.statistics_file = self.data_dir / 'statistics.json'
        self.metadata_file = self.data_dir / 'metadata.json'
        
        # Последнее время сохранения
        self.last_save_time = time.time()
        self.save_interval = 3600  # 1 час по умолчанию
        
        # Блокировка для потокобезопасности
        self.lock = threading.Lock()
    
    def save_all(self, detector):
        """Сохранить все данные детектора"""
        with self.lock:
            try:
                # Получаем статистику
                stats = detector.get_comprehensive_stats()
                
                # Сохраняем в отдельные файлы для лучшей модульности
                with open(self.noise_profile_file, 'w') as f:
                    json.dump(stats['noise_calibration'], f, indent=2)
                
                with open(self.buffer_calibration_file, 'w') as f:
                    json.dump(stats['buffer_averaging'], f, indent=2)
                
                with open(self.adaptive_params_file, 'w') as f:
                    json.dump(stats['adaptive_params'], f, indent=2)
                
                with open(self.statistics_file, 'w') as f:
                    json.dump(stats['detection'], f, indent=2)
                
                # Метаданные
                metadata = {
                    'last_save_time': datetime.now().isoformat(),
                    'version': '1.0',
                    'calibration_complete': stats['adaptive_params']['calibration_complete']
                }
                with open(self.metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                self.last_save_time = time.time()
                return True
                
            except Exception as e:
                print(f"[STORE] Ошибка сохранения: {e}")
                return False
    
    def load_all(self, detector):
        """Загрузить все данные в детектор"""
        with self.lock:
            try:
                # Проверяем существование файлов
                if not self.metadata_file.exists():
                    print(f"[STORE] Нет сохраненных данных в {self.data_dir}")
                    return False
                
                # Загружаем метаданные
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                print(f"[STORE] Загрузка данных от {metadata['last_save_time']}")
                
                # Загружаем профиль шума
                if self.noise_profile_file.exists():
                    with open(self.noise_profile_file, 'r') as f:
                        noise_data = json.load(f)
                    self._restore_noise_calibrator(detector.noise_calibrator, noise_data)
                
                # Загружаем калибровку буферов
                if self.buffer_calibration_file.exists():
                    with open(self.buffer_calibration_file, 'r') as f:
                        buffer_data = json.load(f)
                    self._restore_buffer_averager(detector.buffer_averager, buffer_data)
                
                # Загружаем адаптивные параметры
                if self.adaptive_params_file.exists():
                    with open(self.adaptive_params_file, 'r') as f:
                        params_data = json.load(f)
                    detector.threshold_sigma_multiplier = params_data.get('threshold_sigma', 3.0)
                    detector.calibration_complete = params_data.get('calibration_complete', False)
                
                print(f"[STORE] Данные успешно загружены")
                return True
                
            except Exception as e:
                print(f"[STORE] Ошибка загрузки: {e}")
                return False
    
    def _restore_noise_calibrator(self, calibrator, data):
        """Восстановить калибратор шума"""
        if 'ch0' in data:
            ch0 = data['ch0']
            calibrator.noise_ch0.mean_level = ch0.get('mean', 0.0)
            calibrator.noise_ch0.std_level = ch0.get('std', 1.0)
            calibrator.noise_ch0.max_level = ch0.get('max', 0.0)
            calibrator.noise_ch0.samples_count = data.get('samples_collected', 0)
        
        if 'ch1' in data:
            ch1 = data['ch1']
            calibrator.noise_ch1.mean_level = ch1.get('mean', 0.0)
            calibrator.noise_ch1.std_level = ch1.get('std', 1.0)
            calibrator.noise_ch1.max_level = ch1.get('max', 0.0)
            calibrator.noise_ch1.samples_count = data.get('samples_collected', 0)
        
        if 'correlation' in data:
            corr = data['correlation']
            calibrator.noise_combined.correlation_mean = corr.get('mean', 0.0)
            calibrator.noise_combined.correlation_std = corr.get('std', 1.0)
        
        if 'product' in data:
            prod = data['product']
            calibrator.noise_combined.product_mean = prod.get('mean', 0.0)
            calibrator.noise_combined.product_std = prod.get('std', 1.0)
        
        calibrator.noise_combined.samples_count = data.get('samples_collected', 0)
    
    def _restore_buffer_averager(self, averager, data):
        """Восстановить усреднитель буферов"""
        averager.current_buffers = data.get('current_buffers', 64)
        averager.optimal_buffers = data.get('optimal_buffers', 64)
        averager.optimal_snr = data.get('optimal_snr', 0.0)
    
    def should_save(self):
        """Проверить, нужно ли сохранить данные"""
        if self.save_interval is None:
            return False
        return (time.time() - self.last_save_time) >= self.save_interval
    
    def reset(self):
        """Сбросить все данные (удалить папку)"""
        with self.lock:
            try:
                if self.data_dir.exists():
                    # Создаем бэкап перед удалением
                    backup_dir = Path(str(self.data_dir) + '_backup_' + 
                                    datetime.now().strftime('%Y%m%d_%H%M%S'))
                    shutil.copytree(self.data_dir, backup_dir)
                    print(f"[STORE] Бэкап создан: {backup_dir}")
                    
                    # Удаляем текущую папку
                    shutil.rmtree(self.data_dir)
                    print(f"[STORE] Данные удалены: {self.data_dir}")
                    
                    # Создаем заново
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    return True
            except Exception as e:
                print(f"[STORE] Ошибка сброса: {e}")
                return False
    
    def get_data_age(self):
        """Получить возраст данных"""
        if not self.metadata_file.exists():
            return None
        
        try:
            with open(self.metadata_file, 'r') as f:
                metadata = json.load(f)
            last_save = datetime.fromisoformat(metadata['last_save_time'])
            age = datetime.now() - last_save
            return age
        except Exception:
            return None


class MultiProcessingFrameProcessor:
    """
    Многопроцессорная обработка фреймов на 4 ядрах
    Ускоряет вычисление признаков и обработку данных
    """
    
    def __init__(self, num_workers=4):
        self.num_workers = min(num_workers, mp.cpu_count())
        self.executor = ProcessPoolExecutor(max_workers=self.num_workers)
        print(f"[MP] Инициализировано {self.num_workers} рабочих процессов")
    
    def process_frames_parallel(self, frames_batch):
        """Обработать батч фреймов параллельно"""
        # Разбиваем на чанки для процессов
        chunk_size = max(1, len(frames_batch) // self.num_workers)
        chunks = [frames_batch[i:i + chunk_size] 
                 for i in range(0, len(frames_batch), chunk_size)]
        
        # Обрабатываем параллельно
        futures = [self.executor.submit(self._process_chunk, chunk) 
                  for chunk in chunks]
        
        # Собираем результаты
        results = []
        for future in futures:
            try:
                results.extend(future.result(timeout=5.0))
            except Exception as e:
                print(f"[MP] Ошибка обработки: {e}")
        
        return results
    
    @staticmethod
    def _process_chunk(frames):
        """Обработать чанк фреймов (выполняется в отдельном процессе)"""
        results = []
        for frame in frames:
            # Вычисляем различные метрики
            result = {
                'mean': np.mean(frame),
                'std': np.std(frame),
                'max': np.max(frame),
                'min': np.min(frame)
            }
            results.append(result)
        return results
    
    def shutdown(self):
        """Остановить пул процессов"""
        self.executor.shutdown(wait=True)
        print(f"[MP] Рабочие процессы остановлены")


class AdaptiveRealtimeDetector:
    """
    Адаптивный детектор меток в реальном времени
    Автоматически калибрует шум и адаптирует параметры
    С персистентным хранилищем и многопроцессорной обработкой
    """
    
    def __init__(self, min_buffers=8, max_buffers=64, 
                 data_dir='./adaptive_data',
                 auto_save_interval=3600,
                 use_multiprocessing=True,
                 num_workers=4):
        # Компоненты
        self.buffer_averager = AdaptiveBufferAverager(min_buffers, max_buffers)
        self.noise_calibrator = NoiseCalibrator(learning_rate=0.05)
        
        # Персистентное хранилище
        self.data_store = PersistentDataStore(data_dir)
        self.data_store.save_interval = auto_save_interval
        
        # Многопроцессорная обработка
        self.use_multiprocessing = use_multiprocessing
        if use_multiprocessing:
            self.mp_processor = MultiProcessingFrameProcessor(num_workers)
        else:
            self.mp_processor = None
        
        # Автоматическая загрузка сохраненных данных
        self._try_load_saved_data()
        
        # Запуск автосохранения
        self.auto_save_running = False
        self.auto_save_thread = None
        self._start_auto_save_thread()
        
        # Состояние детекции
        self.marker_detected_ch0 = False
        self.marker_detected_ch1 = False
        self.detection_confidence_ch0 = 0.0
        self.detection_confidence_ch1 = 0.0
        
        # История детекций для адаптации
        self.detection_history = deque(maxlen=1000)
        
        # Статистика
        self.stats = DetectionStats()
        
        # Режимы работы
        self.auto_calibration_mode = True  # автоматическая калибровка при старте
        self.calibration_complete = False
        
        # Параметры адаптации порогов
        self.threshold_sigma_multiplier = 3.0  # начальное значение
        self.min_sigma = 2.0
        self.max_sigma = 5.0
        
        # Для отслеживания ложных срабатываний
        self.false_positive_rate = 0.0
        self.false_positive_history = deque(maxlen=100)
        
        self.lock = threading.Lock()
    
    def process_frame(self, level_ch0: float, level_ch1: float,
                     correlation: float, product: float,
                     user_feedback: Optional[str] = None) -> Tuple[bool, bool, float, float]:
        """
        Обработать фрейм данных
        
        Args:
            level_ch0, level_ch1: уровни сигнала по каналам
            correlation: корреляция между каналами
            product: произведение каналов
            user_feedback: обратная связь от пользователя ('marker', 'noise', 'false_positive')
        
        Returns:
            (detected_ch0, detected_ch1, confidence_ch0, confidence_ch1)
        """
        t_start = time.time()
        
        with self.lock:
            self.stats.total_frames += 1
            
            # Получаем текущее количество буферов для усреднения
            current_buffers = self.buffer_averager.get_current_buffers()
            
            # === Этап 1: Калибровка шума (если еще не завершена) ===
            if self.auto_calibration_mode and not self.calibration_complete:
                # Предварительная проверка: похоже ли на метку?
                # Используем простой порог для начальной оценки
                is_suspected_marker = (level_ch0 > 2000 or level_ch1 > 2000 or 
                                      correlation > 1000 or product > 200000)
                
                # Добавляем в калибровку (если не метка)
                self.noise_calibrator.add_sample(
                    level_ch0, level_ch1, correlation, product,
                    is_marker_suspected=is_suspected_marker
                )
                
                # Проверяем готовность калибровки
                if self.noise_calibrator.is_calibration_ready(min_samples=200):
                    self.calibration_complete = True
                    print(f"[ADAPTIVE] Калибровка шума завершена после {self.stats.total_frames} фреймов")
            
            # === Этап 2: Адаптивные пороги ===
            threshold_ch0 = self.noise_calibrator.get_adaptive_threshold(0, self.threshold_sigma_multiplier)
            threshold_ch1 = self.noise_calibrator.get_adaptive_threshold(1, self.threshold_sigma_multiplier)
            threshold_corr = self.noise_calibrator.get_correlation_threshold(self.threshold_sigma_multiplier)
            threshold_prod = self.noise_calibrator.get_product_threshold(self.threshold_sigma_multiplier)
            
            # === Этап 3: Детекция ===
            detected_ch0 = level_ch0 > threshold_ch0
            detected_ch1 = level_ch1 > threshold_ch1
            detected_corr = correlation > threshold_corr
            detected_prod = product > threshold_prod
            
            # Комбинированная логика (можно настроить)
            # Вариант 1: OR - хотя бы один канал
            # Вариант 2: AND - оба канала (строже)
            # Вариант 3: взвешенное голосование
            
            # Используем взвешенное голосование
            votes_ch0 = sum([detected_ch0, detected_corr, detected_prod])
            votes_ch1 = sum([detected_ch1, detected_corr, detected_prod])
            
            final_detected_ch0 = votes_ch0 >= 2  # минимум 2 из 3
            final_detected_ch1 = votes_ch1 >= 2
            
            # Уверенность (0.0 - 1.0)
            confidence_ch0 = votes_ch0 / 3.0
            confidence_ch1 = votes_ch1 / 3.0
            
            # === Этап 4: SNR оценка ===
            snr_ch0 = self.noise_calibrator.estimate_snr(level_ch0, 0)
            snr_ch1 = self.noise_calibrator.estimate_snr(level_ch1, 1)
            snr_avg = (snr_ch0 + snr_ch1) / 2.0
            
            # === Этап 5: Обновление статистики ===
            if final_detected_ch0 or final_detected_ch1:
                self.stats.marker_frames += 1
            else:
                self.stats.noise_frames += 1
                
                # Если калибровка завершена, продолжаем собирать статистику шума
                if self.calibration_complete:
                    self.noise_calibrator.add_sample(
                        level_ch0, level_ch1, correlation, product,
                        is_marker_suspected=False
                    )
            
            # === Этап 6: Обратная связь от пользователя ===
            if user_feedback == 'false_positive' and (final_detected_ch0 or final_detected_ch1):
                # Ложное срабатывание - увеличиваем пороги
                self.stats.false_positives += 1
                self.false_positive_history.append(1)
                self._adapt_thresholds_on_false_positive()
            
            elif user_feedback == 'marker' and (final_detected_ch0 or final_detected_ch1):
                # Правильное обнаружение
                self.stats.true_positives += 1
                self.false_positive_history.append(0)
            
            elif user_feedback == 'marker' and not (final_detected_ch0 or final_detected_ch1):
                # Пропустили метку - уменьшаем пороги
                self._adapt_thresholds_on_missed_marker()
            
            # === Этап 7: Адаптация количества буферов ===
            detection_time_ms = (time.time() - t_start) * 1000.0
            self.buffer_averager.update_adaptive(snr_avg, detection_time_ms)
            
            # Сохраняем в историю
            self.detection_history.append({
                'timestamp': time.time(),
                'detected_ch0': final_detected_ch0,
                'detected_ch1': final_detected_ch1,
                'confidence_ch0': confidence_ch0,
                'confidence_ch1': confidence_ch1,
                'snr': snr_avg,
                'buffers_used': current_buffers
            })
            
            # Обновляем статистику
            self.stats.avg_buffers_used = current_buffers
            self.stats.detection_speed_ms = detection_time_ms
            
            self.marker_detected_ch0 = final_detected_ch0
            self.marker_detected_ch1 = final_detected_ch1
            self.detection_confidence_ch0 = confidence_ch0
            self.detection_confidence_ch1 = confidence_ch1
            
            return final_detected_ch0, final_detected_ch1, confidence_ch0, confidence_ch1
    
    def _adapt_thresholds_on_false_positive(self):
        """Адаптировать пороги при ложном срабатывании"""
        # Увеличиваем множитель sigma
        self.threshold_sigma_multiplier = min(
            self.threshold_sigma_multiplier + 0.1,
            self.max_sigma
        )
    
    def _adapt_thresholds_on_missed_marker(self):
        """Адаптировать пороги при пропуске метки"""
        # Уменьшаем множитель sigma
        self.threshold_sigma_multiplier = max(
            self.threshold_sigma_multiplier - 0.1,
            self.min_sigma
        )
    
    def start_calibration_session(self, duration_sec: int = 60):
        """
        Запустить сессию калибровки шума
        Пользователь должен убрать все метки на указанное время
        """
        self.auto_calibration_mode = True
        self.calibration_complete = False
        self.noise_calibrator = NoiseCalibrator()  # сброс
        print(f"[ADAPTIVE] Запущена калибровка шума на {duration_sec} сек")
        print(f"[ADAPTIVE] Уберите все метки из зоны детекции!")
    
    def test_buffer_counts_auto(self, test_duration_sec: int = 300):
        """
        Автоматическое тестирование различных количеств буферов
        Запускается на несколько минут с периодической подачей меток
        """
        print(f"[ADAPTIVE] Автоматическое тестирование буферов ({test_duration_sec} сек)")
        print(f"[ADAPTIVE] Периодически подносите и убирайте метку")
        
        self.buffer_averager.calibration_mode = True
        # В основном цикле будет переключаться количество буферов
    
    def get_comprehensive_stats(self) -> Dict:
        """Получить полную статистику"""
        with self.lock:
            stats = {
                'detection': asdict(self.stats),
                'noise_calibration': self.noise_calibrator.get_stats(),
                'buffer_averaging': self.buffer_averager.get_stats(),
                'adaptive_params': {
                    'threshold_sigma': self.threshold_sigma_multiplier,
                    'calibration_complete': self.calibration_complete,
                    'false_positive_rate': self._calculate_false_positive_rate()
                },
                'current_state': {
                    'marker_ch0': self.marker_detected_ch0,
                    'marker_ch1': self.marker_detected_ch1,
                    'confidence_ch0': self.detection_confidence_ch0,
                    'confidence_ch1': self.detection_confidence_ch1
                }
            }
            return stats
    
    def _calculate_false_positive_rate(self) -> float:
        """Вычислить процент ложных срабатываний"""
        if not self.false_positive_history:
            return 0.0
        return sum(self.false_positive_history) / len(self.false_positive_history) * 100.0
    
    def _try_load_saved_data(self):
        """Попытаться загрузить сохраненные данные"""
        try:
            age = self.data_store.get_data_age()
            if age is not None:
                hours = age.total_seconds() / 3600
                print(f"[ADAPTIVE] Найдены данные возрастом {hours:.1f} часов")
                
                # Если данные свежие (< 7 дней), загружаем
                if age < timedelta(days=7):
                    if self.data_store.load_all(self):
                        print(f"[ADAPTIVE] Данные успешно восстановлены")
                    else:
                        print(f"[ADAPTIVE] Не удалось загрузить данные")
                else:
                    print(f"[ADAPTIVE] Данные устарели (> 7 дней), начинаем заново")
            else:
                print(f"[ADAPTIVE] Нет сохраненных данных, начинаем с нуля")
        except Exception as e:
            print(f"[ADAPTIVE] Ошибка загрузки данных: {e}")
    
    def _start_auto_save_thread(self):
        """Запустить фоновый поток автосохранения"""
        if self.data_store.save_interval is None:
            print(f"[ADAPTIVE] Автосохранение отключено")
            return
        self.auto_save_running = True
        self.auto_save_thread = threading.Thread(target=self._auto_save_loop, daemon=True)
        self.auto_save_thread.start()
        print(f"[ADAPTIVE] Автосохранение каждые {self.data_store.save_interval} сек")
    
    def _auto_save_loop(self):
        """Цикл автосохранения"""
        while self.auto_save_running:
            time.sleep(60)  # проверяем каждую минуту
            
            if self.data_store.should_save():
                try:
                    self.data_store.save_all(self)
                    print(f"[ADAPTIVE] Автосохранение выполнено")
                except Exception as e:
                    print(f"[ADAPTIVE] Ошибка автосохранения: {e}")
    
    def save_now(self):
        """Немедленно сохранить данные"""
        return self.data_store.save_all(self)
    
    def reset_all_data(self):
        """Сбросить все накопленные данные"""
        print(f"[ADAPTIVE] Сброс всех данных...")
        if self.data_store.reset():
            # Переинициализируем компоненты
            self.noise_calibrator = NoiseCalibrator(learning_rate=0.05)
            self.calibration_complete = False
            self.stats = DetectionStats()
            print(f"[ADAPTIVE] Данные сброшены, начинаем заново")
            return True
        return False
    
    def save_calibration(self, filepath: str):
        """Сохранить калиброванные параметры (legacy compatibility)"""
        # Используем новую систему хранения
        return self.save_now()
    
    def stop(self):
        """Остановить детектор и сохранить данные"""
        print(f"[ADAPTIVE] Остановка детектора...")
        
        # Останавливаем автосохранение
        self.auto_save_running = False
        if self.auto_save_thread is not None:
            self.auto_save_thread.join(timeout=5.0)
        
        # Финальное сохранение
        self.save_now()
        
        # Останавливаем мультипроцессинг
        if self.mp_processor is not None:
            self.mp_processor.shutdown()
        
        print(f"[ADAPTIVE] Детектор остановлен")
    
    def load_calibration(self, filepath: str):
        """Загрузить калиброванные параметры"""
        try:
            with open(filepath, 'r') as f:
                stats = json.load(f)
            
            # Восстанавливаем параметры
            if 'adaptive_params' in stats:
                self.threshold_sigma_multiplier = stats['adaptive_params'].get('threshold_sigma', 3.0)
                self.calibration_complete = stats['adaptive_params'].get('calibration_complete', False)
            
            print(f"[ADAPTIVE] Калибровка загружена: {filepath}")
            return True
        except Exception as e:
            print(f"[ADAPTIVE] Ошибка загрузки калибровки: {e}")
            return False


# Пример использования
if __name__ == '__main__':
    import random
    
    print("=== Демонстрация адаптивного детектора ===\n")
    
    # Создаем детектор
    detector = AdaptiveRealtimeDetector(min_buffers=8, max_buffers=64)
    
    # Симуляция данных
    print("Фаза 1: Калибровка шума (только шум, без меток)...")
    for i in range(300):
        # Генерируем шум
        noise_ch0 = random.gauss(500, 100)
        noise_ch1 = random.gauss(600, 120)
        noise_corr = random.gauss(200, 50)
        noise_prod = random.gauss(50000, 10000)
        
        detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
            noise_ch0, noise_ch1, noise_corr, noise_prod
        )
        
        if (i + 1) % 100 == 0:
            stats = detector.get_comprehensive_stats()
            print(f"  Фрейм {i+1}: порог_ch0={stats['noise_calibration']['ch0']['threshold']:.1f}, "
                  f"порог_ch1={stats['noise_calibration']['ch1']['threshold']:.1f}")
    
    print("\nФаза 2: Тестирование с метками...")
    for i in range(200):
        # Периодически добавляем метку
        if i % 40 < 10:  # метка присутствует
            signal_ch0 = random.gauss(2000, 300)
            signal_ch1 = random.gauss(2200, 350)
            signal_corr = random.gauss(1500, 200)
            signal_prod = random.gauss(400000, 50000)
            feedback = 'marker'
        else:  # только шум
            signal_ch0 = random.gauss(500, 100)
            signal_ch1 = random.gauss(600, 120)
            signal_corr = random.gauss(200, 50)
            signal_prod = random.gauss(50000, 10000)
            feedback = None
        
        detected_ch0, detected_ch1, conf0, conf1 = detector.process_frame(
            signal_ch0, signal_ch1, signal_corr, signal_prod,
            user_feedback=feedback if detected_ch0 or detected_ch1 else None
        )
        
        if detected_ch0 or detected_ch1:
            print(f"  Фрейм {i}: ОБНАРУЖЕНО! CH0={detected_ch0} ({conf0:.2f}), CH1={detected_ch1} ({conf1:.2f})")
    
    # Итоговая статистика
    print("\n=== Итоговая статистика ===")
    final_stats = detector.get_comprehensive_stats()
    print(json.dumps(final_stats, indent=2))
    
    # Сохраняем калибровку
    detector.save_calibration('./adaptive_calibration.json')
