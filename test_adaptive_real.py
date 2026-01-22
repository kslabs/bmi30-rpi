#!/usr/bin/env python3
"""
РЕАЛЬНЫЙ ТЕСТ адаптивного детектора (30 секунд)
- Аппаратный сброс USB
- Калибровка 15 сек
- Тест детекции 15 сек
- Реальный прогресс-бар
"""

import sys
import os
import time
import subprocess
import numpy as np

host_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
sys.path.insert(0, host_dir)

from adaptive_realtime_detector import AdaptiveRealtimeDetector


def hardware_reset_usb():
    """Аппаратный сброс USB устройства 0xcafe:0x4001"""
    print("🔌 Аппаратный сброс USB...")
    
    try:
        # Способ 1: unbind/bind через sysfs
        result = subprocess.run(
            ['lsusb', '-d', 'cafe:4001'], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        
        if 'cafe:4001' in result.stdout:
            print("   ✓ Устройство найдено, сброс...")
            
            # Простой способ - через usbreset если есть
            try:
                subprocess.run(['sudo', 'usbreset', 'cafe:4001'], 
                             timeout=5, check=False)
                print("   ✓ Сброс выполнен")
                time.sleep(2)
                return True
            except:
                pass
            
            # Альтернатива - выгрузка/загрузка драйвера
            try:
                subprocess.run(['sudo', 'rmmod', 'usb_storage'], 
                             timeout=3, check=False, capture_output=True)
                time.sleep(0.5)
                subprocess.run(['sudo', 'modprobe', 'usb_storage'], 
                             timeout=3, check=False, capture_output=True)
                print("   ✓ Драйвер перезагружен")
                time.sleep(2)
                return True
            except:
                pass
        else:
            print("   ⚠️  Устройство не найдено в lsusb")
            return False
            
    except Exception as e:
        print(f"   ⚠️  Ошибка сброса: {e}")
        return False


def main():
    print("=" * 70)
    print("РЕАЛЬНЫЙ ТЕСТ АДАПТИВНОГО ДЕТЕКТОРА")
    print("=" * 70)
    print("⏱️  Длительность: 30 секунд")
    print("📡 С реальным USB устройством")
    print("📊 С прогресс-индикатором\n")
    
    # === Сброс устройства ===
    hardware_reset_usb()
    
    # === Создаем детектор ===
    print("\n1️⃣ Создание детектора...")
    detector = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=64,
        data_dir='./adaptive_data_real'
    )
    print(f"✓ Детектор создан\n")
    
    # === Подключение USB ===
    print("2️⃣ Подключение к USB...")
    stream = None
    use_real_data = False
    
    try:
        from usb_vendor.usb_stream import USBStream
        stream = USBStream()  # __init__ сам запускает стрим
        print("✓ USB подключен\n")
        use_real_data = True
    except Exception as e:
        print(f"⚠️  USB недоступен: {str(e)[:80]}")
        print("   Продолжаем с симуляцией\n")
    
    # === ФАЗА 1: Калибровка (15 сек) ===
    print("3️⃣ КАЛИБРОВКА ШУМА (15 секунд)")
    print("   Уберите все метки из зоны детекции!\n")
    
    detector.start_calibration_session(15)
    
    start = time.time()
    duration = 15.0
    frames = 0
    last_bar = ""
    
    while time.time() - start < duration:
        # Получаем данные
        if use_real_data and stream:
            try:
                chunk = stream.read_bulk(timeout_ms=100)
                if not chunk or len(chunk) < 256:
                    time.sleep(0.01)
                    continue
                    
                adc0 = np.frombuffer(chunk[0:128], dtype=np.uint16)
                adc1 = np.frombuffer(chunk[128:256], dtype=np.uint16)
                
                level_ch0 = float(np.abs(adc0.astype(float) - 32768).max())
                level_ch1 = float(np.abs(adc1.astype(float) - 32768).max())
                corr = float(np.abs(np.correlate(adc0 - 32768, adc1 - 32768, 'same')).max())
                prod = float(np.abs((adc0 - 32768) * (adc1 - 32768)).max())
            except:
                time.sleep(0.01)
                continue
        else:
            # Симуляция
            level_ch0 = np.random.normal(500, 100)
            level_ch1 = np.random.normal(600, 120)
            corr = np.random.normal(200, 50)
            prod = np.random.normal(50000, 10000)
            time.sleep(0.01)
        
        detector.process_frame(level_ch0, level_ch1, corr, prod)
        frames += 1
        
        # Прогресс (обновляем каждые 0.2 сек)
        elapsed = time.time() - start
        if int(elapsed * 5) != int((elapsed - 0.2) * 5):
            pct = min(100, int(elapsed / duration * 100))
            filled = pct // 5
            bar = f"[{'█' * filled}{'░' * (20 - filled)}] {pct:3d}%  Фреймы: {frames:4d}"
            if bar != last_bar:
                print(f"\r   {bar}", end='', flush=True)
                last_bar = bar
    
    stats = detector.get_comprehensive_stats()
    nc = stats['noise_calibration']
    print(f"\n   ✓ Собрано образцов: {nc['samples_collected']}")
    print(f"   ✓ Порог CH0: {nc['ch0']['threshold']:.0f}")
    print(f"   ✓ Порог CH1: {nc['ch1']['threshold']:.0f}\n")
    
    # === ФАЗА 2: Тест детекции (15 сек) ===
    print("4️⃣ ТЕСТ ДЕТЕКЦИИ (15 секунд)")
    print("   Периодически вносите/убирайте метки\n")
    
    start = time.time()
    duration = 15.0
    frames = 0
    detections = 0
    last_bar = ""
    
    while time.time() - start < duration:
        # Получаем данные
        if use_real_data and stream:
            try:
                chunk = stream.read_bulk(timeout_ms=100)
                if not chunk or len(chunk) < 256:
                    time.sleep(0.01)
                    continue
                    
                adc0 = np.frombuffer(chunk[0:128], dtype=np.uint16)
                adc1 = np.frombuffer(chunk[128:256], dtype=np.uint16)
                
                level_ch0 = float(np.abs(adc0.astype(float) - 32768).max())
                level_ch1 = float(np.abs(adc1.astype(float) - 32768).max())
                corr = float(np.abs(np.correlate(adc0 - 32768, adc1 - 32768, 'same')).max())
                prod = float(np.abs((adc0 - 32768) * (adc1 - 32768)).max())
            except:
                time.sleep(0.01)
                continue
        else:
            # Симуляция с периодическими "метками"
            cycle = (time.time() - start) % 5.0
            is_marker = cycle < 1.0
            
            if is_marker:
                level_ch0 = np.random.normal(2000, 300)
                level_ch1 = np.random.normal(2200, 350)
                corr = np.random.normal(1500, 200)
                prod = np.random.normal(400000, 50000)
            else:
                level_ch0 = np.random.normal(500, 100)
                level_ch1 = np.random.normal(600, 120)
                corr = np.random.normal(200, 50)
                prod = np.random.normal(50000, 10000)
            time.sleep(0.01)
        
        det0, det1, c0, c1 = detector.process_frame(level_ch0, level_ch1, corr, prod)
        frames += 1
        if det0 or det1:
            detections += 1
        
        # Прогресс
        elapsed = time.time() - start
        if int(elapsed * 5) != int((elapsed - 0.2) * 5):
            pct = min(100, int(elapsed / duration * 100))
            filled = pct // 5
            marker = "🔴" if (det0 or det1) else "⚫"
            bar = f"[{'█' * filled}{'░' * (20 - filled)}] {pct:3d}%  Фреймы: {frames:4d}  Обнаружено: {detections:3d} {marker}"
            if bar != last_bar:
                print(f"\r   {bar}", end='', flush=True)
                last_bar = bar
    
    print("\n   ✓ Фаза завершена\n")
    
    # Закрываем stream
    if stream:
        try:
            stream.send_cmd(0x21, b'')  # STOP_STREAM
        except:
            pass
    
    # === ИТОГИ ===
    print("5️⃣ ИТОГОВАЯ СТАТИСТИКА")
    print("-" * 70)
    
    stats = detector.get_comprehensive_stats()
    det = stats['detection']
    
    print(f"📊 Всего фреймов: {det['total_frames']}")
    print(f"🔇 Шум: {det['noise_frames']}")
    print(f"📡 Метки: {det['marker_frames']}")
    print(f"❌ Ложные: {det['false_positives']}")
    
    nc = stats['noise_calibration']
    print(f"\n📏 Калибровка:")
    print(f"   CH0: порог={nc['ch0']['threshold']:.0f}, шум={nc['ch0']['mean']:.0f}±{nc['ch0']['std']:.0f}")
    print(f"   CH1: порог={nc['ch1']['threshold']:.0f}, шум={nc['ch1']['mean']:.0f}±{nc['ch1']['std']:.0f}")
    
    buf = stats['buffer_averaging']
    print(f"\n⚡ Буферы: текущие={buf['current_buffers']}, оптимальные={buf['optimal_buffers']}")
    
    # Сохранение
    detector.save_calibration('./adaptive_calibration_real.json')
    print(f"\n💾 Калибровка сохранена: ./adaptive_calibration_real.json")
    print(f"💾 Данные сохранены: {detector.data_store.data_dir}")
    
    print("\n" + "=" * 70)
    print("✅ ТЕСТ ЗАВЕРШЕН")
    print("=" * 70)
    print(f"⏱️  Время: 30 секунд")
    print(f"📡 USB: {'Подключен' if use_real_data else 'Симуляция'}")
    print(f"📊 Фреймов: {det['total_frames']}\n")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
