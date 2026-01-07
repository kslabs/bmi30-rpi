#!/usr/bin/env python3
"""
Детальная диагностика USB потока
"""
import sys
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream
import time

print("[DIAG] Создаем USBStream с подробным выводом\n")

try:
    stream = USBStream(profile=1, full=True, fast_mode=True)
    print(f"\n[STREAM] Создан успешно")
    print(f"  port_info: {stream.port_info}")
    print(f"  profile: {stream.profile}")
    print(f"  full: {stream.full}")
    print(f"  frame_samples: {stream.frame_samples}")
    
    print(f"\n[STREAM] Состояние после создания:")
    print(f"  frames: {stream.frames}")
    print(f"  bytes: {stream.bytes}")
    print(f"  test_seen: {stream.test_seen}")
    print(f"  last_stat: {stream.last_stat}")
    print(f"  _working_seen: {stream._working_seen}")
    print(f"  disconnected: {stream.disconnected}")
    print(f"  _running: {stream._running}")
    
    print(f"\n[STREAM] Отправляем START_STREAM...")
    stream.send_cmd(0x20, b'')
    
    print(f"\n[STREAM] Ждём данных 5 секунд...")
    start_t = time.time()
    frames_a = 0
    frames_b = 0
    pairs_got = 0
    errors = 0
    
    while time.time() - start_t < 5:
        try:
            if getattr(stream.asm, 'independent', False):
                # Drain both channels to avoid filling qB artificially
                a = stream.get_frame(0, timeout=0.2)
                if a is not None:
                    frames_a += 1
                b = stream.get_frame(1, timeout=0.2)
                if b is not None:
                    frames_b += 1
            else:
                pair = stream.get_stereo(timeout=0.5)
                if pair:
                    pairs_got += 1
                    a, b = pair
                    frames_a += 1
                    frames_b += 1
                    print(f"  [{int(time.time()-start_t)}s] Пара {pairs_got}: {len(a.payload)} + {len(b.payload)} байт")
        except Exception:
            errors += 1
    
    elapsed = time.time() - start_t
    
    print(f"\n[STREAM] Результаты:")
    if getattr(stream.asm, 'independent', False):
        print(f"  Режим: independent")
        print(f"  Получено A: {frames_a}")
        print(f"  Получено B: {frames_b}")
    else:
        print(f"  Режим: paired")
        print(f"  Получено пар: {pairs_got}")
        print(f"  Получено A: {frames_a}")
        print(f"  Получено B: {frames_b}")
    print(f"  Ошибок: {errors}")
    print(f"  Время: {elapsed:.1f}с")
    
    print(f"\n[STREAM] Финальное состояние:")
    print(f"  frames: {stream.frames}")
    print(f"  bytes: {stream.bytes}")
    print(f"  test_seen: {stream.test_seen}")
    print(f"  _working_seen: {stream._working_seen}")
    print(f"  crc_bad: {stream.crc_bad}")
    print(f"  magic_bad: {stream.magic_bad}")
    print(f"  restart_attempts: {stream.restart_attempts}")
    
    # Смотрим в очереди ASM
    if getattr(stream.asm, 'independent', False):
        qsize_a = stream.asm.qA.qsize() if hasattr(stream.asm, 'qA') else 'unknown'
        qsize_b = stream.asm.qB.qsize() if hasattr(stream.asm, 'qB') else 'unknown'
        print(f"  ASM qA: {qsize_a} (dropA={getattr(stream.asm, 'drop_a', 0)})")
        print(f"  ASM qB: {qsize_b} (dropB={getattr(stream.asm, 'drop_b', 0)})")
    else:
        qsize = stream.asm.q.qsize() if hasattr(stream.asm, 'q') else 'unknown'
        print(f"  ASM queue size: {qsize} (dropPairs={getattr(stream.asm, 'drop_pairs', 0)})")
    
    print(f"\n[STREAM] Закрываем поток...")
    stream.send_cmd(0x21, b'')
    stream.close()
    
except Exception as e:
    import traceback
    print(f"\n[ERROR] Исключение: {e}")
    traceback.print_exc()
