"""
Самообучающаяся система определения меток для BMI30
Использует машинное обучение для классификации сигналов и снижения ложных срабатываний
"""

import numpy as np
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import pickle


@dataclass
class SignalFeatures:
    """Признаки извлеченные из сигнала"""
    # Временная область
    mean_amplitude: float
    std_amplitude: float
    peak_amplitude: float
    snr: float  # Signal-to-noise ratio
    
    # Частотная область
    dominant_freq: float
    spectral_centroid: float
    spectral_spread: float
    
    # Корреляционные признаки
    max_correlation: float
    correlation_width: float  # ширина пика корреляции
    correlation_symmetry: float
    
    # Продукт каналов
    max_product: float
    product_std: float
    
    # Временная стабильность
    amplitude_variation: float  # изменение амплитуды во времени
    correlation_stability: float
    
    # Метка (ground truth)
    label: int  # 0=шум, 1=метка типа A, 2=метка типа B, и т.д.
    confidence: float  # уверенность оператора в метке (0.0-1.0)


class FeatureExtractor:
    """Извлечение признаков из сырых данных устройства"""
    
    def __init__(self, sampling_rate: float = 200.0):
        self.sampling_rate = sampling_rate
        
    def extract_from_frame(self, adc0: np.ndarray, adc1: np.ndarray, 
                          product: np.ndarray, correlation: np.ndarray) -> Dict[str, float]:
        """Извлечь признаки из одного фрейма данных"""
        features = {}
        
        # Центрируем данные (убираем DC)
        adc0_centered = adc0.astype(float) - 32768.0
        adc1_centered = adc1.astype(float) - 32768.0
        
        # === Временная область ===
        features['mean_amplitude'] = (np.abs(adc0_centered).mean() + 
                                     np.abs(adc1_centered).mean()) / 2.0
        features['std_amplitude'] = (adc0_centered.std() + adc1_centered.std()) / 2.0
        features['peak_amplitude'] = max(np.abs(adc0_centered).max(), 
                                         np.abs(adc1_centered).max())
        
        # SNR: соотношение сигнал/шум (примерная оценка)
        signal_power = features['mean_amplitude'] ** 2
        noise_power = features['std_amplitude'] ** 2
        features['snr'] = 10 * np.log10(signal_power / (noise_power + 1e-10) + 1e-10)
        
        # === Частотная область (простая оценка через FFT) ===
        fft0 = np.fft.rfft(adc0_centered)
        fft1 = np.fft.rfft(adc1_centered)
        power0 = np.abs(fft0) ** 2
        power1 = np.abs(fft1) ** 2
        power_avg = (power0 + power1) / 2.0
        
        freqs = np.fft.rfftfreq(len(adc0_centered), 1.0 / self.sampling_rate)
        
        # Доминирующая частота
        dominant_idx = np.argmax(power_avg[1:]) + 1  # игнорируем DC
        features['dominant_freq'] = freqs[dominant_idx]
        
        # Спектральный центроид
        features['spectral_centroid'] = np.sum(freqs * power_avg) / (np.sum(power_avg) + 1e-10)
        
        # Спектральное расширение
        features['spectral_spread'] = np.sqrt(
            np.sum(((freqs - features['spectral_centroid']) ** 2) * power_avg) / 
            (np.sum(power_avg) + 1e-10)
        )
        
        # === Корреляционные признаки ===
        features['max_correlation'] = np.abs(correlation).max()
        
        # Ширина пика корреляции (на половине высоты)
        max_corr = np.abs(correlation).max()
        threshold = max_corr / 2.0
        above_threshold = np.abs(correlation) > threshold
        if above_threshold.any():
            features['correlation_width'] = np.sum(above_threshold)
        else:
            features['correlation_width'] = 0.0
        
        # Симметрия корреляции
        mid = len(correlation) // 2
        left_half = correlation[:mid]
        right_half = correlation[mid:mid + len(left_half)][::-1]  # реверс
        features['correlation_symmetry'] = np.corrcoef(left_half, right_half)[0, 1] if len(left_half) > 1 else 0.0
        
        # === Продукт каналов ===
        features['max_product'] = np.abs(product).max()
        features['product_std'] = product.std()
        
        return features
    
    def extract_from_sequence(self, frames: List[Dict]) -> Dict[str, float]:
        """Извлечь признаки из последовательности фреймов (temporal features)"""
        if not frames:
            return {}
        
        # Извлекаем признаки для каждого фрейма
        frame_features = []
        for frame in frames:
            try:
                ff = self.extract_from_frame(
                    frame['adc0'], frame['adc1'],
                    frame['product'], frame['correlation']
                )
                frame_features.append(ff)
            except Exception:
                continue
        
        if not frame_features:
            return {}
        
        # Усредняем признаки
        avg_features = {}
        for key in frame_features[0].keys():
            values = [f[key] for f in frame_features if key in f and np.isfinite(f[key])]
            if values:
                avg_features[key] = np.mean(values)
            else:
                avg_features[key] = 0.0
        
        # Добавляем временные признаки (variation across frames)
        if len(frame_features) > 1:
            # Вариация амплитуды
            amplitudes = [f['mean_amplitude'] for f in frame_features]
            avg_features['amplitude_variation'] = np.std(amplitudes) / (np.mean(amplitudes) + 1e-10)
            
            # Стабильность корреляции
            correlations = [f['max_correlation'] for f in frame_features]
            avg_features['correlation_stability'] = 1.0 - (np.std(correlations) / (np.mean(correlations) + 1e-10))
        else:
            avg_features['amplitude_variation'] = 0.0
            avg_features['correlation_stability'] = 1.0
        
        return avg_features


class SimpleMLClassifier:
    """Простой классификатор на основе порогов и правил с онлайн-обучением"""
    
    def __init__(self):
        self.feature_thresholds = {}
        self.feature_weights = {}
        self.samples_by_class = {0: [], 1: [], 2: []}  # 0=шум, 1=метка_A, 2=метка_B
        self.learning_rate = 0.1
        self.confidence_threshold = 0.6
        
    def fit(self, X: List[Dict[str, float]], y: List[int]):
        """Обучить классификатор на размеченных данных"""
        if not X or not y:
            return
        
        # Группируем образцы по классам
        for features, label in zip(X, y):
            if label in self.samples_by_class:
                self.samples_by_class[label].append(features)
        
        # Вычисляем статистику по каждому признаку для каждого класса
        all_feature_keys = set()
        for features in X:
            all_feature_keys.update(features.keys())
        
        for feature_key in all_feature_keys:
            class_stats = {}
            for label, samples in self.samples_by_class.items():
                if samples:
                    values = [s[feature_key] for s in samples if feature_key in s and np.isfinite(s[feature_key])]
                    if values:
                        class_stats[label] = {
                            'mean': np.mean(values),
                            'std': np.std(values),
                            'min': np.min(values),
                            'max': np.max(values)
                        }
            
            if class_stats:
                self.feature_thresholds[feature_key] = class_stats
        
        # Вычисляем веса признаков на основе разделимости классов
        self._compute_feature_weights()
    
    def _compute_feature_weights(self):
        """Вычислить веса признаков на основе их способности разделять классы"""
        for feature_key, class_stats in self.feature_thresholds.items():
            if len(class_stats) < 2:
                self.feature_weights[feature_key] = 0.0
                continue
            
            # Простая метрика разделимости: разность средних / сумма стандартных отклонений
            means = [stats['mean'] for stats in class_stats.values()]
            stds = [stats['std'] for stats in class_stats.values()]
            
            if np.sum(stds) > 1e-10:
                separability = (np.max(means) - np.min(means)) / (np.sum(stds) + 1e-10)
                self.feature_weights[feature_key] = separability
            else:
                self.feature_weights[feature_key] = 0.0
    
    def predict(self, features: Dict[str, float]) -> Tuple[int, float]:
        """Предсказать класс и уверенность"""
        if not self.feature_thresholds:
            return 0, 0.0  # Нет обученной модели - считаем шумом
        
        # Вычисляем взвешенные голоса для каждого класса
        class_scores = {0: 0.0, 1: 0.0, 2: 0.0}
        total_weight = 0.0
        
        for feature_key, value in features.items():
            if feature_key not in self.feature_thresholds:
                continue
            
            weight = self.feature_weights.get(feature_key, 1.0)
            total_weight += weight
            
            # Для каждого класса вычисляем "похожесть" этого значения
            for label, stats in self.feature_thresholds[feature_key].items():
                mean = stats['mean']
                std = stats['std'] + 1e-10
                
                # Гауссова функция похожести
                similarity = np.exp(-((value - mean) ** 2) / (2 * std ** 2))
                class_scores[label] += weight * similarity
        
        if total_weight > 0:
            for label in class_scores:
                class_scores[label] /= total_weight
        
        # Выбираем класс с максимальным счетом
        predicted_class = max(class_scores, key=class_scores.get)
        confidence = class_scores[predicted_class]
        
        return predicted_class, confidence
    
    def update_online(self, features: Dict[str, float], true_label: int, confidence: float = 1.0):
        """Онлайн-обновление модели на основе нового размеченного образца"""
        if true_label not in self.samples_by_class:
            return
        
        # Добавляем образец в базу
        self.samples_by_class[true_label].append(features)
        
        # Обновляем статистику с экспоненциальным сглаживанием
        for feature_key, value in features.items():
            if not np.isfinite(value):
                continue
            
            if feature_key not in self.feature_thresholds:
                self.feature_thresholds[feature_key] = {}
            
            if true_label not in self.feature_thresholds[feature_key]:
                self.feature_thresholds[feature_key][true_label] = {
                    'mean': value,
                    'std': 1.0,
                    'min': value,
                    'max': value
                }
            else:
                stats = self.feature_thresholds[feature_key][true_label]
                alpha = self.learning_rate * confidence
                
                # Обновляем среднее и дисперсию
                old_mean = stats['mean']
                new_mean = (1 - alpha) * old_mean + alpha * value
                stats['mean'] = new_mean
                
                # Обновляем стандартное отклонение
                old_std = stats['std']
                deviation = abs(value - old_mean)
                new_std = (1 - alpha) * old_std + alpha * deviation
                stats['std'] = max(new_std, 0.1)  # минимальная дисперсия
                
                # Обновляем min/max
                stats['min'] = min(stats['min'], value)
                stats['max'] = max(stats['max'], value)
        
        # Пересчитываем веса признаков
        self._compute_feature_weights()
    
    def save(self, filepath: str):
        """Сохранить модель"""
        model_data = {
            'feature_thresholds': self.feature_thresholds,
            'feature_weights': self.feature_weights,
            'samples_count': {k: len(v) for k, v in self.samples_by_class.items()}
        }
        with open(filepath, 'w') as f:
            json.dump(model_data, f, indent=2)
    
    def load(self, filepath: str):
        """Загрузить модель"""
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, 'r') as f:
                model_data = json.load(f)
            self.feature_thresholds = model_data['feature_thresholds']
            self.feature_weights = model_data['feature_weights']
            return True
        except Exception:
            return False


class MLMarkerDetector:
    """Самообучающийся детектор меток с ML"""
    
    def __init__(self, model_path: str = './ml_model.json', 
                 training_data_dir: str = './captures'):
        self.model_path = model_path
        self.training_data_dir = training_data_dir
        self.feature_extractor = FeatureExtractor()
        self.classifier = SimpleMLClassifier()
        
        # Загружаем существующую модель если есть
        self.classifier.load(model_path)
        
        # Статистика
        self.total_predictions = 0
        self.correct_predictions = 0
        self.false_positives = 0
        self.false_negatives = 0
        
    def load_training_data_from_npz(self, npz_path: str) -> Optional[Tuple[List[Dict], int]]:
        """Загрузить обучающие данные из NPZ файла с метками"""
        try:
            data = np.load(npz_path, allow_pickle=True)
            
            # Извлекаем метку из метаданных
            metadata = data.get('metadata', None)
            if metadata is not None:
                metadata = metadata.item()
                label = metadata.get('label', 0)
                confidence = metadata.get('label_confidence', 1.0)
            else:
                label = 0
                confidence = 0.5
            
            # Извлекаем фреймы
            frames = []
            frame_keys = sorted([k for k in data.keys() if k.startswith('frame_')])
            
            for frame_key in frame_keys:
                frame_data = data[frame_key].item()
                frames.append(frame_data)
            
            if not frames:
                return None
            
            return frames, label, confidence
            
        except Exception as e:
            print(f"[ML] Failed to load {npz_path}: {e}")
            return None
    
    def train_from_directory(self, directory: str = None):
        """Обучить модель на всех размеченных данных из директории"""
        if directory is None:
            directory = self.training_data_dir
        
        npz_files = list(Path(directory).glob('*.npz'))
        if not npz_files:
            print(f"[ML] No training data found in {directory}")
            return
        
        print(f"[ML] Loading {len(npz_files)} training samples...")
        
        X = []  # features
        y = []  # labels
        
        for npz_file in npz_files:
            result = self.load_training_data_from_npz(str(npz_file))
            if result is None:
                continue
            
            frames, label, confidence = result
            
            # Извлекаем признаки
            features = self.feature_extractor.extract_from_sequence(frames)
            if features:
                X.append(features)
                y.append(label)
        
        if X:
            print(f"[ML] Training on {len(X)} samples...")
            self.classifier.fit(X, y)
            self.save_model()
            print(f"[ML] Training complete. Model saved to {self.model_path}")
        else:
            print("[ML] No valid training samples found")
    
    def predict_from_frames(self, frames: List[Dict]) -> Tuple[int, float, Dict]:
        """Предсказать тип метки из последовательности фреймов"""
        features = self.feature_extractor.extract_from_sequence(frames)
        if not features:
            return 0, 0.0, {}
        
        predicted_class, confidence = self.classifier.predict(features)
        self.total_predictions += 1
        
        return predicted_class, confidence, features
    
    def update_with_feedback(self, frames: List[Dict], true_label: int, confidence: float = 1.0):
        """Обновить модель на основе обратной связи пользователя"""
        features = self.feature_extractor.extract_from_sequence(frames)
        if features:
            self.classifier.update_online(features, true_label, confidence)
            
            # Периодически сохраняем модель
            if self.total_predictions % 10 == 0:
                self.save_model()
    
    def save_model(self):
        """Сохранить обученную модель"""
        try:
            self.classifier.save(self.model_path)
            print(f"[ML] Model saved to {self.model_path}")
        except Exception as e:
            print(f"[ML] Failed to save model: {e}")
    
    def get_statistics(self) -> Dict:
        """Получить статистику работы детектора"""
        accuracy = (self.correct_predictions / self.total_predictions * 100 
                   if self.total_predictions > 0 else 0.0)
        
        return {
            'total_predictions': self.total_predictions,
            'correct_predictions': self.correct_predictions,
            'accuracy': accuracy,
            'false_positives': self.false_positives,
            'false_negatives': self.false_negatives,
            'samples_per_class': {k: len(v) for k, v in self.classifier.samples_by_class.items()}
        }
    
    def is_marker_detected(self, frames: List[Dict], confidence_threshold: float = 0.6) -> Tuple[bool, int, float]:
        """Определить, есть ли метка в данных (упрощенный интерфейс)"""
        predicted_class, confidence, _ = self.predict_from_frames(frames)
        
        # Класс 0 = шум, остальные = различные типы меток
        is_marker = predicted_class > 0 and confidence >= confidence_threshold
        
        return is_marker, predicted_class, confidence


# Пример использования
if __name__ == '__main__':
    # Создаем детектор
    detector = MLMarkerDetector()
    
    # Обучаем на существующих данных
    detector.train_from_directory('./captures')
    
    # Показываем статистику
    stats = detector.get_statistics()
    print(f"[ML] Statistics: {stats}")
