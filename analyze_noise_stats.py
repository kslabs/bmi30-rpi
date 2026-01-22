#!/usr/bin/env python3
"""
Анализ собранной статистики шума
"""
import json
import glob
from pathlib import Path

def analyze_stats():
    files = sorted(glob.glob('noise_calibration_data/noise_stats_*.json'))
    
    if not files:
        print("❌ Нет файлов статистики!")
        return
    
    print(f"📊 АНАЛИЗ КАЛИБРОВКИ ШУМА")
    print(f"=" * 70)
    print(f"Всего файлов: {len(files)}")
    print(f"Первый: {Path(files[0]).name}")
    print(f"Последний: {Path(files[-1]).name}")
    print()
    
    # Загрузка последнего файла
    with open(files[-1]) as f:
        latest = json.load(f)
    
    total_samples = latest['total_samples']
    
    print(f"📈 НАКОПЛЕНО ДАННЫХ:")
    print(f"  Всего семплов: {total_samples:,}")
    print(f"  Это примерно: {total_samples / 183 / 3600:.1f} часов @ 183 FPS")
    print()
    
    # Анализ амплитудных параметров
    ch0_max = latest['channels']['ch0']['amplitude']['max']
    ch1_max = latest['channels']['ch1']['amplitude']['max']
    
    print(f"🔊 АМПЛИТУДНЫЕ ПАРАМЕТРЫ:")
    print(f"  CH0 MAX: mean={ch0_max['mean']:.1f}, std={ch0_max['std']:.1f}")
    print(f"  CH1 MAX: mean={ch1_max['mean']:.1f}, std={ch1_max['std']:.1f}")
    
    # Проблема: MAX постоянно 65535 (насыщение!)
    if ch0_max['mean'] > 65530:
        print(f"  ⚠️  ПРОБЛЕМА: CH0 MAX близок к 65535 (насыщение АЦП!)")
    if ch1_max['mean'] > 65530:
        print(f"  ⚠️  ПРОБЛЕМА: CH1 MAX близок к 65535 (насыщение АЦП!)")
    
    # Проверка std - должен быть больше для полезной статистики
    if ch0_max['std'] < 100:
        print(f"  ⚠️  CH0: малое std={ch0_max['std']:.1f} - данные слишком однородны")
    if ch1_max['std'] < 100:
        print(f"  ⚠️  CH1: малое std={ch1_max['std']:.1f} - данные слишком однородны")
    print()
    
    # Мощностные параметры
    ch0_energy = latest['channels']['ch0']['power']['energy']
    ch1_energy = latest['channels']['ch1']['power']['energy']
    
    print(f"⚡ МОЩНОСТНЫЕ ПАРАМЕТРЫ:")
    print(f"  CH0 ENERGY: mean={ch0_energy['mean']:.0f}, std={ch0_energy['std']:.0f}")
    print(f"  CH1 ENERGY: mean={ch1_energy['mean']:.0f}, std={ch1_energy['std']:.0f}")
    print(f"  Вариабельность CH0: {ch0_energy['std'] / ch0_energy['mean'] * 100:.1f}%")
    print(f"  Вариабельность CH1: {ch1_energy['std'] / ch1_energy['mean'] * 100:.1f}%")
    print()
    
    # Even/Odd анализ (критично для детекции!)
    even_odd = latest['even_odd_analysis']
    ch0_even_energy = even_odd['ch0']['even_energy']['mean']
    ch0_odd_energy = even_odd['ch0']['odd_energy']['mean']
    ch0_even_odd_diff = even_odd['ch0']['even_odd_diff']['mean']
    
    print(f"🔀 EVEN/ODD АНАЛИЗ (для детекции противофазности):")
    print(f"  CH0 EVEN энергия: {ch0_even_energy:.0f}")
    print(f"  CH0 ODD энергия:  {ch0_odd_energy:.0f}")
    print(f"  Разница энергий: {abs(ch0_even_energy - ch0_odd_energy):.0f}")
    print(f"  Even-Odd DIFF (противофазность): {ch0_even_odd_diff:.1f}")
    
    if ch0_even_odd_diff < 10:
        print(f"  ⚠️  ПРОБЛЕМА: Diff={ch0_even_odd_diff:.1f} слишком мал!")
        print(f"      Шум синфазный, противофазные сигналы не видны")
    print()
    
    # Кросс-канальная обработка
    cross = latest['cross_channel']
    sum_ch = cross['sum']
    diff_ch = cross['diff']
    
    print(f"🔗 КРОСС-КАНАЛЬНАЯ ОБРАБОТКА:")
    print(f"  SUM (CH0+CH1):   {sum_ch['mean']:.1f} ± {sum_ch['std']:.1f}")
    print(f"  DIFF (|CH0-CH1|): {diff_ch['mean']:.1f} ± {diff_ch['std']:.1f}")
    
    if diff_ch['mean'] < 5:
        print(f"  ⚠️  ПРОБЛЕМА: DIFF={diff_ch['mean']:.1f} близок к нулю")
        print(f"      Оба канала идентичны - нет дифференциальной информации")
    print()
    
    # Итоговая оценка
    print(f"=" * 70)
    print(f"📋 ИТОГОВАЯ ОЦЕНКА:")
    print()
    
    issues = []
    
    # Проверка 1: Насыщение АЦП
    if ch0_max['mean'] > 65530 or ch1_max['mean'] > 65530:
        issues.append("❌ АЦП насыщен (MAX=65535) - теряется информация о пиках")
    
    # Проверка 2: Малая вариабельность
    if ch0_max['std'] < 100 and ch1_max['std'] < 100:
        issues.append("❌ Слишком малое std - данные однородны, нет динамики")
    
    # Проверка 3: Even/Odd не работает
    if ch0_even_odd_diff < 10:
        issues.append("❌ Even/Odd diff=0 - не видно противофазности (критично!)")
    
    # Проверка 4: Каналы идентичны
    if diff_ch['mean'] < 5:
        issues.append("❌ CH0≈CH1 (diff=0) - нет дифференциальной информации")
    
    if issues:
        print("ПРОБЛЕМЫ ОБНАРУЖЕНЫ:")
        for issue in issues:
            print(f"  {issue}")
        print()
        print("⚠️  ВЫВОД: Статистика набрана НЕКОРРЕКТНО!")
        print()
        print("РЕКОМЕНДАЦИИ:")
        print("1. MAX всегда 65535 → проблема в коде (используется max вместо данных)")
        print("2. Even/Odd diff=0 → алгоритм разделения не работает")
        print("3. CH0≈CH1 → каналы не отличаются, возможно дубликат данных")
        print()
        print("НУЖНО ПЕРЕДЕЛАТЬ:")
        print("• Проверить извлечение данных из фреймов")
        print("• Убедиться что data0 и data1 - это массивы, а не скаляры")
        print("• Проверить что even/odd индексы применяются корректно")
        print("• Добавить отладочный вывод сырых данных для проверки")
    else:
        print("✅ Статистика выглядит корректно!")
        print(f"   Собрано достаточно данных для анализа")
    
    print("=" * 70)

if __name__ == '__main__':
    analyze_stats()
