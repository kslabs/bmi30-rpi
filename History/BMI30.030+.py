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
import time
from datetime import datetime

version = 25.00  # Обновляем версию

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Добавить после инициализации других GPIO
gpio13 = DigitalOutputDevice(13)  # Инициализируем GPIO13 для BEEP

# После инициализации других GPIO
gpio1 = DigitalOutputDevice(1)  # Выход синхронизации
gpio26 = GPIOButton(26, pull_up=True, bounce_time=0.001)  # Вход прерывания от PWM с антидребезгом

# После инициализации других GPIO
gpio17 = DigitalOutputDevice(17)  # Выход управления
gpio17.off()  # Устанавливаем постоянный 0

# Исходные значения цифровых резисторов
resistor_values = {"dr0_0": 250, "dr0_1": 250, "dr1_0": 50, "dr1_1": 250}
print(f"состояние резисторов: {resistor_values}")

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

# Счетчики последовательных отклонений для каждой зоны
dc_counter_P1_1 = np.ones(200)  # Счетчик для зоны 1 верхней антенны
dc_counter_P1_2 = np.ones(200)  # Счетчик для зоны 2 верхней антенны
dc_counter_L1_1 = np.ones(200)  # Счетчик для зоны 1 нижней антенны
dc_counter_L1_2 = np.ones(200)  # Счетчик для зоны 2 нижней антенны

# Предыдущие направления изменения для каждой зоны (True - увеличение, False - уменьшение)
prev_direction_P1_1 = np.zeros(200, dtype=bool)
prev_direction_P1_2 = np.zeros(200, dtype=bool)
prev_direction_L1_1 = np.zeros(200, dtype=bool)
prev_direction_L1_2 = np.zeros(200, dtype=bool)

# Добавим после объявления других массивов
# Массивы для хранения истории разностных сигналов (6 последних измерений)
diff_history_P1 = np.zeros((6, 200))  # История разностей верхней антенны
diff_history_L1 = np.zeros((6, 200))  # История разностей нижней антенны
diff_sum_P1 = np.zeros(200)  # Сумма последних 6 разностей верхней антенны
diff_sum_L1 = np.zeros(200)  # Сумма последних 6 разностей нижней антенны
history_index = 0  # Индекс для циклической записи в историю

# Добавить после объявления других глобальных переменных
max_sample_index_P1 = -1  # Индекс максимального значения для верхней антенны
max_sample_index_L1 = -1  # Индекс максимального значения для нижней антенны
max_count_P1 = 0  # Счетчик повторений максимума для верхней антенны
max_count_L1 = 0  # Счетчик повторений максимума для нижней антенны

# Добавим после объявления других массивов
periods_P1_1 = np.zeros((12, 200))  # Хранение периодов верхней антенны, зона 1
periods_P1_2 = np.zeros((12, 200))  # Хранение периодов верхней антенны, зона 2
periods_L1_1 = np.zeros((12, 200))  # Хранение периодов нижней антенны, зона 1
periods_L1_2 = np.zeros((12, 200))  # Хранение периодов нижней антенны, зона 2

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
    threshold1 = 12000
    threshold2 = 20000
    for i in range(len(data) - 180):
        if data[i] > 30000 and data[i + 30] > threshold1 and data[i + 80] > threshold2 and data[i + 165] > threshold1:
            data = data[i:]
            start_sinchronize = i
            #print("Синхронизация данных", i, len(data))
            break 

# В начале файла добавим константы для шагов DC
DC_STEP_LARGE = 16    # Шаг для больших отклонений
DC_STEP_MEDIUM = 4    # Шаг для средних отклонений
DC_STEP_SMALL = 1      # Шаг для малых отклонений

DC_THRESHOLD_HIGH = 10000  # Порог для больших отклонений
DC_THRESHOLD_LOW = 3000    # Порог для малых отклонений

DC_SAVE_INTERVAL = 180  # 3 минуты в секундах
last_dc_save_time = time.time()  # Время последнего сохранения DC

def save_dc_components():
    """Сохранение DC составляющих в файл"""
    dc_data = {
        'dc_P1_1': dc_P1_1.tolist(),
        'dc_P1_2': dc_P1_2.tolist(),
        'dc_L1_1': dc_L1_1.tolist(),
        'dc_L1_2': dc_L1_2.tolist(),
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open('dc_components.json', 'w') as f:
        json.dump(dc_data, f)

def load_dc_components():
    """Загрузка DC составляющих из файла"""
    global dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2
    try:
        with open('dc_components.json', 'r') as f:
            dc_data = json.load(f)
            dc_P1_1 = np.array(dc_data['dc_P1_1'])
            dc_P1_2 = np.array(dc_data['dc_P1_2'])
            dc_L1_1 = np.array(dc_data['dc_L1_1'])
            dc_L1_2 = np.array(dc_data['dc_L1_2'])
            print(f"DC компоненты загружены (сохранены: {dc_data['timestamp']})")
    except FileNotFoundError:
        print("Файл с DC компонентами не найден, используются нулевые значения")

# Векторизованное обновление DC компонентов
def update_dc_components(zone_data, dc_data, counter, prev_direction):
    """Векторизованное обновление DC компонентов"""
    # Вычисляем разности
    diff = np.abs(zone_data - dc_data)
    
    # Определяем направления
    current_direction = dc_data > zone_data
    
    # Обновляем счетчики
    same_direction = current_direction == prev_direction
    counter[same_direction] += 1
    counter[~same_direction] = 1
    prev_direction[~same_direction] = current_direction[~same_direction]
    
    # Определяем шаги
    step = np.ones_like(diff)
    step[diff > DC_THRESHOLD_HIGH] = DC_STEP_LARGE
    step[(diff <= DC_THRESHOLD_HIGH) & (diff > DC_THRESHOLD_LOW)] = DC_STEP_MEDIUM
    step[diff <= DC_THRESHOLD_LOW] = DC_STEP_SMALL
    
    # Умножаем на счетчики
    step = step * counter
    
    # Обновляем DC компоненты
    dc_data[current_direction] -= step[current_direction]
    dc_data[~current_direction] += step[~current_direction]
    
    return dc_data, counter, prev_direction

# Обновленная функция нормализации периодов
def normalize_periods(periods):
    """Центрирует каждый период относительно нуля путем вычитания среднего значения"""
    if len(periods) == 0:
        return periods
        
    # Создаем массив для нормализованных периодов
    normalized_periods = np.zeros_like(periods)
    
    # Для каждого периода вычитаем его среднее значение, 
    # центрируя относительно нуля
    for i in range(len(periods)):
        # Вычисляем среднее значение периода
        period_mean = np.mean(periods[i])
        # Вычитаем среднее, чтобы центрировать относительно нуля
        normalized_periods[i] = periods[i] - period_mean
        
    return normalized_periods

# Исправьте функцию audio_callback, добавив объявление глобальных переменных
def audio_callback(in_data, frame_count, time_info, status):
    global dataADC_P1, dataADC_L1, start_sinchronize, last_dc_save_time
    global zone_P1_1, zone_P1_2, zone_L1_1, zone_L1_2
    global dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2, ac_P1_1, ac_P1_2, ac_L1_1, ac_L1_2
    global sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2
    global diff_history_P1, diff_history_L1, diff_sum_P1, diff_sum_L1, history_index
    global max_sample_index_P1, max_sample_index_L1, max_count_P1, max_count_L1
    global dc_counter_P1_1, dc_counter_P1_2, dc_counter_L1_1, dc_counter_L1_2
    global prev_direction_P1_1, prev_direction_P1_2, prev_direction_L1_1, prev_direction_L1_2
    # Добавляем глобальные переменные для хранения периодов
    global periods_P1_1, periods_P1_2, periods_L1_1, periods_L1_2
    
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
            
            # ---- Сохраняем текущие зоны ----
            zone_P1_1 = dataADC_P1[365:565].copy()
            zone_P1_2 = dataADC_P1[1320:1520].copy()
            zone_L1_1 = dataADC_L1[350:550].copy()
            zone_L1_2 = dataADC_L1[1320:1520].copy()
            
            # ---- Сохраняем все отдельные периоды ----
            for i in range(12):
                # Верхняя антенна
                start_idx_1_P1 = 365 + i * period_P1
                start_idx_2_P1 = 1320 + i * period_P1
                
                if start_idx_2_P1 + 200 <= len(dataADC_P1):
                    periods_P1_1[i] = dataADC_P1[start_idx_1_P1:start_idx_1_P1 + 200].copy()
                    periods_P1_2[i] = dataADC_P1[start_idx_2_P1:start_idx_2_P1 + 200].copy()
                
                # Нижняя антенна
                start_idx_1_L1 = 350 + i * period_L1
                start_idx_2_L1 = 1320 + i * period_L1
                
                if start_idx_2_L1 + 200 <= len(dataADC_L1):
                    periods_L1_1[i] = dataADC_L1[start_idx_1_L1:start_idx_1_L1 + 200].copy()
                    periods_L1_2[i] = dataADC_L1[start_idx_2_L1:start_idx_2_L1 + 200].copy()
            
            # ---- Нормализуем периоды ----
            periods_P1_1 = normalize_periods(periods_P1_1)
            periods_P1_2 = normalize_periods(periods_P1_2)
            periods_L1_1 = normalize_periods(periods_L1_1)
            periods_L1_2 = normalize_periods(periods_L1_2)
            
            # ---- Обнуляем суммы перед накоплением ----
            sum_P1_1 = np.zeros(200)
            sum_P1_2 = np.zeros(200)
            sum_L1_1 = np.zeros(200)
            sum_L1_2 = np.zeros(200)
            
            # ---- Суммирование нормализованных периодов ----
            for i in range(12):
                sum_P1_1 += periods_P1_1[i]
                sum_P1_2 += periods_P1_2[i]
                sum_L1_1 += periods_L1_1[i]
                sum_L1_2 += periods_L1_2[i]
            
            # Накопление DC для обеих зон с переменным шагом
            dc_P1_1, dc_counter_P1_1, prev_direction_P1_1 = update_dc_components(
                zone_P1_1, dc_P1_1, dc_counter_P1_1, prev_direction_P1_1
            )
            dc_P1_2, dc_counter_P1_2, prev_direction_P1_2 = update_dc_components(
                zone_P1_2, dc_P1_2, dc_counter_P1_2, prev_direction_P1_2
            )
            dc_L1_1, dc_counter_L1_1, prev_direction_L1_1 = update_dc_components(
                zone_L1_1, dc_L1_1, dc_counter_L1_1, prev_direction_L1_1
            )
            dc_L1_2, dc_counter_L1_2, prev_direction_L1_2 = update_dc_components(
                zone_L1_2, dc_L1_2, dc_counter_L1_2, prev_direction_L1_2
            )
            
            # Вычисление переменных составляющих для обеих зон
            ac_P1_1 = zone_P1_1 - dc_P1_1
            ac_P1_2 = zone_P1_2 - dc_P1_2
            ac_L1_1 = zone_L1_1 - dc_L1_1
            ac_L1_2 = zone_L1_2 - dc_L1_2

            # Вычисление разностных сигналов и их накопление
            current_diff_P1 = ac_P1_1 - ac_P1_2  # Разность AC сигналов верхней антенны
            current_diff_L1 = ac_L1_1 - ac_L1_2  # Разность AC сигналов нижней антенны
            
            # Сохраняем текущие разности в историю
            diff_history_P1[history_index] = current_diff_P1
            diff_history_L1[history_index] = current_diff_L1
            
            # Обновляем индекс истории
            history_index = (history_index + 1) % 6
            
            # Вычисляем суммы по всей истории
            diff_sum_P1 = np.sum(diff_history_P1, axis=0)
            diff_sum_L1 = np.sum(diff_history_L1, axis=0)

            # После вычисления diff_sum_P1 и diff_sum_L1
            # Поиск максимумов по модулю и подсчет повторений
            current_max_index_P1 = np.argmax(np.abs(diff_sum_P1))
            current_max_index_L1 = np.argmax(np.abs(diff_sum_L1))
            
            # Обработка максимума верхней антенны
            max_in_range_P1 = False
            if abs(current_max_index_P1 - max_sample_index_P1) <= 5:  # Проверяем в диапазоне ±5
                max_count_P1 += 1
                if max_count_P1 > 10:  # Если максимум держится больше 10 раз
                    # Проверяем, является ли максимум наибольшим в диапазоне ±5 и превышает порог
                    start_idx = max(0, current_max_index_P1 - 5)
                    end_idx = min(200, current_max_index_P1 + 6)
                    if (np.argmax(np.abs(diff_sum_P1[start_idx:end_idx])) + start_idx == current_max_index_P1 and 
                        abs(diff_sum_P1[current_max_index_P1]) > 5000):  # Добавляем проверку амплитуды
                        gpio13.on()  # Включаем BEEP только если максимум в диапазоне и превышает порог
                        max_in_range_P1 = True
            else:
                max_count_P1 = 1
                max_sample_index_P1 = current_max_index_P1
                
            # Обработка максимума нижней антенны
            max_in_range_L1 = False
            if abs(current_max_index_L1 - max_sample_index_L1) <= 5:  # Проверяем в диапазоне ±5
                max_count_L1 += 1
                if max_count_L1 > 10:  # Если максимум держится больше 10 раз
                    # Проверяем, является ли максимум наибольшим в диапазоне ±5 и превышает порог
                    start_idx = max(0, current_max_index_L1 - 15)
                    end_idx = min(200, current_max_index_L1 + 16)
                    if (np.argmax(np.abs(diff_sum_L1[start_idx:end_idx])) + start_idx == current_max_index_L1 and 
                        abs(diff_sum_L1[current_max_index_L1]) > 5000):  # Добавляем проверку амплитуды
                        gpio13.on()  # Включаем BEEP только если максимум в диапазоне и превышает порог
                        max_in_range_L1 = True
            else:
                max_count_L1 = 1
                max_sample_index_L1 = current_max_index_L1

            # Выключаем BEEP если ни один из максимумов не подтвержден
            if not (max_in_range_P1 or max_in_range_L1):
                gpio13.off()

        # Проверяем, нужно ли сохранить DC компоненты
        current_time = time.time()
        if current_time - last_dc_save_time >= DC_SAVE_INTERVAL:
            save_dc_components()
            last_dc_save_time = current_time
            print(f"DC компоненты сохранены: {datetime.now().strftime('%H:%M:%S')}")

    update_event.set()
    return in_data, pyaudio.paContinue

# Загружаем сохраненные DC компоненты
load_dc_components()

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
button_labels = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15']
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

# Замените обработчик закрытия окна на этот:
def on_close(event):
    """Обработчик закрытия окна, который останавливает PWM и завершает программу"""
    print("Окно закрывается, завершаем приложение")
    
    # Останавливаем PWM
    try:
        pwm2.stop()
        pwm3.stop()
        print("PWM остановлен")
        
        # Выключаем все GPIO
        gpio12.off()  # Выключаем полную мощность передатчика
        gpio5.off()   # Выключаем индикацию
        gpio6.off()   # Сбрасываем GPIO6
        gpio13.off()  # Выключаем BEEP
        gpio1.on()    # Выход синхронизации в исходное состояние
        gpio17.off()  # Выключаем выход управления
        
        # Закрываем аудио-поток
        if stream and stream.is_active():
            stream.stop_stream()
        stream.close()
        p.terminate()
        
        # Закрываем SPI соединения
        spi0.close()
        spi1.close()
        
        print("Все ресурсы освобождены")
    except Exception as e:
        print(f"Ошибка при закрытии ресурсов: {e}")
    
    # Завершаем программу
    import sys
    sys.exit(0)

# Подключите обработчик к фигуре
fig.canvas.mpl_connect('close_event', on_close)

plt.show()

# Конфигурируем pwm
pwm3 = HardwarePWM(pwm_channel=3, hz=200.0, chip=2)  # OnPWR 196.95120042321б hz=213.35120042321
pwm2 = HardwarePWM(pwm_channel=2, hz=200.0, chip=2)

print("BMI30.100 version: v", version)

# Добавляем счетчик прерываний
interrupt_counter = 0

import threading

# Обработчик прерывания по фронту GPIO26
def handle_pwm_interrupt():
    global interrupt_counter
    interrupt_counter += 1
    
    if interrupt_counter == 12:  # На 12-м прерывании
        gpio1.off()  # Устанавливаем 0
        # Используем более короткий таймер
        threading.Timer(0.00125, gpio1.on).start()  # 1.25 мс = четверть периода при 200 Гц
    elif interrupt_counter == 13:  # На 13-м прерывании
        interrupt_counter = 0  # Сбрасываем счетчик, но не меняем состояние GPIO1

# Привязываем обработчик к прерыванию по фронту
gpio26.when_pressed = handle_pwm_interrupt

# Устанавливаем начальное состояние GPIO1
gpio1.on()  # Исходное состояние - 1

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    pwm2.start(50)  # Запускаем pwm с скважностью 50%
    pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    while True:
        update_event.wait(timeout=0.2)  # Таймаут 200 мс
        update_event.clear()

        # Проверка закрытия окна
        if not plt.fignum_exists(fig.number):
            print("Окно закрыто, завершаем работу")
            break

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
            sum_P1_1,
            sum_P1_2,
            sum_L1_1,
            sum_L1_2,
            diff_sum_P1,  # Добавляем суммы разностей
            diff_sum_L1,
            max_sample_index_P1, max_sample_index_L1  # Добавляем новые параметры
        )
        if not continue_loop:
            break

        # Сохранение DC составляющих каждые DC_SAVE_INTERVAL секунд
        current_time = time.time()
        if current_time - last_dc_save_time >= DC_SAVE_INTERVAL:
            save_dc_components()
            last_dc_save_time = current_time

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
    gpio13.off()  # Выключаем BEEP при завершении
    gpio1.on()  # Выключаем выход синхронизации
    gpio17.off()  # Выключаем выход управления
    print("PWM выключен, GPIO12 = 0, GPIO5 = 0, GPIO6 = 0, GPIO13 = 0, GPIO1 = 0, GPIO17 = 0")