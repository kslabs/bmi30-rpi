import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
import time

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
        'line1': {'label': 'Верхняя Антенна', 'color': 'purple', 'visible': True, 'marker': 'D', 'markevery': [365, 565, 1320, 1520]},
        'line2': {'label': 'Выключена', 'color': 'gray', 'visible': True},
        'use_full_range': True,
        'add_markers': [565, 365, 1320, 1520, 2285, 19565]  # Метки зон
    },
    3: {
        'text': 'Нижняя антенна',
        'show_plot': True,
        'ylim': (-35000, 47000),
        'line1': {'label': 'Выключена', 'color': 'gray', 'visible': True},
        'line2': {'label': 'Нижняя Антенна', 'color': 'chocolate', 'visible': True, 'marker': 'D', 'markevery': [350, 550, 1320, 1520]},
        'use_full_range': True,
        'add_markers': [5, 48, 120, 550, 350, 1320, 1520, 21470]  # Метки зон
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
        'ylim': (-75000, 100000),
        'line1': {'label': 'AC Sum Зона 1 (365-565)', 'color': 'blue', 'visible': True},
        'line2': {'label': 'AC Sum Зона 2 (1320-1520)', 'color': 'purple', 'visible': True},
        'use_ac': True,
        'antenna': 'upper',
        'xlim': (0, 200)
    },
    7: {
        'text': 'AC компоненты нижней антенны',
        'show_plot': True,
        'ylim': (-75000, 100000),
        'line1': {'label': 'AC Sum Зона 1 (350-550)', 'color': 'blue', 'visible': True},
        'line2': {'label': 'AC Sum Зона 2 (1320-1520)', 'color': 'purple', 'visible': True},
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
        'ylim': (-10000, 12000),
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
        'ylim': (-20000, 25000),
        'line1': {'label': '', 'color': 'blue', 'visible': False},
        'line2': {'label': '', 'color': 'red', 'visible': False},
        'xlim': (0, 200),
    },
    13: {
        'text': '12 периодов нижней антенны',
        'show_plot': True,
        'ylim': (-20000, 25000),
        'line1': {'label': '', 'color': 'blue', 'visible': False},
        'line2': {'label': '', 'color': 'red', 'visible': False},
        'xlim': (0, 200),
    },
    14: {
        'text': 'Суммарная амплитуда при сдвиге фаз от -100% до +100% для верхней антенны',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Легенда 14-1', 'color': 'cyan', 'visible': False},
        'line2': {'label': 'Легенда 14-2', 'color': 'magenta', 'visible': False},
    },
    15: {
        'text': 'Суммарная амплитуда при сдвиге фаз от -100% до +100% для нижней антенны',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Легенда 15-1', 'color': 'black', 'visible': False},
        'line2': {'label': 'Легенда 15-2', 'color': 'gray', 'visible': False},
    },
    16: {
        'text': 'Синусоидальные тестовые сигналы',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Синусоида', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Косинусоида', 'color': 'red', 'visible': True},
    },
    17: {
        'text': 'Треугольная и пилообразная волны',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Треугольная волна', 'color': 'green', 'visible': True},
        'line2': {'label': 'Пилообразная волна', 'color': 'orange', 'visible': True},
    },
    18: {
        'text': 'Импульсы и шум',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Импульсы', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Шум', 'color': 'gray', 'visible': True},
    },
    19: {
        'text': 'Модулированные сигналы',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Амплитудная модуляция', 'color': 'teal', 'visible': True},
        'line2': {'label': 'Частотная модуляция', 'color': 'brown', 'visible': True},
    },
    20: {
        'text': 'Сложные колебательные процессы',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Затухающие колебания', 'color': 'darkblue', 'visible': True},
        'line2': {'label': 'Биения', 'color': 'darkred', 'visible': True},
    },
    21: {
        'text': 'Спектр периодов верхней антенны',
        'show_plot': True,
        'ylim': (-100, 10),
        'line1': {'label': 'Спектр периодов зоны 1', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Спектр периодов зоны 2', 'color': 'red', 'visible': True},
    },
    22: {
        'text': 'Спектр периодов нижней антенны',
        'show_plot': True,
        'ylim': (-100, 10),
        'line1': {'label': 'Спектр периодов зоны 1', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Спектр периодов зоны 2', 'color': 'red', 'visible': True},
    },
    23: {
        'text': 'Корреляционный анализ',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Корреляция верхняя антенна', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Корреляция нижняя антенна', 'color': 'chocolate', 'visible': True},
    },
    24: {
        'text': 'Усредненные периоды',
        'show_plot': True,
        'ylim': (-5000, 5000),
        'line1': {'label': 'Верхняя антенна', 'color': 'purple', 'visible': True},
        'line2': {'label': 'Нижняя антенна', 'color': 'chocolate', 'visible': True},
    },
    25: {
        'text': 'Интегральный анализ',
        'show_plot': True,
        'ylim': (-30000, 30000),
        'line1': {'label': 'Интеграл верхняя', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Интеграл нижняя', 'color': 'red', 'visible': True},
    },
    26: {
        'text': 'Тестовые данные 26',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 1-1', 'color': 'cyan', 'visible': True},
        'line2': {'label': 'Тест 1-2', 'color': 'magenta', 'visible': True},
    },
    27: {
        'text': 'Тестовые данные 27',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 2-1', 'color': 'green', 'visible': True},
        'line2': {'label': 'Тест 2-2', 'color': 'orange', 'visible': True},
    },
    28: {
        'text': 'Тестовые данные 28',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 3-1', 'color': 'darkblue', 'visible': True},
        'line2': {'label': 'Тест 3-2', 'color': 'darkred', 'visible': True},
    },
    29: {
        'text': 'Тестовые данные 29',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 4-1', 'color': 'teal', 'visible': True},
        'line2': {'label': 'Тест 4-2', 'color': 'brown', 'visible': True},
    },
    30: {
        'text': 'Тестовые данные 30',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 5-1', 'color': 'navy', 'visible': True},
        'line2': {'label': 'Тест 5-2', 'color': 'maroon', 'visible': True},
    },
    31: {
        'text': 'Тестовые данные 31',
        'show_plot': True,
        'ylim': (-10000, 10000),
        'line1': {'label': 'Тест 5-1', 'color': 'navy', 'visible': True},
        'line2': {'label': 'Тест 5-2', 'color': 'maroon', 'visible': True},
    }
}

'''
# Что показывает кнопка 14/15

Кнопка 14/15 выполняет анализ фазовых сдвигов между зонами 1 и 2 антенны и показывает их оптимальное соотношение. Подробнее:

1. **График показывает зависимость амплитуды от сдвига фаз:**
   - По оси X: значения сдвига от -100 до +100 семплов
   - По оси Y: максимальная амплитуда суммарного сигнала при данном сдвиге

2. **Алгоритм работы:**
   - Берутся сигналы из зоны 1 и зоны 2 антенны (после удаления наклона)
   - Для каждого возможного сдвига фаз (от -100 до +100 семплов) вычисляется:
     - Циклический сдвиг сигнала зоны 2
     - Сумма сигналов зоны 1 и сдвинутой зоны 2
     - Максимальная амплитуда получившейся суммы

3. **Красная точка на графике:**
   - Показывает оптимальный сдвиг, при котором амплитуда максимальна
   - В легенде указывается величина этого сдвига и максимальная амплитуда

4. **Практическое значение:**
   - Этот анализ позволяет определить, при каком сдвиге фаз между зонами сигнал будет наиболее сильным
   - Пик на графике показывает, что сигналы из разных зон имеют определенную фазовую зависимость
   - Если график имеет ярко выраженный максимум, это говорит о наличии корреляции между зонами
'''

last_update_time = time.time()
UPDATE_INTERVAL = 0.05  # 20 обновлений в секунду максимум

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
    spacing = 0.0275  # Расстояние между кнопками
    button_width = 0.025  # Ширина кнопок
    
    for i, label in enumerate(button_labels):
        # Расположение кнопок: первый ряд - 0-15, второй ряд - 16-30
        if i < 16:
            # Первый ряд (кнопки 0-15)
            ax_button = plt.axes([0.1 + (i % 16) * spacing, 0.9, button_width, 0.05])
        else:
            # Второй ряд (кнопки 16-30)
            ax_button = plt.axes([0.1 + ((i - 16) % 16) * spacing, 0.85, button_width, 0.05])
        
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
                diff_sum_P1, diff_sum_L1, max_sample_index_P1, max_sample_index_L1,
                periods_P1_1, periods_P1_2, periods_L1_1, periods_L1_2):
    
    global max_amp_15, max_amp_14, max_phase_15, max_phase_14

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
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, dataADC_P1[start_sample:start_sample + num_samples])
            line2.set_data(x_axis, np.zeros(num_samples))
            
            # Добавляем ромбические маркеры для зон
            marker_points = []
            for marker in config.get('add_markers', []):
                if marker >= start_sample and marker < start_sample + num_samples:
                    marker_points.append(marker)
            
            if marker_points:
                add_diamond_markers(ax, 
                                   marker_points, 
                                   dataADC_P1[marker_points], 
                                   color='red', 
                                   size=8)
            
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
            # Импортируем функцию удаления наклона
            from __main__ import remove_slope
            
            # AC компоненты верхней антенны
            x_axis = np.arange(200)
            
            # Убираем наклон и центрируем относительно нуля
            detrended_sum_P1_1 = remove_slope(sum_P1_1)
            detrended_sum_P1_2 = remove_slope(sum_P1_2)
            detrended_ac_P1_1 = remove_slope(ac_P1_1)
            detrended_ac_P1_2 = remove_slope(ac_P1_2)
            
            # Группируем сигналы: суммы вниз, отдельные AC вверх
            offset_sum = -10000  # Сдвиг вниз для суммарных сигналов
            offset_ac =10000    # Сдвиг вверх для отдельных AC компонентов
            amp_factor = 10     # Увеличиваем амплитуду в 10 раз для зон без сумм
            
            # Отображаем суммы со смещением вниз
            line1.set_data(x_axis, detrended_sum_P1_1 + offset_sum)
            line2.set_data(x_axis, detrended_sum_P1_2 + offset_sum)
            
            # Устанавливаем легенду
            line1.set_label(f'Сумма AC зоны 1 ({offset_sum/1000}k)')
            line2.set_label(f'Сумма AC зоны 2 ({offset_sum/1000}k)')
            
            # Отображаем отдельные AC компоненты со смещением вверх и увеличенной амплитудой
            ax.plot(range(200), detrended_ac_P1_1 * amp_factor + offset_ac, color='green', 
                    label=f'AC зоны 1 (+{offset_ac/1000}k) ×{amp_factor}')
            ax.plot(range(200), detrended_ac_P1_2 * amp_factor + offset_ac, color='red', 
                    label=f'AC зоны 2 (+{offset_ac/1000}k) ×{amp_factor}')
            
            # Добавляем горизонтальные линии для нулевых уровней
            ax.axhline(y=offset_sum, color='blue', linestyle=':', alpha=0.5, label='_nolegend_')
            ax.axhline(y=offset_ac, color='green', linestyle=':', alpha=0.5, label='_nolegend_')
            
            ax.set_xlim(0, 200)
            
        elif current_oscilloscope == 7:
            # Импортируем функцию удаления наклона
            from __main__ import remove_slope
            
            # AC компоненты нижней антенны
            x_axis = np.arange(200)
            
            # Убираем наклон и центрируем относительно нуля
            detrended_sum_L1_1 = remove_slope(sum_L1_1)
            detrended_sum_L1_2 = remove_slope(sum_L1_2)
            detrended_ac_L1_1 = remove_slope(ac_L1_1)
            detrended_ac_L1_2 = remove_slope(ac_L1_2)
            
            # Группируем сигналы: суммы вниз, отдельные AC вверх
            offset_sum = -20000  # Сдвиг вниз для суммарных сигналов
            offset_ac = 20000    # Сдвиг вверх для отдельных AC компонентов
            amp_factor = 10     # Увеличиваем амплитуду в 10 раз для зон без сумм
            
            # Отображаем суммы со смещением вниз
            line1.set_data(x_axis, detrended_sum_L1_1 + offset_sum)
            line2.set_data(x_axis, detrended_sum_L1_2 + offset_sum)
            
            # Устанавливаем легенду
            line1.set_label(f'Сумма AC зоны 1 ({offset_sum/1000}k)')
            line2.set_label(f'Сумма AC зоны 2 ({offset_sum/1000}k)')
            
            # Отображаем отдельные AC компоненты со смещением вверх и увеличенной амплитудой
            ax.plot(range(200), detrended_ac_L1_1 * amp_factor + offset_ac, color='green', 
                    label=f'AC зоны 1 (+{offset_ac/1000}k) ×{amp_factor}')
            ax.plot(range(200), detrended_ac_L1_2 * amp_factor + offset_ac, color='red', 
                    label=f'AC зоны 2 (+{offset_ac/1000}k) ×{amp_factor}')
            
            # Добавляем горизонтальные линии для нулевых уровней
            ax.axhline(y=offset_sum, color='blue', linestyle=':', alpha=0.5, label='_nolegend_')
            ax.axhline(y=offset_ac, color='green', linestyle=':', alpha=0.5, label='_nolegend_')
            
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
            
            # Отрисовываем основные линии
            line1.set_data(x_axis, display_diff_sum_P1)
            line2.set_data(x_axis, display_diff_sum_L1)
            
            # Добавляем ромбические маркеры для максимумов
            if max_sample_index_P1 >= 0:
                ax.plot([max_sample_index_P1], [display_diff_sum_P1[max_sample_index_P1] + 1000], 
                        'D', color='blue', markersize=8)  # Ромбический маркер
            
            if max_sample_index_L1 >= 0:
                ax.plot([max_sample_index_L1], [display_diff_sum_L1[max_sample_index_L1] + 1000], 
                        'D', color='red', markersize=8)  # Ромбический маркер
            
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
                # Импортируем функцию удаления наклона
                from __main__ import remove_slope
                
                # Скрываем стандартные линии
                line1.set_visible(False)
                line2.set_visible(False)
                
                # Очищаем все текущие линии графика, кроме основных
                while len(ax.lines) > 2:
                    ax.lines[-1].remove()
                
                # Очищаем легенду, если она есть
                if ax.legend_ is not None:
                    ax.legend_.remove()
                    
                # Удаляем все текстовые метки на графике
                while len(ax.texts) > 0:
                    ax.texts[0].remove()
                    
                # Настраиваем параметры графика
                ax.set_title('Периоды верхней антенны (Зоны 1 и 2)')
                ax.set_xlim(0, 200)
                ax.grid(True, color='lightgray', linestyle='--', linewidth=0.5)
                
                # Основные линии разметки
                ax.axhline(y=2000, color='blue', linestyle=':', alpha=0.5)
                ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                ax.axhline(y=-2000, color='red', linestyle=':', alpha=0.5)
                
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
                    if i < len(periods_P1_1):
                        # Берем данные из массива периодов
                        data1 = periods_P1_1[i].copy()
                        # Убираем наклон с помощью функции remove_slope
                        data1 = remove_slope(data1)
                        # Сдвигаем вверх
                        data1 += 2000
                        # Рисуем линию
                        line, = ax.plot(range(200), data1, color=colors[i], alpha=0.7)
                        if i < 6:  # Для компактности добавляем в легенду только первые 6 периодов
                            legend_handles.append(line)
                            legend_labels.append(f'П{i+1}')
                    
                    # Зона 2 (сдвиг вниз)
                    if i < len(periods_P1_2):
                        # Берем данные из массива периодов
                        data2 = periods_P1_2[i].copy()
                        # Убираем наклон с помощью функции remove_slope
                        data2 = remove_slope(data2)
                        # Сдвигаем вниз
                        data2 -= 2000
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
            
        elif current_oscilloscope == 13:
            try:
                # Импортируем функцию удаления наклона
                from __main__ import remove_slope
                
                # Скрываем стандартные линии
                line1.set_visible(False)
                line2.set_visible(False)
                
                # Очищаем все текущие линии графика, кроме основных
                while len(ax.lines) > 2:
                    ax.lines[-1].remove()
                
                # Очищаем легенду, если она есть
                if ax.legend_ is not None:
                    ax.legend_.remove()
                    
                # Удаляем все текстовые метки на графике
                while len(ax.texts) > 0:
                    ax.texts[0].remove()
                    
                # Настраиваем параметры графика
                ax.set_title('Периоды нижней антенны (Зоны 1 и 2)')
                ax.set_xlim(0, 200)
                ax.grid(True, color='lightgray', linestyle='--', linewidth=0.5)
                
                # Основные линии разметки
                ax.axhline(y=2000, color='blue', linestyle=':', alpha=0.5)
                ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                ax.axhline(y=-2000, color='red', linestyle=':', alpha=0.5)
                
                # Текстовые метки
                ax.text(10, 1200, "Зона 1 (+2000)", fontsize=8, color='blue')
                ax.text(10, 200, "Центр", fontsize=8, color='black')
                ax.text(10, -800, "Зона 2 (-2000)", fontsize=8, color='red')
                
                # Используем все 12 периодов
                period = 1920
                # Используем градиент цветов для 12 периодов
                colors = plt.cm.rainbow(np.linspace(0, 1, 12))

                # Создаем линии для легенды
                legend_handles = []
                legend_labels = []

                # Отображаем все 12 периодов для обеих зон нижней антенны
                for i in range(12):
                    # Зона 1 (сдвиг вверх)
                    if i < len(periods_L1_1):
                        # Берем данные из массива периодов
                        data1 = periods_L1_1[i].copy()
                        # Убираем наклон с помощью функции remove_slope
                        data1 = remove_slope(data1)
                        # Сдвигаем вверх
                        data1 += 2000
                        # Рисуем линию
                        line, = ax.plot(range(200), data1, color=colors[i], alpha=0.7)
                        if i < 6:  # Для компактности добавляем в легенду только первые 6 периодов
                            legend_handles.append(line)
                            legend_labels.append(f'П{i+1}')
                    
                    # Зона 2 (сдвиг вниз)
                    if i < len(periods_L1_2):
                        # Берем данные из массива периодов
                        data2 = periods_L1_2[i].copy()
                        # Убираем наклон с помощью функции remove_slope
                        data2 = remove_slope(data2)
                        # Сдвигаем вниз
                        data2 -= 2000
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
                print(f"Ошибка отображения кнопки 13: {e}")
                # Восстанавливаем график при ошибке
                ax.clear()
                line1.set_visible(True)
                line2.set_visible(True)
                ax.set_title("График восстановлен после ошибки")
                ax.grid(True)
                ax.legend([line1, line2], ['Верхняя антенна', 'Нижняя антенна'])
                plt.draw()
                return True, False
            
        elif current_oscilloscope == 14:
            try:
                print("Начинаем построение графика для кнопки 14...")
                
                # Скрываем существующие линии, но не удаляем их
                line1.set_visible(False)
                line2.set_visible(False)

                # Очищаем все кроме основных линий
                while len(ax.lines) > 2:
                    ax.lines[-1].remove()
                    
                # Очищаем легенду
                if ax.legend_ is not None:
                    ax.legend_.remove()
                    
                # Удаляем все текстовые метки
                while len(ax.texts) > 0:
                    ax.texts[0].remove()
                
                # Получаем копии данных для работы
                local_sum_P1_1 = sum_P1_1.copy()
                local_sum_P1_2 = sum_P1_2.copy()
                
                # Удаление наклона - встроенная реализация без импорта
                def local_remove_slope(signal):
                    if len(signal) == 0:
                        return signal
                    size = len(signal)
                    chunk_size = size // 5
                    start_mean = np.mean(signal[:chunk_size])
                    end_mean = np.mean(signal[-chunk_size:])
                    slope = (end_mean - start_mean) / (size - chunk_size)
                    offset = start_mean - slope * (chunk_size // 2)
                    x = np.arange(size)
                    line = slope * x + offset
                    return signal - line
                
                # Обрабатываем данные
                detrended_sum_P1_1 = local_remove_slope(local_sum_P1_1)
                detrended_sum_P1_2 = local_remove_slope(local_sum_P1_2)
                
                # Диапазон сдвигов фаз для анализа
                shift_range = range(-100, 101, 2)  # Шаг 2 для ускорения
                amplitudes = np.zeros(len(shift_range))
                shifts = np.array(list(shift_range))
                
                #print(f"Анализируем {len(shifts)} вариантов сдвига...")
                
                # Перебираем все сдвиги и сохраняем амплитуды
                for i, shift in enumerate(shift_range):
                    # Циклический сдвиг второй зоны
                    shifted_signal = np.roll(detrended_sum_P1_2, shift)
                    # Суммирование сигналов
                    sum_signal = detrended_sum_P1_1 + shifted_signal
                    # Находим максимальную амплитуду (по модулю)
                    amplitudes[i] = np.max(np.abs(sum_signal))
                
                # Находим сдвиг с максимальной амплитудой
                max_idx = np.argmax(amplitudes)
                max_shift = shifts[max_idx]
                max_amp = amplitudes[max_idx]
                
                # Сохраняем в глобальные и __main__ переменные
                global max_amp_14, max_phase_14
                max_amp_14 = max_amp
                max_phase_14 = max_shift
                
                # Используем глобальные переменные для __main__
                import __main__
                __main__.max_amp_14 = max_amp
                __main__.max_phase_14 = max_shift
                
                #print(f"Максимальная амплитуда {max_amp:.0f} при сдвиге {max_shift}")
                
                # Создаем простой график
                ax.plot(shifts, amplitudes, 'b-', linewidth=2, label='Амплитуда')
                ax.plot(max_shift, max_amp, 'Dr', markersize=8, label=f'Максимум ({max_shift})')  # 'Dr' - красный ромб
                
                # Настраиваем параметры графика
                ax.set_title(f'Амплитуда от сдвига фаз (макс: {max_amp:.0f} @ {max_shift})')
                ax.set_xlabel('Сдвиг фаз (семплы)')
                ax.set_ylabel('Амплитуда')
                ax.set_xlim(-100, 100)
                ax.set_ylim(max_amp*0.4, max_amp*1.1)
                ax.grid(True)
                ax.legend()
                
                # Обновляем график
                plt.draw()
                fig.canvas.flush_events()
                
                print("График для кнопки 14 построен успешно")
                return True, False
            
            except Exception as e:
                print(f"ОШИБКА при отображении кнопки 14: {e}")
                import traceback
                traceback.print_exc()
                
                # Восстанавливаем график при ошибке
                ax.clear()
                ax.set_title("Ошибка построения графика")
                ax.grid(True)
                plt.draw()
                return True, False
            
        elif current_oscilloscope == 15:
            global max_amp_15, max_phase_15
            try:
                #print("Начинаем построение графика для кнопки 15 (нижняя антенна)...")
                
                # Скрываем существующие линии, но не удаляем их
                line1.set_visible(False)
                line2.set_visible(False)

                # Очищаем все кроме основных линий
                while len(ax.lines) > 2:
                    ax.lines[-1].remove()
                    
                # Очищаем легенду
                if ax.legend_ is not None:
                    ax.legend_.remove()
                    
                # Удаляем все текстовые метки
                while len(ax.texts) > 0:
                    ax.texts[0].remove()
                
                # Получаем копии данных для работы
                local_sum_L1_1 = sum_L1_1.copy()
                local_sum_L1_2 = sum_L1_2.copy()
                
                # Удаление наклона - встроенная реализация без импорта
                def local_remove_slope(signal):
                    if len(signal) == 0:
                        return signal
                    size = len(signal)
                    chunk_size = size // 5
                    start_mean = np.mean(signal[:chunk_size])
                    end_mean = np.mean(signal[-chunk_size:])
                    slope = (end_mean - start_mean) / (size - chunk_size)
                    offset = start_mean - slope * (chunk_size // 2)
                    x = np.arange(size)
                    line = slope * x + offset
                    return signal - line
                
                # Обрабатываем данные нижней антенны
                detrended_sum_L1_1 = local_remove_slope(local_sum_L1_1)
                detrended_sum_L1_2 = local_remove_slope(local_sum_L1_2)
                
                # Диапазон сдвигов фаз для анализа
                shift_range = range(-100, 101, 2)  # Шаг 2 для ускорения
                amplitudes = np.zeros(len(shift_range))
                shifts = np.array(list(shift_range))
                
                #print(f"Анализируем {len(shifts)} вариантов сдвига для нижней антенны...")
                
                # Перебираем все сдвиги и сохраняем амплитуды
                for i, shift in enumerate(shift_range):
                    # Циклический сдвиг второй зоны
                    shifted_signal = np.roll(detrended_sum_L1_2, shift)
                    # Суммирование сигналов
                    sum_signal = detrended_sum_L1_1 + shifted_signal
                    # Находим максимальную амплитуду (по модулю)
                    amplitudes[i] = np.max(np.abs(sum_signal))
                
                # Находим сдвиг с максимальной амплитудой
                max_idx = np.argmax(amplitudes)
                max_shift = shifts[max_idx]
                max_amp = amplitudes[max_idx]
                global max_amp_15, max_phase_15
                max_amp_15 = max_amp
                max_phase_15 = max_shift
                
                #print(f"Максимальная амплитуда {max_amp:.0f} при сдвиге {max_shift}")
                
                # Создаем простой график
                ax.plot(shifts, amplitudes, 'r-', linewidth=2, label='Амплитуда')
                ax.plot(max_shift, max_amp, 'Db', markersize=8, label=f'Максимум ({max_shift})')  # 'Db' - синий ромб
                
                # Настраиваем параметры графика
                ax.set_title(f'Амплитуда от сдвига фаз - нижняя антенна (макс: {max_amp:.0f} @ {max_shift})')
                ax.set_xlabel('Сдвиг фаз (семплы)')
                ax.set_ylabel('Амплитуда')
                ax.set_xlim(-100, 100)
                ax.set_ylim(max_amp*0.4, max_amp*1.1)
                ax.grid(True)
                ax.legend()
                
                # Обновляем график
                plt.draw()
                fig.canvas.flush_events()
                
                #print("График для кнопки 15 построен успешно")
                
                # Используем глобальные переменные
                import __main__
                __main__.max_amp_15 = max_amp
                __main__.max_phase_15 = max_shift
                
                return True, False
            
            except Exception as e:
                print(f"ОШИБКА при отображении кнопки 15: {e}")
                import traceback
                traceback.print_exc()
                
                # Восстанавливаем график при ошибке
                ax.clear()
                ax.set_title("Ошибка построения графика для нижней антенны")
                ax.grid(True)
                plt.draw()
                return True, False
            
        elif current_oscilloscope == 16:
            # Тестовая осциллограмма 1: Синусоида и косинусоида
            x = np.linspace(0, 4*np.pi, num_samples)
            line1.set_data(x, 8000 * np.sin(x))
            line2.set_data(x, 8000 * np.cos(x))
            ax.set_xlim(0, 4*np.pi)
            
        elif current_oscilloscope == 17:
            # Тестовая осциллограмма 2: Треугольная и пилообразная волны
            x = np.linspace(0, 10, num_samples)
            # Треугольная волна
            triangle = 8000 * np.abs((x % 2) - 1) - 4000
            # Пилообразная волна
            sawtooth = 8000 * (x % 1) - 4000
            
            line1.set_data(x, triangle)
            line2.set_data(x, sawtooth)
            ax.set_xlim(0, 10)
            
        elif current_oscilloscope == 18:
            # Тестовая осциллограмма 3: Импульсы и шум
            x = np.linspace(0, 10, num_samples)
            # Импульсы
            pulses = np.zeros_like(x)
            for i in range(1, 10, 2):
                idx = (x > i) & (x < i + 0.5)
                pulses[idx] = 8000
            
            # Шум
            noise = np.random.normal(0, 3000, size=len(x))
            
            line1.set_data(x, pulses)
            line2.set_data(x, noise)
            ax.set_xlim(0, 10)
            
        elif current_oscilloscope == 19:
            # Тестовая осциллограмма 4: Амплитудная и частотная модуляция
            x = np.linspace(0, 10, num_samples)
            
            # Амплитудная модуляция
            carrier = np.sin(2 * np.pi * 5 * x)
            modulator = 0.5 * (1 + np.sin(2 * np.pi * 0.5 * x))
            am = 8000 * carrier * modulator
            
            # Частотная модуляция
            modulation_index = 5
            fm = 6000 * np.sin(2 * np.pi * x + modulation_index * np.sin(2 * np.pi * 0.3 * x))
            
            line1.set_data(x, am)
            line2.set_data(x, fm)
            ax.set_xlim(0, 10)
            
        elif current_oscilloscope == 20:
            # Тестовая осциллограмма 5: Затухающие колебания и биения
            x = np.linspace(0, 10, num_samples)
            
            # Затухающие колебания
            damped = 8000 * np.exp(-0.4 * x) * np.sin(2 * np.pi * 2 * x)
            
            # Биения
            beats = 5000 * np.sin(2 * np.pi * 2.0 * x) + 5000 * np.sin(2 * np.pi * 2.1 * x)
            
            line1.set_data(x, damped)
            line2.set_data(x, beats)
            ax.set_xlim(0, 10)
            
        elif current_oscilloscope >= 15:
            # Для кнопок 14, 15 создаем простые графики с легендами
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
        if current_oscilloscope in [12, 13]:
            # Отключаем автомасштабирование для тяжелых графиков
            ax.relim(visible_only=True)
            ax.autoscale_view(tight=True, scalex=False, scaley=False)
        else:
            # Обычное обновление границ для других графиков
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

# В файл bmi30_plt.py добавим функцию для ускоренной отрисовки с использованием blitting
def init_blit(fig, ax, line1, line2):
    """Инициализация для ускоренной отрисовки с blitting"""
    # Сохраняем фон для быстрой отрисовки
    fig.canvas.draw()
    background = fig.canvas.copy_from_bbox(ax.bbox)
    return background

def fast_draw(fig, ax, background, lines_to_update):
    """Быстрая отрисовка графика с использованием blitting"""
    # Восстанавливаем фон
    fig.canvas.restore_region(background)
    
    # Обновляем только изменившиеся линии
    for line in lines_to_update:
        ax.draw_artist(line)
    
    # Обновляем только измененную область
    fig.canvas.blit(ax.bbox)
    fig.canvas.flush_events()

# Добавьте эту новую функцию
def add_diamond_markers(ax, x_points, y_points, color='red', size=8, label=None):
    """Добавляет ромбические маркеры в указанных точках"""
    ax.plot(x_points, y_points, 'D', color=color, markersize=size, label=label)
    return ax
