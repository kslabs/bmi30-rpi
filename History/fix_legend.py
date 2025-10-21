import matplotlib.pyplot as plt
import numpy as np

def fix_legend(ax, fig):
    """
    Исправляет проблему с легендой для графика 29
    
    Args:
        ax: объект оси matplotlib
        fig: объект фигуры matplotlib
    """
    # Получаем все линии на текущем графике
    lines = ax.get_lines()
    
    # Если линий нет, ничего не делаем
    if not lines:
        return
    
    # Создаем список линий и меток для легенды
    legend_lines = []
    legend_labels = []
    
    # Первая линия - основная разница корреляций
    if len(lines) > 0:
        lines[0].set_label('Разница корреляций')
        legend_lines.append(lines[0])
        legend_labels.append('Разница корреляций')
    
    # Вторая линия - DC компонента (если есть)
    if len(lines) > 1:
        lines[1].set_label('DC компонент')
        legend_lines.append(lines[1])
        legend_labels.append('DC компонент')
    
    # Третья линия - AC компонента (если есть)
    if len(lines) > 2:
        lines[2].set_label('AC компонент')
        legend_lines.append(lines[2])
        legend_labels.append('AC компонент')
    
    # Четвертая и пятая линии - пороги (если есть)
    if len(lines) > 3:
        lines[3].set_label('Порог шума')
        legend_lines.append(lines[3])
        legend_labels.append('Порог шума')
    
    # Явно создаем легенду с нашими линиями и метками
    if legend_lines:
        ax.legend(legend_lines, legend_labels, loc='upper right', fontsize=8)
    
    # Перерисовываем график
    fig.canvas.draw_idle()