import spidev
import numpy as np
import pyaudio
from gpiozero import DigitalOutputDevice, Button as GPIOButton


# Устанавливаем исходное состояние всех выводов
def initialize_gpio():
    gpio12 = DigitalOutputDevice(12, initial_value=False)
    gpio5 = DigitalOutputDevice(5, initial_value=False)
    gpio6 = DigitalOutputDevice(6, initial_value=False)  # GPIO6 для инверсии при прерываниях
    return gpio12, gpio5, gpio6

# Функция установки значения цифровых резисторов для mcp4251
def set_resistor(spi, channel, value):
    spi.xfer2([0b00000000 | (channel << 4), value])  # Используем xfer2 для отправки и получения ответа
    response = spi.xfer2([0b00001100 | (channel << 4), 0xFF])

# Функция обработки прерывания
def toggle_gpio6_and_update_resistors(gpio6):
    gpio6.toggle()

# Функция обновления графика при изменении ползунков
def update_plot(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax, CHUNK):
    start_sample = int(start_sample_slider.val)
    num_samples = int(num_samples_slider.val)
    
    # Ограничиваем значения
    start_sample = max(0, min(start_sample, len(dataADC_P1) - num_samples))
    num_samples = max(10, min(num_samples, len(dataADC_P1) - start_sample))
    
    if start_sample + num_samples > len(dataADC_P1):
        num_samples = len(dataADC_P1) - start_sample
    
    x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
    line1.set_data(x_axis, dataADC_P1[start_sample:start_sample+num_samples])
    line2.set_data(x_axis, dataADC_L1[start_sample:start_sample+num_samples])
    
    ax.set_xlim(start_sample, start_sample + num_samples)
    ax.relim()
    ax.autoscale_view()
    return start_sample, num_samples

# Обработчик для ползунка "Старт"
def update_start(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax, CHUNK):
    start_sample = int(start_sample_slider.val)
    max_length = CHUNK - start_sample
    num_samples_slider.valmax = max_length
    num_samples_slider.ax.set_xlim(num_samples_slider.valmin, max_length)
    num_samples_slider.set_val(min(num_samples_slider.val, max_length))
    return update_plot(val, start_sample_slider, num_samples_slider, dataADC_P1, dataADC_L1, line1, line2, ax, CHUNK)

# Функция переключения графиков
def switch_graph(label, buttons, light_green, text_box, fig, current_oscilloscope, update_needed, show_plot):
    for button in buttons:
        button.ax.set_facecolor('lightgray')
        button.color = 'lightgray'
        button.hovercolor = 'lightgray'
    if label == '0':
        show_plot = False
        buttons[0].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[0].color = light_green
        buttons[0].hovercolor = light_green
        text_box.set_text('0')
        print("График отключен для экономии ресурсов.")
    elif label == '1':
        current_oscilloscope = int(label)
        show_plot = True
        update_needed = True
        buttons[1].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[1].color = light_green
        buttons[1].hovercolor = light_green
        text_box.set_text('Верхняя и нижняя антенны')
        print(f"Переключение на график {current_oscilloscope}")
    elif label == '2':
        current_oscilloscope = int(label)
        show_plot = True
        update_needed = True
        buttons[2].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[2].color = light_green
        buttons[2].hovercolor = light_green
        text_box.set_text('Верхняя антенна')
        print(f"Переключение на график {current_oscilloscope}")
    elif label == '3':
        current_oscilloscope = int(label)
        show_plot = True
        update_needed = True
        buttons[3].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[3].color = light_green
        buttons[3].hovercolor = light_green
        text_box.set_text('Нижняя антенна')
        print(f"Переключение на график {current_oscilloscope}")
    elif label == '4':
        current_oscilloscope = int(label)
        show_plot = True
        update_needed = True
        buttons[4].ax.set_facecolor(light_green)  # Изменяем цвет на светло-зеленый
        buttons[4].color = light_green
        buttons[4].hovercolor = light_green
        text_box.set_text('Резерв')
        print(f"Переключение на график {current_oscilloscope}")
    fig.canvas.draw_idle()  # Обновляем отображение

# Функция обратного вызова для аудио
def audio_callback(in_data, frame_count, time_info, status):
    global dataADC_P1, dataADC_L1
    new_data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    dataADC_P1 = np.concatenate((dataADC_P1[-CHUNK:], new_data[:, 0]))  # Ограничиваем размер
    dataADC_L1 = np.concatenate((dataADC_L1[-CHUNK:], new_data[:, 1]))  # Ограничиваем размер
    return in_data, pyaudio.paContinue
