import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

# Словарь настроек для всех кнопок - центральное место хранения конфигурации
BUTTON_CONFIG = {
    0: {
        'text': 'Выключаем вывод, но работаем',
        'show_plot': False,
        'ylim': (-30000, 30000)
    },
    1: {
        'text': 'Верхняя и нижняя антенны',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'line1': {'label': 'Верхняя Антенна', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Нижняя Антенна', 'color': 'chocolate', 'visible': True},
        'use_full_range': True  # Использовать полный диапазон выборки
    },
    2: {
        'text': 'Верхняя антенна',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'line1': {'label': 'Верхняя Антенна', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Выключена', 'color': 'gray', 'visible': True},
        'use_full_range': True,
        'add_markers': [565, 365, 1320, 1520, 2285, 19565]  # Метки зон
    },
    3: {
        'text': 'Нижняя антенна',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'line1': {'label': 'Выключена', 'color': 'gray', 'visible': True},
        'line2': {'label': 'Нижняя Антенна', 'color': 'chocolate', 'visible': True},
        'use_full_range': True,
        'add_markers': [5, 38, 120, 550, 350, 1320, 1520, 21470]  # Метки зон
    },
    4: {
        'text': 'Зоны ожидания',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'line1': {'label': 'Зона 1 (365-565)', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Зона 2 (1320-1520)', 'color': 'chocolate', 'visible': True},
        'use_zones': True,
        'xlim': (0, 200)
    },
    5: {
        'text': 'DC компоненты сигнала',
        'show_plot': True,
        'ylim': (-35000, 44000),
        'line1': {'label': 'Зона 1 (350-550)', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Зона 2 (1320-1520)', 'color': 'chocolate', 'visible': True},
        'use_zones': True,
        'xlim': (0, 200)
    },
    6: {
        'text': 'AC компоненты верхней антенны',
        'show_plot': True,
        'ylim': (-5000, 5000),
        'line1': {'label': 'AC Sum Зона 1 (365-565)', 'color': 'blue', 'visible': True},
        'line2': {'label': 'AC Sum Зона 2 (1320-1520)', 'color': 'red', 'visible': True},
        'use_ac': True,
        'antenna': 'upper',
        'xlim': (0, 200)
    },
    7: {
        'text': 'AC компоненты нижней антенны',
        'show_plot': True,
        'ylim': (-5000, 5000),
        'line1': {'label': 'AC Sum Зона 1 (350-550)', 'color': 'blue', 'visible': True},
        'line2': {'label': 'AC Sum Зона 2 (1320-1520)', 'color': 'red', 'visible': True},
        'use_ac': True,
        'antenna': 'lower',
        'xlim': (0, 200)
    },
    8: {
        'text': 'Разностные AC сигналы антенн',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Разность AC верхней (1-2)', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Разность AC нижней (1-2)', 'color': 'red', 'visible': True},
        'use_diff': True,
        'xlim': (0, 200)
    },
    9: {
        'text': 'Сумма 6 разностей AC сигналов антенн',
        'show_plot': True,
        'ylim': (-60000, 60000),
        'line1': {'label': 'Сумма 6 разностей верхней ANT', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Сумма 6 разностей нижней ANT', 'color': 'red', 'visible': True},
        'use_diff_sum': True,
        'xlim': (0, 200)
    },
    10: {
        'text': 'Спектральный анализ',
        'show_plot': True,
        'ylim': (-100, 10),
        'line1': {'label': 'Спектр верхней антенны', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Спектр нижней антенны', 'color': 'chocolate', 'visible': True},
        'use_spectrum': True
    },
    11: {
        'text': 'Спектральный анализ разностных сигналов',
        'show_plot': True,
        'ylim': (-100, 10),
        'line1': {'label': 'Спектр разности верхней антенны', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Спектр разности нижней антенны', 'color': 'red', 'visible': True},
        'use_diff_spectrum': True,
        'f_min': 40,
        'f_max': 1000
    },
    12: {
        'text': '12 периодов верхней антенны',
        'show_plot': True,
        'ylim': (-5000, 5000),
        'line1': {'label': '', 'color': 'blue', 'visible': False},
        'line2': {'label': '', 'color': 'red', 'visible': False},
        'xlim': (0, 200),
    },
    13: {
        'text': 'Резерв 13',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Легенда 13-1', 'color': 'green', 'visible': True},
        'line2': {'label': 'Легенда 13-2', 'color': 'orange', 'visible': True},
    },
    14: {
        'text': 'Резерв 14',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Легенда 14-1', 'color': 'cyan', 'visible': True},
        'line2': {'label': 'Легенда 14-2', 'color': 'magenta', 'visible': True},
    },
    15: {
        'text': 'Резерв 15',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Легенда 15-1', 'color': 'black', 'visible': True},
        'line2': {'label': 'Легенда 15-2', 'color': 'gray', 'visible': True},
    }
}

def initialize_plot(CHUNK, dataADC_P1, dataADC_L1):
    fig, ax = plt.subplots()
    ax.grid(color='lightgray', linestyle='--', linewidth=0.5)
    x_axis = np.linspace(0, CHUNK, CHUNK)
    plt.subplots_adjust(left=0.09, right=0.99, top=0.99, bottom=0.125, wspace=0.0, hspace=0.0)

    line1, = ax.plot(x_axis[:CHUNK], np.zeros(CHUNK), label='Верхняя Антенна')
    line2, = ax.plot(x_axis[:CHUNK], np.zeros(CHUNK), label='Нижняя Антенна')
    ax.legend()  # Отображаем легенду один раз
    ax.set_ylim(-30000, 30000)
    plt.ion()

    return fig, ax, line1, line2

def update_plot(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax):
    start_sample = int(start_sample_slider.val)
    num_samples = int(num_samples_slider.val)
    
    # Ограничиваем значения
    start_sample = max(0, min(start_sample, len(dataADC_P1) - num_samples))
    num_samples = max(10, min(num_samples, len(dataADC_P1) - start_sample))
    
    x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
    line1.set_data(x_axis, dataADC_P1[start_sample:start_sample+num_samples])
    line2.set_data(x_axis, dataADC_L1[start_sample:start_sample+num_samples])
    ax.set_xlim(start_sample, start_sample + num_samples)
    ax.relim()
    ax.autoscale_view()
    return start_sample, num_samples, True

def update_start(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax, CHUNK):
    start_sample = int(start_sample_slider.val)
    max_length = CHUNK - start_sample
    num_samples_slider.valmax = max_length
    num_samples_slider.ax.set_xlim(num_samples_slider.valmin, max_length)
    num_samples_slider.set_val(min(num_samples_slider.val, max_length))
    return update_plot(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax)

def initialize_sliders(fig, ax, CHUNK, start_sample, num_samples, update_start, update_plot):
    ax_slider1 = plt.axes([0.1, 0.01, 0.81, 0.03])
    ax_slider2 = plt.axes([0.1, 0.05, 0.81, 0.03])

    start_sample_slider = Slider(ax_slider1, 'Старт', 0, CHUNK, valinit=start_sample, valstep=10)
    num_samples_slider = Slider(ax_slider2, 'Длина', 10, CHUNK, valinit=num_samples, valstep=10)

    start_sample_slider.on_changed(update_start)
    num_samples_slider.on_changed(update_plot)

    return start_sample_slider, num_samples_slider

def initialize_buttons(fig, button_labels, button_width, switch_graph_handler):
    buttons = []
    spacing = 0.0275  # Уменьшаем расстояние между кнопками
    button_width = 0.025  # Ширина кнопок
    for i, label in enumerate(button_labels):
        ax_button = plt.axes([0.1 + i * spacing, 0.9, button_width, 0.05])
        button = Button(ax_button, label)
        button.on_clicked(lambda event, lbl=label: switch_graph_handler(lbl))
        buttons.append(button)
    return buttons

def initialize_text_box():
    ax_text = plt.axes([0.1, 0.95, 0.48, 0.03])
    ax_text.spines['top'].set_linestyle(':')
    ax_text.spines['top'].set_color('lightgray')
    ax_text.spines['bottom'].set_color('none')
    ax_text.spines['left'].set_color('none')
    ax_text.spines['right'].set_color('none')
    ax_text.xaxis.set_visible(False)
    ax_text.yaxis.set_visible(False)
    text_box = plt.text(0.5, 0.5, '', horizontalalignment='center', verticalalignment='center', transform=ax_text.transAxes)
    return text_box

def switch_graph(label, buttons, light_green, text_box, current_oscilloscope, update_needed, show_plot, fig):
    """Обрабатывает нажатия кнопок переключения графиков"""
    button_id = int(label)
    config = BUTTON_CONFIG.get(button_id, {'text': f'Резерв {button_id}', 'show_plot': True})
    
    # Сбрасываем цвет всех кнопок
    for i in range(len(buttons)):
        buttons[i].color = 'white'
        buttons[i].hovercolor = 'lightgray'
        buttons[i].ax.set_facecolor('white')
    
    # Устанавливаем цвет активной кнопки
    buttons[button_id].ax.set_facecolor(light_green)
    buttons[button_id].color = light_green
    buttons[button_id].hovercolor = light_green
    
    # Устанавливаем описание из конфигурации
    text_box.set_text(config['text'])
    
    # Обновляем состояние
    if button_id == 0:
        show_plot[0] = not show_plot[0]  # Для кнопки 0 переключаем видимость
    else:
        current_oscilloscope[0] = button_id
        show_plot[0] = config.get('show_plot', True)
        update_needed[0] = True
    
    print(f"Переключение на график {button_id}")
    fig.canvas.draw_idle()
    
    return current_oscilloscope[0], update_needed[0], show_plot[0]

def set_active_button_color(current_oscilloscope, buttons, light_green, text_box):
    """Устанавливает цвет активной кнопки и соответствующее описание"""
    # Сбрасываем цвет всех кнопок
    for i in range(len(buttons)):
        if i != current_oscilloscope:
            buttons[i].color = 'white'
            buttons[i].hovercolor = 'lightgray'
            buttons[i].ax.set_facecolor('white')
    
    # Устанавливаем цвет активной кнопки
    buttons[current_oscilloscope].ax.set_facecolor(light_green)
    buttons[current_oscilloscope].color = light_green
    buttons[current_oscilloscope].hovercolor = light_green
    
    # Устанавливаем текст из конфигурации
    config = BUTTON_CONFIG.get(current_oscilloscope, {'text': f'Резерв {current_oscilloscope}'})
    text_box.set_text(config['text'])

def update_graph(show_plot, update_needed, current_oscilloscope, start_sample, num_samples, 
                dataADC_P1, dataADC_L1, line1, line2, ax, fig, 
                zone_P1_1, zone_P1_2, zone_L1_1, zone_L1_2, 
                ac_P1_1, ac_P1_2, ac_L1_1, ac_L1_2, 
                dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2,
                sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2,
                diff_sum_P1, diff_sum_L1, max_sample_index_P1, max_sample_index_L1):
    """Обновляет график на основе конфигурации каждой кнопки"""
    
    if not show_plot:
        return True, False
    
    if show_plot:
        # Получаем конфигурацию для текущей кнопки
        config = BUTTON_CONFIG.get(current_oscilloscope, {})
        
        # Очищаем легенду и дополнительные линии
        if hasattr(ax, 'legend_') and ax.legend_ is not None:
            ax.legend_.remove()
        
        # Удаляем все текстовые метки на графике
        while len(ax.texts) > 0:
            ax.texts[0].remove()
        
        # Удаляем все горизонтальные и вертикальные линии
        for line in ax.get_lines():
            if line != line1 and line != line2:
                line.remove()
                
        # Очищаем все дополнительные линии
        while len(ax.lines) > 2:
            ax.lines[-1].remove()
        
        # Восстанавливаем видимость основных линий
        line1.set_visible(True)
        line2.set_visible(True)
        
        # Устанавливаем пределы осей из конфигурации
        if 'ylim' in config:
            ax.set_ylim(*config['ylim'])
        
        # Настраиваем параметры линий из конфигурации
        if 'line1' in config:
            line1.set_label(config['line1'].get('label', 'Линия 1'))
            line1.set_color(config['line1'].get('color', 'blue'))
            line1.set_visible(config['line1'].get('visible', True))
            
        if 'line2' in config:
            line2.set_label(config['line2'].get('label', 'Линия 2'))
            line2.set_color(config['line2'].get('color', 'red'))
            line2.set_visible(config['line2'].get('visible', True))
        
        # Обработка данных в зависимости от типа графика
        if current_oscilloscope == 1:
            # Верхняя и нижняя антенны (полные данные)
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, dataADC_P1[start_sample:start_sample + num_samples])
            line2.set_data(x_axis, dataADC_L1[start_sample:start_sample + num_samples])
            ax.set_xlim(start_sample, start_sample + num_samples)
            
        elif current_oscilloscope == 2:
            # Только верхняя антенна с маркерами
            data_with_markers = dataADC_P1.copy()
            for marker in config.get('add_markers', []):
                if marker < len(data_with_markers):
                    data_with_markers[marker] += 10000
            
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, data_with_markers[start_sample:start_sample + num_samples])
            line2.set_data(x_axis, np.zeros(num_samples))
            ax.set_xlim(start_sample, start_sample + num_samples)
            
        elif current_oscilloscope == 3:
            # Только нижняя антенна с маркерами
            data_with_markers = dataADC_L1.copy()
            for marker in config.get('add_markers', []):
                if marker < len(data_with_markers):
                    data_with_markers[marker] += 10000
            
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, np.zeros(num_samples))
            line2.set_data(x_axis, data_with_markers[start_sample:start_sample + num_samples])
            ax.set_xlim(start_sample, start_sample + num_samples)
            
        elif current_oscilloscope == 4:
            # Зоны верхней антенны
            x_axis = np.arange(200)
            line1.set_data(x_axis, zone_P1_1)
            line2.set_data(x_axis, zone_P1_2)
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 5:
            # Зоны нижней антенны
            x_axis = np.arange(200)
            line1.set_data(x_axis, zone_L1_1)
            line2.set_data(x_axis, zone_L1_2)
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 6:
            # AC компоненты верхней антенны
            x_axis = np.arange(200)
            ac_sum_P1_1 = sum_P1_1 - (dc_P1_1 * 12)
            ac_sum_P1_2 = sum_P1_2 - (dc_P1_2 * 12)
            line1.set_data(x_axis, ac_sum_P1_1)
            line2.set_data(x_axis, ac_sum_P1_2)
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 7:
            # AC компоненты нижней антенны
            x_axis = np.arange(200)
            ac_sum_L1_1 = sum_L1_1 - (dc_L1_1 * 12)
            ac_sum_L1_2 = sum_L1_2 - (dc_L1_2 * 12)
            line1.set_data(x_axis, ac_sum_L1_1)
            line2.set_data(x_axis, ac_sum_L1_2)
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 8:
            # Разностные сигналы
            x_axis = np.arange(200)
            diff_P1 = ac_P1_1 - ac_P1_2
            diff_L1 = ac_L1_1 - ac_L1_2
            line1.set_data(x_axis, diff_P1)
            line2.set_data(x_axis, diff_L1)
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 9:
            # Суммы разностей
            x_axis = np.arange(200)
            display_diff_sum_P1 = diff_sum_P1.copy()
            display_diff_sum_L1 = diff_sum_L1.copy()
            
            if max_sample_index_P1 >= 0:
                display_diff_sum_P1[max_sample_index_P1] += 10000
            if max_sample_index_L1 >= 0:
                display_diff_sum_L1[max_sample_index_L1] += 10000
            
            line1.set_data(x_axis, display_diff_sum_P1)
            line2.set_data(x_axis, display_diff_sum_L1)
            line1.set_label(f'Сумма 6 разностей верхней ANT (max: {max_sample_index_P1})')
            line2.set_label(f'Сумма 6 разностей нижней ANT (max: {max_sample_index_L1})')
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 10:
            # Спектральный анализ
            spectrum_P1 = np.abs(np.fft.fft(dataADC_P1))
            spectrum_L1 = np.abs(np.fft.fft(dataADC_L1))
            
            max_spectrum_P1 = np.maximum(np.max(spectrum_P1), 1e-10)
            max_spectrum_L1 = np.maximum(np.max(spectrum_L1), 1e-10)
            
            spectrum_P1_db = 20 * np.log10(np.maximum(spectrum_P1, 1e-10) / max_spectrum_P1)
            spectrum_L1_db = 20 * np.log10(np.maximum(spectrum_L1, 1e-10) / max_spectrum_L1)
            
            line1.set_data(range(len(spectrum_P1_db)), spectrum_P1_db)
            line2.set_data(range(len(spectrum_L1_db)), spectrum_L1_db)
            
            ax.set_xlim(0, len(spectrum_P1_db)//2)
            
        elif current_oscilloscope == 11:
            # Спектральный анализ разностей
            fs = 384000
            f_min = config.get('f_min', 40)
            f_max = config.get('f_max', 1000)
            
            if len(diff_sum_P1) > 0 and len(diff_sum_L1) > 0:
                freqs_diff_P1, spectrum_diff_P1 = calculate_spectrum(diff_sum_P1, fs, f_min, f_max)
                freqs_diff_L1, spectrum_diff_L1 = calculate_spectrum(diff_sum_L1, fs, f_min, f_max)
                
                line1.set_data(freqs_diff_P1, spectrum_diff_P1)
                line2.set_data(freqs_diff_L1, spectrum_diff_L1)
                
                ax.set_xlim(f_min, f_max)
                
        elif current_oscilloscope == 12:
            try:
                # Скрываем стандартные линии
                line1.set_visible(False)
                line2.set_visible(False)
                
                # Очищаем все текущие линии графика, кроме основных
                while len(ax.lines) > 2:
                    ax.lines[-1].remove()
                
                # Очищаем легенду, если она есть
                if ax.legend_ is not None:
                    ax.legend_.remove()
                    
                # Настраиваем параметры графика
                ax.set_title('Периоды верхней антенны (Зоны 1 и 2)')
                ax.set_xlim(0, 200)
                ax.set_ylim(-6000, 6000)
                ax.grid(True, color='lightgray', linestyle='--', linewidth=0.5)
                
                # Основные линии разметки
                ax.axhline(y=1000, color='blue', linestyle=':', alpha=0.5)
                ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                ax.axhline(y=-1000, color='red', linestyle=':', alpha=0.5)
                
                # Текстовые метки
                ax.text(10, 1200, "Зона 1 (+1000)", fontsize=8, color='blue')
                ax.text(10, 200, "Центр", fontsize=8, color='black')
                ax.text(10, -800, "Зона 2 (-1000)", fontsize=8, color='red')
                
                # Используем все 12 периодов
                period = 1920
                # Используем градиент цветов для 12 периодов
                colors = plt.cm.rainbow(np.linspace(0, 1, 12))

                # Создаем линии для легенды
                legend_handles = []
                legend_labels = []

                # Отображаем все 12 периодов для обеих зон
                for i in range(12):
                    # Зона 1 (сдвиг вверх)
                    start_idx1 = 365 + i * period
                    if start_idx1 + 200 <= len(dataADC_P1):
                        # Берем данные
                        data1 = dataADC_P1[start_idx1:start_idx1 + 200].copy()
                        # Центрируем
                        if len(dc_P1_1) == 200:
                            data1 = data1 - np.mean(dc_P1_1)
                        # Сдвигаем вверх
                        data1 += 1000
                        # Рисуем линию
                        line, = ax.plot(range(200), data1, color=colors[i], alpha=0.7)
                        if i < 6:  # Для компактности добавляем в легенду только первые 6 периодов
                            legend_handles.append(line)
                            legend_labels.append(f'П{i+1}')
                    
                    # Зона 2 (сдвиг вниз)
                    start_idx2 = 1320 + i * period
                    if start_idx2 + 200 <= len(dataADC_P1):
                        # Берем данные
                        data2 = dataADC_P1[start_idx2:start_idx2 + 200].copy()
                        # Центрируем
                        if len(dc_P1_2) == 200:
                            data2 = data2 - np.mean(dc_P1_2)
                        # Сдвигаем вниз
                        data2 -= 1000
                        # Рисуем пунктирную линию
                        ax.plot(range(200), data2, color=colors[i], alpha=0.7, linestyle='--')
                
                # Добавляем легенду в правом верхнем углу
                if legend_handles:
                    ax.legend(legend_handles, legend_labels, loc='upper right', fontsize='small')
                
                # Важно - принудительно обновляем график
                plt.draw()
                fig.canvas.flush_events()
                
                return True, False
                
            except Exception as e:
                print(f"Ошибка отображения кнопки 12: {e}")
                # Восстанавливаем график при ошибке
                ax.clear()
                line1.set_visible(True)
                line2.set_visible(True)
                ax.set_title("График восстановлен после ошибки")
                ax.grid(True)
                ax.legend([line1, line2], ['Верхняя антенна', 'Нижняя антенна'])
                plt.draw()
                return True, False
            
        elif current_oscilloscope >= 13 and current_oscilloscope <= 15:
            # Для кнопок 13, 14, 15 создаем простые графики с легендами
            x_axis = np.arange(start_sample, start_sample + num_samples)
            
            # Используем случайные данные для демонстрации (можно заменить на реальные)
            demo_data1 = np.sin(np.linspace(0, 10, num_samples)) * 10000 + np.random.normal(0, 1000, num_samples)
            demo_data2 = np.cos(np.linspace(0, 10, num_samples)) * 10000 + np.random.normal(0, 1000, num_samples)
            
            line1.set_data(x_axis, demo_data1)
            line2.set_data(x_axis, demo_data2)
            
            # Установка нужных границ
            ax.set_xlim(start_sample, start_sample + num_samples)
            
        # Добавляем легенду в конце для всех графиков
        ax.legend()
        
        # Обновляем границы и перерисовываем график
        ax.relim()
        if current_oscilloscope not in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
            ax.autoscale_view()
        
        fig.canvas.draw()
        fig.canvas.flush_events()

    if not plt.fignum_exists(fig.number):
        return False, False
    
    return True, False

def calculate_spectrum(data, fs, f_min, f_max):
    """Расчет спектра сигнала"""
    if len(data) == 0:
        return np.array([0]), np.array([0])
    
    n_fft = 32768
    data = data - np.mean(data)
    window = np.blackman(len(data))
    windowed_data = data * window
    padded_data = np.pad(windowed_data, (0, n_fft - len(windowed_data)))
    
    spectrum = np.fft.fft(padded_data)
    freqs = np.fft.fftfreq(n_fft, 1/fs)
    
    positive_freq_mask = freqs >= 0
    freqs = freqs[positive_freq_mask]
    spectrum = np.abs(spectrum[positive_freq_mask])
    
    mask = (freqs >= f_min) & (freqs <= f_max)
    freqs = freqs[mask]
    spectrum = spectrum[mask]
    
    spectrum = 20 * np.log10(spectrum / np.max(spectrum) + 1e-10)
    
    window_size = 5
    spectrum = np.convolve(spectrum, np.ones(window_size)/window_size, mode='same')
    
    return freqs, spectrum
