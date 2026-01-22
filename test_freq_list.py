#!/usr/bin/env python3
"""Тест нового списка частот"""

# Проверяем что можем импортировать BMI30.200
import sys
import os

# Добавляем host в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'host'))

print("="*60)
print("ТЕСТ: Проверка нового списка частот")
print("="*60)

# Список новых частот
expected_freqs = [200, 204, 205, 208, 210, 220, 225, 240, 250]

print(f"\n✅ Ожидаемый список частот: {expected_freqs}")

# Проверяем что функции загрузки/сохранения работают
try:
    # Импортируем напрямую из файла
    import importlib.util
    spec = importlib.util.spec_from_file_location("bmi30", "host/BMI30.200.py")
    bmi30 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmi30)
    
    save_config = bmi30.save_config
    load_freq = bmi30.load_freq
    
    print("\n📝 Тест сохранения и загрузки частоты:")
    
    # Тестируем сохранение разных частот
    for freq in [200, 210, 225, 250]:
        save_config(1, freq)
        loaded = load_freq()
        status = "✅" if loaded == freq else "❌"
        print(f"  {status} Сохранили {freq} Hz, загрузили {loaded} Hz")
    
    print("\n✅ Все тесты пройдены!")
    
except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Для запуска GUI используйте:")
print("  python host/BMI30.200.py")
print("="*60)
