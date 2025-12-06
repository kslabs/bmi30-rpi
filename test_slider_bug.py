#!/usr/bin/env python3
"""
Простая проверка: при инициализации buffer=912, что произойдет с отрисовкой?
"""

# Симулируем что случилось в коде

class Sim:
    def __init__(self):
        self.base_buf_len = None
        self.view_len = 0
        self.slider_value = 0
        
    def on_init_buffer(self):
        print("\n=== ON_INIT_BUFFER ===")
        self.base_buf_len = 912
        self.view_len = self.base_buf_len
        print(f"  set view_len = {self.view_len}")
        print(f"  set slider_value = {self.view_len} (setValue вызван)")
        # Но в реальном коде setValue может быть не обработан сразу
        # Давайте симулируем что slider не обновлен
        self.slider_value = 0  # ← Это симулирует баг: setValue был вызван но value еще не обновился
        print(f"  ВНИМАНИЕ: slider_value еще не обновился = {self.slider_value}")
        
    def on_draw(self):
        print("\n=== ON_DRAW ===")
        # СТАРЫЙ КОД (с ошибкой):
        print("  [OLD] vlen = max(1, min(slider_value={}, base_buf_len={}))".format(self.slider_value, self.base_buf_len))
        vlen_old = max(1, min(self.slider_value, self.base_buf_len))
        print(f"  [OLD] vlen = {vlen_old} ← ❌ НЕПРАВИЛЬНО!")
        
        # НОВЫЙ КОД (исправленный):
        print("  [NEW] vlen = max(1, min(view_len={}, base_buf_len={}))".format(self.view_len, self.base_buf_len))
        vlen_new = max(1, min(self.view_len, self.base_buf_len))
        print(f"  [NEW] vlen = {vlen_new} ← ✅ ПРАВИЛЬНО!")

sim = Sim()
sim.on_init_buffer()
sim.on_draw()
print("\n✨ Исправление: используем self.view_len вместо slider_len.value()")
