#!/usr/bin/env python3
"""Тест GUI с синтезированными данными - проверить что отображение работает"""

import sys
import numpy as np
sys.path.insert(0, '/home/techaid/Documents/host')

# Используем QT_QPA_PLATFORM=offscreen для безголовой работы, если нужно
# os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

class SimpleOscilloscope(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        layout = QtWidgets.QVBoxLayout()
        
        # Create plots
        self.p0 = pg.PlotWidget()
        self.p1 = pg.PlotWidget()
        self.p0.setLabel('left', 'ADC0')
        self.p1.setLabel('left', 'ADC1')
        
        self.curve0 = self.p0.plot(pen=None, symbol='o', symbolSize=2)
        self.curve1 = self.p1.plot(pen=None, symbol='o', symbolSize=2)
        
        layout.addWidget(QtWidgets.QLabel("PROFILE=1 (912 samples, 176 Hz)"))
        layout.addWidget(self.p0)
        layout.addWidget(QtWidgets.QLabel("PROFILE=2 (912 samples, 280 Hz)"))
        layout.addWidget(self.p1)
        
        # Test button
        btn = QtWidgets.QPushButton("Generate Test Data")
        btn.clicked.connect(self.generate_test_data)
        layout.addWidget(btn)
        
        self.setLayout(layout)
        self.setWindowTitle("Test Oscilloscope")
        self.resize(800, 600)
        
    def generate_test_data(self):
        print("Generating test data...")
        
        # Generate 912-sample sine waves at different frequencies
        n = 912
        
        # 10 Hz sine wave
        x = np.arange(n)
        freq1 = 10.0  # Hz
        freq2 = 20.0  # Hz
        
        # Generate with sampling rate 176 Hz (for profile 1)
        fs = 176
        t1 = np.arange(n) / fs
        ch0 = (32000 * np.sin(2 * np.pi * freq1 * t1)).astype(np.int16)
        ch1 = (16000 * np.sin(2 * np.pi * freq2 * t1)).astype(np.int16)
        
        print(f"ch0: shape={ch0.shape}, min={ch0.min()}, max={ch0.max()}, mean={ch0.mean():.1f}")
        print(f"ch1: shape={ch1.shape}, min={ch1.min()}, max={ch1.max()}, mean={ch1.mean():.1f}")
        
        # Display
        x_axis = np.arange(len(ch0))
        self.curve0.setData(x_axis, ch0)
        self.curve1.setData(x_axis, ch1)
        self.p0.setXRange(0, len(ch0), padding=0.0)
        self.p1.setXRange(0, len(ch0), padding=0.0)
        
        print("Done!")

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = SimpleOscilloscope()
    window.show()
    
    # Auto-generate on startup
    QtCore.QTimer.singleShot(500, window.generate_test_data)
    
    sys.exit(app.exec_())
