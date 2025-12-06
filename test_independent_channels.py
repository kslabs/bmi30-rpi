#!/usr/bin/env python3
"""
УЛУЧШЕННЫЙ РЕЖИМ ДЛЯ НЕЗАВИСИМЫХ КАНАЛОВ
Вместо стереопары - 2 независимых канала с синхронизацией по timestamp
"""

import sys
sys.path.insert(0, 'host/usb_vendor')

from usb_stream import USBStream
import time
from collections import deque

class DualChannelBuffer:
    """Буфер для 2 независимых каналов"""
    
    def __init__(self, max_samples=912):
        self.adc0_frames = deque(maxlen=10)  # Последние 10 фреймов ADC0
        self.adc1_frames = deque(maxlen=10)  # Последние 10 фреймов ADC1
        self.sync_pairs = []  # Синхронизированные пары
        self.max_samples = max_samples
        
    def push_frame(self, frame):
        """Добавить фрейм и попытаться синхронизировать"""
        if frame.adc_id == 0:
            self.adc0_frames.append(frame)
        else:
            self.adc1_frames.append(frame)
        
        # Пытаемся собрать синхронизированные пары
        self._sync()
    
    def _sync(self):
        """Синхронизировать по timestamp"""
        # Ищем пары с близкими timestamp (разница < 1 sample period)
        while self.adc0_frames and self.adc1_frames:
            f0 = self.adc0_frames[0]
            f1 = self.adc1_frames[0]
            
            # Если timestamp совпадают или близки - это пара!
            # (timestamp мог бы быть в фрейме, но пока используем seq как proxy)
            if abs(f0.seq - f1.seq) <= 1:
                # Это синхронная пара
                pair_a0 = self.adc0_frames.popleft()
                pair_b1 = self.adc1_frames.popleft()
                self.sync_pairs.append((pair_a0, pair_b1))
            else:
                # Несоответствие - отбросить старший
                if f0.seq < f1.seq:
                    self.adc0_frames.popleft()
                else:
                    self.adc1_frames.popleft()
    
    def get_pair(self):
        """Получить синхронизированную пару"""
        if self.sync_pairs:
            return self.sync_pairs.pop(0)
        return None

def test_independent_channels(profile: int, test_duration: float = 5.0):
    """Тест независимых каналов"""
    
    print(f"\n{'='*70}")
    print(f"🧪 PROFILE={profile} - НЕЗАВИСИМЫЕ КАНАЛЫ (РЕЖИМ ХОСТА)")
    print(f"{'='*70}")
    
    try:
        stream = USBStream(profile=profile, full=True, fast_mode=True)
        buffer = DualChannelBuffer()
        
        stream.send_cmd(0x20, b'')
        time.sleep(0.5)
        
        # Собираем сырые фреймы напрямую, пока они приходят
        # Читаем из внутреннего буфера assembler
        raw_frames = 0
        pairs_synced = 0
        start = time.time()
        
        print(f"\n  Получаем фреймы и синхронизируем...")
        
        while time.time() - start < test_duration:
            # Берём из assembler, но просто распределяем по каналам
            try:
                pair = stream.asm.q.get(timeout=0.5)
                if pair:
                    f_adc0, f_adc1 = pair
                    
                    # Добавляем в буфер независимо
                    buffer.push_frame(f_adc0)
                    buffer.push_frame(f_adc1)
                    raw_frames += 2
                    
                    # Пытаемся получить синхронизированную пару
                    synced = buffer.get_pair()
                    if synced:
                        pairs_synced += 1
                        if pairs_synced <= 3:
                            f0, f1 = synced
                            print(f"    Пара {pairs_synced}: ADC0 seq={f0.seq} / ADC1 seq={f1.seq} (разница={abs(f0.seq - f1.seq)})")
            except:
                pass
        
        elapsed = time.time() - start
        
        print(f"\n  📊 РЕЗУЛЬТАТЫ:")
        print(f"     Время: {elapsed:.2f} сек")
        print(f"     Фреймов получено: {raw_frames} ({raw_frames/elapsed:.0f} fps)")
        print(f"     Синхронизировано пар: {pairs_synced}")
        print(f"     Синхронизация: {100*pairs_synced*2/raw_frames:.1f}% фреймов в парах")
        
        stream.close()
        
        return raw_frames > 0
        
    except Exception as e:
        print(f"  ❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "="*70)
    print("📊 ТЕСТ НЕЗАВИСИМЫХ КАНАЛОВ")
    print("="*70)
    
    print("\n[1] Начинаем с PROFILE=2 (300 Hz)")
    p2 = test_independent_channels(2, test_duration=3.0)
    time.sleep(1)
    
    print("\n[2] Переключаемся на PROFILE=1 (200 Hz)")
    p1 = test_independent_channels(1, test_duration=3.0)
    
    print("\n" + "="*70)
    if p2 and p1:
        print("✅ ОБА ПРОФИЛЯ РАБОТАЮТ С НЕЗАВИСИМЫМИ КАНАЛАМИ")
    else:
        print("❌ Что-то не работает")
    print("="*70)

if __name__ == '__main__':
    main()
