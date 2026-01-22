#!/usr/bin/env python3
"""
Быстрое автоматическое обучение ML-модели на существующих захватах
Использует эвристики для автоматической разметки неразмеченных данных
"""

import numpy as np
from pathlib import Path
from ml_marker_detector import MLMarkerDetector, FeatureExtractor
import argparse


def auto_label_capture(npz_path: str, extractor: FeatureExtractor) -> int:
    """
    Автоматически определить метку для захвата на основе эвристик
    Возвращает: 0=шум, 1=метка
    """
    try:
        data = np.load(npz_path, allow_pickle=True)
        
        # Проверяем существующую метку
        metadata = data.get('metadata', None)
        if metadata is not None:
            metadata = metadata.item()
            existing_label = metadata.get('label', None)
            if existing_label is not None and existing_label > 0:
                print(f"[AUTO] {Path(npz_path).name}: уже размечено как {existing_label}")
                return existing_label
        
        # Извлекаем фреймы
        frames = []
        frame_keys = sorted([k for k in data.keys() if k.startswith('frame_')])
        for frame_key in frame_keys:
            frame_data = data[frame_key].item()
            frames.append(frame_data)
        
        if not frames:
            return 0
        
        # Извлекаем признаки
        features = extractor.extract_from_sequence(frames)
        if not features:
            return 0
        
        # ЭВРИСТИКИ для автоматической разметки:
        
        # 1. Проверка амплитуды - метки обычно имеют выраженную амплитуду
        amplitude_threshold = 2000.0  # можно настроить
        has_amplitude = features.get('mean_amplitude', 0) > amplitude_threshold
        
        # 2. Проверка корреляции - метки имеют высокую корреляцию между каналами
        correlation_threshold = 1000.0  # можно настроить
        has_correlation = features.get('max_correlation', 0) > correlation_threshold
        
        # 3. Проверка SNR - метки имеют хорошее соотношение сигнал/шум
        snr_threshold = 10.0  # dB
        has_good_snr = features.get('snr', 0) > snr_threshold
        
        # 4. Проверка продукта каналов - метки имеют высокий продукт
        product_threshold = 500000.0  # можно настроить
        has_product = features.get('max_product', 0) > product_threshold
        
        # 5. Стабильность - метки стабильны во времени
        stability_threshold = 0.7
        is_stable = features.get('correlation_stability', 0) > stability_threshold
        
        # Комбинированное решение (нужно выполнение большинства условий)
        conditions = [has_amplitude, has_correlation, has_good_snr, has_product, is_stable]
        score = sum(conditions)
        
        if score >= 3:  # минимум 3 из 5 условий
            label = 1  # метка
            reason = f"amplitude={has_amplitude}, corr={has_correlation}, snr={has_good_snr}, prod={has_product}, stable={is_stable}"
            print(f"[AUTO] {Path(npz_path).name}: МЕТКА (score={score}/5) [{reason}]")
        else:
            label = 0  # шум
            print(f"[AUTO] {Path(npz_path).name}: ШУМ (score={score}/5)")
        
        # Сохраняем автоматическую метку обратно в файл
        save_auto_label(npz_path, label, confidence=0.7)  # confidence < 1.0 для авто-меток
        
        return label
        
    except Exception as e:
        print(f"[AUTO] Ошибка обработки {Path(npz_path).name}: {e}")
        return 0


def save_auto_label(npz_path: str, label: int, confidence: float = 0.7):
    """Сохранить автоматическую метку в NPZ файл"""
    try:
        data = np.load(npz_path, allow_pickle=True)
        
        # Обновляем метаданные
        metadata = data.get('metadata', None)
        if metadata is not None:
            metadata = metadata.item()
        else:
            metadata = {}
        
        # Не перезаписываем ручные метки
        if 'label' in metadata and metadata.get('label_confidence', 0) >= 1.0:
            return
        
        metadata['label'] = label
        metadata['label_confidence'] = confidence
        metadata['label_source'] = 'auto'
        metadata['label_timestamp'] = str(np.datetime64('now'))
        
        # Пересохраняем
        save_dict = {'metadata': metadata}
        for key in data.keys():
            if key.startswith('frame_'):
                save_dict[key] = data[key]
        
        np.savez(npz_path, **save_dict)
        
    except Exception as e:
        print(f"[AUTO] Ошибка сохранения метки для {Path(npz_path).name}: {e}")


def main():
    parser = argparse.ArgumentParser(description='Автоматическое обучение ML-модели')
    parser.add_argument('--captures-dir', default='./captures', 
                       help='Директория с захватами (default: ./captures)')
    parser.add_argument('--model-path', default='./ml_model.json',
                       help='Путь для сохранения модели (default: ./ml_model.json)')
    parser.add_argument('--auto-label', action='store_true',
                       help='Автоматически разметить неразмеченные данные')
    parser.add_argument('--force-relabel', action='store_true',
                       help='Перезаписать существующие автоматические метки')
    
    args = parser.parse_args()
    
    print(f"[TRAIN] Автоматическое обучение ML-модели")
    print(f"[TRAIN] Директория с данными: {args.captures_dir}")
    print(f"[TRAIN] Путь к модели: {args.model_path}")
    print()
    
    # Создаем детектор
    detector = MLMarkerDetector(
        model_path=args.model_path,
        training_data_dir=args.captures_dir
    )
    
    # Автоматическая разметка (если включено)
    if args.auto_label:
        print("[TRAIN] Шаг 1: Автоматическая разметка данных")
        print("-" * 50)
        
        extractor = FeatureExtractor()
        npz_files = list(Path(args.captures_dir).glob('*.npz'))
        
        if not npz_files:
            print(f"[TRAIN] Нет NPZ файлов в {args.captures_dir}")
            return
        
        print(f"[TRAIN] Найдено {len(npz_files)} файлов")
        
        labeled_count = 0
        for npz_file in npz_files:
            label = auto_label_capture(str(npz_file), extractor)
            if label > 0:
                labeled_count += 1
        
        print(f"\n[TRAIN] Размечено: {labeled_count} меток, {len(npz_files) - labeled_count} шумов")
        print()
    
    # Обучение модели
    print("[TRAIN] Шаг 2: Обучение модели")
    print("-" * 50)
    
    detector.train_from_directory(args.captures_dir)
    
    # Статистика
    print("\n[TRAIN] Шаг 3: Статистика модели")
    print("-" * 50)
    
    stats = detector.get_statistics()
    print(f"Образцов по классам:")
    print(f"  Шум (0): {stats['samples_per_class'].get(0, 0)}")
    print(f"  Метка (1): {stats['samples_per_class'].get(1, 0)}")
    print(f"  Метка типа B (2): {stats['samples_per_class'].get(2, 0)}")
    
    total_samples = sum(stats['samples_per_class'].values())
    print(f"\nВсего обучающих образцов: {total_samples}")
    
    if total_samples < 20:
        print("\n⚠️  ВНИМАНИЕ: Мало обучающих данных!")
        print("Рекомендуется собрать минимум 50-100 образцов для хорошей работы модели.")
    else:
        print("\n✓ Модель обучена успешно!")
    
    print(f"\nМодель сохранена в: {args.model_path}")
    print("\nДля использования в BMI30.200.py:")
    print("  export BMI30_ML_ENABLE=1")
    print(f"  export BMI30_ML_MODEL_PATH={args.model_path}")
    print("  python host/BMI30.200.py")


if __name__ == '__main__':
    main()
