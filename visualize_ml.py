#!/usr/bin/env python3
"""
Визуализация работы ML-системы определения меток
Показывает распределение признаков для меток и шумов
"""

import numpy as np
import sys
import os
from pathlib import Path

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

try:
    import matplotlib
    matplotlib.use('TkAgg')  # или 'Qt5Agg'
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    print("⚠️ matplotlib не установлен. Установите: pip install matplotlib")
    MATPLOTLIB_AVAILABLE = False
    sys.exit(1)

from ml_marker_detector import MLMarkerDetector, FeatureExtractor


def load_all_captures(captures_dir='./captures'):
    """Загрузить все захваты и извлечь признаки"""
    extractor = FeatureExtractor()
    
    features_by_label = {0: [], 1: [], 2: []}  # 0=шум/неизвестно, 1=метка, 2=шум_явный
    
    npz_files = list(Path(captures_dir).glob('*.npz'))
    
    print(f"Загрузка {len(npz_files)} файлов из {captures_dir}...")
    
    for i, npz_file in enumerate(npz_files):
        if (i + 1) % 10 == 0:
            print(f"  Обработано {i+1}/{len(npz_files)}...")
        
        try:
            data = np.load(str(npz_file), allow_pickle=True)
            
            # Извлекаем метку
            metadata = data.get('metadata', None)
            if metadata is not None:
                metadata = metadata.item()
                label = metadata.get('label', 0)
            else:
                label = 0
            
            # Извлекаем фреймы
            frames = []
            frame_keys = sorted([k for k in data.keys() if k.startswith('frame_')])
            for frame_key in frame_keys:
                frame_data = data[frame_key].item()
                frames.append(frame_data)
            
            if not frames:
                continue
            
            # Извлекаем признаки
            features = extractor.extract_from_sequence(frames)
            if not features:
                continue
            
            features_by_label[label].append(features)
            
        except Exception as e:
            print(f"  Ошибка {npz_file.name}: {e}")
    
    print(f"Загружено:")
    print(f"  Неизвестно/шум (0): {len(features_by_label[0])}")
    print(f"  Метки (1): {len(features_by_label[1])}")
    print(f"  Шум явный (2): {len(features_by_label[2])}")
    
    return features_by_label


def plot_feature_distributions(features_by_label):
    """Построить распределения признаков"""
    
    if not features_by_label[0] and not features_by_label[1]:
        print("⚠️ Нет данных для визуализации")
        return
    
    # Получаем список всех признаков
    sample = features_by_label.get(1, features_by_label.get(0, [None]))[0]
    if sample is None:
        return
    
    feature_names = sorted(sample.keys())
    
    # Создаем сетку графиков
    n_features = len(feature_names)
    n_cols = 3
    n_rows = (n_features + n_cols - 1) // n_cols
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 4 * n_rows))
    fig.suptitle('Распределение признаков: Метки vs Шум', fontsize=16)
    
    axes = axes.flatten() if n_features > 1 else [axes]
    
    for idx, feature_name in enumerate(feature_names):
        ax = axes[idx]
        
        # Собираем значения для каждого класса
        for label, color, name in [(0, 'red', 'Неизвестно/Шум'), 
                                     (1, 'green', 'Метка'),
                                     (2, 'orange', 'Шум явный')]:
            if not features_by_label[label]:
                continue
            
            values = [f[feature_name] for f in features_by_label[label] 
                     if feature_name in f and np.isfinite(f[feature_name])]
            
            if values:
                ax.hist(values, bins=20, alpha=0.5, color=color, label=name, density=True)
        
        ax.set_xlabel(feature_name)
        ax.set_ylabel('Плотность')
        ax.set_title(feature_name.replace('_', ' ').title())
        ax.legend()
        ax.grid(True, alpha=0.3)
    
    # Скрываем лишние оси
    for idx in range(n_features, len(axes)):
        axes[idx].axis('off')
    
    plt.tight_layout()
    
    # Сохраняем
    output_file = './ml_features_distribution.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✓ График сохранен: {output_file}")
    
    plt.show()


def plot_feature_importance(features_by_label):
    """Построить важность признаков (separability)"""
    
    if not features_by_label[1]:
        print("⚠️ Нет размеченных меток для анализа важности")
        return
    
    # Объединяем метки и шумы
    marker_features = features_by_label[1]
    noise_features = features_by_label[0] + features_by_label[2]
    
    if not noise_features:
        print("⚠️ Нет шумов для сравнения")
        return
    
    feature_names = sorted(marker_features[0].keys())
    separability = {}
    
    for feature_name in feature_names:
        # Значения для меток
        marker_values = [f[feature_name] for f in marker_features 
                        if feature_name in f and np.isfinite(f[feature_name])]
        
        # Значения для шумов
        noise_values = [f[feature_name] for f in noise_features 
                       if feature_name in f and np.isfinite(f[feature_name])]
        
        if not marker_values or not noise_values:
            separability[feature_name] = 0.0
            continue
        
        # Метрика разделимости: разность средних / сумма стандартных отклонений
        marker_mean = np.mean(marker_values)
        marker_std = np.std(marker_values)
        noise_mean = np.mean(noise_values)
        noise_std = np.std(noise_values)
        
        if marker_std + noise_std > 0:
            sep = abs(marker_mean - noise_mean) / (marker_std + noise_std + 1e-10)
        else:
            sep = 0.0
        
        separability[feature_name] = sep
    
    # Сортируем по важности
    sorted_features = sorted(separability.items(), key=lambda x: x[1], reverse=True)
    
    # График
    fig, ax = plt.subplots(figsize=(10, 8))
    
    names = [f[0].replace('_', ' ').title() for f in sorted_features]
    values = [f[1] for f in sorted_features]
    
    colors = ['green' if v > 0.5 else 'orange' if v > 0.2 else 'red' for v in values]
    
    ax.barh(names, values, color=colors, alpha=0.7)
    ax.set_xlabel('Разделимость (выше = лучше)')
    ax.set_title('Важность признаков для различения меток и шумов')
    ax.grid(True, alpha=0.3, axis='x')
    
    # Добавляем легенду
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='green', alpha=0.7, label='Высокая (>0.5)'),
        Patch(facecolor='orange', alpha=0.7, label='Средняя (0.2-0.5)'),
        Patch(facecolor='red', alpha=0.7, label='Низкая (<0.2)')
    ]
    ax.legend(handles=legend_elements, loc='lower right')
    
    plt.tight_layout()
    
    output_file = './ml_feature_importance.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✓ График сохранен: {output_file}")
    
    plt.show()
    
    # Выводим топ-5
    print("\n📊 Топ-5 наиболее важных признаков:")
    for i, (name, value) in enumerate(sorted_features[:5], 1):
        print(f"  {i}. {name.replace('_', ' ').title()}: {value:.2f}")


def plot_2d_scatter(features_by_label):
    """Построить 2D scatter plot лучших двух признаков"""
    
    if not features_by_label[1]:
        return
    
    marker_features = features_by_label[1]
    noise_features = features_by_label[0] + features_by_label[2]
    
    if not noise_features:
        return
    
    # Найдем два самых важных признака
    feature_names = sorted(marker_features[0].keys())
    separability = {}
    
    for feature_name in feature_names:
        marker_values = [f[feature_name] for f in marker_features 
                        if feature_name in f and np.isfinite(f[feature_name])]
        noise_values = [f[feature_name] for f in noise_features 
                       if feature_name in f and np.isfinite(f[feature_name])]
        
        if not marker_values or not noise_values:
            separability[feature_name] = 0.0
            continue
        
        marker_mean = np.mean(marker_values)
        marker_std = np.std(marker_values)
        noise_mean = np.mean(noise_values)
        noise_std = np.std(noise_values)
        
        sep = abs(marker_mean - noise_mean) / (marker_std + noise_std + 1e-10)
        separability[feature_name] = sep
    
    # Два лучших признака
    sorted_features = sorted(separability.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_features) < 2:
        return
    
    feat1_name = sorted_features[0][0]
    feat2_name = sorted_features[1][0]
    
    # Собираем данные
    fig, ax = plt.subplots(figsize=(10, 8))
    
    for label, color, name, marker in [(1, 'green', 'Метка', 'o'),
                                        (0, 'red', 'Неизвестно', 'x'),
                                        (2, 'orange', 'Шум', '^')]:
        if not features_by_label[label]:
            continue
        
        x_values = [f[feat1_name] for f in features_by_label[label] 
                   if feat1_name in f and feat2_name in f 
                   and np.isfinite(f[feat1_name]) and np.isfinite(f[feat2_name])]
        y_values = [f[feat2_name] for f in features_by_label[label] 
                   if feat1_name in f and feat2_name in f 
                   and np.isfinite(f[feat1_name]) and np.isfinite(f[feat2_name])]
        
        if x_values:
            ax.scatter(x_values, y_values, c=color, marker=marker, s=100, 
                      alpha=0.6, label=name, edgecolors='black', linewidths=0.5)
    
    ax.set_xlabel(feat1_name.replace('_', ' ').title())
    ax.set_ylabel(feat2_name.replace('_', ' ').title())
    ax.set_title('2D визуализация: Метки vs Шум (два лучших признака)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    output_file = './ml_2d_scatter.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✓ График сохранен: {output_file}")
    
    plt.show()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Визуализация ML-системы')
    parser.add_argument('--captures-dir', default='./captures',
                       help='Директория с захватами')
    parser.add_argument('--type', choices=['all', 'dist', 'importance', 'scatter'],
                       default='all', help='Тип графика')
    
    args = parser.parse_args()
    
    if not MATPLOTLIB_AVAILABLE:
        return 1
    
    print("=" * 60)
    print("ВИЗУАЛИЗАЦИЯ ML-СИСТЕМЫ")
    print("=" * 60)
    
    # Загружаем данные
    features_by_label = load_all_captures(args.captures_dir)
    
    total = sum(len(v) for v in features_by_label.values())
    if total == 0:
        print("\n⚠️ Нет данных для визуализации!")
        print("Сначала соберите данные и разметьте их.")
        return 1
    
    print(f"\nВсего образцов: {total}")
    
    # Строим графики
    if args.type in ['all', 'dist']:
        print("\n" + "=" * 60)
        print("График 1: Распределение признаков")
        print("=" * 60)
        plot_feature_distributions(features_by_label)
    
    if args.type in ['all', 'importance']:
        print("\n" + "=" * 60)
        print("График 2: Важность признаков")
        print("=" * 60)
        plot_feature_importance(features_by_label)
    
    if args.type in ['all', 'scatter']:
        print("\n" + "=" * 60)
        print("График 3: 2D Scatter plot")
        print("=" * 60)
        plot_2d_scatter(features_by_label)
    
    print("\n" + "=" * 60)
    print("✓ Визуализация завершена!")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
