#!/usr/bin/env python3
from __future__ import annotations
import sys
import time
import threading
from typing import Optional, Tuple

import numpy as np  # type: ignore[import-not-found]
import serial  # type: ignore[import-not-found]

import USB_io
import USB_proto


def _try_set_windows(ser: serial.Serial, win0: Optional[Tuple[int,int]], win1: Optional[Tuple[int,int]], block_hz: Optional[int]) -> None:
    try:
        if win0 is not None and win1 is not None:
            payload = np.asarray([win0[0], win0[1], win1[0], win1[1]], dtype=np.uint16).tobytes()
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_WINDOWS, payload=payload)
        elif win0 is not None:
            payload = np.asarray([win0[0], win0[1], 0, 0], dtype=np.uint16).tobytes()
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_WINDOWS, payload=payload)
        if block_hz is not None:
            USB_proto.send_cmd_no_ack(ser, USB_proto.CMD_SET_BLOCK_HZ, payload=np.asarray([int(block_hz)], dtype=np.uint16).tobytes())
    except Exception:
        pass


def run_plot_fast(port: str, *, win0: Optional[Tuple[int,int]] = None, win1: Optional[Tuple[int,int]] = None,
                  block_hz: Optional[int] = None, samples: int = 1000,
                  target_fps: int = 20, warmup_timeout_sec: Optional[float] = None) -> int:
    try:
        import pyqtgraph as pg  # type: ignore
        try:
            from PySide6 import QtWidgets, QtCore  # type: ignore
        except Exception:
            from PyQt5 import QtWidgets, QtCore  # type: ignore
    except Exception as e:
        print(f"[plot-fast] Требуется pyqtgraph + PySide6/PyQt5: {e}")
        return 2

    ser = USB_io.open_serial(port, timeout=0)
    _try_set_windows(ser, win0, win1, block_hz)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = QtWidgets.QMainWindow()
    win.setWindowTitle("USB Plot — fast (PyQtGraph)")
    cw = QtWidgets.QWidget(); win.setCentralWidget(cw)
    layout = QtWidgets.QVBoxLayout(cw)
    plot = pg.PlotWidget()
    layout.addWidget(plot)
    plot.setBackground('w')
    plot.showGrid(x=True, y=True, alpha=0.2)
    plot.setYRange(-33000, 33000)
    plot.setLabel('left', 'Amplitude', units='int16')
    plot.setLabel('bottom', 'Sample')
    penL = pg.mkPen(color=(30, 144, 255), width=1.0)  # dodgerblue
    penR = pg.mkPen(color=(255, 140, 0), width=1.0)   # darkorange
    curveL = plot.plot(np.arange(samples), np.zeros(samples, dtype=np.int16), pen=penL, name='L')
    curveR = plot.plot(np.arange(samples), np.zeros(samples, dtype=np.int16), pen=penR, name='R')

    # Буферы и поток чтения
    ringL = np.zeros(samples, dtype=np.int16)
    ringR = np.zeros(samples, dtype=np.int16)
    idx = 0
    lock = threading.Lock()
    stop_ev = threading.Event()
    bytes_seen = 0

    def reader_loop():
        nonlocal idx, bytes_seen
        tail = b''
        while not stop_ev.is_set():
            try:
                avail = getattr(ser, 'in_waiting', 0)
            except Exception:
                avail = 0
            if avail <= 0:
                time.sleep(0.002)
                continue
            to_read = min(8192, int(avail))
            b = ser.read(to_read)
            if not b:
                time.sleep(0.001)
                continue
            bytes_seen += len(b)
            bb = tail + b
            n = len(bb) // 4  # 2 ch * int16
            if n == 0:
                tail = bb
                continue
            data = np.frombuffer(bb[:n*4], dtype='<i2').reshape(-1, 2)
            tail = bb[n*4:]
            with lock:
                # Запись в кольцевой буфер
                if n >= samples:
                    ringL[:] = data[-samples:, 0]
                    ringR[:] = data[-samples:, 1]
                    idx = 0
                else:
                    end = idx + n
                    if end <= samples:
                        ringL[idx:end] = data[:, 0]
                        ringR[idx:end] = data[:, 1]
                    else:
                        first = samples - idx
                        if first > 0:
                            ringL[idx:] = data[:first, 0]
                            ringR[idx:] = data[:first, 1]
                        rest = n - first
                        if rest > 0:
                            ringL[:rest] = data[first:, 0]
                            ringR[:rest] = data[first:, 1]
                    idx = (idx + n) % samples

    th = threading.Thread(target=reader_loop, daemon=True)
    th.start()

    # Таймер отрисовки ~20 Гц
    interval_ms = max(10, int(1000 / max(1, target_fps)))
    last_fps_time = time.time(); frames = 0; fps = 0.0

    def on_timer():
        nonlocal frames, last_fps_time, fps
        # warmup timeout: если байты так и не пошли
        if warmup_timeout_sec and warmup_timeout_sec > 0:
            if bytes_seen == 0 and (time.time() - start_time) > warmup_timeout_sec:
                stop_ev.set(); plot_timer.stop(); app.quit()
                return
        with lock:
            if idx == 0:
                yL = ringL.copy()
                yR = ringR.copy()
            else:
                yL = np.concatenate([ringL[idx:], ringL[:idx]])
                yR = np.concatenate([ringR[idx:], ringR[:idx]])
        x = np.arange(samples)
        curveL.setData(x, yL)
        curveR.setData(x, yR)
        frames += 1
        now = time.time()
        if now - last_fps_time >= 1.0:
            fps = frames / (now - last_fps_time)
            frames = 0
            last_fps_time = now
            plot.setTitle(f"fast plot — ~{fps:.1f} FPS; buf={samples}")

    plot_timer = QtCore.QTimer()
    plot_timer.timeout.connect(on_timer)
    plot_timer.start(interval_ms)

    start_time = time.time()
    win.resize(900, 420)
    win.show()
    rc = 0
    try:
        rc = app.exec()
    finally:
        stop_ev.set()
        try:
            plot_timer.stop()
        except Exception:
            pass
        try:
            th.join(timeout=1.0)
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass
    return 0 if (rc == 0 and bytes_seen > 0) else (2 if bytes_seen == 0 else rc)
