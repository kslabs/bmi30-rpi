#!/usr/bin/env python3
"""
Тест адаптивного детектора с реальными данными от USB-устройства
Запускается на 60 секунд для проверки работы в реальном времени
"""

import sys
import os
import time
import signal
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent / 'host'))

import numpy as np
import usb.core
import usb.util
from adaptive_realtime_detector import AdaptiveRealtimeDetector


class BMI30Device:
    """Класс для работы с BMI30 устройством"""
    
    VID = 0x04D8
    PID = 0x0053
    INTERFACE = 0
    ENDPOINT_IN = 0x81
    
    def __init__(self):
        self.dev = None
        self.interface_claimed = False
        
    def connect(self):
        """Подключение к устройству"""
        print("Поиск BMI30 устройства...")
        self.dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
        
        if self.dev is None:
            raise RuntimeError("Устройство BMI30 не найдено")
        
        print(f"✓ Устройство найдено: {self.dev}")
        
        # Освобождаем интерфейс если занят
        if self.dev.is_kernel_driver_active(self.INTERFACE):
            try:
                self.dev.detach_kernel_driver(self.INTERFACE)
                print("✓ Kernel driver отключен")
            except usb.core.USBError as e:
                print(f"⚠️  Не удалось отключить kernel driver: {e}")
        
        # Захватываем интерфейс
        try:
            usb.util.claim_interface(self.dev, self.INTERFACE)
            self.interface_claimed = True
            print("✓ Интерфейс захвачен")
        except usb.core.USBError as e:
            raise RuntimeError(f"Не удалось захватить интерфейс: {e}")
        
        return True
    
    def read_frame(self, timeout=100):
        """Чтение одного фрейма данных"""
        try:
            data = self.dev.read(self.ENDPOINT_IN, 64, timeout)
            return bytes(data)
        except usb.core.USBError as e:
            if e.errno == 110:  # Timeout
                return None
            raise
    
    def disconnect(self):
        """Отключение от устройства"""
        if self.interface_claimed:
            try:
                usb.util.release_interface(self.dev, self.INTERFACE)
                print("✓ Интерфейс освобожден")
            except:
                pass
            self.interface_claimed = False


def parse_frame(data):
    """Парсинг фрейма данных от BMI30"""
    if not data or len(data) < 64:
        return None
    
    # Извлекаем данные ADC (предполагаемый формат)
    # Это нужно адаптировать под реальный протокол BMI30
    try:
        # Пример извлечения данных (адаптируйте под ваш протокол)
        ch0 = int.from_bytes(data[0:2], byteorder='little', signed=True)
        ch1 = int.from_bytes(data[2:4], byteorder='little', signed=True)
        
        # Вычисляем корреляцию и произведение
        corr = ch0 * ch1 / 1000.0  # Нормализация
        prod = abs(ch0 * ch1)
        
        return ch0, ch1, corr, prod
    except:
        return None


def print_stats(detector, elapsed):
    """Печать статистики детектора"""
    stats = detector.get_comprehensive_stats()
    
    print("\n" + "=" * 60)
    print(f"СТАТИСТИКА (время работы: {elapsed:.1f} сек)")
    print("=" * 60)
    
    # Калибровка
    cal = stats['noise_calibration']
    print(f"\nКалибровка шума:")
    print(f"  Статус: {'✓ Завершена' if cal['is_calibrated'] else '⏳ В процессе'}")
    print(f"  Образцов: {cal['samples_collected']}")
    print(f"  Порог CH0: {cal['ch0']['threshold']:.1f}")
    print(f"  Порог CH1: {cal['ch1']['threshold']:.1f}")
    
    # Буферизация
    buf = stats['buffer_optimization']
    print(f"\nБуферизация:")
    print(f"  Текущий размер: {buf['current_size']} буферов")
    print(f"  Лучший размер: {buf['best_size']} буферов")
    print(f"  Протестировано: {buf['tested_count']}/{buf['total_sizes']}")
    
    # Детекция
    det = stats['detection']
    print(f"\nДетекция:")
    print(f"  Всего кадров: {det['total_frames']}")
    print(f"  Кадров с меткой: {det['marker_frames']}")
    if det['total_frames'] > 0:
        print(f"  Частота меток: {100.0 * det['marker_frames'] / det['total_frames']:.1f}%")
    
    # Обучение
    learn = stats['learning']
    print(f"\nОбучение:")
    print(f"  Подтверждений: {learn['confirmations']}")
    print(f"  Отклонений: {learn['rejections']}")
    print(f"  Пропусков: {learn['missed_reports']}")


def test_realtime_usb(duration=60):
    """Тест с реальными USB данными"""
    
    print("\n" + "=" * 60)
    print(f"ТЕСТ С РЕАЛЬНЫМ USB УСТРОЙСТВОМ ({duration} сек)")
    print("=" * 60)
    
    # Подключение к устройству
    device = BMI30Device()
    try:
        device.connect()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        print("\nПроверьте:")
        print("  1. Устройство BMI30 подключено")
        print("  2. У вас есть права доступа к USB (sudo или udev rules)")
        print("  3. Устройство не занято другим процессом")
        return False
    
    # Создаем детектор
    print("\nСоздание адаптивного детектора...")
    detector = AdaptiveRealtimeDetector(
        min_buffers=8,
        max_buffers=64,
        data_dir='./usb_detector_data',
        auto_save_interval=30,  # Автосохранение каждые 30 сек
        use_multiprocessing=False  # Для простоты
    )
    print("✓ Детектор создан")
    
    # Запускаем калибровку
    print(f"\nЗапуск калибровки на {duration} сек...")
    print("Нажмите Ctrl+C для остановки\n")
    
    detector.start_calibration()
    
    start_time = time.time()
    frames_received = 0
    frames_parsed = 0
    markers_detected = 0
    last_stats_time = start_time
    
    # Обработчик Ctrl+C
    def signal_handler(sig, frame):
        print("\n\n⚠️  Прервано пользователем")
        raise KeyboardInterrupt
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        while True:
            elapsed = time.time() - start_time
            
            # Проверка времени
            if elapsed >= duration:
                print(f"\n✓ Время истекло ({duration} сек)")
                break
            
            # Чтение фрейма
            data = device.read_frame(timeout=100)
            if data:
                frames_received += 1
                
                # Парсинг фрейма
                parsed = parse_frame(data)
                if parsed:
                    frames_parsed += 1
                    ch0, ch1, corr, prod = parsed
                    
                    # Обработка детектором
                    is_marker, confidence = detector.process_frame(ch0, ch1, corr, prod)
                    
                    if is_marker:
                        markers_detected += 1
                        print(f"🔔 МЕТКА #{markers_detected} обнаружена! "
                              f"(CH0={ch0:.0f}, CH1={ch1:.0f}, уверенность={confidence:.2f})")
            
            # Статистика каждые 10 секунд
            if elapsed - last_stats_time >= 10:
                fps = frames_parsed / elapsed if elapsed > 0 else 0
                print(f"\n[{elapsed:.0f}с] Получено: {frames_received}, "
                      f"Обработано: {frames_parsed} ({fps:.1f} FPS), "
                      f"Метки: {markers_detected}")
                last_stats_time = elapsed
        
        # Финальная статистика
        elapsed = time.time() - start_time
        print_stats(detector, elapsed)
        
        fps = frames_parsed / elapsed if elapsed > 0 else 0
        print(f"\nПроизводительность:")
        print(f"  Получено фреймов: {frames_received}")
        print(f"  Обработано: {frames_parsed}")
        print(f"  Средняя скорость: {fps:.1f} FPS")
        print(f"  Обнаружено меток: {markers_detected}")
        
        # Сохранение данных
        print("\nСохранение данных...")
        if detector.save_now():
            print("✓ Данные сохранены в ./usb_detector_data/")
        
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print_stats(detector, elapsed)
    
    finally:
        # Очистка
        detector.stop()
        device.disconnect()
        print("\n✓ Тест завершен")
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Тест адаптивного детектора с USB')
    parser.add_argument('--duration', type=int, default=60,
                       help='Длительность теста в секундах (по умолчанию: 60)')
    
    args = parser.parse_args()
    
    try:
        success = test_realtime_usb(duration=args.duration)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
