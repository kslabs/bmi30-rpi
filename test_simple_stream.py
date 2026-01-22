#!/usr/bin/env python3
"""
ПРОСТОЙ ТЕСТ - проверка потока данных от USB
Длительность: 10 секунд
"""
import sys
import os
import time
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

print("=" * 70)
print("ПРОСТОЙ ТЕСТ ПОТОКА USB")
print("=" * 70)
print("⏱️  Длительность: 10 секунд")
print("📡 Подключение к устройству...\n")

# Сброс
import subprocess
try:
    subprocess.run(['sudo', 'usbreset', 'cafe:4001'], timeout=5, check=False, capture_output=True)
    print("✓ USB сброшен")
    time.sleep(2)
except:
    print("⚠️  Сброс не выполнен")

# Подключение
try:
    from usb_vendor.usb_stream import USBStream
    
    print("📡 Создание USBStream...")
    stream = USBStream(profile=1, full=True)
    
    print("✓ USB подключен")
    print(f"✓ Устройство: {stream.dev}")
    print("\n📊 Чтение данных 10 секунд...\n")
    
    start = time.time()
    duration = 10.0
    frames = 0
    bytes_received = 0
    last_pct = -1
    
    while time.time() - start < duration:
        elapsed = time.time() - start
        
        # Читаем фреймы (ADC0 и ADC1)
        try:
            frame0 = stream.get_frame(0, timeout=0.1)
            frame1 = stream.get_frame(1, timeout=0.1)
            
            if frame0 is not None:
                frames += 1
                bytes_received += len(frame0.data) if hasattr(frame0, 'data') else 256
        except Exception as e:
            pass
        
        # Прогресс каждые 5%
        pct = int(elapsed / duration * 100)
        if pct != last_pct and pct % 5 == 0:
            last_pct = pct
            filled = pct // 5
            bar = '█' * filled + '░' * (20 - filled)
            print(f"[{bar}] {pct:3d}%  Фреймы: {frames:5d}  Байт: {bytes_received:8d}  Скорость: {frames/elapsed:.1f} кадр/сек")
    
    print(f"\n✅ ЗАВЕРШЕНО")
    print(f"   Всего фреймов: {frames}")
    print(f"   Всего байт: {bytes_received}")
    print(f"   Средняя скорость: {frames/duration:.1f} кадр/сек")
    
    # Остановка
    try:
        stream.send_cmd(0x21, b'')
    except:
        pass
    
except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
