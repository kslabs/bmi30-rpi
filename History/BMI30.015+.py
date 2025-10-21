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
from bmi30_plt import (
    initialize_plot,
    update_start,
    switch_graph,
    update_plot,
    initialize_buttons,
    set_active_button_color,
    update_graph
)
import threading  # Импортируем модуль threading
import json

version = 15.00  # Обновляем версию

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = GPIOButton(26, pull_up=True)

# Исходные значения цифровых резисторов
resistor_values = {"dr0_0": 250, "dr0_1": 250, "dr1_0": 50, "dr1_1": 250}
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
dataADC_P1 = np.zeros(CHUNK, dtype=int)
dataADC_L1 = np.zeros(CHUNK, dtype=int)
start_sinchronize = 0

# Добавляем глобальные переменные для хранения зон ожидания
zone_P1_1 = np.zeros(200)  # Зона 1 верхней антенны (370-570)
zone_P1_2 = np.zeros(200)  # Зона 2 верхней антенны (1320-1520)
zone_L1_1 = np.zeros(200)  # Зона 1 нижней антенны (350-550)
zone_L1_2 = np.zeros(200)  # Зона 2 нижней антенны (1320-1520)

# Добавляем массивы для хранения постоянных составляющих
dc_P1_1 = np.zeros(200)  # Постоянная составляющая зоны 1 верхней антенны
dc_P1_2 = np.zeros(200)  # Постоянная составляющая зоны 2 верхней антенны
dc_L1_1 = np.zeros(200)  # Постоянная составляющая зоны 1 нижней антенны
dc_L1_2 = np.zeros(200)  # Постоянная составляющая зоны 2 нижней антенны

# Массивы для хранения переменных составляющих
ac_P1_1 = np.zeros(200)  # Переменная составляющая зоны 1 верхней антенны
ac_P1_2 = np.zeros(200)  # Переменная составляющая зоны 2 верхней антенны
ac_L1_1 = np.zeros(200)  # Переменная составляющая зоны 1 нижней антенны
ac_L1_2 = np.zeros(200)  # Переменная составляющая зоны 2 нижней антенны

sum_P1_1 = np.zeros(200)  # Сумма для зоны 1 верхней антенны
sum_P1_2 = np.zeros(200)  # Сумма для зоны 2 верхней антенны
sum_L1_1 = np.zeros(200)  # Сумма для зоны 1 нижней антенны
sum_L1_2 = np.zeros(200)  # Сумма для зоны 2 нижней антенны

# Создаем событие для обновления графика
update_event = threading.Event()

# Функция для сохранения настроек
def save_settings(filename, settings):
    with open(filename, 'w') as f:
        json.dump(settings, f)

# Функция для загрузки настроек
def load_settings(filename):
    try:
        with open(filename, 'r') as f:
            settings = json.load(f)
    except FileNotFoundError:
        settings = {}
    return settings

# Файл для сохранения настроек
settings_file = 'settings.json'

# Загрузка настроек
settings = load_settings(settings_file)

# Восстановление настроек
current_oscilloscope = settings.get('current_oscilloscope', 1)
window_size = settings.get('window_size', (800, 600))

# Функция синхронизации данных
def synchronize_data(data):
    global start_sinchronize
    threshold1 = 11000
    threshold2 = 20000
    for i in range(len(data) - 90):
        if data[i] > threshold1 and data[i + 25] > threshold1 and data[i + 81] > threshold2:
            data = data[i:]
            start_sinchronize = i
            #print("Синхронизация данных", i, len(data))
            break 

# Функция обратного вызова для аудио
def audio_callback(in_data, frame_count, time_info, status):
    global dataADC_P1, dataADC_L1, start_sinchronize, zone_P1_1, zone_P1_2, zone_L1_1, zone_L1_2
    global dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2, ac_P1_1, ac_P1_2, ac_L1_1, ac_L1_2
    global sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2  # Добавляем глобальные переменные для сумм
    
    start_sinchronize = 0
    new_data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    dataADC_P1 = np.concatenate((dataADC_P1[-CHUNK:], new_data[:, 0]))
    dataADC_L1 = np.concatenate((dataADC_L1[-CHUNK:], new_data[:, 1]))
    
    if len(dataADC_L1) > CHUNK:
        synchronize_data(dataADC_L1)
        dataADC_L1 = dataADC_L1[start_sinchronize:]
        dataADC_P1 = dataADC_P1[start_sinchronize:]
        
        if len(dataADC_P1) > CHUNK and len(dataADC_L1) > CHUNK:
            # Фиксированный период 1920 семплов для обеих антенн
            period_P1 = 1920  # Фиксированный период для верхней антенны
            period_L1 = 1920  # Фиксированный период для нижней антенны
            
            # Обнуляем суммы перед накоплением
            sum_P1_1 = np.zeros(200)
            sum_P1_2 = np.zeros(200)
            sum_L1_1 = np.zeros(200)
            sum_L1_2 = np.zeros(200)
            
            # Суммирование для верхней антенны
            for i in range(12):
                start_idx_1_P1 = 365 + i * period_P1
                start_idx_2_P1 = 1320 + i * period_P1
                
                if start_idx_2_P1 + 200 <= len(dataADC_P1):
                    sum_P1_1 += dataADC_P1[start_idx_1_P1:start_idx_1_P1 + 200]
                    sum_P1_2 += dataADC_P1[start_idx_2_P1:start_idx_2_P1 + 200]
            
            # Суммирование для нижней антенны
            for i in range(12):
                start_idx_1_L1 = 350 + i * period_L1
                start_idx_2_L1 = 1320 + i * period_L1
                
                if start_idx_2_L1 + 200 <= len(dataADC_L1):
                    sum_L1_1 += dataADC_L1[start_idx_1_L1:start_idx_1_L1 + 200]
                    sum_L1_2 += dataADC_L1[start_idx_2_L1:start_idx_2_L1 + 200]
            
            # Сохраняем текущие зоны
            zone_P1_1 = dataADC_P1[365:565].copy()
            zone_P1_2 = dataADC_P1[1320:1520].copy()
            zone_L1_1 = dataADC_L1[350:550].copy()
            zone_L1_2 = dataADC_L1[1320:1520].copy()
            
            # Накопление DC для обеих зон
            for j in range(200):
                # Для верхней антенны зона 1
                if dc_P1_1[j] > zone_P1_1[j]:
                    dc_P1_1[j] -= 10
                else:
                    dc_P1_1[j] += 10
                    
                # Для верхней антенны зона 2
                if dc_P1_2[j] > zone_P1_2[j]:
                    dc_P1_2[j] -= 10
                else:
                    dc_P1_2[j] += 10
                    
                # Для нижней антенны зона 1
                if dc_L1_1[j] > zone_L1_1[j]:
                    dc_L1_1[j] -= 10
                else:
                    dc_L1_1[j] += 10
                    
                # Для нижней антенны зона 2
                if dc_L1_2[j] > zone_L1_2[j]:
                    dc_L1_2[j] -= 10
                else:
                    dc_L1_2[j] += 10
            
            # Вычисление переменных составляющих для обеих зон
            ac_P1_1 = zone_P1_1 - dc_P1_1
            ac_P1_2 = zone_P1_2 - dc_P1_2
            ac_L1_1 = zone_L1_1 - dc_L1_1
            ac_L1_2 = zone_L1_2 - dc_L1_2
    
    update_event.set()
    return in_data, pyaudio.paContinue

# Создаём поток захвата аудио
stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback)

# Переменные управления осциллограммами
# current_oscilloscope = 1  # Указывает, какая осциллограмма отображается
start_sample = 0  # Начало отображаемого диапазона
num_samples = CHUNK  # Количество отображаемых семплов
update_needed = False  # Флаг для отслеживания необходимости обновления графика
show_plot = True  # Флаг для отображения осциллограммы

# Визуализация осциллограммы
print("Инициализация осциллограммы...")
fig, ax = plt.subplots(figsize=(window_size[0] / 100, window_size[1] / 100))
ax.grid(color='lightgray', linestyle='--', linewidth=0.5)
x_axis = np.linspace(0, CHUNK, CHUNK)
plt.subplots_adjust(left=0.09, right=0.99, top=0.99, bottom=0.125, wspace=0.0, hspace=0.0)

line1, = ax.plot(x_axis[:CHUNK], np.zeros(CHUNK), label='Верхняя Антенна', color='purple')
line2, = ax.plot(x_axis[:CHUNK], np.zeros(CHUNK), label='Нижняя Антенна', color='chocolate')
ax.legend()  # Отображаем легенду один раз
ax.set_ylim(-35000, 44000)
plt.ion()
print("Осциллограмма инициализирована.")

# Добавляем ползунки для изменения отображаемого диапазона
ax_slider1 = plt.axes([0.1, 0.01, 0.81, 0.03])
ax_slider2 = plt.axes([0.1, 0.05, 0.81, 0.03])

# Создаем слайдеры
start_sample_slider = Slider(ax_slider1, 'Старт', 0, CHUNK, valinit=start_sample, valstep=10)
num_samples_slider = Slider(ax_slider2, 'Длина', 10, CHUNK, valinit=num_samples, valstep=10)

# Функция обновления графика при изменении ползунков
def update_plot_handler(val):
    global start_sample, num_samples, update_needed
    if current_oscilloscope in [4, 5]:
        # Для графиков 4 и 5 ограничиваем длину до 200 семплов
        num_samples = min(200, val)
    else:
        # Для графиков 1, 2, 3 используем полную длину CHUNK
        num_samples = min(CHUNK - start_sample, val)
    update_needed = True
    return start_sample, num_samples, update_needed

# Обработчик для ползунка "Старт"
def update_start_handler(val):
    global start_sample, num_samples, update_needed
    if current_oscilloscope in [4, 5]:
        # Для графиков 4 и 5 ограничиваем старт до 200 семплов
        start_sample = min(200 - num_samples, val)
    else:
        # Для графиков 1, 2, 3 используем полную длину CHUNK
        start_sample = min(CHUNK - num_samples, val)
    update_needed = True
    return start_sample, num_samples, update_needed

def update_sliders_range():
    global start_sample, num_samples
    if current_oscilloscope in [4, 5]:
        max_val = 200
    else:
        max_val = CHUNK
        
    start_sample_slider.valmax = max_val
    num_samples_slider.valmax = max_val
    
    # Ограничиваем значения в допустимом диапазоне
    start_sample = min(start_sample, max_val)
    num_samples = min(num_samples, max_val)
    
    # Обновляем значения слайдеров без вызова обработчиков
    start_sample_slider.set_val(start_sample)
    num_samples_slider.set_val(num_samples)
    
    # Обновляем отображение слайдеров
    start_sample_slider.ax.set_xlim(start_sample_slider.valmin, start_sample_slider.valmax)
    num_samples_slider.ax.set_xlim(num_samples_slider.valmin, num_samples_slider.valmax)

# Привязываем обработчики к слайдерам
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
    settings['current_oscilloscope'] = current_oscilloscope
    save_settings(settings_file, settings)
    update_sliders_range()  # Обновляем диапазоны ползунков
    print("switch_graph_handler: график переключен")

# Добавляем кнопки для переключения графиков
button_labels = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
button_width = 0.05  # Уменьшаем ширину кнопок в 2 раза
buttons = initialize_buttons(fig, button_labels, button_width, switch_graph_handler)

# Устанавливаем цвет активной кнопки при запуске
light_green = '#90EE90'  # Светло-зеленый цвет
set_active_button_color(current_oscilloscope, buttons, light_green, text_box)

fig.canvas.draw_idle()  # Обновляем отображение

# Обработчик изменения размера окна
def on_resize(event):
    window_size = (event.width, event.height)
    settings['window_size'] = window_size
    save_settings(settings_file, settings)
    print("on_resize: размер окна изменен")

fig.canvas.mpl_connect('resize_event', on_resize)

plt.show()

# Конфигурируем pwm
pwm3 = HardwarePWM(pwm_channel=3, hz=200.0, chip=2)  # OnPWR 196.95120042321б hz=213.35120042321
pwm2 = HardwarePWM(pwm_channel=2, hz=200.0, chip=2)

print("BMI30.100 version: v", version)

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    pwm2.start(50)  # Запускаем pwm с скважностью 50%
    pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    while True:
        update_event.wait()  # Ожидаем события для обновления графика
        update_event.clear()  # Сбрасываем событие после обновления графика

        continue_loop, update_needed = update_graph(
            show_plot, 
            update_needed, 
            current_oscilloscope, 
            start_sample, 
            num_samples, 
            dataADC_P1, 
            dataADC_L1, 
            line1, 
            line2, 
            ax, 
            fig,
            zone_P1_1,
            zone_P1_2,
            zone_L1_1,
            zone_L1_2,
            ac_P1_1,
            ac_P1_2,
            ac_L1_1,
            ac_L1_2,
            dc_P1_1,
            dc_P1_2,
            dc_L1_1,
            dc_L1_2,
            sum_P1_1,  # Добавляем параметры сумм
            sum_P1_2,
            sum_L1_1,
            sum_L1_2
        )
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