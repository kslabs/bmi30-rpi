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
        #'add_markers': [37, 55, 78, 420, 660, 1460, 1700, 2380, 4296, 6200, 8104, 10058, 11976, 13880, 15784, 17738, 19654, 21558]  # Метки зон 3255, 3495
        #'add_markers': [0, 1460, 3342, 5239, 7137, 9137, 11020, 12915, 14813, 16816, 18697, 20594, 22493]  # Метки зон 3255, 3495
        'add_markers': [0]  # Метки зон 3255, 3495
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
        'text': 'Суммированные зоны с учетом смещений',  # Изменяем описание
        'show_plot': True,
        'ylim': (-200000, 200000),  # Расширяем диапазон значений
        'line1': {'label': 'High Level Зоны', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Low Level Зоны', 'color': 'red', 'visible': True},
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
        'text': 'Кросс-корреляция AC компонент High/Low зон',
        'show_plot': True,
        'ylim': (-100000, 100000),
        'line1': {'label': 'Кросс-корреляция AC', 'color': 'blue', 'visible': True},
        'line2': {'label': 'Максимум', 'color': 'red', 'visible': True},
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
        'text': 'История изменений формы сигнала',
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
        'text': 'Разница корреляций (31 - 30)',
        'show_plot': True,
        'ylim': (-1000000, 1000000),
        'line1': {'label': 'Разница корреляций', 'color': 'green', 'visible': True},
        'line2': {'label': '', 'color': 'orange', 'visible': False},
    },
    30: {
        'text': 'Противофазная корреляция High/Low',
        'show_plot': True,
        'ylim': (-1000000, 1000000),
        'line1': {'label': 'Противофазная корреляция', 'color': 'purple', 'visible': True},
        'line2': {'label': '', 'color': 'orange', 'visible': False},
    },
    31: {
        'text': 'Кросс-корреляция High/Low зон',
        'show_plot': True,
        'ylim': (-1000000, 1000000),
        'line1': {'label': 'Кросс-корреляция', 'color': 'green', 'visible': True},
        'line2': {'label': '', 'color': 'red', 'visible': False},
    }
}

# Переменные для ограничения диапазона поиска максимума
PHASE_SHIFT_MIN = 0      # Минимальное значение сдвига фаз для поиска максимума
PHASE_SHIFT_MAX = 75     # Максимальное значение сдвига фаз для поиска максимума

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

def initialize_buttons(fig, button_labels, button_width, callback_function):
    """Инициализирует кнопки для переключения графиков"""
    buttons = []
    
    # Уменьшаем ширину кнопок в 4 раза и сближаем их
    actual_width = button_width / 2  # Уменьшаем в 4 раза вместо 2
    
    # Рассчитываем доступное пространство и интервал
    available_space = 0.5  # От 0.1 до 0.9 по ширине
    button_count_per_row = 16
    total_button_width = actual_width * button_count_per_row
    spacing_per_button = (available_space - total_button_width) / (button_count_per_row - 1)
    
    for i, label in enumerate(button_labels):
        if i < 16:
            # Первый ряд кнопок (0-15)
            x_pos = 0.1 + i * (actual_width + spacing_per_button)
            ax_button = plt.axes([x_pos, 0.9, actual_width, 0.04])
        else:
            # Второй ряд кнопок (16-31)
            idx = i - 16
            x_pos = 0.1 + idx * (actual_width + spacing_per_button)
            ax_button = plt.axes([x_pos, 0.85, actual_width, 0.04])
            
        button = Button(ax_button, label)
        button.on_clicked(lambda event, l=label: callback_function(l))
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
                diff_sum_P1, diff_sum_L1,
                max_sample_index_P1, max_sample_index_L1,
                periods_P1_1, periods_P1_2, periods_L1_1, periods_L1_2,
                sum_high_level_shifted=None, sum_low_level_shifted=None,
                cross_correlation_sum=None, ac_high_level=None, ac_low_level=None,
                antiphase_correlation_sum=None, correlation_threshold=None, 
                correlation_detection_count=None, correlation_detection_threshold=None,
                correlation_changes=None, correlation_change_threshold=None,
                correlation_sound_active=False):  # Добавляем параметр со значением по умолчанию
    
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
                ax.grid(True, color='lightgray', linestyle='--', linewidth=0.5)
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
                
                # Находим индексы, соответствующие диапазону сдвигов от PHASE_SHIFT_MIN до PHASE_SHIFT_MAX
                valid_indices = np.where((shifts >= PHASE_SHIFT_MIN) & (shifts <= PHASE_SHIFT_MAX))[0]
                
                # Находим максимальную амплитуду только в этом диапазоне
                if len(valid_indices) > 0:
                    max_idx_restricted = valid_indices[np.argmax(amplitudes[valid_indices])]
                    max_shift = shifts[max_idx_restricted]
                    max_amp = amplitudes[max_idx_restricted]
                    
                    # Добавляем поиск минимума в том же диапазоне
                    min_idx_restricted = valid_indices[np.argmin(amplitudes[valid_indices])]
                    min_shift = shifts[min_idx_restricted]
                    min_amp = amplitudes[min_idx_restricted]
                else:
                    # Если нет точек в заданном диапазоне, используем весь массив
                    max_idx = np.argmax(amplitudes)
                    max_shift = shifts[max_idx]
                    max_amp = amplitudes[max_idx]
                    
                    min_idx = np.argmin(amplitudes)
                    min_shift = shifts[min_idx]
                    min_amp = amplitudes[min_idx]
                
                # Сохраняем в глобальные и __main__ переменные
                global max_amp_14, max_phase_14
                max_amp_14 = max_amp
                max_phase_14 = max_shift
                
                # Используем глобальные переменные для __main__
                import __main__
                __main__.max_amp_14 = max_amp
                __main__.max_phase_14 = max_shift
                
                #print(f"Максимальная амплитуда {max_amp:.0f} при сдвиге {max_shift}")
                
                # Вычисляем разность амплитуд и фаз
                delta_amp = max_amp - min_amp  # Разность амплитуд
                delta_phase = max_shift - min_shift  # Разность фаз
                
                # Экспортируем значения в основной модуль
                __main__.delta_amp_14 = delta_amp
                __main__.delta_phase_14 = delta_phase
                
                # Создаем простой график
                ax.clear()  # Очищаем график перед обновлением
                ax.plot(shifts, amplitudes, 'r-', linewidth=2)  # Основной график амплитуды
                
                # Выделяем зону контроля фазы светло-зеленым цветом
                ax.axvspan(PHASE_SHIFT_MIN, PHASE_SHIFT_MAX, alpha=0.15, color='lightgreen')
                
                # Добавляем вертикальные линии для границ
                ax.axvline(x=PHASE_SHIFT_MIN, color='green', linestyle='--', alpha=0.5)
                ax.axvline(x=PHASE_SHIFT_MAX, color='green', linestyle='--', alpha=0.5)
                
                # Отображаем максимум и минимум разными цветами
                ax.plot(max_shift, max_amp, 'Dg', markersize=8)  # Максимум - темно-зеленый ромбик
                ax.plot(min_shift, min_amp, 'Db', markersize=8)  # Минимум - темно-синий ромбик
                
                # Обновляем заголовок с информацией о разности
                ax.set_title(f'Верхняя ANT - max: {max_amp:.0f} / {max_shift}, min: {min_amp:.0f} / {min_shift}\n'
                             f'ΔА: {delta_amp:.0f}, ΔФ: {delta_phase:.0f}')
                
                # Настраиваем параметры графика
                ax.set_xlabel('Сдвиг фаз (семплы)')
                ax.set_ylabel('Амплитуда')
                ax.set_xlim(-100, 100)
                ax.set_ylim(0, max_amp*1.4)  # Увеличиваем масштаб для лучшей видимости
                ax.grid(True)
                # Убираем легенду для избежания дублирования
                
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
                
                # Находим индексы, соответствующие диапазону сдвигов от PHASE_SHIFT_MIN до PHASE_SHIFT_MAX
                valid_indices = np.where((shifts >= PHASE_SHIFT_MIN) & (shifts <= PHASE_SHIFT_MAX))[0]
                
                # Находим максимальную амплитуду только в этом диапазоне
                if len(valid_indices) > 0:
                    max_idx_restricted = valid_indices[np.argmax(amplitudes[valid_indices])]
                    max_shift = shifts[max_idx_restricted]
                    max_amp = amplitudes[max_idx_restricted]
                    
                    # Добавляем поиск минимума в том же диапазоне
                    min_idx_restricted = valid_indices[np.argmin(amplitudes[valid_indices])]
                    min_shift = shifts[min_idx_restricted]
                    min_amp = amplitudes[min_idx_restricted]
                else:
                    # Если нет точек в заданном диапазоне, используем весь массив
                    max_idx = np.argmax(amplitudes)
                    max_shift = shifts[max_idx]
                    max_amp = amplitudes[max_idx]
                    
                    min_idx = np.argmin(amplitudes)
                    min_shift = shifts[min_idx]
                    min_amp = amplitudes[min_idx]
                
                global max_amp_15, max_phase_15
                max_amp_15 = max_amp
                max_phase_15 = max_shift
                
                #print(f"Максимальная амплитуда {max_amp:.0f} при сдвиге {max_shift}")
                
                # Вычисляем разность амплитуд и фаз
                delta_amp = max_amp - min_amp  # Разность амплитуд
                delta_phase = max_shift - min_shift  # Разность фаз
                
                # Экспортируем значения в основной модуль
                import __main__
                __main__.delta_amp_15 = delta_amp
                __main__.delta_phase_15 = delta_phase
                
                # Создаем простой график
                ax.clear()  # Очищаем график перед обновлением
                ax.plot(shifts, amplitudes, 'r-', linewidth=2)  # Основной график амплитуды
                
                # Выделяем зону контроля фазы светло-зеленым цветом
                ax.axvspan(PHASE_SHIFT_MIN, PHASE_SHIFT_MAX, alpha=0.15, color='lightgreen')
                
                # Добавляем вертикальные линии для границ
                ax.axvline(x=PHASE_SHIFT_MIN, color='green', linestyle='--', alpha=0.5)
                ax.axvline(x=PHASE_SHIFT_MAX, color='green', linestyle='--', alpha=0.5)
                
                # Отображаем максимум и минимум разными цветами
                ax.plot(max_shift, max_amp, 'Dg', markersize=8)  # Максимум - темно-зеленый ромбик
                ax.plot(min_shift, min_amp, 'Db', markersize=8)  # Минимум - темно-синий ромбик
                
                # Обновляем заголовок с информацией о разности
                ax.set_title(f'Нижняя ANT - max: {max_amp:.0f} / {max_shift}; min: {min_amp:.0f} / {min_shift}; ΔА: {delta_amp:.0f}; ΔФ: {delta_phase:.0f}')
                
                # Настраиваем параметры графика
                ax.set_xlabel('Сдвиг фаз (семплы)')
                ax.set_ylabel('Амплитуда')
                ax.set_xlim(-100, 100)
                ax.set_ylim(0, max_amp*1.4)  # Увеличиваем масштаб для лучшей видимости
                ax.grid(True)
                # Убираем легенду для избежания дублирования
                
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
            
        elif current_oscilloscope == 16 and sum_high_level_shifted is not None and sum_low_level_shifted is not None:
            # Очищаем график
            ax.clear()
            ax.set_title('Суммированные зоны с учетом смещений')
            ax.grid(True)
            
            # Создаем массив индексов для оси X
            x_indices = np.arange(len(sum_high_level_shifted))
            
            # Строим графики с указанием меток легенды
            high_level_line, = ax.plot(x_indices, sum_high_level_shifted, 'b-', label='High Level Зоны')
            low_level_line, = ax.plot(x_indices, sum_low_level_shifted, 'r-', label='Low Level Зоны')
            
            # Устанавливаем пределы для осей
            ax.set_xlim(0, len(sum_high_level_shifted))
            max_val = max(np.max(np.abs(sum_high_level_shifted)), np.max(np.abs(sum_low_level_shifted))) * 1.5
            ax.set_ylim(-max_val, max_val)
            
            # Добавляем легенду
            ax.legend()
            
            # Обновляем данные для линий line1 и line2
            line1.set_data(x_indices, sum_high_level_shifted)
            line2.set_data(x_indices, sum_low_level_shifted)
            
            # Обновляем график
            update_needed = False

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
            
        elif current_oscilloscope == 27 and show_plot:
            # Очищаем график
            ax.clear()
            ax.set_title('История изменений формы сигнала')
            ax.grid(True)
            
            print(f"График 27: correlation_changes тип={type(correlation_changes)}, элементов={len(correlation_changes) if correlation_changes is not None else 'None'}")
            
            if correlation_changes is not None and len(correlation_changes) > 0:
                # Строим график истории изменений
                values = np.array(correlation_changes)
                x_indices = np.arange(len(values))
                
                # Рисуем основную линию
                main_line, = ax.plot(x_indices, values, 'g-', linewidth=1.5, label='Изменение формы')
                
                # Безопасное добавление пороговой линии с проверкой на None
                if correlation_change_threshold is not None:
                    threshold_line = ax.axhline(y=correlation_change_threshold, color='r', linestyle='--', 
                                              linewidth=1, alpha=0.7, label=f'Порог: {correlation_change_threshold}')
                    
                    # Безопасное вычисление y_max
                    y_max = max(np.max(values)*1.2, correlation_change_threshold*1.5, 0.05)
                    
                    # Добавляем легенду с обеими линиями
                    ax.legend(handles=[main_line, threshold_line])
                else:
                    # Если порог не определен, используем только значения данных
                    y_max = max(np.max(values)*1.2, 0.05)
                    
                    # Добавляем легенду только с основной линией
                    ax.legend(handles=[main_line])
                
                # Добавляем метки осей
                ax.set_xlim(0, max(len(values), 2))
                ax.set_ylim(0, y_max)
                ax.set_xlabel('Измерения')
                ax.set_ylabel('Изменение формы')
                
                # Обновляем линии для сохранения графика при переключении
                line1.set_data(x_indices, values)
                line2.set_data([], [])
            else:
                ax.text(0.5, 0.5, 'Нет данных об изменениях', 
                       horizontalalignment='center', verticalalignment='center',
                       transform=ax.transAxes, fontsize=14)
                line1.set_data([], [])
                line2.set_data([], [])
            
            # Обновляем график
            fig.canvas.draw_idle()
            update_needed = False

        elif current_oscilloscope == 29:
            if cross_correlation_sum is not None and antiphase_correlation_sum is not None and len(cross_correlation_sum) > 0 and len(antiphase_correlation_sum) > 0:
                # Вычисляем разницу корреляций
                correlation_diff = cross_correlation_sum - antiphase_correlation_sum
                
                # Определяем смещения для оси X
                shifts = np.arange(-100, 101)
                
                # Очищаем график
                
                ax.clear()
                
                # Вычисляем статистики шума и сигнала для отображения
                noise_area = list(range(0, 50)) + list(range(150, 200))  # Индексы [-100..-50] и [+50..+100]
                signal_area = list(range(50, 150))  # Индексы [-50..+50]
                
                noise_values = [correlation_diff[i] for i in noise_area]
                noise_mean = np.mean(noise_values)
                noise_std = np.std(noise_values) + 100
                
                signal_values = [correlation_diff[i] for i in signal_area]
                signal_mean = np.mean(signal_values)
                signal_max = max([abs(val - noise_mean) for val in signal_values])
                
                # Вычисляем SNR и порог
                snr = signal_max / max(1, noise_std)
                snr_threshold = correlation_threshold  # Порог SNR
                
                # Рисуем основной график
                diff_line, = ax.plot(shifts, correlation_diff, 'b-', linewidth=1.5, label='Разница корреляций')
                
                # Рисуем линии уровней шума
                ax.axhline(y=noise_mean, color='gray', linestyle='--', alpha=0.7, label='Средний уровень шума')
                
                # Рисуем линии для порога (средний шум ± порог)
                upper_threshold = noise_mean + noise_std * (snr_threshold + 0.1)
                lower_threshold = noise_mean - noise_std * (snr_threshold + 0.1)
                
                ax.axhline(y=upper_threshold, color='red', linestyle='-', alpha=0.5, linewidth=1, label='Порог (+10%)')
                ax.axhline(y=lower_threshold, color='red', linestyle='-', alpha=0.5, linewidth=1)
                
                # Заливаем области шума для наглядности
                ax.fill_between(shifts[0:50], noise_mean-noise_std*1.5, noise_mean+noise_std*1.5, 
                                color='lightgray', alpha=0.3, label='Шумовая зона')
                ax.fill_between(shifts[150:200], noise_mean-noise_std*1.5, noise_mean+noise_std*1.5, 
                                color='lightgray', alpha=0.3)
                
                # Заливаем сигнальную область для наглядности
                ax.fill_between(shifts[50:150], noise_mean-noise_std*1.5, noise_mean+noise_std*1.5, 
                                color='lightyellow', alpha=0.2, label='Сигнальная зона')
                
                # Добавляем текст с SNR и порогом - переместим ниже кнопок
                ax.text(0.02, 0.75, f'SNR: {snr:.2f} / {snr_threshold+0.1:.2f}',
                        transform=ax.transAxes, fontsize=10, verticalalignment='top',
                        horizontalalignment='left',
                        bbox=dict(boxstyle='round', facecolor='lightgreen' if snr > (snr_threshold+0.1) else 'white', alpha=0.6))

                # Добавляем текст с информацией о звуке - еще ниже
                if correlation_sound_active:
                    ax.text(0.02, 0.65, f'BEEP: ON ({correlation_detection_count}/{correlation_detection_threshold})',
                           transform=ax.transAxes, fontsize=10, verticalalignment='top',
                           horizontalalignment='left',
                           bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.6))
                
                # Добавляем текст с информацией о звуке
                if correlation_sound_active:
                    ax.text(0.02, 0.85, f'BEEP: ON ({correlation_detection_count}/{correlation_detection_threshold})',
                           transform=ax.transAxes, fontsize=10, verticalalignment='top',
                           horizontalalignment='left',
                           bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.6))
                
                # Определяем минимальное и максимальное значения для оси Y
                min_value = min(min(correlation_diff), lower_threshold * 1.2)
                max_value = max(max(correlation_diff), upper_threshold * 1.2)
                y_margin = (max_value - min_value) * 0.1  # 10% запас
                
                # Настраиваем пределы осей
                ax.set_xlim(-100, 100)
                ax.set_ylim(min_value - y_margin, max_value + y_margin)
                
                # Добавляем метки осей и заголовок
                ax.set_xlabel('Смещение (семплы)')
                ax.set_ylabel('Разница корреляций')
                ax.set_title('Анализ формы графика разности корреляций')
                
                # Создаём коллекцию линий для легенды с явным указанием меток
                legend_items = []
                if 'diff_line' in locals():
                    legend_items.append((diff_line, 'Разница корреляций'))

                # Добавляем в коллекцию другие линии, если они существуют
                for i, line in enumerate(ax.lines):
                    if i > 0:  # Пропускаем первую линию (уже добавлена)
                        if hasattr(line, 'get_label') and line.get_label() and not line.get_label().startswith('_'):
                            legend_items.append((line, line.get_label()))

                # Добавляем легенду только если есть элементы с метками
                if legend_items:
                    handles, labels = zip(*legend_items)
                    ax.legend(handles=handles, labels=labels, loc='upper right', fontsize=8)
                else:
                    # Добавляем пустую легенду с одним элементом
                    ax.legend(['Разница корреляций'], loc='upper right', fontsize=8)
                
                # Добавляем сетку для лучшей читаемости
                ax.grid(True, linestyle=':', alpha=0.7)
                
                # Обновляем данные основных линий
                line1.set_data(shifts, correlation_diff)
                line2.set_data([], [])
                
            else:
                # Если данных нет - очищаем график
                ax.clear()
                ax.set_title('График разности корреляций')
                ax.set_xlabel('Смещение (семплы)')
                ax.set_ylabel('Разница корреляций')
                line1.set_data([], [])
                line2.set_data([], [])

        elif current_oscilloscope == 30:
            # Очищаем график
            ax.clear()
            ax.set_title('Противофазная корреляция между High и Low зонами')
            ax.grid(True)
            
            if antiphase_correlation_sum is not None and len(antiphase_correlation_sum) > 0:
                # Создаем массив смещений для оси X
                shifts = np.arange(-100, 101)  # От -100 до 100
                
                # Строим график противофазной корреляции
                corr_line, = ax.plot(shifts, antiphase_correlation_sum, 'purple', linewidth=1.5, label='Противофазная корреляция')
                
                # Находим максимальное значение корреляции и его смещение
                max_idx = np.argmax(antiphase_correlation_sum)
                max_shift = max_idx - 100  # Центрируем относительно 0
                max_value = antiphase_correlation_sum[max_idx]
                
                # Находим минимальное значение корреляции и его смещение
                min_idx = np.argmin(antiphase_correlation_sum)
                min_shift = min_idx - 100  # Центрируем относительно 0
                min_value = antiphase_correlation_sum[min_idx]
                
                # Добавляем вертикальную линию на максимуме
                ax.axvline(x=max_shift, color='orange', linestyle='--', linewidth=1)
                
                # Добавляем вертикальную линию на минимуме
                ax.axvline(x=min_shift, color='blue', linestyle='--', linewidth=1)
                
                # Добавляем горизонтальную линию на уровне 0
                ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.7)
                
                # Добавляем точку максимума
                ax.plot(max_shift, max_value, 'o', color='orange', markersize=6)
                
                # Добавляем точку минимума
                ax.plot(min_shift, min_value, 'o', color='blue', markersize=6)
                
                # Добавляем информационный текст
                ax.text(0.05, 0.95, f'Максимум: смещение {max_shift}, значение {max_value:.0f}\nМинимум: смещение {min_shift}, значение {min_value:.0f}',
                        transform=ax.transAxes, fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
                
                # Добавляем текст о разнице между максимумом и минимумом
                ax.text(0.05, 0.80, f'Разница: {max_value - min_value:.0f}',
                        transform=ax.transAxes, fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.6))
                
                # Настраиваем несимметричные пределы по оси Y, как на графике 31
                max_abs_val = np.max(np.abs(antiphase_correlation_sum))
                y_min = -max_abs_val - 4  # Нижняя граница (смещаем на 4 вниз)
                y_max = max_abs_val * 1.4  # Верхняя граница (на 40% больше)
                
                # Устанавливаем пределы для осей
                ax.set_xlim(-100, 100)
                ax.set_ylim(y_min, y_max)
                
                # Добавляем метки осей
                ax.set_xlabel('Смещение (семплы)')
                ax.set_ylabel('Корреляция')
                
                # Обновляем данные для основных линий
                line1.set_data(shifts, antiphase_correlation_sum)
                line2.set_data([], [])
                
                # Добавляем легенду
                ax.legend()
            else:
                ax.text(0.5, 0.5, 'Данные отсутствуют', 
                      horizontalalignment='center', verticalalignment='center',
                      transform=ax.transAxes, fontsize=14)
                line1.set_data([], [])
                line2.set_data([], [])
            
            # Обновляем график
            fig.canvas.draw_idle()
            update_needed = False

        elif current_oscilloscope == 31:
            # Очищаем график
            ax.clear()
            ax.set_title('Кросс-корреляция между High и Low зонами')
            ax.grid(True)
            
            if cross_correlation_sum is not None and len(cross_correlation_sum) > 0:
                # Создаем массив смещений для оси X
                shifts = np.arange(-100, 101)  # От -100 до 100
                
                # Данные остаются неизменными, но мы смещаем оси графика
                corr_line, = ax.plot(shifts, cross_correlation_sum, 'g-', linewidth=1.5, label='Кросс-корреляция')
                
                # Находим максимальное значение корреляции и его смещение
                max_idx = np.argmax(cross_correlation_sum)
                max_shift = max_idx - 100  # Центрируем относительно 0
                max_value = cross_correlation_sum[max_idx]
                
                # Добавляем вертикальную линию на максимуме
                ax.axvline(x=max_shift, color='r', linestyle='--', linewidth=1)
                
                # Добавляем горизонтальную линию на уровне 0
                ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.7)
                
                # Добавляем точку максимума
                ax.plot(max_shift, max_value, 'ro', markersize=6)
                
                # Добавляем текст с информацией о максимуме
                ax.text(0.05, 0.95, f'Максимум при смещении: {max_shift} (значение: {max_value:.0f})',
                        transform=ax.transAxes, fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
                
                # Настраиваем несимметричные пределы по оси Y
                # Верхний предел на 40% больше чем нижний, с учетом смещения нуля вниз на 4 единицы
                max_abs_val = np.max(np.abs(cross_correlation_sum))
                y_min = -max_abs_val - (-max_abs_val * 0.5)    # Нижняя граница (смещаем на 4 вниз)
                y_max = max_abs_val * 1.3  # Верхняя граница (на 40% больше)
                
                # Устанавливаем пределы для осей
                ax.set_xlim(-100, 100)
                ax.set_ylim(y_min, y_max)
                
                # Добавляем метки осей
                ax.set_xlabel('Смещение (семплы)')
                ax.set_ylabel('Корреляция')
                
                # Обновляем данные для основных линий
                line1.set_data(shifts, cross_correlation_sum)
                line2.set_data([], [])
                
                # Добавляем легенду
                ax.legend()
            else:
                ax.text(0.5, 0.5, 'Данные отсутствуют', 
                       horizontalalignment='center', verticalalignment='center',
                       transform=ax.transAxes, fontsize=14)
                line1.set_data([], [])
                line2.set_data([], [])
            
            # Обновляем график
            fig.canvas.draw_idle()
            update_needed = False

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

def calculate_deltas(dataADC_P1, dataADC_L1, sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2):
    """
    Вычисляет дельты амплитуд и фаз между сигналами для обнаружения объектов
    
    Args:
        dataADC_P1: Данные с верхней антенны
        dataADC_L1: Данные с нижней антенны
        sum_P1_1, sum_P1_2: Суммы для верхней антенны
        sum_L1_1, sum_L1_2: Суммы для нижней антенны
        
    Returns:
        delta_amp_14: Дельта амплитуд для верхней антенны
        delta_phase_14: Дельта фаз для верхней антенны
        delta_amp_15: Дельта амплитуд для нижней антенны
        delta_phase_15: Дельта фаз для нижней антенны
    """
    # Вычисляем дельту амплитуд и фаз для верхней антенны (P1)
    max_idx_P1_1 = np.argmax(np.abs(sum_P1_1)) if len(sum_P1_1) > 0 else 0
    max_idx_P1_2 = np.argmax(np.abs(sum_P1_2)) if len(sum_P1_2) > 0 else 0
    
    max_val_P1_1 = np.abs(sum_P1_1[max_idx_P1_1]) if len(sum_P1_1) > 0 else 0
    max_val_P1_2 = np.abs(sum_P1_2[max_idx_P1_2]) if len(sum_P1_2) > 0 else 0
    
    delta_amp_14 = np.abs(max_val_P1_1 - max_val_P1_2)
    delta_phase_14 = max_idx_P1_1 - max_idx_P1_2
    
    # Вычисляем дельту амплитуд и фаз для нижней антенны (L1)
    max_idx_L1_1 = np.argmax(np.abs(sum_L1_1)) if len(sum_L1_1) > 0 else 0
    max_idx_L1_2 = np.argmax(np.abs(sum_L1_2)) if len(sum_L1_2) > 0 else 0
    
    max_val_L1_1 = np.abs(sum_L1_1[max_idx_L1_1]) if len(sum_L1_1) > 0 else 0
    max_val_L1_2 = np.abs(sum_L1_2[max_idx_L1_2]) if len(sum_L1_2) > 0 else 0
    
    delta_amp_15 = np.abs(max_val_L1_1 - max_val_L1_2)
    delta_phase_15 = max_idx_L1_1 - max_idx_L1_2
    
    return delta_amp_14, delta_phase_14, delta_amp_15, delta_phase_15

def compute_adaptive_correlation_threshold(correlation_diff, correlation_index=None, 
                                         sound_active=False, base_threshold_ratio=0.1,
                                         current_threshold=None, adaptation_rate=0.05):
    """
    Анализирует форму графика разности корреляций для обнаружения сигнала
    
    Args:
        correlation_diff: Массив со значениями разности корреляций
        correlation_index: Не используется (оставлен для совместимости)
        sound_active: Активен ли звуковой сигнал в данный момент
        base_threshold_ratio: Базовый процент над уровнем шума (0.1 = 10%)
        current_threshold: Текущее значение порога
        adaptation_rate: Скорость адаптации порога
    
    Returns:
        tuple: (отношение сигнал/шум, флаг обнаружения)
    """
    if correlation_diff is None or len(correlation_diff) < 180:
        return 2.0, False
    
    # Определяем области шума (края графика) и сигнала (центр)
    noise_area = list(range(0, 50)) + list(range(150, 200))
    signal_area = list(range(50, 150))
    
    # Вычисляем базовые статистики шума
    noise_values = [correlation_diff[i] for i in noise_area]
    noise_mean = np.mean(noise_values)
    noise_std = np.std(noise_values) + 100  # Добавляем небольшой запас
    
    # Вычисляем максимальное отклонение сигнала от среднего уровня шума
    signal_values = [correlation_diff[i] for i in signal_area]
    signal_deviations = [abs(val - noise_mean) for val in signal_values]
    max_signal_deviation = max(signal_deviations)
    
    # Вычисляем SNR как отношение максимального отклонения к СКО шума
    snr = max_signal_deviation / max(1, noise_std)
    
    # Используем фиксированный базовый порог с небольшой адаптацией
    base_threshold = 2.0  # Более низкий порог для повышения чувствительности
    
    # Если есть предыдущий порог, адаптируем его медленно
    if current_threshold is not None:
        # Замедляем адаптацию, если звук активен
        actual_rate = adaptation_rate / 10 if sound_active else adaptation_rate
        threshold = current_threshold * (1 - actual_rate) + base_threshold * actual_rate
    else:
        threshold = base_threshold
    
    # Определяем обнаружение - SNR должно превышать порог + базовый процент
    detection = snr > (threshold * (1.0 + base_threshold_ratio))
    
    return snr, detection
