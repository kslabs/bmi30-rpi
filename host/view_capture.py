#!/usr/bin/env python3
"""
view_capture.py - Просмотр сохраненных осциллограмм из NPZ файлов

Использование:
    python view_capture.py <файл.npz>
    python view_capture.py captures/capture_20260115_143052.npz

Управление:
    ← → или A/D - перемотка кадра назад/вперед
    Space - пауза/воспроизведение
    Home/End - первый/последний кадр
    1-5 - изменить скорость воспроизведения
"""

from __future__ import annotations
import sys
import os
import numpy as np

# Qt setup (same as BMI30.200.py)
if "QT_QPA_PLATFORM" not in os.environ:
    if os.getenv("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif os.getenv("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")
os.environ.pop("QT_QPA_PLATFORMTHEME", None)

try:
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
    from PyQt5 import QtWidgets, QtCore
    import pyqtgraph as pg
except Exception:
    try:
        os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
        from PySide6 import QtWidgets, QtCore
        import pyqtgraph as pg
    except Exception as e:
        print(f"ERROR: Cannot import Qt/pyqtgraph: {e}")
        sys.exit(1)


class CaptureViewer:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data = None
        self.n_frames = 0
        self.current_frame = 0
        self.playing = False
        self.play_speed = 1  # frames per tick
        
        # Load NPZ file
        self._load_capture()
        
        # Create GUI
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.win = QtWidgets.QMainWindow()
        self.win.setWindowTitle(f"Capture Viewer: {os.path.basename(filepath)}")
        
        central = QtWidgets.QWidget()
        self.win.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Info label
        self.info_lbl = QtWidgets.QLabel()
        self.info_lbl.setWordWrap(True)
        layout.addWidget(self.info_lbl)
        
        # Control bar
        ctrl_bar = QtWidgets.QHBoxLayout()
        
        self.btn_first = QtWidgets.QPushButton("⏮ First")
        self.btn_first.clicked.connect(self._go_first)
        ctrl_bar.addWidget(self.btn_first)
        
        self.btn_prev = QtWidgets.QPushButton("◀ Prev")
        self.btn_prev.clicked.connect(self._go_prev)
        ctrl_bar.addWidget(self.btn_prev)
        
        self.btn_play = QtWidgets.QPushButton("▶ Play")
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self._toggle_play)
        ctrl_bar.addWidget(self.btn_play)
        
        self.btn_next = QtWidgets.QPushButton("Next ▶")
        self.btn_next.clicked.connect(self._go_next)
        ctrl_bar.addWidget(self.btn_next)
        
        self.btn_last = QtWidgets.QPushButton("Last ⏭")
        self.btn_last.clicked.connect(self._go_last)
        ctrl_bar.addWidget(self.btn_last)
        
        self.speed_lbl = QtWidgets.QLabel(f"Speed: {self.play_speed}x")
        ctrl_bar.addWidget(self.speed_lbl)
        
        layout.addLayout(ctrl_bar)
        
        # Frame slider
        slider_bar = QtWidgets.QHBoxLayout()
        slider_bar.addWidget(QtWidgets.QLabel("Frame:"))
        self.frame_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(max(0, self.n_frames - 1))
        self.frame_slider.setValue(0)
        self.frame_slider.valueChanged.connect(self._on_slider_change)
        slider_bar.addWidget(self.frame_slider, 1)
        self.frame_lbl = QtWidgets.QLabel(f"0 / {self.n_frames}")
        slider_bar.addWidget(self.frame_lbl)
        layout.addLayout(slider_bar)
        
        # Plots
        self.plotw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.plotw, 1)
        
        self.p0 = self.plotw.addPlot(row=0, col=0, title="ADC0 (1/0)")
        self.p1 = self.plotw.addPlot(row=1, col=0, title="ADC1 (1/0)")
        
        # Plot curves
        self.curve0_even = self.p0.plot(pen=pg.mkPen('#ffb86b', width=1.5), symbol=None)
        self.curve0_odd = self.p0.plot(pen=pg.mkPen('#00e5ff', width=1.5), symbol=None)
        self.curve1_even = self.p1.plot(pen=pg.mkPen('#ff6b6b', width=1.5), symbol=None)
        self.curve1_odd = self.p1.plot(pen=pg.mkPen('#00ffd5', width=1.5), symbol=None)
        
        self.p0.showGrid(x=True, y=True, alpha=0.3)
        self.p1.showGrid(x=True, y=True, alpha=0.3)
        
        try:
            self.p1.setXLink(self.p0)
        except Exception:
            pass
        
        self.p0.setYRange(0, 65535, padding=0.02)
        self.p1.setYRange(0, 65535, padding=0.02)
        
        # Timer for playback
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)  # 20 FPS playback
        self.timer.timeout.connect(self._play_tick)
        
        # Keyboard shortcuts
        try:
            self.win.keyPressEvent = self._on_key_press
        except Exception:
            pass
        
        # Update display
        self._update_display()
        self._update_info()
        
        # Show window
        self.win.resize(1200, 800)
        self.win.show()
    
    def _load_capture(self):
        """Load NPZ file and extract metadata."""
        try:
            self.data = np.load(self.filepath)
            self.n_frames = int(self.data['n_frames'][0])
            if self.n_frames == 0:
                raise ValueError("No frames in capture file")
            print(f"[VIEWER] Loaded {self.n_frames} frames from {self.filepath}")
        except Exception as e:
            print(f"ERROR: Failed to load capture file: {e}")
            sys.exit(1)
    
    def _update_display(self):
        """Update plots with current frame data."""
        try:
            idx = self.current_frame
            if idx < 0 or idx >= self.n_frames:
                return
            
            # Get frame data
            data0_even = self.data['data0_even'][idx]
            data0_odd = self.data['data0_odd'][idx]
            data1_even = self.data['data1_even'][idx]
            data1_odd = self.data['data1_odd'][idx]
            
            # Find actual data length (non-zero region)
            buf_len = int(self.data['buf_len'][0])
            
            # Update curves
            x = np.arange(buf_len)
            self.curve0_even.setData(x, data0_even[:buf_len])
            self.curve0_odd.setData(x, data0_odd[:buf_len])
            self.curve1_even.setData(x, data1_even[:buf_len])
            self.curve1_odd.setData(x, data1_odd[:buf_len])
            
            # Update frame label
            self.frame_lbl.setText(f"{idx} / {self.n_frames}")
            
            # Block slider signals to avoid feedback loop
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(idx)
            self.frame_slider.blockSignals(False)
            
        except Exception as e:
            print(f"[VIEWER] Error updating display: {e}")
    
    def _update_info(self):
        """Update info label with metadata and detector state."""
        try:
            idx = self.current_frame
            
            # Metadata
            profile = int(self.data['profile'][0])
            freq_hz = int(self.data['freq_hz'][0])
            avg_n = int(self.data['avg_n'][0])
            stream_mode = int(self.data['stream_mode'][0])
            det_source = str(self.data['det_source'][0])
            det_ratio = float(self.data['det_ratio'][0])
            
            # Trigger info
            trigger_time = float(self.data['trigger_time'][0])
            reason = str(self.data['reason'][0])
            
            # Frame-specific detector state
            det_thr0 = int(self.data['det_thr0'][idx])
            det_thr1 = int(self.data['det_thr1'][idx])
            det_lvl0 = int(self.data['det_lvl0'][idx])
            det_lvl1 = int(self.data['det_lvl1'][idx])
            det_shift0 = int(self.data['det_shift0'][idx])
            det_shift1 = int(self.data['det_shift1'][idx])
            det_amp0 = int(self.data['det_amp0'][idx])
            det_amp1 = int(self.data['det_amp1'][idx])
            det_hold0 = bool(self.data['det_hold0'][idx])
            det_hold1 = bool(self.data['det_hold1'][idx])
            det_frozen = bool(self.data['det_frozen'][idx])
            
            timestamp = float(self.data['timestamps'][idx])
            rel_time = timestamp - trigger_time
            
            info_text = (
                f"<b>Capture Info:</b> Profile={profile} Freq={freq_hz}Hz avg_n={avg_n} mode={stream_mode}<br>"
                f"<b>Trigger:</b> {reason}<br>"
                f"<b>Frame {idx}:</b> t={rel_time:+.3f}s | "
                f"DC={'FROZEN' if det_frozen else 'RUN'} | "
                f"A0: {det_amp0} thr={det_thr0} lvl={det_lvl0} sh={det_shift0} {'H' if det_hold0 else '-'} | "
                f"A1: {det_amp1} thr={det_thr1} lvl={det_lvl1} sh={det_shift1} {'H' if det_hold1 else '-'}"
            )
            
            self.info_lbl.setText(info_text)
            
        except Exception as e:
            self.info_lbl.setText(f"Error reading metadata: {e}")
    
    def _go_first(self):
        self.current_frame = 0
        self._update_display()
        self._update_info()
    
    def _go_last(self):
        self.current_frame = self.n_frames - 1
        self._update_display()
        self._update_info()
    
    def _go_prev(self):
        self.current_frame = max(0, self.current_frame - 1)
        self._update_display()
        self._update_info()
    
    def _go_next(self):
        self.current_frame = min(self.n_frames - 1, self.current_frame + 1)
        self._update_display()
        self._update_info()
    
    def _toggle_play(self, enabled: bool):
        self.playing = enabled
        if self.playing:
            self.btn_play.setText("⏸ Pause")
            self.timer.start()
        else:
            self.btn_play.setText("▶ Play")
            self.timer.stop()
    
    def _play_tick(self):
        """Auto-advance frame during playback."""
        if not self.playing:
            return
        self.current_frame += self.play_speed
        if self.current_frame >= self.n_frames:
            self.current_frame = 0  # Loop
        self._update_display()
        self._update_info()
    
    def _on_slider_change(self, value: int):
        self.current_frame = value
        self._update_display()
        self._update_info()
    
    def _on_key_press(self, event):
        """Handle keyboard shortcuts."""
        try:
            key = event.key()
            if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_A):
                self._go_prev()
            elif key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_D):
                self._go_next()
            elif key == QtCore.Qt.Key_Space:
                self.btn_play.setChecked(not self.btn_play.isChecked())
            elif key == QtCore.Qt.Key_Home:
                self._go_first()
            elif key == QtCore.Qt.Key_End:
                self._go_last()
            elif key == QtCore.Qt.Key_1:
                self.play_speed = 1
                self.speed_lbl.setText(f"Speed: {self.play_speed}x")
            elif key == QtCore.Qt.Key_2:
                self.play_speed = 2
                self.speed_lbl.setText(f"Speed: {self.play_speed}x")
            elif key == QtCore.Qt.Key_3:
                self.play_speed = 5
                self.speed_lbl.setText(f"Speed: {self.play_speed}x")
            elif key == QtCore.Qt.Key_4:
                self.play_speed = 10
                self.speed_lbl.setText(f"Speed: {self.play_speed}x")
            elif key == QtCore.Qt.Key_5:
                self.play_speed = 20
                self.speed_lbl.setText(f"Speed: {self.play_speed}x")
        except Exception:
            pass
    
    def run(self):
        """Start Qt event loop."""
        sys.exit(self.app.exec_())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python view_capture.py <capture_file.npz>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)
    
    viewer = CaptureViewer(filepath)
    viewer.run()


if __name__ == '__main__':
    main()
