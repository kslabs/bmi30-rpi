#!/usr/bin/env python3
"""Диагностика: проверить как инициализируется GUI буфер"""

import sys
import numpy as np
sys.path.insert(0, '/home/techaid/Documents/host')

from PyQt5 import QtWidgets, QtCore

# Минимальный тест GUI инициализации
class MinimalTest(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.base_buf_len = None
        self.view_len = 0
        self.data0 = np.zeros(0, dtype=np.int16)
        
        # Создадим слайдер как в BMI30.200.py
        self.slider_len = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_len.setMinimum(0)
        self.slider_len.setMaximum(0)
        self.slider_len.setValue(0)
        
        print(f"[INIT] Слайдер создан: min=0, max=0, value={self.slider_len.value()}")
        
        # Симулируем приход первого буфера
        self.init_buffer()
        
        # Симулируем отрисовку
        self.draw()
        
    def init_buffer(self):
        """Симулируем инициализацию буфера при получении первых данных"""
        print("\n[SIMULATE] Получены первые данные (912 семплов)...")
        
        self.base_buf_len = 912
        self.data0 = np.zeros(self.base_buf_len, dtype=np.int16)
        
        # Устанавливаем слайдер как в коде
        self.view_len = self.base_buf_len
        self.slider_len.setMinimum(1)
        self.slider_len.setMaximum(self.base_buf_len)
        self.slider_len.setValue(self.view_len)
        
        print(f"[AFTER INIT] base_buf_len={self.base_buf_len}")
        print(f"[AFTER INIT] view_len={self.view_len}")
        print(f"[AFTER INIT] slider_len: min=1, max={self.base_buf_len}, value={self.slider_len.value()}")
        print(f"[AFTER INIT] len(data0)={len(self.data0)}")
        
    def draw(self):
        """Симулируем отрисовку как в BMI30.200.py строка ~484"""
        print("\n[DRAW] Начинаем отрисовку...")
        
        if self.base_buf_len is not None:
            slider_value = int(self.slider_len.value())
            vlen = max(1, min(slider_value, self.base_buf_len))
            vstart = 0
            vlen = min(vlen, len(self.data0) - vstart)
            
            print(f"  slider_len.value() = {slider_value}")
            print(f"  max(1, min({slider_value}, {self.base_buf_len})) = {vlen} (ДО min)")
            print(f"  min({vlen}, {len(self.data0)} - {vstart}) = {vlen} (ПОСЛЕ min)")
            print(f"  РЕЗУЛЬТАТ: будет отрисовано {vlen} семплов")
            
            if vlen == 1:
                print(f"  ❌ ПРОБЛЕМА: отрисовывается только 1 семпл!")
                print(f"  len(self.data0) = {len(self.data0)}")
                if len(self.data0) > 0:
                    print(f"  len(self.data0) - vstart = {len(self.data0) - vstart}")
            elif vlen == self.base_buf_len:
                print(f"  ✅ ПРАВИЛЬНО: отрисовывается весь буфер ({vlen} семплов)")

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    test = MinimalTest()
