#!/usr/bin/env python3
"""Простой тест: проверяет что GUI отображает осциллограмму"""
import sys
import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
import numpy as np

class TestWindow:
    def __init__(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self.win = QtWidgets.QMainWindow()
        self.win.setWindowTitle("Test: Осциллограмма всегда видна")
        central = QtWidgets.QWidget()
        self.win.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # График
        self.plot_widget = pg.PlotWidget()
        layout.addWidget(self.plot_widget)
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Sample')
        
        # Кривая для данных
        self.curve = self.plot_widget.plot(pen='g')
        
        # Буфер данных (начально нулевой)
        self.data = np.zeros(1360, dtype=np.int16)
        self.counter = 0
        
        # Таймер для обновления
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update)
        self.timer.start(50)  # 20 FPS
        
        self.win.resize(800, 600)
        self.win.show()
        print("[TEST] GUI запущен, осциллограмма должна быть видна")
        print("[TEST] Нулевые значения отображаются как прямая линия на нуле")
    
    def _update(self):
        """Обновляет график - всегда отображает данные"""
        x = np.arange(len(self.data))
        self.curve.setData(x, self.data)
        
        # Каждые 2 секунды меняем данные для демонстрации
        self.counter += 1
        if self.counter % 40 == 0:
            if np.all(self.data == 0):
                # Заполняем синусоидой
                self.data[:] = (np.sin(np.linspace(0, 10*np.pi, len(self.data))) * 10000).astype(np.int16)
                print("[TEST] Данные: синусоида")
            else:
                # Обнуляем
                self.data[:] = 0
                print("[TEST] Данные: нули")
    
    def run(self):
        return self.app.exec_()

if __name__ == '__main__':
    win = TestWindow()
    sys.exit(win.run())
