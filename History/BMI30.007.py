import time
import pyaudio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
import os
import spidev
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button as GPIOButton
from rpi_hardware_pwm import HardwarePWM
from bmi30_def import initialize_gpio, set_resistor, toggle_gpio6_and_update_resistors, update_plot
from bmi30_plt import initialize_plot, update_start, switch_graph, update_plot, initialize_buttons, set_active_button_color, update_graph  # Импортируем функцию update_graph
import threading  # Импортируем модуль threading

version = 8.00  # Обновляем версию

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = GPIOButton(26, pull_up=True)

# Исходные значения цифровых резисторов
resistor_values = {"dr0_0": 200, "dr0_1": 00, "dr1_0": 75, "dr1_1": 255}
print(f"состояние резисторов: {resistor_values}")

# Привязываем обработчик прерывания
button.when_pressed = lambda: toggle_gpio6_and_update_resistors(gpio6)

# Настраиваем SPI для двух MCP4251
spi0 = spidev.SpiDev()
spi1 = spidev.SpiDev()

spi0.open(0, 0)
spi1.open(0, 1)

spi0.max_speed_hz = 10000000  # 1 МГц
spi1.max_speed_hz = 10000000  # 1 МГц

spi0.mode = 0
spi0.lsbfirst = False

spi1.mode = 0
spi1.lsbfirst = False

# Устанавливаем цифровые резисторы в исходное состояние
set_resistor(spi0, 0, resistor_values["dr0_0"])
set_resistor(spi0, 1, resistor_values["dr0_1"])
set_resistor(spi1, 0, resistor_values["dr1_0"])
set_resistor(spi1, 1, resistor_values["dr1_1"])

# Настройка параметров АЦП
CHUNK = 23400  # Количество сэмплов на буфер
RATE = 384000  # Частота дискретизации

# Создаём экземпляр PyAudio
p = pyaudio.PyAudio()

# Инициализируем массивы для данных
dataADC1 = np.zeros(CHUNK, dtype=int)
dataADC2 = np.zeros(CHUNK, dtype=int)

# Создаем событие для обновления графика
update_event = threading.Event()

# Функция обратного вызова для аудио
def audio_callback(in_data, frame_count, time_info, status):
    global dataADC1, dataADC2
    new_data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    dataADC1 = np.concatenate((dataADC1[-CHUNK:], new_data[:, 0]))  # Ограничиваем размер
    dataADC2 = np.concatenate((dataADC2[-CHUNK:], new_data[:, 1]))  # Ограничиваем размер
    update_event.set()  # Устанавливаем событие для обновления графика
    return in_data, pyaudio.paContinue

# Создаём поток захвата аудио
stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback)

# Переменные управления осциллограммами
current_oscilloscope = 1  # Указывает, какая осциллограмма отображается
start_sample = 0  # Начало отображаемого диапазона
num_samples = CHUNK  # Количество отображаемых семплов
update_needed = False  # Флаг для отслеживания необходимости обновления графика
show_plot = True  # Флаг для отображения осциллограммы

# Визуализация осциллограммы
fig, ax, line1, line2 = initialize_plot(CHUNK, dataADC1, dataADC2)

# Функция обновления графика при изменении ползунков
def update_plot_handler(val):
    global start_sample, num_samples, update_needed
    start_sample, num_samples, update_needed = update_plot(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax)

# Обработчик для ползунка "Старт"
def update_start_handler(val):
    global start_sample, num_samples, update_needed
    start_sample, num_samples, update_needed = update_start(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax, CHUNK)

# Добавляем ползунки для изменения отображаемого диапазона
ax_slider1 = plt.axes([0.1, 0.01, 0.81, 0.03])
ax_slider2 = plt.axes([0.1, 0.05, 0.81, 0.03])

start_sample_slider = Slider(ax_slider1, 'Старт', 0, CHUNK, valinit=start_sample, valstep=10)
num_samples_slider = Slider(ax_slider2, 'Длина', 10, CHUNK, valinit=num_samples, valstep=10)

start_sample_slider.on_changed(update_start_handler)
num_samples_slider.on_changed(update_plot_handler)

# Добавляем текстовое поле для отображения названия активной кнопки
ax_text = plt.axes([0.1, 0.95, 0.48, 0.03])  # Укорачиваем текстовое поле еще на 20%
ax_text.spines['top'].set_linestyle(':')  # Делаем рамку точечной
ax_text.spines['top'].set_color('lightgray')  # Делаем рамку светлее
ax_text.spines['bottom'].set_color('none')  # Удаляем нижнюю рамку
ax_text.spines['left'].set_color('none')  # Удаляем левую рамку
ax_text.spines['right'].set_color('none')  # Удаляем правую рамку
ax_text.xaxis.set_visible(False)  # Удаляем подписи снизу рамки
ax_text.yaxis.set_visible(False)  # Удаляем подписи слева рамки
text_box = plt.text(0.5, 0.5, '', horizontalalignment='center', verticalalignment='center', transform=ax_text.transAxes)

# Функция переключения графиков
def switch_graph_handler(label):
    global current_oscilloscope, update_needed, show_plot
    current_oscilloscope, update_needed, show_plot = switch_graph(label, buttons, light_green, text_box, [current_oscilloscope], [update_needed], [show_plot], fig)

# Добавляем кнопки для переключения графиков
button_labels = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
button_width = 0.05  # Уменьшаем ширину кнопок в 2 раза
buttons = initialize_buttons(fig, button_labels, button_width, switch_graph_handler)

# Устанавливаем цвет активной кнопки при запуске
light_green = '#90EE90'  # Светло-зеленый цвет
set_active_button_color(current_oscilloscope, buttons, light_green, text_box)

fig.canvas.draw_idle()  # Обновляем отображение

plt.show()

# Конфигурируем pwm
pwm3 = HardwarePWM(pwm_channel=3, hz=200, chip=2)  # OnPWR
pwm2 = HardwarePWM(pwm_channel=2, hz=200, chip=2)

print("BMI30.100 version: v", version)

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    pwm2.start(50)  # Запускаем pwm с скважностью 50%
    pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    while True:
        update_event.wait()  # Ожидаем события для обновления графика
        update_event.clear()  # Сбрасываем событие после обновления графика

        continue_loop, update_needed = update_graph(show_plot, update_needed, current_oscilloscope, start_sample, num_samples, dataADC1, dataADC2, line1, line2, ax, fig)
        if not continue_loop:
            break

except KeyboardInterrupt:
    print("Остановка PWM")
    pwm2.stop()  # Останавливаем PWM при прерывании
    pwm3.stop()  # Останавливаем PWM при прерывании
except Exception as e:
    print(f"Ошибка: {e}")
finally:
    plt.ioff()
    pwm2.stop()
    pwm3.stop()
    print("Остановка осциллограммы, завершаем работу...")
    
    if stream and stream.is_active():
        stream.stop_stream()
    stream.close()
    p.terminate()
    plt.close(fig)  # Закрываем осциллограмму

    gpio12.off()  # Всегда сбрасываем GPIO12 в 0 (выключаем полную мощность передатчика)
    gpio5.off()  # Выключаем индикацию работы передатчика
    gpio6.off()  # Сбрасываем GPIO6 при завершении
    spi0.close()  # Закрываем SPI соединения
    spi1.close()
    time.sleep(0.1)  # Даем время системе обработать изменение состояния
    gpio5.value = False  # Принудительно оставляем GPIO5 в 0 для ускорения разряда датчика наличия сигнала
    print("PWM выключен, GPIO12 = 0, GPIO5 = 0, GPIO6 = 0")
