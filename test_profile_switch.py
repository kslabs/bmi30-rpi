#!/usr/bin/env python3
"""
Тест переключения профилей - посмотреть как меняются данные
"""
import sys
import time
sys.path.insert(0, '/home/techaid/Documents/host')

from usb_vendor.usb_stream import USBStream

def test_profiles():
    """Протестировать оба профиля"""
    
    for profile in [1, 2]:
        print(f"\n{'='*60}")
        print(f"ПРОФИЛЬ {profile} ({'200 Hz' if profile == 1 else '300 Hz'})")
        print(f"{'='*60}")
        
        try:
            stream = USBStream(profile=profile, full=True, fast_mode=True)
            stream.send_cmd(0x20, b'')  # START_STREAM
            
            # Ждём 2 секунды данных
            start_t = time.time()
            frame_count = 0
            
            while time.time() - start_t < 2.0:
                try:
                    got = stream.get_stereo(timeout=0.5)
                    if got and got[0] is not None:
                        frame_count += 1
                        a, b, ch0, ch1 = got
                        
                        if frame_count == 1:
                            print(f"✓ Первый кадр получен:")
                            print(f"  Фрейм A: seq={a.seq}, samples={len(ch0)}, payload_len={a.payload_len}, flags=0x{a.flags:02x}")
                            print(f"  Фрейм B: seq={b.seq}, samples={len(ch1)}, payload_len={b.payload_len}, flags=0x{b.flags:02x}")
                            print(f"  ch0: len={len(ch0)}, min={ch0.min()}, max={ch0.max()}, mean={ch0.mean():.1f}")
                            print(f"  ch1: len={len(ch1)}, min={ch1.min()}, max={ch1.max()}, mean={ch1.mean():.1f}")
                        elif frame_count % 10 == 0:
                            print(f"✓ Кадр #{frame_count}")
                except Exception as e:
                    print(f"  Ошибка получения данных: {e}")
                    break
            
            print(f"✓ Всего получено кадров за 2сек: {frame_count}")
            
        except Exception as e:
            print(f"✗ Ошибка профиля {profile}: {e}")
        finally:
            try:
                stream.send_cmd(0x21, b'')  # STOP_STREAM
                stream.close()
            except:
                pass

if __name__ == '__main__':
    test_profiles()
