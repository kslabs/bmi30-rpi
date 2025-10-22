#!/usr/bin/env python3
from __future__ import annotations
import time
from typing import Optional, List
import os

import numpy as np  # type: ignore[import-not-found]
import serial  # type: ignore[import-not-found]

import USB_io
import USB_frame
import USB_proto


def try_set_windows(ser: serial.Serial, win0: tuple[int,int]|None, win1: tuple[int,int]|None, block_hz: Optional[int]) -> None:
    try:
        if win0 is not None and win1 is not None:
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_WINDOWS, payload=np.asarray([win0[0], win0[1], win1[0], win1[1]], dtype=np.uint16).tobytes())
        elif win0 is not None:
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_WINDOWS, payload=np.asarray([win0[0], win0[1], 0, 0], dtype=np.uint16).tobytes())
        if block_hz is not None:
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_BLOCK_HZ, payload=np.asarray([int(block_hz)], dtype=np.uint16).tobytes())
    except Exception:
        pass


def run_plot(port: str, *, win0: tuple[int,int]|None = None, win1: tuple[int,int]|None = None,
             block_hz: Optional[int] = None, quiet: bool = False,
             crc_none: bool = True, frame_timeout_sec: float = 2.0,
             raw_fallback: bool = True, raw_samples: int = 1000,
             warmup_timeout_sec: float | None = None,
             trim_edge_samples: int = 0) -> int:
    try:
        # Избегаем Qt: форсируем TkAgg до импорта pyplot
        import matplotlib
        os.environ.setdefault('MPLBACKEND', 'TkAgg')
        try:
            matplotlib.use('TkAgg', force=False)
        except Exception:
            pass
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except Exception as e:
        print(f"[plot] matplotlib недоступен: {e}")
        return 2

    ser = USB_io.open_serial(port, timeout=0.2)
    try:
        try_set_windows(ser, win0, win1, block_hz)

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.set_title("Ожидание кадра…")
        # шкала Y для int16
        try:
            ax.set_ylim(-33000, 33000)
            ax.yaxis.set_major_locator(mticker.MultipleLocator(10000))
            ax.yaxis.set_minor_locator(mticker.MultipleLocator(5000))
            ax.grid(True, which='major', alpha=0.25)
            ax.grid(True, which='minor', alpha=0.10)
            ax.minorticks_on()
        except Exception:
            ax.grid(True, alpha=0.2)
        fig.tight_layout(); plt.pause(0.001)

        # ожидание первого валидного кадра с дедлайном на RAW
        t0 = time.time(); last_log = 0.0
        fallback_deadline = t0 + (warmup_timeout_sec if (warmup_timeout_sec and warmup_timeout_sec > 0) else 3.0)
        frame = None
        while frame is None and plt.fignum_exists(fig.number):
            try:
                frame = USB_frame.read_frame(
                    ser,
                    crc_strategy=('none' if crc_none else 'auto'),
                    sync_wait_s=1.5,
                    frame_timeout_s=frame_timeout_sec,
                )
            except Exception as e:
                now = time.time()
                if now - last_log > 1.0:
                    print(f"[plot] ожидание кадра: {e}")
                    last_log = now
                if raw_fallback and now >= fallback_deadline:
                    return _run_plot_raw(fig, ax, ser, raw_samples)
                if (not raw_fallback) and warmup_timeout_sec and warmup_timeout_sec > 0 and now >= fallback_deadline:
                    return 2
                continue

        if frame is None:
            return 1

        data = frame['data']
        if trim_edge_samples > 0 and data.shape[0] > 2*trim_edge_samples:
            data = data[trim_edge_samples:-trim_edge_samples]
        ch = frame['channels']
        n = data.shape[0]
        x = np.arange(n)

        colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red']
        lines = []
        for c in range(min(ch, 4)):
            ln, = ax.plot(x, data[:, c], lw=1.0, color=colors[c % len(colors)], label=f'Ch{c}')
            lines.append(ln)

        seam_vlines: List = []
        cum = 0
        for _, l in frame['wins']:
            cum += l
            pos = cum - trim_edge_samples if trim_edge_samples > 0 else cum
            if 0 < pos < n:
                seam_vlines.append(ax.axvline(pos, color='0.85', lw=0.8))

        ax.set_xlim(0, n-1)
        ax.set_title(f"seq={frame['seq']} msec={frame['msec']} wins={len(frame['wins'])} samples={n} crc={frame['crc_variant']}")
        ax.legend(loc='upper right')
        fig.tight_layout(); plt.pause(0.001)

        # обновление
        prev_last = data[-1, :min(ch, 4)].copy() if n > 0 else None
        while plt.fignum_exists(fig.number):
            try:
                fr = USB_frame.read_frame(
                    ser,
                    crc_strategy=('none' if crc_none else 'auto'),
                    sync_wait_s=1.0,
                    frame_timeout_s=frame_timeout_sec,
                )
            except Exception:
                continue

            d = fr['data']
            if trim_edge_samples > 0 and d.shape[0] > 2*trim_edge_samples:
                d = d[trim_edge_samples:-trim_edge_samples]

            if prev_last is not None and d.shape[0] > 0:
                jumps = d[0, :min(d.shape[1], prev_last.shape[0])] - prev_last[:min(d.shape[1], prev_last.shape[0])]
                max_jump = int(np.max(np.abs(jumps))) if jumps.size else 0
            else:
                max_jump = 0

            if d.shape[0] != n:
                n = d.shape[0]
                x = np.arange(n)
                ax.set_xlim(0, n-1)
                try:
                    ax.set_ylim(-33000, 33000)
                except Exception:
                    pass
                for c, ln in enumerate(lines):
                    ln.set_xdata(x)
                for vl in seam_vlines:
                    try:
                        vl.remove()
                    except Exception:
                        pass
                seam_vlines = []
                cum = 0
                for _, l in fr['wins']:
                    cum += l
                    pos = cum - trim_edge_samples if trim_edge_samples > 0 else cum
                    if 0 < pos < n:
                        seam_vlines.append(ax.axvline(pos, color='0.85', lw=0.8))

            for c, ln in enumerate(lines):
                if c < d.shape[1]:
                    ln.set_ydata(d[:, c])

            ax.set_title(f"seq={fr['seq']} msec={fr['msec']} wins={len(fr['wins'])} samples={d.shape[0]} crc={fr['crc_variant']} jump={max_jump}")
            if d.shape[0] > 0:
                prev_last = d[-1, :min(d.shape[1], len(lines))].copy()
            plt.pause(0.001)
        return 0
    finally:
        try:
            ser.close()
        except Exception:
            pass


def _run_plot_raw(fig, ax, ser: serial.Serial, samples: int = 2048) -> int:
    """Простейший «сырой» плот: читаем interleaved int16 LE (2 канала) и рисуем скользящее окно."""
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return 2
    ax.cla()
    ax.set_title("RAW view (int16 LE, 2ch). Ожидание данных…")
    try:
        import matplotlib.ticker as mticker
        ax.set_ylim(-33000, 33000)
        ax.yaxis.set_major_locator(mticker.MultipleLocator(10000))
        ax.yaxis.set_minor_locator(mticker.MultipleLocator(5000))
        ax.grid(True, which='major', alpha=0.25)
        ax.grid(True, which='minor', alpha=0.10)
        ax.minorticks_on()
    except Exception:
        ax.grid(True, alpha=0.2)
    x = np.arange(samples)
    yL = np.zeros(samples, dtype=np.int16)
    yR = np.zeros(samples, dtype=np.int16)
    lnL, = ax.plot(x, yL, lw=1.0, color='tab:blue', label='L')
    lnR, = ax.plot(x, yR, lw=1.0, color='tab:orange', label='R')
    ax.set_xlim(0, samples-1)
    ax.legend(loc='upper right')
    fig.tight_layout(); plt.pause(0.001)
    # Неблокирующее чтение для высокой частоты обновления
    try:
        old_timeout = ser.timeout
        ser.timeout = 0
    except Exception:
        old_timeout = None
    tail = b''
    bufL = yL.copy(); bufR = yR.copy()
    last_draw = time.time()
    frames_drawn = 0
    fps_last = time.time(); fps_val = 0.0
    while plt.fignum_exists(fig.number):
        try:
            avail = getattr(ser, 'in_waiting', 0)
        except Exception:
            avail = 0
        if avail and avail > 0:
            to_read = min(8192, int(avail))
            b = ser.read(to_read)
        else:
            b = b''
        if not b:
            # нет новых байт — лёгкая пауза
            plt.pause(0.005)
            continue
        bb = tail + b
        n = len(bb) // 4  # 2ch * int16
        if n == 0:
            tail = bb
            continue
        data = np.frombuffer(bb[:n*4], dtype='<i2').reshape(-1, 2)
        tail = bb[n*4:]
        # сдвигаем кольцевой буфер
        take = min(n, samples)
        if take < samples:
            bufL = np.roll(bufL, -take); bufR = np.roll(bufR, -take)
            bufL[-take:] = data[-take:, 0]
            bufR[-take:] = data[-take:, 1]
        else:
            bufL[:] = data[-samples:, 0]
            bufR[:] = data[-samples:, 1]
        # без искажений: отображаем сырые значения
        lnL.set_ydata(bufL)
        lnR.set_ydata(bufR)
        # обновляем заголовок с FPS
        frames_drawn += 1
        now = time.time()
        if now - fps_last >= 1.0:
            fps_val = frames_drawn / (now - fps_last)
            frames_drawn = 0
            fps_last = now
        ax.set_title(f"RAW view (2ch), обновление — ~{fps_val:.1f} FPS")
        # короткая пауза для GUI цикла
        plt.pause(0.001)
    # вернуть timeout
    try:
        if old_timeout is not None:
            ser.timeout = old_timeout
    except Exception:
        pass
    return 0
