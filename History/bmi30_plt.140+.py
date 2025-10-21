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
    for i, label in enumerate(button_labels):
        ax_button = plt.axes([0.1 + i * 0.06, 0.9, button_width, 0.05])
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
    for button in buttons:
        button.ax.set_facecolor('lightgray')
        button.color = 'lightgray'
        button.hovercolor = 'lightgray'
    if label == '0':
        show_plot[0] = False
        buttons[0].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[0].color = light_green
        buttons[0].hovercolor = light_green
        text_box.set_text('Выключаем осциллограмму, но программа работает')
        print("График отключен для экономии ресурсов.")
    elif label == '1':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[1].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[1].color = light_green
        buttons[1].hovercolor = light_green
        text_box.set_text('Верхняя и нижняя антенны (сырые данные)')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '2':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[2].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[2].color = light_green
        buttons[2].hovercolor = light_green
        text_box.set_text('Верхняя антенна (сырые данные)')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '3':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[3].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[3].color = light_green
        buttons[3].hovercolor = light_green
        text_box.set_text('Нижняя антенна (сырые данные)')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '4':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[4].ax.set_facecolor(light_green)
        buttons[4].color = light_green
        buttons[4].hovercolor = light_green
        text_box.set_text('Зоны ожидания метки верхней антенны (сырые данные)')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '5':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[5].ax.set_facecolor(light_green)
        buttons[5].color = light_green
        buttons[5].hovercolor = light_green
        text_box.set_text('Зоны ожидания метки нижней антенны (сырые данные)')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '6':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[6].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[6].color = light_green
        buttons[6].hovercolor = light_green
        text_box.set_text('Резерв')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '7':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[7].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[7].color = light_green
        buttons[7].hovercolor = light_green
        text_box.set_text('Резерв')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '8':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[8].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[8].color = light_green
        buttons[8].hovercolor = light_green
        text_box.set_text('Резерв')
        print(f"Переключение на график {current_oscilloscope[0]}")
    elif label == '9':
        current_oscilloscope[0] = int(label)
        show_plot[0] = True
        update_needed[0] = True
        buttons[9].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[9].color = light_green
        buttons[9].hovercolor = light_green
        text_box.set_text('Резерв')
        print(f"Переключение на график {current_oscilloscope[0]}")
    fig.canvas.draw_idle()  # Обновляем отображение
    return current_oscilloscope[0], update_needed[0], show_plot[0]

def set_active_button_color(current_oscilloscope, buttons, light_green, text_box):
    if current_oscilloscope == 1:
        buttons[1].ax.set_facecolor(light_green)
        buttons[1].color = light_green
        buttons[1].hovercolor = light_green
        text_box.set_text('Верхняя и нижняя антенны')
    elif current_oscilloscope == 2:
        buttons[2].ax.set_facecolor(light_green)
        buttons[2].color = light_green
        buttons[2].hovercolor = light_green
        text_box.set_text('Верхняя антенна')
    elif current_oscilloscope == 3:
        buttons[3].ax.set_facecolor(light_green)
        buttons[3].color = light_green
        buttons[3].hovercolor = light_green
        text_box.set_text('Нижняя антенна')
    elif current_oscilloscope == 4:
        buttons[4].ax.set_facecolor(light_green)
        buttons[4].color = light_green
        buttons[4].hovercolor = light_green
        text_box.set_text('Резерв')
    elif current_oscilloscope == 5:
        buttons[5].ax.set_facecolor(light_green)
        buttons[5].color = light_green
        buttons[5].hovercolor = light_green
        text_box.set_text('Резерв')
    elif current_oscilloscope == 6:
        buttons[6].ax.set_facecolor(light_green)
        buttons[6].color = light_green
        buttons[6].hovercolor = light_green
        text_box.set_text('Резерв')
    elif current_oscilloscope == 7:
        buttons[7].ax.set_facecolor(light_green)
        buttons[7].color = light_green
        buttons[7].hovercolor = light_green
        text_box.set_text('Резерв')
    elif current_oscilloscope == 8:
        buttons[8].ax.set_facecolor(light_green)
        buttons[8].color = light_green
        buttons[8].hovercolor = light_green
        text_box.set_text('Резерв')
    elif current_oscilloscope == 9:
        buttons[9].ax.set_facecolor(light_green)
        buttons[9].color = light_green
        buttons[9].hovercolor = light_green
        text_box.set_text('Резерв')
    else:
        buttons[0].ax.set_facecolor(light_green)
        buttons[0].color = light_green
        buttons[0].hovercolor = light_green
        text_box.set_text('Выключаем вывод, но работаем')

def update_graph(show_plot, update_needed, current_oscilloscope, start_sample, num_samples, dataADC_P1, dataADC_L1, line1, line2, ax, fig, zone_P1_1, zone_P1_2, zone_L1_1, zone_L1_2):
    if show_plot:
        len_P1 = len(dataADC_P1)
        len_L1 = len(dataADC_L1)
        
        # Очищаем текущую легенду
        ax.legend_.remove() if ax.legend_ else None
        
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
            dataADC_P1[565] = dataADC_P1[565] + 10000  # Изменено с 550 на 565
            dataADC_P1[365] = dataADC_P1[365] + 10000  # Изменено с 350 на 365
            dataADC_P1[1320] = dataADC_P1[1320] + 10000
            dataADC_P1[1520] = dataADC_P1[1520] + 10000
            
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
            dataADC_L1[550] = dataADC_L1[550] + 10000
            dataADC_L1[350] = dataADC_L1[350] + 10000
            dataADC_L1[1320] = dataADC_L1[1320] + 10000
            dataADC_L1[1520] = dataADC_L1[1520] + 10000
            
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
            
        ax.legend()  # Добавляем обновленную легенду
        ax.relim()
        ax.autoscale_view()
        fig.canvas.draw()
        fig.canvas.flush_events()

    if not plt.fignum_exists(fig.number):
        return False, False

    return True, False
