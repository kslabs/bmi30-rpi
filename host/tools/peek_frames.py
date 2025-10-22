import sys, time, numpy as np
sys.path.insert(0, "usb_vendor")
from usb_stream import USBStream

CMD_SET_PROFILE = 0x14
CMD_START_STREAM = 0x20
CMD_STOP_STREAM = 0x21
CMD_SET_FRAME_SAMPLES = 0x17
CMD_SET_FULL_MODE = 0x13  # 1=FULL, 0=DIAG (по договоренности)
CMD_GET_STATUS = 0x30


def try_mode(stream: USBStream, full: bool, wait_s: float = 3.0, max_pairs: int = 5) -> int:
    mode_byte = b"\x01\x00" if full else b"\x00\x00"
    stream.send_cmd(CMD_SET_FULL_MODE, mode_byte)
    time.sleep(0.02)
    stream.send_cmd(CMD_SET_PROFILE, b"\x01")  # профиль 1 = 200 Гц
    time.sleep(0.02)
    stream.send_cmd(CMD_SET_FRAME_SAMPLES, (10).to_bytes(2, "little"))
    time.sleep(0.02)
    stream.send_cmd(CMD_START_STREAM, b"")
    time.sleep(0.05)

    print(f"Режим: {'FULL' if full else 'DIAG'} — ожидание {wait_s}s…")
    deadline = time.time() + wait_s
    pairs = 0
    eq_seq = 0
    plus1_seq = 0
    other_seq = 0
    while time.time() < deadline and pairs < max_pairs:
        pair = stream.get_stereo(timeout=0.5)
        if not pair:
            # периодически дернем STAT для контроля
            try:
                stream.send_cmd(CMD_GET_STATUS, b"")
            except Exception:
                pass
            print("… нет пары …")
            continue
        a, b = pair
        ch0 = np.frombuffer(a.payload, dtype="<i2")
        ch1 = np.frombuffer(b.payload, dtype="<i2")
        # Оценим согласованность seq: равны или B= A+1 (разрешено хостом)
        if b.seq == a.seq:
            seq_note = "EQ"
            eq_seq += 1
        elif b.seq == (a.seq + 1) & 0xFFFFFFFF:
            seq_note = "+1"
            plus1_seq += 1
        else:
            seq_note = f"{b.seq - a.seq}"
            other_seq += 1
        print(
            f"SEQ A={a.seq:#010x} B={b.seq:#010x} ({seq_note}) "
            f"len0={len(ch0)} len1={len(ch1)} f0={a.flags:#04x} f1={b.flags:#04x}"
        )
        print(f"  ch0[:8]={ch0[:8]}\n  ch1[:8]={ch1[:8]}")
        pairs += 1
    try:
        stream.send_cmd(CMD_STOP_STREAM, b"")
    except Exception:
        pass
    time.sleep(0.03)
    if pairs:
        print(
            f"Итого пар: {pairs}. seq EQ: {eq_seq}, +1: {plus1_seq}, проч.: {other_seq}"
        )
    return pairs


def main():
    stream = None
    try:
        stream = USBStream(profile=1, full=True, test_as_data=False, frame_samples=10)
        print("USBStream открыт.")
        total = 0
        total += try_mode(stream, full=True, wait_s=3.0)
        if total == 0:
            print("FULL не дал пар, пробуем DIAG…")
            total += try_mode(stream, full=False, wait_s=3.0)
        if total == 0:
            print("Ни в FULL, ни в DIAG пары не пришли. Проверьте прошивку.")
    except Exception as e:
        print("Ошибка открытия/чтения:", e)
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
