import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

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
    spacing = 0.0275  # Уменьшаем расстояние между кнопками в 2 раза (было 0.06)
    button_width = 0.025  # Увеличиваем ширину кнопок в 1.5 раза (было 0.0125)
    for i, label in enumerate(button_labels):
        ax_button = plt.axes([0.1 + i * spacing, 0.9, button_width, 0.05])
        button = Button(ax_button, label)
        button.on_clicked(lambda event, lbl=label: switch_graph_handler(lbl))
        buttons.append(button)
    return buttons

def initialize_text_box():
    ax_text = plt.axes([0.1, 0.95, 0.48, 0.03])  # Укорачиваем текстовое поле еще на 20%
    ax_text.spines['top'].set_linestyle(':')  # Делаем рамку точечной
    ax_text.spines['top'].set_color('lightgray')  # Делаем рамку светлее
    ax_text.spines['bottom'].set_color('none')  # Удаляем нижнюю рамку
    ax_text.spines['left'].set_color('none')  # Удаляем левую рамку
    ax_text.spines['right'].set_color('none')  # Удаляем правую рамку
    ax_text.xaxis.set_visible(False)  # Удаляем подписи снизу рамки
    ax_text.yaxis.set_visible(False)  # Удаляем подписи слева рамки
    text_box = plt.text(0.5, 0.5, '', horizontalalignment='center', verticalalignment='center', transform=ax_text.transAxes)
    return text_box

def switch_graph(label, buttons, light_green, text_box, current_oscilloscope, update_needed, show_plot, fig):
    """Обрабатывает нажатия кнопок переключения графиков"""
    button_id = int(label)
    
    # Если это кнопка 0 (выключение графика)
    if button_id == 0:
        show_plot[0] = not show_plot[0]
        print("Переключение видимости осциллограммы")
    else:
        # Для всех остальных кнопок
        current_oscilloscope[0] = button_id
        show_plot[0] = True
        update_needed[0] = True
        
    # Обновляем цвет кнопки и текст описания
    set_active_button_color(current_oscilloscope[0], buttons, light_green, text_box)
    
    print(f"Переключение на график {current_oscilloscope[0]}")
    fig.canvas.draw_idle()
    
    return current_oscilloscope[0], update_needed[0], show_plot[0]

def set_active_button_color(current_oscilloscope, buttons, light_green, text_box):
    """Устанавливает цвет активной кнопки и соответствующее описание"""
    
    # Сбрасываем цвет всех кнопок
    for button in buttons:
        button.ax.set_facecolor('white')
        button.color = 'white' 
        button.hovercolor = 'lightgray'
    
    # Словарь соответствия номеров кнопок и их описаний
    button_descriptions = {
        0: 'Выключаем вывод, но работаем',
        1: 'Верхняя и нижняя антенны (сырые данные)',
        2: 'Верхняя антенна',
        3: 'Нижняя антенна',
        4: 'Зоны ожидания',
        5: 'DC компоненты сигнала',
        6: 'AC компоненты верхней антенны',
        7: 'AC компоненты нижней антенны',
        8: 'Разностные AC сигналы антенн',
        9: 'Сумма 6 разностей AC сигналов антенн',
        10: 'Спектральный анализ',
        11: 'Спектральный анализ разностных сигналов',
        12: '12 периодов верхней антенны',
        13: 'Резерв 13',
        14: 'Резерв 14',
        15: 'Резерв 15'
    }
    
    # Устанавливаем цвет активной кнопки
    if current_oscilloscope < len(buttons):
        buttons[current_oscilloscope].ax.set_facecolor(light_green)
        buttons[current_oscilloscope].color = light_green
        buttons[current_oscilloscope].hovercolor = light_green
    
    # Устанавливаем описание кнопки
    description = button_descriptions.get(current_oscilloscope, f'Резерв {current_oscilloscope}')
    text_box.set_text(description)

def update_graph(show_plot, update_needed, current_oscilloscope, start_sample, num_samples, 
                dataADC_P1, dataADC_L1, line1, line2, ax, fig, 
                zone_P1_1, zone_P1_2, zone_L1_1, zone_L1_2, 
                ac_P1_1, ac_P1_2, ac_L1_1, ac_L1_2, 
                dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2,
                sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2,
                diff_sum_P1, diff_sum_L1, max_sample_index_P1, max_sample_index_L1):
    if not show_plot:
        return True, False
    
    if show_plot:
        # Очищаем легенду
        if hasattr(ax, 'legend_') and ax.legend_ is not None:
            ax.legend_.remove()
        
        # Очищаем дополнительные линии (оставляем только две основные)
        while len(ax.lines) > 2:
            ax.lines[-1].remove()
        
        # Восстанавливаем видимость основных линий по умолчанию
        line1.set_visible(True)
        line2.set_visible(True)
        
        if current_oscilloscope in [1, 2, 3]:
            # Стандартный диапазон для основных графиков
            ax.set_ylim(-35000, 44000)
            
        elif current_oscilloscope in [4, 5]:
            # Диапазон для зон ожидания
            ax.set_ylim(-35000, 44000)
            
        elif current_oscilloscope in [6, 7]:
            # Уменьшенный диапазон для AC компонент
            ax.set_ylim(-5000, 5000)
            
        elif current_oscilloscope in [8, 9]:
            # Расширенный диапазон для сумм
            ax.set_ylim(-250000, 250000)

        # Далее ваш существующий код для отрисовки графиков...
        if current_oscilloscope == 1:
            # Используем значения ползунков для отображения данных
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, dataADC_P1[start_sample:start_sample + num_samples])
            line2.set_data(x_axis, dataADC_L1[start_sample:start_sample + num_samples])
            line1.set_label('Верхняя Антенна')
            line2.set_label('Нижняя Антенна')
            line1.set_color('purple')
            line2.set_color('chocolate')
            ax.set_xlim(start_sample, start_sample + num_samples)
        elif current_oscilloscope == 2:
            # Обновляем метки зон для отображения на графике
            #dataADC_P1[1320] = dataADC_P1[1320] + 10000
            #dataADC_P1[1520] = dataADC_P1[1520] + 10000
            
            dataADC_P1[565] = dataADC_P1[565] + 10000  # Изменено с 550 на 565
            dataADC_P1[365] = dataADC_P1[365] + 10000  # Изменено с 350 на 365
            dataADC_P1[1320] = dataADC_P1[1320] + 10000
            dataADC_P1[1520] = dataADC_P1[1520] + 10000
            dataADC_P1[2285] = dataADC_P1[2285] + 10000
            dataADC_P1[19565] = dataADC_P1[19565] + 10000
            
            
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, dataADC_P1[start_sample:start_sample + num_samples])
            line2.set_data(x_axis, np.zeros(num_samples))
            line1.set_label('Верхняя Антенна')
            line2.set_label('Выключена')
            line1.set_color('purple')
            line2.set_color('gray')
            ax.set_xlim(start_sample, start_sample + num_samples)
        elif current_oscilloscope == 3:
            # Добавляем метки зон
            dataADC_L1[5] = dataADC_L1[5] + 10000
            dataADC_L1[38] = dataADC_L1[38] + 10000
            dataADC_L1[120] = dataADC_L1[120] + 10000
            
            dataADC_L1[550] = dataADC_L1[550] + 10000
            dataADC_L1[350] = dataADC_L1[350] + 10000
            dataADC_L1[1320] = dataADC_L1[1320] + 10000
            dataADC_L1[1520] = dataADC_L1[1520] + 10000
            dataADC_L1[21470] = dataADC_L1[21470] + 10000
            
            x_axis = np.arange(start_sample, start_sample + num_samples)
            line1.set_data(x_axis, np.zeros(num_samples))
            line2.set_data(x_axis, dataADC_L1[start_sample:start_sample + num_samples])
            line1.set_label('Выключена')
            line2.set_label('Нижняя Антенна')
            line1.set_color('gray')
            line2.set_color('chocolate')
            ax.set_xlim(start_sample, start_sample + num_samples)
        elif current_oscilloscope == 4:
            # Используем сохраненные зоны верхней антенны
            x_axis = np.arange(200)
            line1.set_data(x_axis, zone_P1_1)  # Первая зона (365-565)
            line2.set_data(x_axis, zone_P1_2)  # Вторая зона (1320-1520)
            line1.set_label('Зона 1 (365-565)')  # Обновлена метка
            line2.set_label('Зона 2 (1320-1520)')
            line1.set_color('purple')
            line2.set_color('chocolate')
            ax.set_xlim(0, 200)
            ax.set_ylim(-35000, 44000)  # Возвращаем исходный масштаб по Y
            
        elif current_oscilloscope == 5:
            # Используем сохраненные зоны нижней антенны
            x_axis = np.arange(200)
            line1.set_data(x_axis, zone_L1_1)  # Первая зона (350-550)
            line2.set_data(x_axis, zone_L1_2)  # Вторая зона (1320-1520)
            line1.set_label('Зона 1 (350-550)')
            line2.set_label('Зона 2 (1320-1520)')
            line1.set_color('purple')
            line2.set_color('chocolate')
            ax.set_xlim(0, 200)
            ax.set_ylim(-35000, 44000)  # Возвращаем исходный масштаб по Y
            
        elif current_oscilloscope == 6:
            # Для верхней антенны: суммы минус DC
            x_axis = np.arange(200)
            ac_sum_P1_1 = sum_P1_1 - (dc_P1_1 * 12)  # Умножаем dc на 12, так как сумма из 12 зон
            ac_sum_P1_2 = sum_P1_2 - (dc_P1_2 * 12)
            line1.set_data(x_axis, ac_sum_P1_1)
            line2.set_data(x_axis, ac_sum_P1_2)
            line1.set_label('AC Sum Зона 1 (365-565)')
            line2.set_label('AC Sum Зона 2 (1320-1520)')
            line1.set_color('blue')
            line2.set_color('red')
            ax.set_xlim(0, 200)
            ax.set_ylim(-30000, 40000)  # Используем тот же диапазон что и для сумм
            
        elif current_oscilloscope == 7:
            # Для нижней антенны: суммы минус DC
            x_axis = np.arange(200)
            ac_sum_L1_1 = sum_L1_1 - (dc_L1_1 * 12)  # Умножаем dc на 12, так как сумма из 12 зон
            ac_sum_L1_2 = sum_L1_2 - (dc_L1_2 * 12)
            line1.set_data(x_axis, ac_sum_L1_1)
            line2.set_data(x_axis, ac_sum_L1_2)
            line1.set_label('AC Sum Зона 1 (350-550)')
            line2.set_label('AC Sum Зона 2 (1320-1520)')
            line1.set_color('blue')
            line2.set_color('red')
            ax.set_xlim(0, 200)
            ax.set_ylim(-30000, 40000)  # Используем тот же диапазон что и для сумм
            
        elif current_oscilloscope == 8:
            # Разностные сигналы для обеих антенн
            x_axis = np.arange(200)
            diff_P1 = ac_P1_1 - ac_P1_2  # Разность AC сигналов верхней антенны
            diff_L1 = ac_L1_1 - ac_L1_2  # Разность AC сигналов нижней антенны
            
            line1.set_data(x_axis, diff_P1)
            line2.set_data(x_axis, diff_L1)
            line1.set_label('Разность AC верхней (1-2)')
            line2.set_label('Разность AC нижней (1-2)')
            line1.set_color('blue')
            line2.set_color('red')
            ax.set_xlim(0, 200)
            ax.set_ylim(-10000, 10000)
            
        elif current_oscilloscope == 9:
            # Накопленные за 6 измерений разности
            x_axis = np.arange(200)
            
            # Создаем копии массивов для отображения
            display_diff_sum_P1 = diff_sum_P1.copy()
            display_diff_sum_L1 = diff_sum_L1.copy()
            
            # Добавляем метки на максимумах
            if max_sample_index_P1 >= 0:
                display_diff_sum_P1[max_sample_index_P1] += 10000
            if max_sample_index_L1 >= 0:
                display_diff_sum_L1[max_sample_index_L1] += 10000
            
            line1.set_data(x_axis, display_diff_sum_P1)
            line2.set_data(x_axis, display_diff_sum_L1)
            line1.set_label(f'Сумма 6 разностей верхней ANT (max: {max_sample_index_P1})')
            line2.set_label(f'Сумма 6 разностей нижней ANT (max: {max_sample_index_L1})')
            line1.set_color('blue')
            line2.set_color('red')
            ax.set_xlim(0, 200)
            ax.set_ylim(-60000, 60000)  # Увеличиваем диапазон в 6 раз
            
        elif current_oscilloscope == 10:
            # Вычисление спектра с защитой от деления на ноль
            spectrum_P1 = np.abs(np.fft.fft(dataADC_P1))
            spectrum_L1 = np.abs(np.fft.fft(dataADC_L1))
            
            # Находим максимальные значения, защищаясь от нулей
            max_spectrum_P1 = np.maximum(np.max(spectrum_P1), 1e-10)
            max_spectrum_L1 = np.maximum(np.max(spectrum_L1), 1e-10)
            
            # Безопасное вычисление логарифма
            spectrum_P1_db = 20 * np.log10(np.maximum(spectrum_P1, 1e-10) / max_spectrum_P1)
            spectrum_L1_db = 20 * np.log10(np.maximum(spectrum_L1, 1e-10) / max_spectrum_L1)
            
            line1.set_data(range(len(spectrum_P1_db)), spectrum_P1_db)
            line2.set_data(range(len(spectrum_L1_db)), spectrum_L1_db)
            
            ax.set_xlim(0, len(spectrum_P1_db)//2)
            ax.set_ylim(-100, 10)
            
            update_needed = False
            
        elif current_oscilloscope == 11:
            # Спектральный анализ разностных сигналов
            fs = 384000
            f_min = 40
            f_max = 1000
            
            if len(diff_sum_P1) > 0 and len(diff_sum_L1) > 0:
                # Рассчитываем спектры разностных сигналов
                freqs_diff_P1, spectrum_diff_P1 = calculate_spectrum(diff_sum_P1, fs, f_min, f_max)
                freqs_diff_L1, spectrum_diff_L1 = calculate_spectrum(diff_sum_L1, fs, f_min, f_max)
                
                # Отображаем спектры
                line1.set_data(freqs_diff_P1, spectrum_diff_P1)
                line2.set_data(freqs_diff_L1, spectrum_diff_L1)
                line1.set_label('Спектр разностей верхней ANT')
                line2.set_label('Спектр разностей нижней ANT')
                line1.set_color('blue')
                line2.set_color('red')
                
                ax.set_xlim(f_min, f_max)
                ax.set_ylim(0, max(np.max(spectrum_diff_P1), np.max(spectrum_diff_L1)) * 1.1)
                ax.set_xlabel('Частота, Гц')
                ax.set_ylabel('Амплитуда')
                ax.grid(True)
            
        ax.legend()
        ax.relim()
        if current_oscilloscope not in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
            ax.autoscale_view()  # Автомасштабирование только для неопределенных графиков
        fig.canvas.draw()
        fig.canvas.flush_events()

    if not plt.fignum_exists(fig.number):
        return False, False

    return True, False

def calculate_spectrum(data, fs, f_min, f_max):
    """
    Улучшенный расчет спектра сигнала
    """
    if len(data) == 0:
        return np.array([0]), np.array([0])
    
    # Увеличиваем размер FFT и количество точек для анализа
    n_fft = 32768  # Увеличиваем размер FFT для лучшего разрешения
    
    # Удаляем постоянную составляющую
    data = data - np.mean(data)
    
    # Применяем окно Блэкмана-Харриса для лучшего частотного разрешения
    window = np.blackman(len(data))
    windowed_data = data * window
    
    # Добавляем нули для улучшения разрешения
    padded_data = np.pad(windowed_data, (0, n_fft - len(windowed_data)))
    
    # Выполняем FFT
    spectrum = np.fft.fft(padded_data)
    freqs = np.fft.fftfreq(n_fft, 1/fs)
    
    # Берем только положительные частоты
    positive_freq_mask = freqs >= 0
    freqs = freqs[positive_freq_mask]
    spectrum = np.abs(spectrum[positive_freq_mask])
    
    # Находим индексы для нужного диапазона частот
    mask = (freqs >= f_min) & (freqs <= f_max)
    freqs = freqs[mask]
    spectrum = spectrum[mask]
    
    # Нормализуем спектр и переводим в дБ
    spectrum = 20 * np.log10(spectrum / np.max(spectrum) + 1e-10)
    
    # Сглаживание спектра
    window_size = 5
    spectrum = np.convolve(spectrum, np.ones(window_size)/window_size, mode='same')
    
    return freqs, spectrum
