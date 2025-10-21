#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import time
import argparse
from datetime import datetime
import serial  # type: ignore[import-not-found]

import USB_io
import USB_proto
import USB_frame
import USB_plot
import json


def to_hex(b: bytes, max_len: int = 64) -> str:
    if not b:
        return ""
    view = b[:max_len]
    s = ' '.join(f"{x:02X}" for x in view)
    if len(b) > max_len:
        s += f" …(+{len(b)-max_len})"
    return s


def main():
    parser = argparse.ArgumentParser(description='USB CDC приёмник кадров (модульная версия)')
    parser.add_argument('--port', default='auto')
    parser.add_argument('--baudrate', type=int, default=None, help='Скорость CDC (например 921600, 1500000, 2000000)')
    parser.add_argument('--warmup-frames', type=int, default=2)
    parser.add_argument('--warmup-timeout-sec', type=float, default=3.0)
    parser.add_argument('--passive-stream', action='store_true', default=True)
    parser.add_argument('--quiet', action='store_true', default=False)
    parser.add_argument('--frame-timeout-sec', type=float, default=2.0, help='Таймаут на чтение одного кадра (сек)')
    parser.add_argument('--crc-none', action='store_true', default=False, help='Не проверять CRC (для отладки/плота)')
    parser.add_argument("--sniff", action="store_true", help="Быстрый тест: за 1с проверить байты на всех CDC-портах и выйти")
    parser.add_argument("--dump-raw", type=int, default=0, help="Считать N байт сырых данных с выбранного порта и выйти")
    parser.add_argument("--probe-frame", type=int, default=0, help="Выровнять по MAGIC и вывести N байт после заголовка для диагностики")
    parser.add_argument("--plot", action="store_true", help="Запустить живую осциллограмму кадра")
    parser.add_argument("--plot-fast", action="store_true", help="Быстрый плот на PyQtGraph (~20 FPS)")
    parser.add_argument("--plot-fast-frames", action="store_true", help="Быстрый плот на PyQtGraph, синхр. по кадрам")
    parser.add_argument("--data-samples-limit", type=int, default=None, help="Лимит выборок на канал из кадра для плота (например 4 для тестового режима); None = без ограничения")
    # Настройки UI/рендера
    parser.add_argument("--ui-target-hz", type=int, default=20, help="Целевая частота таймера UI (Гц)")
    parser.add_argument("--render-max-hz", type=float, default=20.0, help="Макс. частота перерисовки (Гц), доп. троттлинг")
    parser.add_argument("--render-decimate", type=int, default=0, help="Децимация кадров отрисовки: рисовать каждый N-й кадр (0/1 = без децимации)")
    parser.add_argument("--len-min", type=int, default=60, help="Минимальная длина окна (семплы/канал) для ползунка")
    parser.add_argument("--len-max", type=int, default=600, help="Максимальная длина окна (семплы/канал) для ползунка")
    parser.add_argument("--win0", type=str, default="", help="Окно 0: start,len (например 1024,512)")
    parser.add_argument("--win1", type=str, default="", help="Окно 1: start,len")
    parser.add_argument("--block-hz", type=int, default=None, help="Частота кадров (Hz) для устройства")
    parser.add_argument("--block-rate-max", action="store_true", default=False, help="Установить максимальную частоту блоков (CMD_SET_BLOCK_RATE=0xFFFF)")
    parser.add_argument("--start-stream", action="store_true", default=False, help="Послать CMD_START_STREAM (0x20) после настройки устройства")
    parser.add_argument("--stop-stream", action="store_true", default=False, help="Послать CMD_STOP_STREAM (0x21) перед настройкой устройства")
    parser.add_argument("--apply-device-cfg", action="store_true", default=False, help="Отправлять SET_WINDOWS/SET_BLOCK_HZ на устройство при запуске")
    parser.add_argument("--config", type=str, default="USB_config.json", help="Путь к файлу конфигурации по умолчанию")
    parser.add_argument("--dump-one-frame", action="store_true", help="Считать и вывести один полный кадр (RAW)")
    parser.add_argument("--dump-frame-raw40", action="store_true", help="Считать 40 байт от начала заголовка (без MAGIC) и вывести hex")
    parser.add_argument("--send-windows", type=str, default="", help="Отправить CMD_SET_WINDOWS: start0,len0,start1,len1 и выйти (пример: 0,4,0,0)")
    # Вывод данных в терминал
    parser.add_argument("--print-csv", action="store_true", help="Печатать данные кадра в CSV (seq,index,<ch0>..<chN>)")
    parser.add_argument("--csv-header", action="store_true", help="Печатать заголовок CSV один раз")
    parser.add_argument("--csv-limit", type=int, default=0, help="Лимит строк CSV на кадр (0 = весь кадр)")
    parser.add_argument("--print-head-i16", type=int, default=0, help="Печатать первые N значений int16 на канал для кадра")
    parser.add_argument("--print-head-hex", type=int, default=0, help="Печатать первые N байт payload в hex для кадра")
    parser.add_argument("--max-frames", type=int, default=0, help="Остановиться после N кадров (0 = без ограничений)")
    parser.add_argument("--print-raw-loop", action="store_true", help="Непрерывно печатать сырые байты из порта (hex)")
    parser.add_argument("--line-bytes", type=int, default=32, help="Сколько байт показывать в строке при raw-loop")
    parser.add_argument("--sync-first", action="store_true", help="Перед raw-loop выровняться по MAGIC (5A A5)")
    # Высокоскоростной слив без парсинга (для теста, чтобы не тормозить устройство)
    parser.add_argument("--drain-only", action="store_true", help="Быстро читать и отбрасывать байты (без парсинга), печатать скорость")
    parser.add_argument("--drain-seconds", type=float, default=0.0, help="Сколько секунд сливать (0 = бесконечно)")
    parser.add_argument("--count-magic", action="store_true", help="Считать последовательности 5A A5 в потоке (прибл. кол-во кадров)")
    parser.add_argument("--test-fake-seq", action="store_true", help="Тест: отправить START и проанализировать первые 3 кадра (test + 2 fake) и первый статус (32B STAT v2)")
    parser.add_argument("--vendor-bulk", action="store_true", help="Читать поток через Vendor Bulk (EP 0x83) вместо CDC")
    args = parser.parse_args()

    # Загрузка конфигурации (по умолчанию: USB_config.json). CLI-параметры имеют приоритет.
    cfg = {}
    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    def cfg_get(path, default=None):
        cur = cfg
        try:
            for k in path.split('.'):
                if k:
                    cur = cur[k]
            return cur
        except Exception:
            return default

    def cfg_has(path: str) -> bool:
        """Проверить, существует ли ключ в конфиге (без подстановки умолчаний)."""
        cur = cfg
        try:
            for k in path.split('.'):            
                if not isinstance(cur, dict) or k not in cur:
                    return False
                cur = cur[k]
            return True
        except Exception:
            return False

    # Если не указаны ключи CLI, подставим из конфигурации
    if args.port == 'auto':
        args.port = cfg_get('port', 'auto')
    # Режим работы: если не выбран явный режим и нет флагов печати — можно взять из конфигурации
    if not (
        args.sniff or args.dump_raw or args.probe_frame or args.plot or args.plot_fast or args.plot_fast_frames
        or (getattr(args, 'print_csv', False)) or (getattr(args, 'print_head_i16', 0) and args.print_head_i16 > 0)
        or (getattr(args, 'print_head_hex', 0) and args.print_head_hex > 0)
    ):
        # Режим работы из конфигурации
        mode = cfg_get('mode', '')
        if mode == 'plot':
            args.plot = True
        elif mode == 'plot-fast':
            args.plot_fast = True
        elif mode == 'plot-fast-frames':
            args.plot_fast_frames = True
    # Если заданы флаги печати — выключаем любые plot-режимы (приоритет печати)
    if (getattr(args, 'print_csv', False)) or (getattr(args, 'print_head_i16', 0) and args.print_head_i16 > 0) or (getattr(args, 'print_head_hex', 0) and args.print_head_hex > 0):
        args.plot = False
        args.plot_fast = False
        args.plot_fast_frames = False
    if args.warmup_frames == 2:
        args.warmup_frames = int(cfg_get('warmup_frames', args.warmup_frames))
    if args.warmup_timeout_sec == 3.0:
        args.warmup_timeout_sec = float(cfg_get('warmup_timeout_sec', args.warmup_timeout_sec))
    # Применение команд к устройству (окна/частота) — только если явно разрешено
    apply_cfg = bool(args.apply_device_cfg or cfg_get('plot.apply_device_cfg', False))
    # Если запускаем интерактивный высокоскоростной plot-fast-frames и не задано явных ограничений — используем максимум
    try:
        if apply_cfg:
            want_fast = bool(args.plot_fast_frames or (cfg_get('mode', '') == 'plot-fast-frames'))
            if want_fast:
                # Только если пользователь не задал явно block_hz/--block-rate-max
                if (args.block_hz is None) and (not args.block_rate_max):
                    # Игнорируем block_hz из конфига и включаем максимум
                    args.block_rate_max = True
    except Exception:
        pass
    if apply_cfg:
        # Если явно запрошен максимум, не подхватываем ограничение из конфига
        if args.block_hz is None and not args.block_rate_max:
            bhz = cfg_get('plot.block_hz', None)
            if bhz is not None:
                args.block_hz = int(bhz)
        if not args.block_rate_max:
            try:
                args.block_rate_max = bool(cfg_get('plot.block_rate_max', False))
            except Exception:
                pass
        if not args.start_stream:
            try:
                args.start_stream = bool(cfg_get('plot.start_stream', False))
            except Exception:
                pass
        if not args.stop_stream:
            try:
                args.stop_stream = bool(cfg_get('plot.stop_stream', False))
            except Exception:
                pass
        if not args.win0:
            w0 = cfg_get('plot.win0', None)
            if isinstance(w0, list) and len(w0) == 2:
                args.win0 = f"{int(w0[0])},{int(w0[1])}"
        if not args.win1:
            w1 = cfg_get('plot.win1', None)
            if isinstance(w1, list) and len(w1) == 2:
                args.win1 = f"{int(w1[0])},{int(w1[1])}"
    if not hasattr(args, 'frame_timeout_sec') or args.frame_timeout_sec == 2.0:
        try:
            args.frame_timeout_sec = float(cfg_get('plot.frame_timeout_sec', args.frame_timeout_sec))
        except Exception:
            pass
    # Эффективный флаг CRC: по умолчанию выключаем CRC для высокой скорости,
    # если явно не задано иное в конфиге/CLI
    crc_none_eff = True
    try:
        # CLI имеет приоритет, если пользователь явно задал --crc-none
        if getattr(args, 'crc_none', False):
            crc_none_eff = True
        # Если в конфиге есть явный ключ, используем его значение
        elif cfg_has('plot.crc_none'):
            crc_none_eff = bool(cfg_get('plot.crc_none', True))
    except Exception:
        pass
    # Настройки UI троттлинга из конфига (если заданы)
    try:
        v = cfg_get('plot.ui_target_hz', None)
        if v is not None:
            args.ui_target_hz = int(v)
    except Exception:
        pass
    try:
        v = cfg_get('plot.render_max_hz', None)
        if v is not None:
            args.render_max_hz = float(v)
    except Exception:
        pass
    try:
        v = cfg_get('plot.render_decimate', None)
        if v is not None:
            args.render_decimate = int(v)
    except Exception:
        pass
    # Лимит выборок на канал (для plot-fast-frames)
    if getattr(args, 'data_samples_limit', None) is None:
        try:
            # поддержим оба ключа в конфиге на всякий случай
            v = cfg_get('plot.data_samples_limit_per_ch', None)
            if v is None:
                v = cfg_get('plot.data_samples_limit', None)
            if v is not None:
                args.data_samples_limit = int(v)
        except Exception:
            pass

    if args.sniff:
        ports = USB_io.list_cdc_ports()
        if not ports:
            print("[sniff] Порты не найдены (/dev/ttyACM* или /dev/ttyUSB*)")
            return 1
        print(f"[sniff] Найдены порты: {', '.join(ports)}")
        any_bytes = False
        for p in ports:
            info = USB_io.sniff_port_bytes(p, seconds=1.0, sample_limit=64)
            hex_sample = to_hex(info['sample'])
            print(f"[sniff] {p}: total={info['total']} bytes; sample: {hex_sample if hex_sample else '<none>'}")
            any_bytes = any_bytes or (info['total'] > 0)
        return 0 if any_bytes else 2

    # Специальный режим тестирования новой прошивки (fake pair)
    if getattr(args, 'test_fake_seq', False):
        if args.vendor_bulk:
            from USB_vnd import open_vendor
            ser = open_vendor()
            port = 'usb:vendor-bulk'
        else:
            port = USB_io.wait_for_cdc_port(args.port)
            ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
        try:
            print(f"[fake-seq] Порт: {port}")
            # Отправим START (ACK ожидаем; если нет ACK - продолжаем, чтобы поймать поток)
            try:
                rsp = USB_proto.start_stream(ser)
                print(f"[fake-seq] CMD_START rsp={rsp}")
            except Exception as e:
                print(f"[fake-seq] START err (игнорируем): {e}")

            frames = []
            t_start = time.time()
            deadline = t_start + 6.0  # немного больше времени
            while len(frames) < 3 and time.time() < deadline:
                try:
                    fr = USB_frame.read_frame(
                        ser,
                        crc_strategy='none',
                        sync_wait_s=1.0,
                        io_timeout_s=0.5,
                        frame_timeout_s=1.0,
                        max_retries=1,
                        fast_drop=True,
                    )
                    raw_len = len(fr.get('raw', b''))
                    frames.append((fr, raw_len))
                    print(f"[fake-seq] frame#{len(frames)} seq={fr['seq']} raw_len={raw_len} total={fr['total_samples']} ch={fr['channels']} fmt=0x{fr['fmt']:04X} crc={fr['crc_variant']}")
                except TimeoutError:
                    continue
                except Exception as e:
                    print(f"[fake-seq] read_frame err: {e}")
                    # продолжаем попытки до дедлайна
            if len(frames) < 2:
                print(f"[fake-seq] WARNING: получено только {len(frames)} кадр(ов) за {time.time()-t_start:.2f}s")

            # Эвристика классификации
            def classify(idx, fr_raw_len, fr):
                # Новая прошивка: диагностические кадры fmt&0x0080, ch=2, total=128, raw_len≈530 (2+16+512)
                if (fr['fmt'] & 0x0080) and fr.get('channels') == 2 and fr.get('total_samples') == 128:
                    return 'DIAG128'
                # Старый сценарий (если вдруг): маленький тестовый кадр
                if fr_raw_len < 128 and idx == 0:
                    return 'TEST'
                return 'UNEXPECTED'

            for i,(fr, rl) in enumerate(frames):
                tag = classify(i, rl, fr)
                raw_head = to_hex(fr['raw'][:32], max_len=32)
                print(f"[fake-seq] #{i+1} tag={tag} seq={fr['seq']} raw_len={rl} hdr16={to_hex(fr['raw'][2:18], max_len=32)} head32={raw_head}")

            # Попытка считывания первого статусного блока (32B STAT v2) после фейков
            status_bytes = b''
            status_block = b''
            t_stat_deadline = time.time() + 2.0
            while time.time() < t_stat_deadline and not status_block:
                try:
                    chunk = ser.read(64)
                except Exception:
                    chunk = b''
                if not chunk:
                    time.sleep(0.02)
                    continue
                status_bytes += chunk
                # ищем 'STAT'
                pos = status_bytes.find(b'STAT')
                if pos >= 0 and len(status_bytes) >= pos + 32:
                    status_block = status_bytes[pos:pos+32]
                    break
                # ограничим буфер чтобы не раздувался
                if len(status_bytes) > 256:
                    status_bytes = status_bytes[-256:]
            status_found = False
            if status_block:
                # Попытка парсинга предполагаемой структуры
                sb = status_block
                parsed = {}
                try:
                    import struct as _st
                    if sb.startswith(b'STAT') and len(sb) >= 24:
                        version = sb[4]
                        flags = sb[5]
                        channels = sb[6]
                        # sb[7] reserved
                        last_sent_seq = int.from_bytes(sb[8:10], 'little')
                        produced_seq = int.from_bytes(sb[10:12], 'little')
                        sent_ch0 = int.from_bytes(sb[12:14], 'little')
                        sent_ch1 = int.from_bytes(sb[14:16], 'little')
                        uptime_ms = int.from_bytes(sb[16:20], 'little')
                        errors = int.from_bytes(sb[20:22], 'little')
                        debug0 = int.from_bytes(sb[22:24], 'little') if len(sb) >= 24 else 0
                        debug1 = int.from_bytes(sb[24:26], 'little') if len(sb) >= 26 else 0
                        parsed = {
                            'version': version,
                            'flags': flags,
                            'channels': channels,
                            'last_sent_seq': last_sent_seq,
                            'produced_seq': produced_seq,
                            'sent_ch0': sent_ch0,
                            'sent_ch1': sent_ch1,
                            'uptime_ms': uptime_ms,
                            'errors': errors,
                            'debug0': debug0,
                            'debug1': debug1,
                        }
                except Exception:
                    parsed = {}
                print(f"[fake-seq] STATUS32 len=32 raw={to_hex(status_block, max_len=64)} parsed={parsed}")
                if status_block.startswith(b'STAT'):
                    status_found = True
            else:
                print(f"[fake-seq] STATUS32 не обнаружен (bytes_collected={len(status_bytes)})")

            # Сводка
            if frames:
                lens = [rl for _,rl in frames]
                print(f"[fake-seq] summary lens={lens}")
            # Простая валидация ожидаемого паттерна
            ok = False
            # Новое правило: достаточно 2 диагностических кадра DIAG128 с одинаковым seq и STATUS32
            if len(frames) >= 2:
                tags = [classify(i, rl, fr) for i,(fr,rl) in enumerate(frames[:2])]
                diag_ok = all(t == 'DIAG128' for t in tags)
                same_seq = (frames[0][0]['seq'] == frames[1][0]['seq'])
                ok = diag_ok and same_seq and status_found
            print(f"[fake-seq] pattern_ok={ok}")
            return 0 if ok else 3
        finally:
            try:
                ser.close()
            except Exception:
                pass

    if args.dump_raw and args.dump_raw > 0:
        port = USB_io.wait_for_cdc_port(args.port)
        data = USB_io.capture_bytes(port, count=args.dump_raw, seconds=2.0)
        print(f"[dump] Порт: {port}, получено {len(data)} байт")
        print(f"[dump] head: {to_hex(data, max_len=96)}")
        # Поиск MAGIC/ALT_MAGIC
        magic = b"\x5A\xA5"; alt = b"\xA5\x5A"
        mi = data.find(magic)
        ai = data.find(alt)
        print(f"[dump] Поиск 5A A5: {'найден на смещении '+str(mi) if mi>=0 else 'не найден'}")
        print(f"[dump] Поиск A5 5A: {'найден на смещении '+str(ai) if ai>=0 else 'не найден'}")
        return 0

    if args.print_raw_loop:
        port = USB_io.wait_for_cdc_port(args.port)
        ser = USB_io.open_serial(port, timeout=0.1, baudrate=args.baudrate)
        try:
            if args.sync_first:
                try:
                    USB_io.sync_to_magic(ser, max_wait_s=3.0)
                    print("[raw-loop] Синхронизация по MAGIC выполнена")
                except Exception as e:
                    print(f"[raw-loop] Sync warn: {e}")
            print(f"[raw-loop] Чтение из {port}. Ctrl+C для остановки.")
            ln = int(max(1, args.line_bytes))
            buf = b''
            while True:
                try:
                    chunk = ser.read(512)
                    if chunk:
                        buf += chunk
                        while len(buf) >= ln:
                            line = buf[:ln]
                            buf = buf[ln:]
                            print(' '.join(f"{x:02X}" for x in line))
                    else:
                        time.sleep(0.02)
                except KeyboardInterrupt:
                    break
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    if args.drain_only:
        if args.vendor_bulk:
            from USB_vnd import open_vendor
            ser = open_vendor()
            port = 'usb:vendor-bulk'
        else:
            port = USB_io.wait_for_cdc_port(args.port)
            ser = USB_io.open_serial(port, timeout=0.0, baudrate=args.baudrate)
        try:
            print(f"[drain] Начат слив из {port} (timeout=0). Ctrl+C для остановки.")
            t0 = time.time(); last = t0; total = 0; last_total = 0
            magic = b"\x5A\xA5"; prev = b''; magic_total = 0; magic_last = 0
            limit_t = (t0 + args.drain_seconds) if (args.drain_seconds and args.drain_seconds > 0) else None
            while True:
                if limit_t and time.time() >= limit_t:
                    break
                try:
                    b = ser.read(65536)
                except Exception:
                    b = b''
                if b:
                    total += len(b)
                    if args.count_magic:
                        chunk = prev + b
                        # Поскользим по окнам длиной 2, считаем совпадения 5A A5
                        if len(chunk) >= 2:
                            mv = memoryview(chunk)
                            for i in range(len(chunk)-1):
                                if mv[i] == 0x5A and mv[i+1] == 0xA5:
                                    magic_total += 1
                        prev = chunk[-1:]
                    else:
                        prev = b[-1:]
                now = time.time()
                if now - last >= 1.0:
                    dt = now - last; bytes_sec = (total - last_total) / max(1e-6, dt)
                    msg = f"[drain] {bytes_sec/1000.0:.1f} kB/s"
                    if args.count_magic:
                        fps = (magic_total - magic_last) / max(1e-6, dt)
                        msg += f", ~{fps:.1f} fps (MAGIC)"
                    print(msg)
                    last = now; last_total = total; magic_last = magic_total
                # избегаем горячего цикла, если данных нет
                if not b:
                    time.sleep(0.0005)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    if args.send_windows:
        if args.vendor_bulk:
            from USB_vnd import open_vendor
            ser = open_vendor()
            port = 'usb:vendor-bulk'
        else:
            port = USB_io.wait_for_cdc_port(args.port)
            ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
        try:
            try:
                a,b,c,d = (int(x.strip()) for x in args.send_windows.split(','))
            except Exception:
                print(f"[send-windows] неверный формат: {args.send_windows}")
                return 2
            import numpy as _np
            payload = _np.asarray([a,b,c,d], dtype=_np.uint16).tobytes()
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_WINDOWS, payload=payload)
            print(f"[send-windows] CMD_SET_WINDOWS start0={a} len0={b} start1={c} len1={d} отправлено")
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    if args.dump_frame_raw40:
        port = USB_io.wait_for_cdc_port(args.port)
        ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
        try:
            USB_io.sync_to_magic(ser, max_wait_s=2.0)
            hdr = USB_io.read_exact(ser, 16, 'header', timeout_s=1.0)
            rest = USB_io.read_exact(ser, 24, 'rest40', timeout_s=1.0)  # 4 (table) + 16 (payload) + 4 (crc)
            raw40 = hdr + rest
            print(f"[raw40] {to_hex(raw40, max_len=200)}")
            # Выведем первые 16 байт payload
            payload_head = rest[4:4+16]
            print(f"[raw40] payload[0:16]: {to_hex(payload_head, max_len=64)}")
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    if args.dump_one_frame:
        port = USB_io.wait_for_cdc_port(args.port)
        ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
        try:
            print(f"[dump-one] Порт: {port}")
            frame = USB_frame.read_frame(ser, crc_strategy='none', sync_wait_s=2.0, io_timeout_s=1.0, frame_timeout_s=3.0)
            raw = frame.get('raw', b'')
            print(f"[dump-one] raw_len={len(raw)} bytes: {to_hex(raw, max_len=256)}")
            payload = frame.get('data')
            try:
                # покажем первые 16 байт payload в hex и как int16
                pay_bytes = raw[-(len(payload)*payload.shape[1]*2 + 4):-4] if hasattr(payload, 'shape') else b''
            except Exception:
                pay_bytes = b''
            if pay_bytes:
                print(f"[dump-one] payload head: {to_hex(pay_bytes, max_len=32)}")
                try:
                    import numpy as _np
                    words = _np.frombuffer(pay_bytes[:16], dtype='<i2')
                    print("[dump-one] first 8 int16:", ' '.join(f"0x{int(x)&0xFFFF:04X}" for x in words))
                except Exception:
                    pass
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    if args.plot or args.plot_fast or args.plot_fast_frames:
        if args.vendor_bulk:
            from USB_vnd import open_vendor
            ser = open_vendor()
            port = 'usb:vendor-bulk'
        else:
            port = USB_io.wait_for_cdc_port(args.port)
        def parse_win(s: str):
            if not s:
                return None
            try:
                a, b = s.split(',')
                return (int(a), int(b))
            except Exception:
                print(f"[plot] неверный формат окна: {s}")
                return None
        # Передавать команды устройству только если разрешено
        w0 = parse_win(args.win0) if apply_cfg else None
        w1 = parse_win(args.win1) if apply_cfg else None
        
        # Для plot_fast_frames принудительно устанавливаем окна на 300 семплов
        if args.plot_fast_frames:
            w0 = (0, 300)
            w1 = (0, 300)
        
        if args.plot_fast_frames:
            import USB_plot_fast
            rc = USB_plot_fast.run_plot_fast_frames(
                port,
                window_samples=1000,
                target_hz=int(getattr(args, 'ui_target_hz', 30) or 30),  # Умеренная частота 30 fps
                crc_none=bool(crc_none_eff),
                frame_timeout_sec=float(getattr(args, 'frame_timeout_sec', 2.0)),
                win0=w0,
                win1=w1,
                block_hz=(args.block_hz if apply_cfg else None),
                frames_to_display=1,
                align_to_frame_start=True,
                # без лимита по умолчанию; ограничение применяется только если задано явно
                data_samples_limit_per_ch=getattr(args, 'data_samples_limit', None),
                baudrate=args.baudrate,
                block_rate_max=(args.block_rate_max if apply_cfg or args.block_rate_max else False),
                start_stream=(args.start_stream if apply_cfg or args.start_stream else False),
                stop_stream=(args.stop_stream if apply_cfg or args.stop_stream else False),
                render_max_hz=float(getattr(args, 'render_max_hz', 20.0) or 0.0),
                render_decimate_frames=int(getattr(args, 'render_decimate', 0) or 0),
                slider_min=30,
                slider_max=300,
                ser=(ser if args.vendor_bulk else None),
            )
        elif args.plot_fast:
            import USB_plot_fast
            rc = USB_plot_fast.run_plot_fast(
                port,
                raw_samples=1000,
                target_hz=20,
                baudrate=args.baudrate,
            )
        else:
            # В режиме plot предпочтём отключить CRC, чтобы график не прерывался от несоответствий
            # Передаём настройки устойчивости
            rc = USB_plot.run_plot(
                port,
                win0=w0,
                win1=w1,
                block_hz=args.block_hz,
                quiet=args.quiet,
                crc_none=bool(crc_none_eff),
                frame_timeout_sec=float(getattr(args, 'frame_timeout_sec', 2.0)),
                warmup_timeout_sec=float(getattr(args, 'warmup_timeout_sec', 0.0)) or None,
            )
        return rc

    # Режим: максимально быстрый приём кадров без отрисовки (sink)
    if not (args.plot or args.plot_fast or args.plot_fast_frames) and args.max_frames == 0 and not (args.print_csv or args.print_head_i16 or args.print_head_hex):
        port = USB_io.wait_for_cdc_port(args.port)
        ser = USB_io.open_serial(port, timeout=0.0, baudrate=args.baudrate)
        try:
            print(f"[sink] Приём кадров без обработки из {port}. Ctrl+C для остановки.")
            shown = 0; t0 = time.time(); last = t0; total_bytes = 0; last_bytes = 0; last_seq = None; lost = 0
            while True:
                try:
                    frame = USB_frame.read_frame(
                        ser,
                        crc_strategy=('none' if crc_none_eff else 'auto'),
                        sync_wait_s=0.5,
                        frame_timeout_s=0.5,
                        fast_drop=True,
                        max_retries=1,
                    )
                except TimeoutError:
                    continue
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[sink] err: {e}")
                    continue
                shown += 1
                data = frame.get('data')
                ch = int(frame.get('channels', data.shape[1] if getattr(data, 'ndim', 1) == 2 else 1))
                n = int(data.shape[0]) if getattr(data, 'ndim', 1) == 2 else 0
                total_bytes += n * ch * 2
                seq = int(frame.get('seq', 0))
                if last_seq is not None:
                    gap = (seq - last_seq) & 0xFFFF
                    if gap != 1 and gap > 0:
                        lost += (gap - 1)
                last_seq = seq
                now = time.time()
                if now - last >= 1.0:
                    dur = now - last
                    fps = shown / max(1e-6, (now - t0))
                    kBps = (total_bytes - last_bytes) / max(1e-6, dur) / 1000.0
                    print(f"[sink] {fps:.1f} fps, {kBps:.1f} kB/s, lost={lost}")
                    last = now; last_bytes = total_bytes; shown = 0
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    

    if args.probe_frame and args.probe_frame > 0:
        port = USB_io.wait_for_cdc_port(args.port)
        ser = USB_io.open_serial(port, timeout=0.2, baudrate=args.baudrate)
        try:
            print(f"[probe] Порт: {port}")
            USB_io.sync_to_magic(ser, max_wait_s=2.0)
            hdr = USB_io.read_exact(ser, 16, 'header')
            print(f"[probe] hdr16: {to_hex(hdr, max_len=64)}")
            # Вариант A
            import struct
            ver_A = struct.unpack_from('<H', hdr, 0)[0]
            ts_A = struct.unpack_from('<H', hdr, 2)[0]
            msec_BE = struct.unpack_from('>I', hdr, 4)[0]
            msec_LE = struct.unpack_from('<I', hdr, 4)[0]
            seq_A = struct.unpack_from('<H', hdr, 8)[0]
            fmt_A = struct.unpack_from('<H', hdr, 10)[0]
            ch_A = struct.unpack_from('<H', hdr, 12)[0]
            tbl_A = struct.unpack_from('<H', hdr, 14)[0]
            # Вариант B (swap total<->table)
            ver_B = ver_A
            tbl_B = ts_A
            ts_B = tbl_A
            ch_B = ch_A
            seq_B = seq_A
            fmt_B = fmt_A
            print(f"[probe] A: ver={ver_A} total={ts_A} msecBE={msec_BE} msecLE={msec_LE} seq={seq_A} fmt={fmt_A} ch={ch_A} table_bytes={tbl_A}")
            print(f"[probe] B: ver={ver_B} total={ts_B} msecBE={msec_BE} msecLE={msec_LE} seq={seq_B} fmt={fmt_B} ch={ch_B} table_bytes={tbl_B}")
            # захват N байт после заголовка
            n = args.probe_frame
            body = USB_io.read_exact(ser, n, f'probe[{n}]')
            print(f"[probe] after_hdr[{n}] head: {to_hex(body, max_len=min(96, n))}")
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return 0

    session = 0
    try:
        while True:
            session += 1
            print(f'===== Сессия подключения #{session} =====', flush=True)
            if args.vendor_bulk:
                from USB_vnd import open_vendor
                ser = open_vendor()
                port = 'usb:vendor-bulk'
            else:
                port = USB_io.wait_for_cdc_port(args.port)
                ser = USB_io.open_serial(port, baudrate=args.baudrate)
            # Короткий таймаут чтения, чтобы Ctrl+C ловился быстро
            try:
                ser.timeout = 0.1
            except Exception:
                pass
            print(f'Открыт порт {port} (сессия #{session})', flush=True)
            # Диагностика: посмотрим очередь входящих байт
            try:
                iw = getattr(ser, 'in_waiting', 0)
                print(f'[link] in_waiting сразу после открытия: {iw}', flush=True)
            except Exception:
                pass
            try:
                # Пассивный прогрев
                warmed = 0
                warm_deadline = None
                if args.warmup_frames > 0 and args.warmup_timeout_sec > 0:
                    warm_deadline = time.time() + args.warmup_timeout_sec
                if args.warmup_frames > 0:
                    print(f'Прогрев: ожидаю {args.warmup_frames} валидных кадр(ов)...', flush=True)
                while warmed < args.warmup_frames:
                    try:
                        frame = USB_frame.read_frame(
                            ser,
                            crc_strategy=('none' if args.crc_none else 'auto'),
                            sync_wait_s=max(3.0, args.warmup_timeout_sec),
                            frame_timeout_s=args.frame_timeout_sec,
                        )
                        warmed += 1
                        if not args.quiet:
                            print(f"seq={frame['seq']}, msec={frame['msec']}, total={frame['total_samples']}, wins={len(frame['wins'])}")
                    except Exception as e:
                        if warm_deadline and time.time() > warm_deadline:
                            print(f'Прогрев: таймаут: {e}', flush=True)
                            # Исправление: при истечении таймаута прогрева — выходим из программы, не уходим в бесконечные переподключения
                            try:
                                ser.close()
                            except Exception:
                                pass
                            print('Порт закрыт (таймаут прогрева)', flush=True)
                            return 2
                        continue

                if args.warmup_frames > 0 and warmed == 0:
                    print('[warmup] Кадры не обнаружены — завершаю', flush=True)
                    try:
                        ser.close()
                    except Exception:
                        pass
                    print(f'Порт закрыт (конец сессии #{session})', flush=True)
                    return 2
                # Основной цикл: читаем и при необходимости печатаем содержимое кадров
                shown = 0
                csv_header_printed = False
                while True:
                    try:
                        frame = USB_frame.read_frame(
                            ser,
                            crc_strategy=('none' if args.crc_none else 'auto'),
                            frame_timeout_s=args.frame_timeout_sec,
                        )
                        shown += 1
                        print(f"seq={frame['seq']}, total={frame['total_samples']}, crc={frame['crc_variant']}", flush=True)

                        # Печать первых N байт payload в hex
                        if args.print_head_hex and args.print_head_hex > 0:
                            try:
                                import numpy as _np
                                data = frame.get('data')
                                if data is not None:
                                    # Преобразуем payload из матрицы обратно в байты LE int16
                                    pay_bytes = _np.asarray(data, dtype='<i2').tobytes()
                                    head = pay_bytes[: int(args.print_head_hex)]
                                    hex_s = ' '.join(f"{x:02X}" for x in head)
                                    print(f"  payload[hex][: {len(head)}]: {hex_s}")
                            except Exception as e:
                                print(f"  [print_head_hex] err: {e}")

                        # Печать первых N значений int16 на канал
                        if args.print_head_i16 and args.print_head_i16 > 0:
                            try:
                                import numpy as _np
                                data = frame.get('data')
                                if data is not None:
                                    n = min(int(args.print_head_i16), int(data.shape[0]))
                                    ch = int(frame.get('channels', data.shape[1]))
                                    # Ограничим печать каналов для компактности: до 4
                                    ch_to_show = min(ch, 4)
                                    rows = []
                                    for i in range(n):
                                        vals = ' '.join(f"{int(data[i, c])}" for c in range(ch_to_show))
                                        rows.append(f"    [{i}] {vals}")
                                    print("  int16 head:")
                                    for r in rows:
                                        print(r)
                            except Exception as e:
                                print(f"  [print_head_i16] err: {e}")

                        # CSV вывод: seq,index,<ch0>..<chN>
                        if args.print_csv:
                            try:
                                import numpy as _np
                                data = frame.get('data')
                                if data is not None:
                                    ch = int(frame.get('channels', data.shape[1]))
                                    # Заголовок
                                    if args.csv_header and not csv_header_printed:
                                        header = ["seq", "index"] + [f"ch{c}" for c in range(ch)]
                                        print(','.join(header))
                                        csv_header_printed = True
                                    # Данные
                                    limit = int(args.csv_limit) if args.csv_limit and args.csv_limit > 0 else data.shape[0]
                                    limit = max(0, min(limit, data.shape[0]))
                                    for i in range(limit):
                                        row = [str(int(frame['seq'])), str(i)] + [str(int(data[i, c])) for c in range(ch)]
                                        print(','.join(row))
                            except Exception as e:
                                print(f"  [print_csv] err: {e}")

                        # Лимит кадров
                        if args.max_frames and shown >= args.max_frames:
                            print(f"Достигнут лимит кадров (--max-frames={args.max_frames})", flush=True)
                            break
                    except TimeoutError as e:
                        # Если поток временно пропал — выйдем в следующую сессию
                        print(f'[loop] Таймаут чтения: {e}', flush=True)
                        break
                    except Exception as e:
                        print(f'[loop] Ошибка чтения: {e}', flush=True)
                        break
            except Exception as e:
                print(f'[session] Ошибка: {e}', flush=True)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
                print(f'Порт закрыт (конец сессии #{session})', flush=True)
    except KeyboardInterrupt:
        print('Остановлено по Ctrl+C', flush=True)


if __name__ == '__main__':
    sys.exit(main())
