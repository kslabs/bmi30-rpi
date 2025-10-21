import time
import pyaudio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

# Перенаправляем вывод на локальный дисплей Raspberry Pi5, если запускать скрипт удаленно:
import os
os.environ['DISPLAY'] = ':0'

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
    update_graph,
    calculate_deltas,
    compute_adaptive_correlation_threshold
)
import bmi30_plt  # Добавьте этот импорт для доступа к модулю напрямую
import threading  # Импортируем модуль threading
import json
from datetime import datetime


# Добавьте эти строки в начало программы после импортов
import signal
import sys

def signal_handler(sig, frame):
    print('Получен сигнал прерывания, завершаем работу...')
    # Здесь код очистки ресурсов
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Добавьте в начале файла после импортов
def get_raspberry_pi_version():
    """Определяет версию Raspberry Pi"""
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read()
        if 'Raspberry Pi 5' in model:
            return 5
        elif 'Raspberry Pi 4' in model:
            return 4
        else:
            return 3  # По умолчанию возвращаем 3
    except:
        return 3  # В случае ошибки возвращаем 3 для совместимости

# Определяем параметры PWM для GPIO13 в зависимости от версии Pi
pi_version = get_raspberry_pi_version()
if pi_version == 5:
    # Для Raspberry Pi 5: GPIO13 -> PWM2.4
    BEEP_PWM_CHIP = 2
    BEEP_PWM_CHANNEL = 4
else:
    # Для Raspberry Pi 4 и ниже: GPIO13 -> PWM0.1
    BEEP_PWM_CHIP = 0
    BEEP_PWM_CHANNEL = 1

print(f"Обнаружен Raspberry Pi {pi_version}, BEEP PWM настроен на chip={BEEP_PWM_CHIP}, channel={BEEP_PWM_CHANNEL}")

version = 57.11  # Обновляем версию

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Добавьте эту строку после инициализации других GPIO
gpio13 = DigitalOutputDevice(13)  # Инициализируем GPIO13 для BEEP

# На определение PWM для звукового сигнала
# beep_pwm = HardwarePWM(pwm_channel=1, hz=1000, chip=0)  # Используем PWM0.1 на GPIO13
# Инициализируем PWM для BEEP с частотой 1 кГц для звука

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
CHUNK = 22990  # Количество сэмплов на буфер 22960
CHUNK2 = CHUNK * 2  # Увеличиваем размер буфера в 2 раза
RATE = 384000  # Частота дискретизации
start_work_zone1 = 1340  # Начальный отсчет для 1 зоны ожидания
length_work_zone1 = 240  # Длина отсчета для 1 зоны ожидания
start_work_zone2 = 2320  # Начальный отсчет для 2 зоны ожидания
length_work_zone2 = 240  # Длина отсчета для 2 зоны ожидания


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
max_amp_15 = 0  # Амплитуда максимума для нижней антенны 
max_amp_14 = 0  # Амплитуда максимума для верхней антенны 
max_phase_15 = 0  # Фаза максимума для нижней антенны
max_phase_14 = 0  # Фаза максимума для верхней антенны

# Добавьте после существующих переменных max_amp_15, max_amp_14, max_phase_15, max_phase_14:
delta_amp_15 = 0        # Дельта амплитуд для нижней антенны 
delta_amp_14 = 0        # Дельта амплитуд для верхней антенны
delta_phase_15 = 0      # Дельта фаз для нижней антенны
delta_phase_14 = 0      # Дельта фаз для верхней антенны
prev_delta_amp_15 = 0   # Предыдущая дельта амплитуд для нижней антенны
prev_delta_phase_15 = 0 # Предыдущая дельта фаз для нижней антенны

# Новые глобальные переменные - добавьте их сразу после max_phase_15 и max_phase_14
prev_max_amp_15 = 0             # Предыдущая амплитуда для нижней антенны
prev_max_phase_15 = 0           # Предыдущая фаза для нижней антенны
consecutive_detections = 0      # Счетчик последовательных обнаружений
count_phase = 2                 # Требуемое количество последовательных обнаружений для включения сигнала >=
stable_phase_threshold = 16      # Порог стабильности фазы (±5 отсчетов)
amplitude_threshold = 90000     # Порог амплитуды для сигнализации
last_beep_time = time.time()    # Время последнего срабатывания звукового сигнала
silent_warning_periods = [30, 60, 120, 300]  # Периоды для предупреждений в секундах (30с, 1м, 2м, 5м)
silent_warnings_shown = {period: False for period in silent_warning_periods}  # Отметка о показанных предупреждениях
delta_pfase_signal_on = 0       # изменение фазы при обнаружении сигнала
#переменные для ограничения области поиска максимума
phase_shift_min = -40      # Минимальное значение сдвига фаз для поиска максимума
phase_shift_max = 75     # Максимальное значение сдвига фаз для поиска максимума


adaptive_threshold = amplitude_threshold  # Адаптивный порог, который будет меняться
threshold_margin = 1.2         # Множитель для порога (20% запас)
threshold_increase_rate = 1    # Скорость увеличения порога при наличии сигнала
threshold_decrease_rate = 1     # Скорость уменьшения порога, если сигнал ниже
threshold_update_enabled = True # Флаг разрешения обновления порога
below_threshold_counter = 1     # Счетчик измерений ниже порога
below_threshold_limit = 8      # Сколько раз подряд должно быть ниже порога для включения адаптации после детектирования
prev_threshold = 1 # Предыдущий порог для сравнения
increase_amount = 10 # Сколько увеличивать порог при каждом срабатывании

# Добавляем отладочную информацию с контролем частоты вывода
debug_output = 1  # 1=вкл, 0=выкл

# Добавить после других глобальных переменных
last_threshold_value = adaptive_threshold  # Для отслеживания изменений порога

# После объявления amplitude_threshold, last_beep_time и других переменных
beep_mode = "continuous"  # "continuous" (постоянный) или "intermittent" (прерывистый)
beep_counter = 0  # Счетчик для прерывистого сигнала
last_beep_timestamp = ""  # Временная метка последнего срабатывания
last_max_amplitude = 0    # Амплитуда при последнем срабатывании 
last_max_phase = 0        # Фаза при последнем срабатывании
last_phase_diff = 0       # Изменение фазы при последнем срабатывании
last_beep_time_ms = 0     # Время последнего переключения звука (для высокочастотного пиканья)

# Добавим после объявления других массивов
periods_P1_1 = np.zeros((12, 200))  # Хранение периодов верхней антенны, зона 1
periods_P1_2 = np.zeros((12, 200))  # Хранение периодов верхней антенны, зона 2
periods_L1_1 = np.zeros((12, 200))  # Хранение периодов нижней антенны, зона 1
periods_L1_2 = np.zeros((12, 200))  # Хранение периодов нижней антенны, зона 2

# Создаем событие для обновления графика
update_event = threading.Event()

# Добавляем после других глобальных переменных
stabilization_cycles = 0        # Счетчик циклов для периода стабилизации
STABILIZATION_LIMIT = 16        # Количество циклов перед началом адаптации
initial_threshold = adaptive_threshold  # Запоминаем начальный порог

# Добавьте глобальные переменные для новых сумм
sum_high_level_shifted = np.zeros(240)  # Сумма high_level зон с учетом смещений
sum_low_level_shifted = np.zeros(240)   # Сумма low_level зон с учетом смещений

# Переменные для контроля частоты обновления суммированных зон
zone_sum_update_counter = 0
ZONE_SUM_UPDATE_INTERVAL = 2  # Обновлять суммы только каждые N циклов

# Ускоренная функция суммирования зон с векторизацией операций

def sum_zones_with_shifts_fast(data, zone_marks, zone_length=240, shifts_range=10):
    """
    Оптимизированная версия для суммирования зон с учетом смещений
    
    Args:
        data: исходный массив данных
        zone_marks: список начальных индексов зон
        zone_length: длина каждой зоны (240 отсчетов)
        shifts_range: диапазон смещений (-shifts_range до +shifts_range)
        
    Returns:
        Массив суммы зон с учетом всех смещений
    """
    # Создаем пустой массив для результата
    sum_result = np.zeros(zone_length)
    
    # Предварительно выделяем память под все зоны для быстрого доступа
    valid_zones = []
    for start_idx in zone_marks:
        if start_idx + zone_length <= len(data):
            valid_zones.append(data[start_idx:start_idx + zone_length])
    
    # Если нет зон, возвращаем пустой массив
    if not valid_zones:
        return sum_result
    
    # Обработка без смещения для всех зон (shift = 0)
    for zone in valid_zones:
        sum_result += zone
    
    # Обработка положительных смещений
    for shift in range(1, shifts_range + 1):
        for zone in valid_zones:
            sum_result[shift:] += zone[:zone_length-shift]
    
    # Обработка отрицательных смещений
    for shift in range(1, shifts_range + shifts_range):
        for zone in valid_zones:
            sum_result[:zone_length-shift] += zone[shift:]
    
    return sum_result

# Добавьте функцию кэширования результатов для повторяющихся участков данных

def compute_zones_hash(data, marks):
    """Вычисляет хэш для зон данных для определения изменений"""
    hash_val = 0
    for start in marks:
        if start + 240 <= len(data):
            zone = data[start:start + 240]
            hash_val += np.sum(zone) + np.std(zone)
    return hash_val

# Переменные для кэширования
prev_high_hash = 0
prev_low_hash = 0
prev_high_sum = None
prev_low_sum = None

# Модифицируем функцию save_settings

def save_settings(filename, settings):
    """Сохраняет настройки и адаптивные пороги в JSON файл"""
    # Сохраняем адаптивные пороги в словаре настроек
    if 'adaptive_threshold' not in settings:
        # Добавляем только при первом сохранении или если значения отсутствуют
        settings['adaptive_threshold'] = float(adaptive_threshold)
        settings['max_amp_15'] = float(max_amp_15)
        settings['max_phase_15'] = int(max_phase_15)
        settings['max_amp_14'] = float(max_amp_14)
        settings['max_phase_14'] = int(max_phase_14)
        
        # Добавляем адаптивный порог корреляции
        settings['adaptive_correlation_threshold'] = float(adaptive_correlation_threshold)
    else:
        # Обновляем существующие значения
        settings['adaptive_threshold'] = float(adaptive_threshold)
        settings['max_amp_15'] = float(max_amp_15)
        settings['max_phase_15'] = int(max_phase_15)
        settings['max_amp_14'] = float(max_amp_14)
        settings['max_phase_14'] = int(max_phase_14)
        
        # Обновляем адаптивный порог корреляции
        settings['adaptive_correlation_threshold'] = float(adaptive_correlation_threshold)
    
    # Добавляем параметры дельты
    settings['delta_amp_15'] = float(delta_amp_15)
    settings['delta_phase_15'] = int(delta_phase_15)
    settings['delta_amp_14'] = float(delta_amp_14)
    settings['delta_phase_14'] = int(delta_phase_14)
    
    # Добавляем время последнего сохранения
    settings['last_threshold_save'] = time.time()
    
    # Сохраняем в файл
    with open(filename, 'w') as f:
        json.dump(settings, f)

# Модифицируем функцию load_settings

def load_settings(filename):
    """Загружает настройки и адаптивные пороги из JSON файла"""
    global adaptive_threshold, max_amp_15, max_phase_15, max_amp_14, max_phase_14
    global delta_amp_15, delta_phase_15, delta_amp_14, delta_phase_14
    global adaptive_correlation_threshold, correlation_sound_active  # Добавляем обе переменные
    
    try:
        with open(filename, 'r') as f:
            settings = json.load(f)
            
        # Загружаем адаптивные пороги, если они есть в файле
        if 'adaptive_threshold' in settings:
            adaptive_threshold = settings.get('adaptive_threshold', amplitude_threshold)
            print(f"Загружен адаптивный порог: {adaptive_threshold:.0f}")
            
        if 'max_amp_15' in settings:
            max_amp_15 = settings.get('max_amp_15', 0)
            max_phase_15 = settings.get('max_phase_15', 0)
            print(f"Загружены параметры нижней антенны: амплитуда={max_amp_15:.0f}, фаза={max_phase_15}")
            
        if 'max_amp_14' in settings:
            max_amp_14 = settings.get('max_amp_14', 0)
            max_phase_14 = settings.get('max_phase_14', 0)
            print(f"Загружены параметры верхней антенны: амплитуда={max_amp_14:.0f}, фаза={max_phase_14}")
        
        if 'delta_amp_15' in settings:
            delta_amp_15 = settings.get('delta_amp_15', 0)
            delta_phase_15 = settings.get('delta_phase_15', 0)
            print(f"Загружены параметры дельты для нижней антенны: Δ амплитуд={delta_amp_15:.0f}, Δ фаз={delta_phase_15}")
            
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
    threshold1 = -23000
    threshold2 = -30000
    for i in range(len(data) - 595):
        #if data[i] > 28000 and data[i + 48] > 28000 and data[i + 120] > threshold2: # and data[i + 165] > threshold1:
        #if data[i] < -22000 and data[i + 40] > 20000 and data[i + 124] < -22000 and data[i + 146] < -22000:
        #if data[i] < 0 and data[i + 37] < -30000 and data[i + 55] < -26000 and data[i + 78] < -24000:
        if data[i + 37] < -31000 and data[i + 55] < -26000 and data[i + 78] < -24000:
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

high_level_mark = [420, 2380, 4296, 6200, 8104, 10058, 11976, 13880, 15784, 17738, 19654, 21558]  # Метки зон high
low_level_mark = [1460, 3342, 5239, 7137, 9137, 11020, 12915, 14813, 16816, 18697, 20594, 22493]  # Метки зон low

DC_SAVE_INTERVAL = 180  # 3 минуты в секундах
last_dc_save_time = time.time()  # Время последнего сохранения DC

# Добавляем после объявления DC_SAVE_INTERVAL переменную для отслеживания времени последнего сохранения настроек
# (Примерно строка 265)

# Интервал сохранения адаптивных порогов (в секундах)
THRESHOLD_SAVE_INTERVAL = 180  # 3 минуты в секундах
last_threshold_save_time = time.time()

# 1. Добавьте новую переменную после last_dc_save_time (примерно строка 263)
last_correlation_dc_save_time = time.time()  # Время последнего сохранения DC корреляции

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
    """Центрирует каждый период относительно нуля, убирая наклон"""
    if len(periods) == 0:
        return periods
        
    # Создаем массив для нормализованных периодов
    normalized_periods = np.zeros_like(periods)
    
    # Для каждого периода убираем наклон и центрируем 
    # относительно нуля
    for i in range(len(periods)):
        # Убираем наклон с помощью линейной функции
        slope_corrected = remove_slope(periods[i])
        
        # Центрируем относительно нуля
        period_mean = np.mean(slope_corrected)
        normalized_periods[i] = slope_corrected - period_mean
        
    return normalized_periods

# Добавьте эту функцию в BMI30.031.py после функции normalize_periods
def remove_slope(signal):
    """Удаляет наклон сигнала, вычисляя линейную функцию по началу и концу"""
    if signal is None and len(signal) == 0:
        return np.zeros(1)
    
    # Получаем размер сигнала и вычисляем размер 1/5 части
    size = len(signal)
    chunk_size = size // 5
    
    # Вычисляем среднее значение в первой и последней 1/5 части
    start_mean = np.mean(signal[:chunk_size])
    end_mean = np.mean(signal[-chunk_size:])
    
    # Вычисляем наклон и смещение линейной функции
    # y = slope * x + offset
    slope = (end_mean - start_mean) / (size - chunk_size)
    offset = start_mean - slope * (chunk_size // 2)  # Центр первого чанка
    
    # Создаем массив с линейной функцией наклона
    x = np.arange(size)
    line = slope * x + offset
    
    # Вычитаем линейную функцию из сигнала
    corrected_signal = signal - line
    
    return corrected_signal

# Глобальная переменная для хранения результата суммирования high и low зон
cross_correlation_sum = np.zeros(201)  # 201 элемент для смещений от -100 до +100

# Параметры для расчета кросс-корреляции
CROSS_CORRELATION_SHIFTS = 100  # Смещение в обе стороны (±100 семплов)
cross_correlation_update_counter = 0
CROSS_CORRELATION_UPDATE_INTERVAL = 1  # Обновляем на каждой итерации

# Функция для вычисления кросс-корреляции между суммами high_level и low_level
def calculate_cross_correlation(high_level_data, low_level_data, max_shift=100):
    """
    Вычисляет кросс-корреляцию между двумя массивами с учетом смещений от -max_shift до +max_shift
    
    Args:
        high_level_data: Массив данных для high level зон
        low_level_data: Массив данных для low level зон
        max_shift: Максимальное смещение в обе стороны
        
    Returns:
        Массив кросс-корреляции длиной 2*max_shift+1
    """
    # Проверяем, что массивы не пустые и имеют одинаковую длину
    if len(high_level_data) == 0 and len(low_level_data) == 0 and len(high_level_data) != len(low_level_data):
        return np.zeros(2*max_shift+1)
    
    data_length = len(high_level_data)
    result = np.zeros(2*max_shift+1)
    
    # Нормализуем массивы для лучшего сравнения
    high_norm = high_level_data - np.mean(high_level_data)
    low_norm = low_level_data - np.mean(low_level_data)
    
    # Вычисляем корреляцию для всех смещений
    for shift in range(-max_shift, max_shift+1):
        idx = shift + max_shift  # Индекс в результирующем массиве
        
        if shift < 0:
            # Смещение влево: high[-shift:] * low[:data_length+shift]
            overlap_size = data_length + shift
            if overlap_size > 0:
                result[idx] = np.sum(high_norm[-shift:] * low_norm[:overlap_size])
        elif shift > 0:
            # Смещение вправо: high[:data_length-shift] * low[shift:]
            overlap_size = data_length - shift
            if overlap_size > 0:
                result[idx] = np.sum(high_norm[:overlap_size] * low_norm[shift:])
        else:
            # Без смещения
            result[idx] = np.sum(high_norm * low_norm)
    
    return result

# Добавьте после объявления переменной cross_correlation_sum

# Глобальная переменная для хранения противофазной корреляции
antiphase_correlation_sum = np.zeros(201)  # 201 элемент для смещений от -100 до +100

# Функция для вычисления противофазной кросс-корреляции
def calculate_antiphase_correlation(high_level_data, low_level_data, max_shift=100):
    """
    Вычисляет корреляцию между сигналами, когда один из них инвертирован (противофазная корреляция)
    
    Args:
        high_level_data: Массив данных high level зон
        low_level_data: Массив данных low level зон
        max_shift: Максимальное смещение
        
    Returns:
        Массив противофазной корреляции
    """
    # Инвертируем low_level_data для поиска максимума противофазной корреляции
    inverted_low_data = -low_level_data
    
    # Используем существующую функцию с инвертированными данными
    return calculate_cross_correlation(high_level_data, inverted_low_data, max_shift)

# AC компоненты для суммированных зон
ac_high_level = np.zeros(240)  # AC компонента high_level
ac_low_level = np.zeros(240)   # AC компонента low_level

# Функция для выделения AC компоненты сигнала
def extract_ac_component(signal):
    """
    Выделяет AC компоненту из сигнала, удаляя среднее значение (DC компоненту)
    
    Args:
        signal: Входной сигнал
        
    Returns:
        AC компонента сигнала
    """
    if signal is None and len(signal) == 0:
        return np.zeros(1)
    
    # Простой способ: вычесть среднее значение
    return signal - np.mean(signal)

# Добавьте эти переменные в начало файла, вместе с другими глобальными параметрами
correlation_threshold = 60000000000000      # Порог для разницы корреляций
correlation_index = 145            # Индекс соответствующий смещению +45 (100 + 45)
correlation_detection_count = 0    # Счетчик последовательных превышений порога
correlation_detection_threshold = 2  # Требуемое количество превышений для активации
correlation_based_detection = True  # Включение/отключение нового метода обнаружения

# Переменные для адаптивного порога корреляций
adaptive_correlation_threshold = 3.0  # Сбрасываем до разумного значения (было 10000)
correlation_threshold_history = []
correlation_sound_active = False  # Инициализируем переменную


# Переменная для хранения DC-компоненты корреляции
correlation_dc_component = None

# Добавьте эти функции после функций save_dc_components и load_dc_components

def save_correlation_dc():
    """Сохранение DC составляющей корреляции в файл"""
    global correlation_dc_component, last_correlation_dc_save_time
    
    if 'correlation_dc_component' in globals() and correlation_dc_component is not None:
        dc_data = {
            'correlation_dc_component': correlation_dc_component.tolist(),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open('correlation_dc.json', 'w') as f:
            json.dump(dc_data, f)
        
        # Обновляем время последнего сохранения
        last_correlation_dc_save_time = time.time()
        
        if debug_output:
            print(f"DC-компонента корреляции сохранена ({datetime.now().strftime('%H:%M:%S')})")

def detect_signal_by_gradient(correlation_ac, base_threshold_multiplier=1.5):
    """
    Обнаруживает сигнал на основе градиента (производной) AC-компоненты
    
    Args:
        correlation_ac: AC-компонента разности корреляций
        base_threshold_multiplier: Множитель для адаптивного порога
        
    Returns:
        tuple: (индекс искажения, флаг обнаружения, величина порога)
    """
    if correlation_ac is None or len(correlation_ac) < 10:
        return 0, False, 0
    
    # 1. Вычисляем градиент (разности между соседними точками)
    gradient = np.abs(np.diff(correlation_ac))
    
    # 2. Возводим градиент в квадрат для усиления больших изменений
    squared_gradient = gradient ** 2
    
    # 3. Вычисляем индекс искажения как сумму квадратов градиента
    distortion_index = np.sum(squared_gradient)
    
    # 4. Определяем адаптивный порог обнаружения
    global gradient_history, gradient_threshold
    
    # Инициализируем переменные, если они не существуют
    if 'gradient_history' not in globals():
        gradient_history = []
    if 'gradient_threshold' not in globals():
        gradient_threshold = 0
        
    # Обновляем историю измерений
    gradient_history.append(distortion_index)
    if len(gradient_history) > 30:  # Храним историю последних 30 измерений
        gradient_history.pop(0)
    
    # Вычисляем порог как среднее значение истории, умноженное на коэффициент
    if len(gradient_history) >= 5:  # Ждем хотя бы 5 измерений для устойчивости
        # Используем нижние 70% значений для определения порога шума
        sorted_history = sorted(gradient_history)
        noise_history = sorted_history[:int(len(sorted_history) * 0.7)]
        noise_level = np.mean(noise_history) if noise_history else 0
        
        # Обновляем порог плавно
        if gradient_threshold == 0:
            gradient_threshold = noise_level * base_threshold_multiplier
        else:
            # Плавная адаптация порога (20% к новому значению)
            target_threshold = noise_level * base_threshold_multiplier
            gradient_threshold = gradient_threshold * 0.8 + target_threshold * 0.2
    
    # 5. Определяем наличие сигнала (порог > 0, чтобы избежать деления на 0)
    signal_detected = distortion_index > gradient_threshold if gradient_threshold > 0 else False
    
    return distortion_index, signal_detected, gradient_threshold

# Глобальные переменные для градиентного метода
gradient_history = []  # История значений индекса искажения
gradient_threshold = 0  # Порог для обнаружения сигнала



def load_correlation_dc():
    """Загрузка DC составляющей корреляции из файла"""
    global correlation_dc_component
    
    try:
        with open('correlation_dc.json', 'r') as f:
            dc_data = json.load(f)
            correlation_dc_component = np.array(dc_data['correlation_dc_component'])
            print(f"DC-компонента корреляции загружена (сохранена: {dc_data['timestamp']})")
            print(f"Размер загруженной DC-компоненты: {len(correlation_dc_component)}")
    except FileNotFoundError:
        print("Файл с DC-компонентой корреляции не найден")
        correlation_dc_component = None
    except Exception as e:
        print(f"Ошибка при загрузке DC-компоненты корреляции: {e}")
        correlation_dc_component = None
        
    # Проверяем, что загрузка прошла успешно
    if correlation_dc_component is not None:
        print("DC-компонента корреляции успешно загружена")
    else:
        print("DC-компонента будет инициализирована при первом запуске")

# Заменить импортированную функцию на локальную реализацию:

def compute_correlation_dc(correlation_diff, alpha=0.005):
    """
    Медленное вычисление DC-составляющей для графика разности корреляций
    
    Args:
        correlation_diff: Массив разности корреляций
        alpha: Коэффициент для медленного накопления
        
    Returns:
        DC-компонента графика разности корреляций
    """
    global correlation_dc_component
    
    # Проверяем, инициализирована ли DC-компонента
    if correlation_dc_component is None:
        correlation_dc_component = np.full_like(correlation_diff, np.mean(correlation_diff))
        print("DC-компонента корреляции инициализирована средним значением")
    elif len(correlation_dc_component) != len(correlation_diff):
        # Если размеры не совпадают, переинициализируем
        correlation_dc_component = np.full_like(correlation_diff, np.mean(correlation_diff))
        print(f"DC-компонента переинициализирована. Новый размер: {len(correlation_diff)}")
    
    # Медленно адаптируем DC-компоненту к текущему значению
    correlation_dc_component = correlation_dc_component * (1 - alpha) + correlation_diff * alpha
    
    return correlation_dc_component

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
    global sum_high_level_shifted, sum_low_level_shifted
    global zone_sum_update_counter
    global periods_P1_1, periods_P1_2, periods_L1_1, periods_L1_2
    global prev_high_hash, prev_low_hash, prev_high_sum, prev_low_sum
    global cross_correlation_sum, cross_correlation_update_counter
    global antiphase_correlation_sum
    global adaptive_correlation_threshold, correlation_detection_count, correlation_sound_active  # Добавляем эти переменные

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
                    if (np.argmax(np.abs(diff_sum_P1[start_idx:end_idx])) + start_idx == current_max_index_P1 in 
                        abs(diff_sum_P1[current_max_index_P1]) > 5000):  # Добавляем проверку амплитуды
            #            gpio13.on()  # Включаем BEEP только если максимум в диапазоне и превышает порог
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
                    if (np.argmax(np.abs(diff_sum_L1[start_idx:end_idx])) + start_idx == current_max_index_L1 in 
                        abs(diff_sum_L1[current_max_index_L1]) > 5000):  # Добавляем проверку амплитуды
            #            gpio13.on()  # Включаем BEEP только если максимум в диапазоне и превышает порог
                        max_in_range_L1 = True
            else:
                max_count_L1 = 1
                max_sample_index_L1 = current_max_index_L1

            # Выключаем BEEP если ни один из максимумов не подтвержден
            #if not (max_in_range_P1 or max_in_range_L1):
            #    gpio13.off()

            # Вычисляем суммы зон с учетом смещений по таймеру
            zone_sum_update_counter += 1
            if zone_sum_update_counter >= ZONE_SUM_UPDATE_INTERVAL:
                # Расчет хэшей для определения изменений
                current_high_hash = compute_zones_hash(dataADC_L1, high_level_mark)
                current_low_hash = compute_zones_hash(dataADC_L1, low_level_mark)

                # Обновляем только если данные изменились существенно
                if abs(current_high_hash - prev_high_hash) > 1000 and prev_high_sum is None:
                    sum_high_level_shifted = sum_zones_with_shifts_fast(dataADC_L1, high_level_mark, 240, 10)
                    prev_high_hash = current_high_hash
                    prev_high_sum = sum_high_level_shifted
                else:
                    sum_high_level_shifted = prev_high_sum

                if abs(current_low_hash - prev_low_hash) > 1000 and prev_low_sum is None:
                    sum_low_level_shifted = sum_zones_with_shifts_fast(dataADC_L1, low_level_mark, 240, 10)
                    prev_low_hash = current_low_hash
                    prev_low_sum = sum_low_level_shifted
                else:
                    sum_low_level_shifted = prev_low_sum

                zone_sum_update_counter = 0

            # Вычисляем AC компоненты для суммированных зон
            ac_high_level = extract_ac_component(sum_high_level_shifted)
            ac_low_level = extract_ac_component(sum_low_level_shifted)

            # Вычисляем кросс-корреляцию между AC компонентами high и low зон
            cross_correlation_sum = calculate_cross_correlation(
                ac_high_level, ac_low_level, CROSS_CORRELATION_SHIFTS)

            # Вычисляем противофазную корреляцию между AC компонентами high и low зон
            antiphase_correlation_sum = calculate_antiphase_correlation(
                ac_high_level, ac_low_level, CROSS_CORRELATION_SHIFTS)

            if current_oscilloscope == 23:  # Отображаем на графике 23
                max_idx = np.argmax(cross_correlation_sum)
                max_shift = max_idx - CROSS_CORRELATION_SHIFTS
                max_value = cross_correlation_sum[max_idx]
                print(f"Кросс-корреляция AC компонент: макс={max_value:.0f} при сдвиге={max_shift}")
                update_needed = True  # Принудительно обновляем график

            if current_oscilloscope == 30:  # Отображаем на графике 30
                max_idx = np.argmax(antiphase_correlation_sum)
                max_shift = max_idx - CROSS_CORRELATION_SHIFTS
                max_value = antiphase_correlation_sum[max_idx]
                print(f"Противофазная корреляция: макс={max_value:.0f} при сдвиге={max_shift}")
                update_needed = True  # Принудительно обновляем график

        # Проверяем, нужно ли сохранить DC компоненты
        current_time = time.time()
        if current_time - last_dc_save_time >= DC_SAVE_INTERVAL:
            save_dc_components()
            last_dc_save_time = current_time
            print(f"++++++++++++++++DC компоненты сохранены: {datetime.now().strftime('%H:%M:%S')}")

        # Сохраняем DC корреляции каждые 180 секунд
        current_time = time.time()
        if current_time - last_correlation_dc_save_time >= DC_SAVE_INTERVAL:
            save_correlation_dc()

    update_event.set()
    return in_data, pyaudio.paContinue

# Загружаем сохраненные DC компоненты
load_dc_components()
# Загружаем сохраненную DC-компоненту корреляции
load_correlation_dc()

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
plt.subplots_adjust(left=0.09, right=0.99, top=0.975, bottom=0.125, wspace=0.0, hspace=0.0)

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
    
    # Принудительно обновляем график 31
    if current_oscilloscope == 31:
        update_needed = True
        
    print("switch_graph_handler: график переключен")

# Добавляем кнопки для переключения графиков
button_labels = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', 
                 '16', '17', '18', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31']
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
        #pwm2.stop()
        #pwm3.stop()
        print("PWM остановлен")
        
        # Выключаем все GPIO
        gpio12.off()  # Выключаем полную мощность передатчика
        gpio5.off()   # Выключаем индикацию
        gpio6.off()   # Сбрасываем GPIO6
        gpio13.off()  # Выключаем BEEP
        gpio1.on()    # Выход синхронизации в исходное состояние
        gpio17.off()  # Выключаем выход управления
        
        # Закрываем аудио-поток
        if stream in stream.is_active():
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

# Добавьте эту переменную после объявления других PWM
beep_pwm = None  # Хранение PWM для звукового сигнала

# Добавьте эту функцию перед использованием кнопки beep_mode_button
def toggle_beep_mode(event=None):
    global beep_mode
    stop_beep()  # Сначала останавливаем текущий звук
    
    if beep_mode == "continuous":
        beep_mode = "intermittent"
        beep_mode_button.label.set_text("Прерывистый звук")
        print("Режим звука: прерывистый")
    else:
        beep_mode = "continuous"
        beep_mode_button.label.set_text("Постоянный звук")
        print("Режим звука: постоянный")
    
    fig.canvas.draw_idle()


def toggle_detection_method(event=None):
    global correlation_based_detection
    correlation_based_detection = not correlation_based_detection
    if correlation_based_detection:
        detection_button.label.set_text("Метод: Корреляция")
    else:
        detection_button.label.set_text("Метод: Дельта амплитуд")
    print(f"Режим обнаружения: {'корреляция' if correlation_based_detection else 'дельта амплитуд'}")
    fig.canvas.draw_idle()

# После создания кнопок для переключения графиков и перед plt.show()
# Добавляем кнопки управления режимами в столбик справа
button_width = 0.15
button_height = 0.03
button_x = 0.62  # Сдвигаем вправо, чтобы не закрывать легенду

# Первая кнопка (режим звука) - сверху
ax_beep_button = plt.axes([button_x, 0.94, button_width, button_height])
beep_mode_button = Button(ax_beep_button, "Постоянный звук", color='lightskyblue')
beep_mode_button.on_clicked(toggle_beep_mode)

# Вторая кнопка (метод обнаружения) - под первой
ax_detection_button = plt.axes([button_x, 0.90, button_width, button_height])
detection_button = Button(ax_detection_button, "Метод: Корреляция", color='lightgreen')
detection_button.on_clicked(toggle_detection_method)

plt.show()

# Конфигурируем pwm
#pwm3 = HardwarePWM(pwm_channel=3, hz=200.0, chip=2)  # OnPWR 196.95120042321б hz=213.35120042321
#pwm2 = HardwarePWM(pwm_channel=2, hz=200.0, chip=2)

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

# Добавьте глобальную переменную для управления прерывистым звуком
beep_timer = None  # Таймер для прерывистого сигнала
beep_state = False  # Состояние звукового сигнала (вкл/выкл)

# Заменить функции управления звуком на следующие:
def start_continuous_beep():
    """Включение постоянного звукового сигнала"""
    global beep_pwm
    # Выключаем предыдущий PWM если он был
    if beep_pwm:
        beep_pwm.stop()
        beep_pwm = None
    
    # Просто включаем GPIO13 как цифровой выход
    gpio13.on()

def start_intermittent_beep():
    """Включение прерывистого звукового сигнала через аппаратный PWM"""
    global beep_pwm
    
    # Выключаем предыдущий PWM если он был
    if beep_pwm:
        beep_pwm.stop()
        beep_pwm = None
    
    try:
        # Используем определенные параметры для данной версии Pi
        beep_pwm = HardwarePWM(pwm_channel=BEEP_PWM_CHANNEL, hz=10, chip=BEEP_PWM_CHIP)
        beep_pwm.start(50)  # 50% скважность
        print(f"Прерывистый звук активирован через PWM{BEEP_PWM_CHIP}.{BEEP_PWM_CHANNEL} на GPIO13")
    except Exception as e:
        print(f"Ошибка при запуске PWM для звука: {e}")
        # В случае ошибки используем запасной вариант
        fallback_intermittent_beep()

def stop_beep():
    """Остановка любого звукового сигнала"""
    global beep_pwm, gpio13, beep_timer
    
    # 1. Сначала останавливаем программный таймер если он был запущен
    if beep_timer:
        try:
            beep_timer.cancel()
            beep_timer = None
        except:
            pass
    
    # 2. Затем останавливаем аппаратный PWM
    if beep_pwm:
        try:
            beep_pwm.stop()
            beep_pwm = None
        except Exception as e:
            print(f"Ошибка при остановке PWM: {e}")
    
    # 3. Используем более надежный метод сброса GPIO13
    try:
        # Сначала полностью удаляем текущий объект gpio13
        try:
            gpio13.close()
        except:
            pass
            
        # Используем прямой доступ к системным файлам для сброса GPIO
        os.system(f"echo 13 > /sys/class/gpio/unexport 2>/dev/null")
        time.sleep(0.05)
        os.system(f"echo 13 > /sys/class/gpio/export 2>/dev/null")
        
        # Затем создаем новый объект gpio13
        gpio13 = DigitalOutputDevice(13)
        gpio13.off()
        
        #print("Звук остановлен")
    except Exception as e:
        print(f"Ошибка при остановке звука: {e}")

def fallback_intermittent_beep():
    """Запасной вариант для прерывистого звука с использованием программных таймеров"""
    global beep_timer, beep_state
    
    # Выключаем предыдущий таймер если он был
    if beep_timer:
        beep_timer.cancel()
    
    # Функция для переключения состояния звука
    def toggle_beep_state():
        global beep_timer, beep_state
        if beep_mode != "intermittent":
            return
            
        beep_state = not beep_state
        if beep_state:
            gpio13.on()
        else:
            gpio13.off()
        
        # Перезапускаем таймер для следующего переключения
        if beep_mode == "intermittent":
            beep_timer = threading.Timer(0.05, toggle_beep_state)
            beep_timer.daemon = True
            beep_timer.start()
    
    # Запускаем первое переключение
    beep_state = True
    gpio13.on()
    beep_timer = threading.Timer(0.05, toggle_beep_state)
    beep_timer.daemon = True
    beep_timer.start()
    print("Прерывистый звук активирован через программный таймер")

def ensure_beep_off():
    """Гарантирует, что звуковой сигнал выключен"""
    global beep_pwm, gpio13
    
    # Останавливаем PWM если он был
    if beep_pwm:
        try:
            beep_pwm.stop()
        except:
            pass
        beep_pwm = None
    
    # Переинициализируем GPIO13
    try:
        gpio13.close()
    except:
        pass
    
    try:
        gpio13 = DigitalOutputDevice(13)
        gpio13.off()
        print("GPIO13 (BEEP) сброшен в выключенное состояние")
    except Exception as e:
        print(f"Ошибка при сбросе GPIO13: {e}")

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    #pwm2.start(50)  # Запускаем pwm с скважностью 50%
    #pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    # Гарантируем выключение звукового сигнала
    ensure_beep_off()
    
    while True:
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
            diff_sum_P1,
            diff_sum_L1,
            max_sample_index_P1, max_sample_index_L1,
            periods_P1_1,
            periods_P1_2,
            periods_L1_1,
            periods_L1_2,
            sum_high_level_shifted,
            sum_low_level_shifted,
            cross_correlation_sum,
            ac_high_level,
            ac_low_level,
            antiphase_correlation_sum,
            adaptive_correlation_threshold,
            correlation_detection_count,
            correlation_detection_threshold,
            None,
            None,
            correlation_sound_active,
            correlation_dc_component  # Добавляем передачу DC-компоненты
        )
        if not continue_loop:
            break

        # В основном цикле программы, примерно около строки 1660, заменим текущий блок обработки
        if correlation_based_detection and len(cross_correlation_sum) > 0 and len(antiphase_correlation_sum) > 0:
            # Вычисляем разницу корреляций
            correlation_diff = cross_correlation_sum - antiphase_correlation_sum
            
            # Вычисляем DC компоненту с медленной адаптацией
            correlation_dc = compute_correlation_dc(correlation_diff, alpha=0.005)
            
            # Удаляем DC из сигнала для получения AC-компоненты
            correlation_ac = correlation_diff - correlation_dc
            
            # НОВЫЙ МЕТОД: Детектирование сигнала на основе градиента
            distortion_index, gradient_signal_detected, gradient_threshold = detect_signal_by_gradient(correlation_ac, 1.5)
            
            # Для обратной совместимости сохраняем старый метод для отладки
            # Вычисляем характеристики шума и сигнала
            noise_area = list(range(0, 50)) + list(range(150, 200))
            noise_values = [correlation_ac[i] for i in noise_area]
            noise_mean = np.mean(noise_values)
            noise_std = np.std(noise_values) + 100
            
            signal_area = list(range(50, 150))
            signal_values = [correlation_ac[i] for i in signal_area]
            signal_mean = np.mean(signal_values)
            signal_max = max([abs(val - noise_mean) for val in signal_values])
            
            # Вычисляем SNR по старому методу для сравнения
            snr = signal_max / max(1, noise_std * 1.2)
            snr_threshold = 2.0
            
            # ИСПОЛЬЗУЕМ НОВЫЙ МЕТОД для принятия решения
            signal_detected = gradient_signal_detected
            
            # Проверяем обнаружение и счетчик последовательных превышений
            if signal_detected:
                # Увеличиваем счетчик последовательных обнаружений
                correlation_detection_count += 1
                
                # Если счетчик превысил порог - активируем сигнал
                if correlation_detection_count >= correlation_detection_threshold:
                    # Сигнал обнаружен - включаем звук согласно выбранному режиму
                    if beep_mode == "continuous":
                        start_continuous_beep()
                    else:
                        start_intermittent_beep()
                    
                    # Обновляем время обнаружения
                    last_beep_time = time.time()
                    last_beep_timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    # Устанавливаем флаг активности звука
                    correlation_sound_active = True
                    
                    # Выводим информацию об обнаружении с учетом градиентного метода
                    print(f"Сигнал обнаружен! Индекс искажения: {distortion_index:.0f}/{gradient_threshold:.0f}, "
                          f"SNR: {snr:.2f}, Счетчик: {correlation_detection_count}/{correlation_detection_threshold}")
            else:
                # Сбрасываем счетчик, если сигнал не обнаружен
                correlation_detection_count = 0
                
                # Выключаем звук и обновляем флаг
                if correlation_sound_active:
                    stop_beep()
                    correlation_sound_active = False
            
            # Выводим отладочную информацию с данными обоих методов
            if debug_output:
                print(f"Форма графика: Индекс={distortion_index:.0f}/{gradient_threshold:.0f} | "
                      f"SNR={snr:.2f} | Сигнал: {signal_mean:.0f} | "
                      f"Детекция: {correlation_detection_count}/{correlation_detection_threshold} | "
                      f"BEEP: {'ON' if correlation_sound_active else 'OFF'}")

except KeyboardInterrupt:
    print("Остановка PWM по Ctrl+C")
    #pwm2.stop()  # Останавливаем PWM при прерывании
    #pwm3.stop()  # Останавливаем PWM при прерывании
    
    # Очистка ресурсов
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # Выключаем все GPIO
    gpio12.off()  # Выключаем полную мощность передатчика
    gpio5.off()   # Выключаем индикацию
    gpio6.off()   # Сбрасываем GPIO6
    gpio13.off()  # Выключаем BEEP
    gpio1.on()    # Выход синхронизации в исходное состояние
    gpio17.off()  # Выключаем выход управления
    
    # Закрываем SPI соединения
    spi0.close()
    spi1.close()
    
    print("Все ресурсы освобождены, программа остановлена")
    import sys
    sys.exit(0)  # Принудительно завершаем программу
except Exception as e:
    print(f"Ошибка: {e}")
finally:
    plt.ioff()
    #pwm2.stop()
    #pwm3.stop()
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

