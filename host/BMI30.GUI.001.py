#!/usr/bin/env python3
"""BMI30 remote GUI v001.

This GUI does not open USB. It connects to the BMI30 core service API and uses
that running service for status, frames, and control commands.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np  # type: ignore


SERVICE_URL = os.getenv("BMI30_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")

try:
    from PyQt5 import QtCore, QtWidgets
except Exception:
    from PySide6 import QtCore, QtWidgets  # type: ignore

try:
    import pyqtgraph as pg  # type: ignore
except Exception as exc:
    pg = None
    PG_IMPORT_ERR = exc
else:
    PG_IMPORT_ERR = None


def api_get(path: str, timeout: float = 1.5):
    with urlopen(SERVICE_URL + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_command(action: str, **params):
    payload = json.dumps({"action": action, "params": params}).encode("utf-8")
    req = Request(
        SERVICE_URL + "/api/command",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


class RemoteGui:
    def __init__(self):
        if PG_IMPORT_ERR:
            raise RuntimeError(f"pyqtgraph/Qt is not available: {PG_IMPORT_ERR}")
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.win = QtWidgets.QMainWindow()
        self.win.setWindowTitle(f"BMI30 Remote GUI 001 -> {SERVICE_URL}")
        root = QtWidgets.QWidget()
        self.win.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)

        top = QtWidgets.QHBoxLayout()
        layout.addLayout(top)
        self.status = QtWidgets.QLabel("Connecting to BMI30 service...")
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)

        self.freq_box = QtWidgets.QComboBox()
        self.freq_box.addItems(["200 Hz", "204 Hz", "205 Hz", "208 Hz", "210 Hz", "220 Hz", "225 Hz", "240 Hz", "250 Hz"])
        self.freq_box.currentTextChanged.connect(self._freq_changed)
        top.addWidget(self.freq_box)

        self.avg_box = QtWidgets.QComboBox()
        self.avg_box.addItems(["8", "16", "24", "32", "40", "48", "56", "64"])
        self.avg_box.currentTextChanged.connect(self._avg_changed)
        top.addWidget(self.avg_box)

        self.ratio_box = QtWidgets.QComboBox()
        self.ratio_box.addItems([f"{1.1 + 0.1 * i:.1f}" for i in range(20)])
        self.ratio_box.currentTextChanged.connect(self._ratio_changed)
        top.addWidget(self.ratio_box)

        self.btn_reconnect = QtWidgets.QPushButton("Reconnect")
        self.btn_reconnect.clicked.connect(lambda: self._send("reconnect"))
        top.addWidget(self.btn_reconnect)

        self.btn_reset = QtWidgets.QPushButton("Reset Det")
        self.btn_reset.clicked.connect(lambda: self._send("reset_detector"))
        top.addWidget(self.btn_reset)

        self.btn_tim2 = QtWidgets.QPushButton("TX")
        self.btn_tim2.setCheckable(True)
        self.btn_tim2.toggled.connect(lambda checked: self._send("tim2", enabled=bool(checked)))
        top.addWidget(self.btn_tim2)

        self.btn_sound = QtWidgets.QPushButton("Sound")
        self.btn_sound.setCheckable(True)
        self.btn_sound.toggled.connect(lambda checked: self._send("sound", enabled=bool(checked)))
        top.addWidget(self.btn_sound)

        self.plotw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.plotw, 1)
        self.p0 = self.plotw.addPlot(row=0, col=0, title="ADC1")
        self.p1 = self.plotw.addPlot(row=1, col=0, title="ADC2")
        self.p0.showGrid(x=True, y=True, alpha=0.25)
        self.p1.showGrid(x=True, y=True, alpha=0.25)
        self.p1.setXLink(self.p0)
        self.p0.setYRange(0, 65535)
        self.p1.setYRange(0, 65535)
        self.c0e = self.p0.plot(pen=pg.mkPen("#ffb86b", width=1.3))
        self.c0o = self.p0.plot(pen=pg.mkPen("#00e5ff", width=1.3))
        self.c1e = self.p1.plot(pen=pg.mkPen("#ff6b6b", width=1.3))
        self.c1o = self.p1.plot(pen=pg.mkPen("#00ffd5", width=1.3))

        bottom = QtWidgets.QHBoxLayout()
        layout.addLayout(bottom)
        self.mode_group = QtWidgets.QButtonGroup()
        self.mode_group.setExclusive(True)
        self.mode_buttons = []
        for idx in range(8):
            btn = QtWidgets.QToolButton()
            btn.setText(str(idx))
            btn.setCheckable(True)
            btn.setFixedSize(44, 38)
            self.mode_group.addButton(btn, idx)
            self.mode_buttons.append(btn)
            bottom.addWidget(btn)
        self.mode_group.idClicked.connect(self._mode_clicked)
        bottom.addStretch(1)

        self._syncing = False
        self.timer = QtCore.QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _send(self, action: str, **params) -> None:
        try:
            result = api_command(action, **params)
            if not result.get("ok", False):
                self.status.setText(f"{action}: {result.get('error', 'failed')}")
        except Exception as exc:
            self.status.setText(f"Service command failed: {exc}")

    def _mode_clicked(self, idx: int) -> None:
        if self._syncing:
            return
        self._send("mode", idx=int(idx))

    def _freq_changed(self, text: str) -> None:
        if self._syncing:
            return
        try:
            self._send("frequency", hz=int(text.split()[0]))
        except Exception:
            pass

    def _avg_changed(self, text: str) -> None:
        if self._syncing:
            return
        try:
            self._send("avg", avg_n=int(text))
        except Exception:
            pass

    def _ratio_changed(self, text: str) -> None:
        if self._syncing:
            return
        try:
            self._send("det_ratio", value=float(text))
        except Exception:
            pass

    def _poll(self) -> None:
        try:
            status = api_get("/api/status", timeout=0.8)
            frame = api_get("/api/frame?max_points=900", timeout=0.8)
        except URLError as exc:
            self.status.setText(f"BMI30 service offline: {exc}")
            return
        except Exception as exc:
            self.status.setText(f"BMI30 service error: {exc}")
            return
        self._apply_status(status)
        self._apply_frame(frame)

    def _apply_status(self, data: dict) -> None:
        mode = data.get("mode", {})
        conn = data.get("connection", {})
        det = data.get("detector", {})
        fps = data.get("fps", {})
        selected = int(mode.get("selected") or 0)
        self._syncing = True
        try:
            if 0 <= selected < len(self.mode_buttons):
                self.mode_buttons[selected].setChecked(True)
            freq = int(mode.get("desired_freq") or mode.get("freq_hz") or 200)
            self.freq_box.setCurrentText(f"{freq} Hz")
            avg = int(mode.get("avg_n") or 24)
            self.avg_box.setCurrentText(str(avg))
            ratio = float(mode.get("det_ratio") or 2.0)
            self.ratio_box.setCurrentText(f"{ratio:.1f}")
            tim2 = data.get("tim2", {})
            self.btn_tim2.setChecked(bool(tim2.get("enabled", False)))
            self.btn_sound.setChecked(bool((data.get("sound") or {}).get("enabled", False)))
        finally:
            self._syncing = False
        connected = "connected" if conn.get("connected") else ("connecting" if conn.get("connecting") else "offline")
        text = (
            f"{connected} | mode {selected} | stream {mode.get('stream_mode')} | "
            f"BUF {mode.get('base_buf_len')} | {mode.get('freq_hz')} Hz | "
            f"Afps {float(fps.get('a') or 0):.1f} Bfps {float(fps.get('b') or 0):.1f} | "
            f"thr {det.get('thr0')}/{det.get('thr1')} lvl {det.get('lvl0')}/{det.get('lvl1')}"
        )
        self.status.setText(text)

    def _apply_frame(self, data: dict) -> None:
        if not data.get("available"):
            return
        x = np.asarray(data.get("x") or [], dtype=np.int32)
        if x.size <= 0:
            return

        def arr(name: str) -> np.ndarray:
            return np.asarray(data.get(name) or [], dtype=np.uint16)

        self.c0e.setData(x, arr("data0_even"))
        self.c0o.setData(x, arr("data0_odd"))
        self.c1e.setData(x, arr("data1_even"))
        self.c1o.setData(x, arr("data1_odd"))

    def run(self) -> int:
        self.win.resize(1000, 700)
        self.win.show()
        if hasattr(self.app, "exec_"):
            return int(self.app.exec_())
        return int(self.app.exec())


def main() -> int:
    gui = RemoteGui()
    return gui.run()


if __name__ == "__main__":
    raise SystemExit(main())
