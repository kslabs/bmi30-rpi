#!/usr/bin/env python3
"""
Вывести 10-й буфер сэмплов ADC1 в шестнадцатеричном виде
"""

import sys
sys.path.insert(0, 'host/usb_vendor')

from usb_stream import USBStream
import time

def main():
    print("Получение буфера ADC1...")
    
    stream = USBStream(profile=2, full=True, fast_mode=True)
    stream.send_cmd(0x20, b'')
    
    time.sleep(0.5)
    
    frame_count = 0
    adc1_frames = []
    
    # Собираем пары до тех пор, пока не получим достаточно фреймов ADC1
    start = time.time()
    while time.time() - start < 5.0 and len(adc1_frames) < 15:
        try:
            pair = stream.asm.q.get(timeout=0.5)
            if pair:
                frameA, frameB = pair
                
                # frameB это ADC1
                adc1_frames.append(frameB)
                frame_count += 1
                
                if frame_count == 10:
                    print(f"\n✓ Получен 10-й буфер ADC1")
                    print(f"  Seq: {frameB.seq}")
                    print(f"  Samples: {frameB.samples}")
                    print(f"  Размер payload: {len(frameB.payload)} байт")
                    
                    print(f"\n{'='*80}")
                    print(f"БУФЕР ADC1 №{10} в HEX:")
                    print(f"{'='*80}\n")
                    
                    # Выводим в hex формате по 16 байт в строке
                    for i in range(0, len(frameB.payload), 16):
                        chunk = frameB.payload[i:i+16]
                        hex_str = ' '.join(f'{b:02x}' for b in chunk)
                        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                        print(f"{i:04x}: {hex_str:<48} | {ascii_str}")
                    
                    print(f"\n{'='*80}")
                    print(f"Итого: {len(frameB.payload)} байт")
                    print(f"Это {len(frameB.payload)//2} int16 сэмплов")
                    
                    break
        except:
            pass
    
    stream.close()

if __name__ == '__main__':
    main()
