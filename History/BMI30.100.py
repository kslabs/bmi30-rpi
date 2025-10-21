import sys
import time
import numpy as np
# import pyaudio
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
import threading
from datetime import datetime
import json
import traceback
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button as GPIOButton, InputDevice
# import lgpio
import spidev
import os
from bmi30_plt import (
    update_start,
    switch_graph,
    update_plot,
    initialize_buttons,
    set_active_button_color,
    update_graph,
    calculate_deltas
)
import bmi30_plt

# --- Глобальные переменные ---
version = "59.23" # Обновим версию
beep_pwm = None # Инициализируем переменную beep_pwm

# Добавьте эти переменные в начало файла, вместе с другими глобальными параметрами
correlation_threshold = 60000000000000      # Порог для разницы корреляций
correlation_index = 145            # Индекс соответствующий смещению +45 (100 + 45)
correlation_detection_count = 0    # Счетчик последовательных превышений порога
correlation_detection_threshold = 2  # Требуемое количество превышений для активации
correlation_based_detection = True  # Включение/отключение нового метода обнаружения

# Переменная для адаптивного порога корреляции 
adaptive_correlation_threshold = 3.0  # Начальное значение
correlation_sound_active = False  # Флаг активности звука по корреляции

# ВАЖНО: Используйте только английские ключевые слова Python (and, or, if, in, not, etc.)
# use_english_keywords_only


# ВАЖНО: Используйте только английские ключевые слова Python (and, or, if, in, not, etc.)
# use_english_keywords_only


import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button as GPIOButton
# import lgpio
import spidev
# from rpi_hardware_pwm import HardwarePWM
from bmi30_def import initialize_gpio, set_resistor, toggle_gpio6_and_update_resistors, update_plot
from bmi30_plt import (
    update_start,
    switch_graph,
    update_plot,
    initialize_buttons,
    set_active_button_color,
    update_graph,
    calculate_deltas
    # compute_adaptive_correlation_threshold  # Удалите эту линию
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

version = 100.04  # Обновляем версию

# Инициализируем GPIO
gpio5 = DigitalOutputDevice(5)  # Оставляем только GPIO5 для индикации
gpio22 = InputDevice(22)      # GPIO22 для сигнала готовности от STM32

# Настраиваем SPI
spi0 = spidev.SpiDev()
spi0.open(0, 0) # Используем аппаратный CS0 (GPIO8)
spi0.max_speed_hz = 4000000  # 4 МГц
spi0.mode = 0
spi0.lsbfirst = False
spi0.bits_per_word = 8 # Возвращаем 8-битный режим

# Создаем буфер для отправки ОДИН РАЗ, чтобы не делать это в цикле.
# Размер буфера равен максимальному ожидаемому количеству байт.
TX_BUFFER = [0xA5] * ((1373 + 2) * 2)

# --- Новые функции для SPI протокола ---

# Глобальные переменные для контроля частоты сообщений о таймауте
last_timeout_message_time = {}
TIMEOUT_MESSAGE_INTERVAL = 10 # секунд

def request_spi_data(length_bytes):
    """
    Ждет готовности STM32 и читает данные по SPI в 8-битном режиме.
    length_bytes: количество 8-битных байт для чтения.
    """
    global spi0, gpio22, last_timeout_message_time, TX_BUFFER
    
    # Проверяем готовность STM32
    timeout = 0.01 # 10 мс
    start_wait = time.time()
    while not gpio22.is_active:
        if time.time() - start_wait > timeout:
            current_time = time.time()
            # Выводим сообщение о таймауте не чаще раза в 10 секунд
            if current_time - last_timeout_message_time.get('read', 0) > TIMEOUT_MESSAGE_INTERVAL:
                print(f"Таймаут ожидания готовности STM32 на GPIO22")
                last_timeout_message_time['read'] = current_time
            return [] # Возвращаем пустой список, если STM32 не готов
        time.sleep(0.0001)

    # --- Используем заранее созданный глобальный буфер ---
    try:
        # xfer2 отправляет срез из глобального буфера tx_data и возвращает полученные байты.
        # Использование среза [:] гарантирует, что мы отправим нужное количество байт.
        rx_data = spi0.xfer2(TX_BUFFER[:length_bytes])
    except OSError as e:
        print(f"!!! Ошибка SPI при чтении/записи данных: {e}")
        return []
    return rx_data

def parse_spi_data(byte_data):
    """
    Преобразует список 8-битных байт в массив 16-битных слов numpy.
    Предполагается, что порядок байт - Big Endian (MSB первый).
    """
    # Проверяем, что количество байт четное
    if len(byte_data) % 2 != 0:
        print("Ошибка: получено нечетное количество байт, невозможно преобразовать в 16-битные слова.")
        return np.array([], dtype=np.int16)

    # Используем эффективный метод numpy для преобразования
    # Создаем numpy массив из байт
    dt = np.dtype(np.int16)
    dt = dt.newbyteorder('<') # '<' означает Little-Endian (LSB first)
    #dt = dt.newbyteorder('>') # '>' означает Big-Endian (MSB first)
    # Преобразуем список байт в массив numpy uint8, затем "смотрим" на него как на int16
    word_array = np.frombuffer(bytearray(byte_data), dtype=dt)
    return word_array

# --- Конец новых функций для SPI протокола ---


# Устанавливаем цифровые резисторы в исходное состояние
# set_resistor(spi0, 0, resistor_values["dr0_0"])
# set_resistor(spi0, 1, resistor_values["dr0_1"])


# Настройка параметров АЦП
CHUNK = 1373  # Количество сэмплов на буфер (1375 всего - 2 заголовок)
CHUNK2 = CHUNK * 2  # Увеличиваем размер буфера в 2 раза
RATE = 275000  # Частота дискретизации
start_work_zone1 = 140  # Начальный отсчет для 1 зоны ожидания
length_work_zone1 = 240  # Длина отсчета для 1 зоны ожидания
start_work_zone2 = 720  # Начальный отсчет для 2 зоны ожидания
length_work_zone2 = 240  # Длина отсчета для 2 зоны ожидания


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
    Существенно оптимизированная версия для суммирования зон с учетом смещений
    """
    # Кэширование результатов для повторяющихся вызовов
    cache_key = hash(data.tobytes()) + hash(tuple(zone_marks))
    
    if not hasattr(sum_zones_with_shifts_fast, 'cache'):
        sum_zones_with_shifts_fast.cache = {}
    
    if cache_key in sum_zones_with_shifts_fast.cache:
        return sum_zones_with_shifts_fast.cache[cache_key]
    
    # Создаем пустой массив для результата
    sum_result = np.zeros(zone_length)
    
    # Получаем валидные зоны один раз
    valid_zones = []
    for start_idx in zone_marks:
        if start_idx + zone_length <= len(data):
            valid_zones.append(data[start_idx:start_idx + zone_length])
    
    if not valid_zones:
        return sum_result
    
    # Преобразуем список зон в numpy массив для векторизации
    zones_array = np.array(valid_zones)
    
    # Сначала суммируем все зоны без смещения
    sum_result += np.sum(zones_array, axis=0)
    
    # Положительные смещения - векторизованная версия
    for shift in range(1, shifts_range + 1):
        for zone in zones_array:
            sum_result[shift:] += zone[:zone_length-shift]
    
    # Отрицательные смещения - векторизованная версия
    for shift in range(1, shifts_range + shifts_range):
        for zone in zones_array:
            sum_result[:zone_length-shift] += zone[shift:]
    
    # Сохраняем результат в кэш
    sum_zones_with_shifts_fast.cache[cache_key] = sum_result
    
    # Ограничиваем размер кэша
    if len(sum_zones_with_shifts_fast.cache) > 50:
        sum_zones_with_shifts_fast.cache = {}
    
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
        settings['max_phase_14'] = int(max_phase_15)
        
        # Добавляем адаптивный порог корреляции
        if 'adaptive_correlation_threshold' in globals():
            settings['adaptive_correlation_threshold'] = float(adaptive_correlation_threshold)
    else:
        # Обновляем существующие значения
        settings['adaptive_threshold'] = float(adaptive_threshold)
        settings['max_amp_15'] = float(max_amp_15)
        settings['max_phase_15'] = int(max_phase_15)
        settings['max_amp_14'] = float(max_amp_14)
        settings['max_phase_14'] = int(max_phase_15)
        
        # Обновляем адаптивный порог корреляции
        if 'adaptive_correlation_threshold' in globals():
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
        #if data[i + 37] < -31000 and data[i + 55] < -26000 and data[i + 78] < -24000:
        if data[i] < -20000 and data[i+1] > -20000: # and data[i + 78] < -24000:
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

#high_level_mark = [420, 2380, 4296, 6200, 8104, 10058, 11976, 13880, 15784, 17738, 19654, 21558]  # Метки зон high
#low_level_mark = [1460, 3342, 5239, 7137, 9137, 11020, 12915, 14813, 16816, 18697, 20594, 22493]  # Метки зон low
high_level_mark = [330, 2285, 4206, 6110, 8014, 9965, 11885, 13790, 15693, 17645, 19563, 21467]  # Метки зон high
low_level_mark = [1370, 3252, 5149, 7047, 9047, 10930, 12825, 14723, 16726, 18607, 20504, 22403]  # Метки зон low



DC_SAVE_INTERVAL = 180  # 3 минуты в секундах
last_dc_save_time = time.time()  # Время последнего сохранения DC

# Добавляем после объявления DC_SAVE_INTERVAL переменную для отслеживания времени последнего сохранения настроек
# (Примерно строка 265)

# Интервал сохранения адаптивных порогов (в секундах)
THRESHOLD_SAVE_INTERVAL = 180  # 3 минуты в секундах
last_threshold_save_time = time.time()

def save_dc_components():
    """Сохранение DC составляющих в файл"""
    global dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2
    
    # Проверка, что DC компоненты имеют правильные значения
    if len(dc_P1_1) == 0 or np.all(dc_P1_1 == 0):
        print("Внимание: DC компоненты пусты или равны нулю, сохранение отменено")
        return False
    
    # Создаем копии массивов, чтобы избежать потери данных при сериализации
    dc_data = {
        'dc_P1_1': dc_P1_1.tolist(),
        'dc_P1_2': dc_P1_2.tolist(),
        'dc_L1_1': dc_L1_1.tolist(),
        'dc_L1_2': dc_L1_2.tolist(),
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Проверяем, что данные не пустые
    if not dc_data['dc_P1_1'] or not dc_data['dc_P1_2'] or not dc_data['dc_L1_1'] or not dc_data['dc_L1_2']:
        print("Ошибка: данные пусты, сохранение отменено")
        return False
    
    # Используем абсолютный путь для гарантированного сохранения
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    dc_file_path = os.path.join(script_dir, 'dc_components.json')
    
    try:
        # Создаем временный файл и только потом переименовываем для атомарной операции
        temp_file = dc_file_path + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(dc_data, f)
        
        # Если все успешно, переименовываем файл
        os.replace(temp_file, dc_file_path)
        
        print(f"++++++++++++++++DC компоненты сохранены: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Путь к файлу: {dc_file_path}")
        print(f"Сохранены DC: P1_1 max={np.max(dc_P1_1):.1f}, P1_2 max={np.max(dc_P1_2):.1f}, L1_1 max={np.max(dc_L1_1):.1f}, L1_2 max={np.max(dc_L1_2):.1f}")
        
        # Проверяем, что файл действительно существует после сохранения
        if os.path.exists(dc_file_path):
            print(f"Файл успешно создан, размер: {os.path.getsize(dc_file_path)} байт")
        else:
            print(f"ОШИБКА: файл не создан после сохранения!")
            
        return True
    except Exception as e:
        print(f"Ошибка при сохранении DC компонент: {e}")
        import traceback
        traceback.print_exc()
        return False

def load_dc_components():
    """Загрузка DC составляющих из файла"""
    global dc_P1_1, dc_P1_2, dc_L1_1, dc_L1_2
    global dc_counter_P1_1, dc_counter_P1_2, dc_counter_L1_1, dc_counter_L1_2
    global prev_direction_P1_1, prev_direction_P1_2, prev_direction_L1_1, prev_direction_L1_2
    
    # Используем абсолютный путь для гарантированного доступа
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    dc_file_path = os.path.join(script_dir, 'dc_components.json')
    print(f"*** Пытаемся загрузить DC компоненты из файла: {dc_file_path}")
    
    try:
        # Проверяем существование файла
        if not os.path.exists(dc_file_path):
            print(f"Файл DC компонент не существует: {dc_file_path}")
            return False
        
        # Проверяем, что файл не пуст
        if os.path.getsize(dc_file_path) == 0:
            print(f"Файл DC компонент пуст: {dc_file_path}")
            return False
            
        # Открываем файл и загружаем данные
        with open(dc_file_path, 'r') as f:
            file_content = f.read()
            print(f"Прочитано {len(file_content)} байт из файла")
            
            # Проверяем, что файл содержит JSON
            if not file_content.strip().startswith('{'):
                print(f"Файл не содержит JSON данных")
                return False
            
            dc_data = json.loads(file_content)
            print(f"JSON успешно загружен, timestamp: {dc_data.get('timestamp', 'не указан')}")
            
            # Загружаем DC компоненты
            loaded_dc_P1_1 = np.array(dc_data['dc_P1_1'])
            loaded_dc_P1_2 = np.array(dc_data['dc_P1_2'])
            loaded_dc_L1_1 = np.array(dc_data['dc_L1_1'])
            loaded_dc_L1_2 = np.array(dc_data['dc_L1_2'])
            
            # Проверяем размеры массивов
            print(f"Размеры загруженных массивов: P1_1={len(loaded_dc_P1_1)}, P1_2={len(loaded_dc_P1_2)}, " 
                  f"L1_1={len(loaded_dc_L1_1)}, L1_2={len(loaded_dc_L1_2)}")
            
            # Проверяем, что массивы не пустые и имеют нужную длину
            if (len(loaded_dc_P1_1) == 200 and len(loaded_dc_P1_2) == 200 and
                len(loaded_dc_L1_1) == 200 and len(loaded_dc_L1_2) == 200):
                
                # Проверяем, что массивы не содержат только нули
                if not np.all(loaded_dc_P1_1 == 0):
                    # ИСПРАВЛЕНИЕ: Используем np.copyto для обновления содержимого массива вместо создания нового
                    np.copyto(dc_P1_1, loaded_dc_P1_1)
                    np.copyto(dc_P1_2, loaded_dc_P1_2)
                    np.copyto(dc_L1_1, loaded_dc_L1_1)
                    np.copyto(dc_L1_2, loaded_dc_L1_2)
                
                    # Инициализируем счетчики для DC-адаптации
                    dc_counter_P1_1.fill(5)  # Начинаем с уже накопленными счетчиками
                    dc_counter_P1_2.fill(5)
                    dc_counter_L1_1.fill(5)
                    dc_counter_L1_2.fill(5)
                    
                    print(f"*** DC компоненты успешно загружены (сохранены: {dc_data['timestamp']})")
                    print(f"Загружены DC: P1_1 max={np.max(dc_P1_1):.1f}, P1_2 max={np.max(dc_P1_2):.1f}, "
                          f"L1_1 max={np.max(dc_L1_1):.1f}, L1_2 max={np.max(dc_L1_2):.1f}")
                          
                    # Проверяем, что данные действительно скопированы
                    if np.max(dc_P1_1) > 0:
                        print("Проверка успешна: данные не нулевые")
                    else:
                        print("ОШИБКА: данные нулевые после копирования")
                        
                    return True
                else:
                    print("Предупреждение: Загруженные DC компоненты содержат только нули, используются значения по умолчанию")
            else:
                print(f"Предупреждение: Неверная длина загруженных DC компонент: "
                      f"P1_1={len(loaded_dc_P1_1)}, P1_2={len(loaded_dc_P1_2)}, "
                      f"L1_1={len(loaded_dc_L1_1)}, L1_2={len(loaded_dc_L1_2)}")
                
    except FileNotFoundError:
        print(f"Файл с DC компонентами не найден: {dc_file_path}")
    except json.JSONDecodeError as e:
        print(f"Ошибка декодирования JSON файла: {e}")
        # Выводим содержимое файла для отладки
        try:
            with open(dc_file_path, 'r') as f:
                print(f"Первые 100 символов файла: {f.read(100)}")
        except:
            pass
    except Exception as e:
        print(f"Ошибка при загрузке DC компонент: {e}")
        import traceback
        traceback.print_exc()
    
    # Если не удалось загрузить, инициализируем нулевыми значениями
    print("Используем нулевые значения для DC компонент")
    return False

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
    if len(signal) == 0:
        return signal
    
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
    """Оптимизированная версия расчета кросс-корреляции"""
    # Проверка входных данных
    if len(high_level_data) == 0 or len(low_level_data) == 0 or len(high_level_data) != len(low_level_data):
        return np.zeros(2*max_shift+1)
    
    # Используем numpy.correlate для быстрого вычисления корреляции
    # Это намного быстрее ручного расчета
    data_length = len(high_level_data)
    
    # Нормализуем данные
    high_norm = high_level_data - np.mean(high_level_data)
    low_norm = low_level_data - np.mean(low_level_data)
    
    # Используем numpy.correlate с режимом 'full' для получения всех смещений
    # Это намного эффективнее, чем вручную считать смещения в цикле
    full_corr = np.correlate(high_norm, low_norm, mode='full')
    
    # Вырезаем интересующую нас часть корреляции
    mid_point = len(full_corr) // 2
    start_idx = mid_point - max_shift
    end_idx = mid_point + max_shift + 1
    
    # Проверка границ
    if start_idx < 0:
        start_idx = 0
    if end_idx > len(full_corr):
        end_idx = len(full_corr)
        
    result = full_corr[start_idx:end_idx]
    
    # Если полученный результат не соответствует ожидаемой длине, дополняем его нулями
    if len(result) < 2*max_shift+1:
        padding = np.zeros(2*max_shift+1)
        padding[:len(result)] = result
        result = padding
    
    return result[:2*max_shift+1]

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
    if signal is None or len(signal) == 0:
        return np.zeros(1)
    
    # Простой способ: вычесть среднее значение
    return signal - np.mean(signal)

# УДАЛЕНО: def audio_callback(...) - вся функция удалена, так как больше не используется

# Загружаем сохраненные DC компоненты
load_dc_components()
# Проверяем, успешно ли загружены DC компоненты
print("*** Проверка загрузки DC компонент ***")
print(f"DC компоненты: P1_1 max={np.max(dc_P1_1):.1f}, P1_2 max={np.max(dc_P1_2):.1f}, L1_1 max={np.max(dc_L1_1):.1f}, L1_2 max={np.max(dc_L1_2):.1f}")
if np.all(dc_P1_1 == 0):
    print("ВНИМАНИЕ: DC компоненты не были загружены или все значения равны нулю!")
    print("DC компоненты будут накапливаться с нуля")
else:
    print("DC компоненты успешно загружены и готовы к использованию")
    
    
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


def calculate_correlation_dc(correlation_diff, alpha=0.005):
    """
    Вычисляет DC составляющую для разницы корреляций с медленной адаптацией
    
    Args:
        correlation_diff: массив разницы корреляций
        alpha: коэффициент скорости адаптации (меньше = медленнее)
        
    Returns:
        Массив DC компоненты
    """
    if not hasattr(calculate_correlation_dc, 'dc_component'):
        # Инициализация при первом вызове
        calculate_correlation_dc.dc_component = np.zeros_like(correlation_diff)
    
    # Проверка соответствия размеров
    if len(calculate_correlation_dc.dc_component) != len(correlation_diff):
        calculate_correlation_dc.dc_component = np.zeros_like(correlation_diff)
    
    # Экспоненциальное скользящее среднее (EMA)
    calculate_correlation_dc.dc_component = (1-alpha) * calculate_correlation_dc.dc_component + alpha * correlation_diff
    
    return calculate_correlation_dc.dc_component


# Функция переключения графиков
def switch_graph_handler(label):
    global current_oscilloscope, update_needed, show_plot
    current_oscilloscope, update_needed, show_plot = switch_graph(label, buttons, light_green, text_box, [current_oscilloscope], [update_needed], [show_plot], fig)
    settings['current_oscilloscope'] = current_oscilloscope
    save_settings(settings_file, settings)
    update_sliders_range()  # Обновляем диапазоны ползунков
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

def on_close(event):
    """Обработчик закрытия окна, который останавливает PWM и завершает программу"""
    print("Окно закрывается, завершаем приложение")
    
    # Принудительное сохранение DC компонент
    print("Сохраняем DC компоненты перед закрытием...")
    save_dc_components()  # Прямой вызов, не асинхронный
    
    try:
        print("Отправка команды на выключение по SPI...")
        # stop_beep() # Позже здесь будет команда по SPI
        
        # Выключаем все GPIO
        gpio5.off()   # Выключаем индикацию
        gpio22.close()# Закрываем вход
        
        # Закрываем SPI соединения
        spi0.close()
        
        print("Все ресурсы освобождены")
    except Exception as e:
        print(f"Ошибка при закрытии ресурсов: {e}")
    
    # Завершаем программу
    sys.exit(0)

# Добавьте эту переменную перед использованием кнопки beep_mode_button
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
    global correlation_based_detection, update_needed
    correlation_based_detection = not correlation_based_detection
    if correlation_based_detection:
        detection_button.label.set_text("Метод: Корреляция")
    else:
        detection_button.label.set_text("Метод: Дельта амплитуд")
    update_needed = True  # Указываем, что требуется обновление графика
    print(f"Режим обнаружения переключен на: {'корреляция' if correlation_based_detection else 'дельта амплитуд'}")
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

# Используйте асинхронное сохранение в файлы:
def async_save_dc_components():
    threading.Thread(target=save_dc_components).start()


# Конфигурируем pwm
#pwm3 = HardwarePWM(pwm_channel=3, hz=200.0, chip=2)  # OnPWR 196.95120042321б hz=213.35120042321
#pwm2 = HardwarePWM(pwm_channel=2, hz=200.0, chip=2)

print("BMI30.100 version: v", version)

# Добавьте глобальную переменную для управления прерывистым звуком
beep_timer = None  # Таймер для прерывистого сигнала
beep_state = False  # Состояние звукового сигнала (вкл/выкл)

# Заменить функции управления звуком на следующие:
def start_continuous_beep():
    """Включение постоянного звукового сигнала (ВРЕМЕННО ОТКЛЮЧЕНО)"""
    print("SPI_CMD: START_CONTINUOUS_BEEP (disabled)")
    # request_spi_data(adc_id=2, buf_idx=1, start_addr=0, length=0)

def start_intermittent_beep():
    """Включение прерывистого звукового сигнала (ВРЕМЕННО ОТКЛЮЧЕНО)"""
    print("SPI_CMD: START_INTERMITTENT_BEEP (disabled)")
    # request_spi_data(adc_id=2, buf_idx=2, start_addr=0, length=0)

def stop_beep():
    """Остановка любого звукового сигнала (ВРЕМЕННО ОТКЛЮЧЕНО)"""
    global beep_timer
    if beep_timer:
        try:
            beep_timer.cancel()
            beep_timer = None
        except:
            pass
    print("SPI_CMD: STOP_BEEP (disabled)")
    # request_spi_data(adc_id=2, buf_idx=0, start_addr=0, length=0)

def fallback_intermittent_beep():
    """Запасной вариант для прерывистого звука (ВРЕМЕННО ОТКЛЮЧЕНО)"""
    print("SPI_CMD: FALLBACK_INTERMITTENT_BEEP (disabled)")
    # request_spi_data(adc_id=2, buf_idx=2, start_addr=0, length=0)


def ensure_beep_off():
    """Гарантирует, что звуковой сигнал выключен (ВРЕМЕННО ОТКЛЮЧЕНО)"""
    print("SPI_CMD: ENSURE_BEEP_OFF (disabled)")
    # request_spi_data(adc_id=2, buf_idx=0, start_addr=0, length=0)

try:
    gpio5.on()  # GPIO5 LED индикации, включаем
    
    # Гарантируем выключение звукового сигнала при старте
    ensure_beep_off()
    
    fps_limit = 0.03  # Ограничение до ~30 FPS
    last_update_time = 0

    # Добавьте эту переменную для управления отладочным выводом
    debug_output_interval = 10  # Выводить отладочную информацию каждые N циклов
    debug_counter = 0

    while True:
        # ======================================================================
        # ВРЕМЕННО ПОЛНОСТЬЮ ОТКЛЮЧАЕМ ГРАФИЧЕСКИЙ ИНТЕРФЕЙС ДЛЯ ТЕСТА SPI
        # ======================================================================
        
        # ТЕСТ: ожидаем ровно 100 слов (200 байт), первые 2 слова — заголовок
        TEST_TOTAL_WORDS = 100
        EXPECTED_LENGTH_BYTES = TEST_TOTAL_WORDS * 2
        received_bytes = request_spi_data(length_bytes=EXPECTED_LENGTH_BYTES)

        # Получаем текущее время для метки
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Выводим в терминал заголовок и часть данных для проверки
        if received_bytes:
            # Парсим байты в 16-битные слова
            received_words = parse_spi_data(received_bytes)

            if len(received_words) >= 2:
                # Заголовок (HEX), приводим к uint16 для корректного вывода
                header1 = f"{np.uint16(received_words[0]):#06x}"
                header2 = f"{np.uint16(received_words[1]):#06x}"

                # Превью следующих слов (до 16 слов) в HEX
                preview_end = min(2 + 16, len(received_words))
                hex_data_preview = [f"{np.uint16(w):#06x}" for w in received_words[2:preview_end]]

                # Сообщение о длине (проверяем, что 100 слов)
                length_msg = "" if len(received_words) == TEST_TOTAL_WORDS else f" (ожидалось {TEST_TOTAL_WORDS})"

                print(f"{timestamp} | Получено слов: {len(received_words)}{length_msg}. Заголовок: [{header1}, {header2}]. Данные: {hex_data_preview}...")
            else:
                hex_data_preview = [f"{np.uint16(w):#06x}" for w in received_words]
                print(f"{timestamp} | Получено неполных данных: {len(received_words)} слов. Данные: {hex_data_preview}")
        else:
            # Сообщаем о таймауте
            print(f"{timestamp} | Таймаут, данные не получены.")
        
        # Небольшая пауза, чтобы не перегружать процессор и терминал
        time.sleep(0.001)
        continue
        # ======================================================================




        # Проверка закрытия окна
        if not plt.fignum_exists(fig.number):
            print("Окно закрыто, завершаем работу")
            break

        # Ограничение частоты обновления
        current_time = time.time()
        if current_time - last_update_time < fps_limit:
            # Пропускаем обновление, если прошло недостаточно времени
            plt.pause(0.001)  # Короткая пауза для обработки событий
            fig.canvas.start_event_loop(0.001)  # Явный запуск цикла обработки событий
            continue

        last_update_time = current_time
        
        # --- Временная упрощенная логика получения данных ---
        # Длина в 16-битных словах: 2 слова заголовка + CHUNK слов данных
        EXPECTED_LENGTH_WORDS = CHUNK + 2

       # Просто читаем данные, которые готов отдать STM32
        received_words = request_spi_data(length_words=EXPECTED_LENGTH_WORDS * 2) # *2 для байт

        if len(received_words) == EXPECTED_LENGTH_WORDS:
            # Анализируем заголовок, чтобы понять, что мы получили
            source_id = received_words[0] # ID теперь 16-битный
            header2 = received_words[1]   # Второе слово заголовка
            if source_id == 1:
                # Это данные от ADC1 (P1)
                dataADC_P1 = received_words[2:] # Данные начинаются с третьего слова
                dataADC_L1.fill(0) # Обнуляем второй канал
            elif source_id == 2:
                # Это данные от ADC2 (L1)
                dataADC_L1 = received_words[2:] # Данные начинаются с третьего слова
                dataADC_P1.fill(0) # Обнуляем первый канал
            else:
                # Неизвестный ID, обнуляем оба канала
                hex_id = f"{source_id:#06x}"
                print(f"Получен неизвестный ID источника: {hex_id}")
                dataADC_P1.fill(0)
                dataADC_L1.fill(0)
        else:
            # Если ничего не получено (таймаут), обнуляем оба канала
            dataADC_P1.fill(0)
            dataADC_L1.fill(0)
        # --- Конец упрощенной логики ---


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
            CROSS_CORRELATION_SHIFTS
            )
        if not continue_loop:
            break

        # В основном цикле программы, перед проверкой условия обнаружения сигнала:
        # Рассчитываем дельты амплитуд для детекции сигнала
        delta_amp_14, delta_phase_14, delta_amp_15, delta_phase_15 = bmi30_plt.calculate_deltas(
            dataADC_P1, dataADC_L1, sum_P1_1, sum_P1_2, sum_L1_1, sum_L1_2
        )
        
        # После этой строки delta_amp_15 и другие переменные должны иметь правильные значения

        # Добавляем сохранение предыдущего значения порога в начало блока логики адаптивного порога (примерно строка 1010)

        # После периода стабилизации применяем логику адаптации
        prev_threshold = adaptive_threshold  # Сохраняем предыдущее значение порога

        if stabilization_cycles < STABILIZATION_LIMIT:
            # Период стабилизации - не меняем порог
            stabilization_cycles += 1
            if debug_output:
                print(f"Стабилизация: цикл {stabilization_cycles}/{STABILIZATION_LIMIT}, порог: {adaptive_threshold:.0f}")
        else:
            # После периода стабилизации применяем логику адаптации
            if delta_amp_15 > adaptive_threshold:
                # Сигнал превышает порог - увеличиваем порог в любом случае
                adaptive_threshold += threshold_increase_rate
                
                # Отключаем адаптацию при первом обнаружении
                if threshold_update_enabled:
                    threshold_update_enabled = False
                    delta_pfase_signal_on = abs(delta_phase_15 - prev_delta_phase_15)
                    if debug_output:
                        print(f"Сигнал обнаружен, адаптация отключена, порог: {adaptive_threshold:.0f} ; Δфазы: {delta_pfase_signal_on}")
                
                # Сбрасываем счетчик измерений ниже порога
                below_threshold_counter = 0
            
            # Добавляем новое условие для "слепой зоны" - когда сигнал ниже порога, но с учетом запаса превышает порог
            elif delta_amp_15 > 0 and delta_amp_15 * threshold_margin >= adaptive_threshold and delta_amp_15 <= adaptive_threshold:
                # Сигнал в "слепой зоне" - повышаем порог адаптивно
                blind_zone_diff = (delta_amp_15 * threshold_margin) - adaptive_threshold
                
                # Определяем скорость увеличения в зависимости от разницы
                if blind_zone_diff > 10000:
                    increase_amount = 1000
                elif blind_zone_diff > 1000:
                    increase_amount = 100
                elif blind_zone_diff > 100:
                    increase_amount = 10
                else:
                    increase_amount = 1
                
                # Увеличиваем порог на нужную величину
                adaptive_threshold += increase_amount
                
                # Продолжаем адаптацию в этом случае
                below_threshold_counter = 0
                
            elif delta_amp_15 > 0 and delta_amp_15 * threshold_margin < adaptive_threshold:
                # Сигнал ниже порога
                below_threshold_counter += 1
                
                if threshold_update_enabled:
                    # Адаптация включена - настраиваем порог под уровень шума
                    if delta_amp_15 > 0:  # Если есть какой-то сигнал
                        # Устанавливаем порог чуть выше уровня шума
                        new_threshold = delta_amp_15 * threshold_margin
                        # Если новый порог выше текущего - используем его
                        # иначе АДАПТИВНО снижаем текущий порог
                        if new_threshold > adaptive_threshold:
                            adaptive_threshold = new_threshold
                            if debug_output:
                                print(f"Порог повышен до уровня шума+{(threshold_margin-1)*100:.0f}%: {adaptive_threshold:.0f}")
                        else:
                            # Рассчитываем разницу между текущим и желаемым порогом
                            threshold_diff = adaptive_threshold - new_threshold
                            
                            # Определяем скорость уменьшения в зависимости от разницы
                            if threshold_diff > 100000:
                                decrease_amount = 1000
                            elif threshold_diff > 10000:
                                decrease_amount = 100
                            elif threshold_diff > 1000:
                                decrease_amount = 10
                            else:
                                decrease_amount = threshold_decrease_rate  # Стандартный шаг для малых разниц
                            
                            # Уменьшаем порог на вычисленную величину
                            adaptive_threshold -= decrease_amount
                            
                            #if debug_output:
                            #    print(f"Порог адаптивно снижается на {decrease_amount}: {adaptive_threshold:.0f}")
                            
                elif below_threshold_counter >= below_threshold_limit:
                    # Если сигнал был ниже порога достаточно долго - включаем адаптацию
                    threshold_update_enabled = True
                    #if debug_output:
                        #print(f"Адаптация порога включена после {below_threshold_counter} измерений ниже порога")

        # Теперь условие обнаружения сигнала с обновленным адаптивным порогом по дельте амплитуд
        if delta_amp_15 > adaptive_threshold:
            # Проверяем, находится ли новая дельта фаз на том же уровне (в пределах порога)
            if abs(delta_phase_15 - prev_delta_phase_15) <= stable_phase_threshold:
                consecutive_detections += 1
                # Сигнализируем только если значения стабильны в течение нужного числа отсчетов
                if consecutive_detections >= count_phase:
                    # Принудительно включаем BEEP в зависимости от выбранного режима
                    if beep_mode == "continuous":
                        start_continuous_beep()
                    else:
                        start_intermittent_beep()
                    
                    # Сохраняем данные о текущем обнаружении
                    last_max_amplitude = delta_amp_15  # Сохраняем дельту амплитуд вместо максимальной амплитуды
                    last_max_phase = delta_phase_15    # Сохраняем дельту фаз вместо фазы максимума
                    last_phase_diff = abs(delta_phase_15 - prev_delta_phase_15)
                    last_beep_timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    print(f"Сигнал обнаружен! Δ амплитуд: {delta_amp_15:.0f}; Порог: {adaptive_threshold:.0f}; Δ фаз: {delta_phase_15}; Стабильность: {last_phase_diff:.0f};")
            else:
                # Если фаза изменилась значительно, сбрасываем счетчик и адаптируем порог
                consecutive_detections = 1
                
                # Сразу устанавливаем адаптивный порог равным сигналу с учетом запаса
                #old_threshold = adaptive_threshold
                #adaptive_threshold = adaptive_threshold * threshold_margin
                
                if debug_output:
                    print(f"Фаза нестабильна, сбрасываем счетчик, адаптивный порог стал: {adaptive_threshold:.0f}")
            
            # Обновляем предыдущие значения для следующей итерации
            prev_max_amp_15 = max_amp_15
            prev_max_phase_15 = max_phase_15
            prev_delta_amp_15 = delta_amp_15
            prev_delta_phase_15 = delta_phase_15
        else:
            # Если амплитуда ниже порога, сбрасываем счетчик и выключаем BEEP
           
            consecutive_detections = 0
            stop_beep()  # Останавливаем любой звуковой сигнал
            
            # Дополнительная проверка - выключен ли звук
            if beep_pwm is not None:
                print("PWM всё ещё активен, принудительно выключаем")
                ensure_beep_off()
            
            # Проверяем время тишины
            current_time = time.time()
            silent_time = current_time - last_beep_time
            
            # Выводим количество времени без сигнала и информацию о последнем обнаружении
            if debug_output:
                minutes, seconds = divmod(int(silent_time), 60)
                hours, minutes = divmod(minutes, 60)
                
                time_str = ""
                if hours > 0:
                    time_str = f"{hours}ч {minutes}м {seconds}с"
                else:
                    time_str = f"{minutes}м {seconds}с"
                
                # Добавляем информацию о последнем обнаружении, если оно было
                if last_max_amplitude > 0:
                    print(f"Время без сигнала: {time_str} | Последний сигнал ({last_beep_timestamp}): "
                          f"A={last_max_amplitude:.0f}, Ф={last_max_phase:.0f}, ΔФ={last_phase_diff:.0f}")
                else:
                    print(f"Время без сигнала: {time_str} | Сигнал не был обнаружен")
                
                #if max_amp_15 > 0 и max_amp_15 < adaptive_threshold:
                #    print(f"Текущая амплитуда ниже порога: {max_amp_15:.0f} < {adaptive_threshold:.0f}")

        # Исправляем логику отображения изменений порога (примерно строка 1145-1158)

        if debug_output:
            signal_threshold = delta_amp_15 * threshold_margin  # Вычисляем пороговое значение на основе текущей дельты
            comp_symbol = '<' if signal_threshold < adaptive_threshold else '>'
            
            # Определяем стрелку направления в зависимости от того, как изменился порог
            threshold_diff = adaptive_threshold - prev_threshold
            if threshold_diff > 0:
                arrow = "↑"
            else:
                arrow = "↓"
            
            # Сохраняем значение изменения
            change_value = abs(threshold_diff)
            
            info_str = (
                f"Текущий порог: {adaptive_threshold:.0f} | "
                f"ΔA15: {delta_amp_15:.0f} | "
                f"ΔФ15: {delta_phase_15:.0f} | "
                f"Порог стаб.: {stable_phasethreshold} | "
                f"Режим: {'~' if threshold_update_enabled else '-'} | "
                f"Порог: {arrow} {change_value:3.0f}"
            )
            # Добавьте в строку info_str после существующего вывода
            if correlation_based_detection and len(cross_correlation_sum) > 0 and len(antiphase_correlation_sum) > 0:
                correlation_diff = cross_correlation_sum - antiphase_correlation_sum
                info_str += f" | Корреляция: макс={np.max(correlation_diff):.0f}, мин={np.min(correlation_diff):.0f}"
            
            print(info_str)

        # Сохранение DC компонент каждые DC_SAVE_INTERVAL секунд
        current_time = time.time()
        if current_time - last_dc_save_time >= DC_SAVE_INTERVAL:
            # Проверяем, что прошло достаточно времени с последнего сохранения
            if last_dc_save_time > 0:
                elapsed_time = current_time - last_dc_save_time
                if elapsed_time < DC_SAVE_INTERVAL:
                    time_to_next_save = DC_SAVE_INTERVAL - elapsed_time
                    # Принудительная пауза, чтобы не перегружать систему
                    plt.pause(time_to_next_save)
            
            # Сохраняем DC компоненты асинхронно
            async_save_dc_components()
            last_dc_save_time = current_time

        # Сохранение адаптивных порогов каждые THRESHOLD_SAVE_INTERVAL секунд
        current_time = time.time()
        if current_time - last_threshold_save_time >= THRESHOLD_SAVE_INTERVAL:
            # Сохраняем настройки и адаптивные пороги
            save_settings(settings_file, settings)
            last_threshold_save_time = current_time
            if debug_output:
                print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!Адаптивные пороги сохранены: {adaptive_threshold:.0f}, delta_amp_15={delta_amp_15:.0f}, delta_phase_15={delta_phase_15}")

        # Вместо прямого вызова в основном цикле:
        if current_time - last_dc_save_time >= DC_SAVE_INTERVAL:
            async_save_dc_components()
            last_dc_save_time = current_time


        # В основном цикле, после обновления адаптивного порога:
        if adaptive_threshold != last_threshold_value:
            #print(f"Порог изменен: {last_threshold_value:.0f} -> {adaptive_threshold:.0f}")
            last_threshold_value = adaptive_threshold

        # В основном цикле после вызова update_graph добавьте:

        # Специальный код для принудительного обновления графика 31
        if current_oscilloscope == 31 and show_plot:
            # Принудительно обновляем данные линий
            shifts = np.arange(-CROSS_CORRELATION_SHIFTS, CROSS_CORRELATION_SHIFTS + 1)
            line1.set_data(shifts, cross_correlation_sum)
            # Принудительно обновляем график, даже если update_needed=False
            fig.canvas.draw_idle()

        # Замените весь блок обработки корреляции в основном цикле на этот:
        if correlation_based_detection and len(cross_correlation_sum) and len(antiphase_correlation_sum) > 0:
            # Вычисляем разницу корреляций только для отображения на графике 29
            correlation_diff = cross_correlation_sum - antiphase_correlation_sum
            
            # Для отладки можно оставить базовую информацию
            if debug_output:
                print(f"Корреляция: максимум={np.max(correlation_diff):.0f}, минимум={np.min(correlation_diff):.0f}")

        # В основном цикле:
        debug_counter += 1
        if debug_output and debug_counter >= debug_output_interval:
            # Вывод отладочной информации
            print(f"Отладка: текущий порог {adaptive_threshold:.0f}")
            debug_counter = 0

        if correlation_based_detection:
            # Логика обнаружения на основе корреляции
            if len(cross_correlation_sum) > 0 and len(antiphase_correlation_sum) > 0:
                correlation_diff = cross_correlation_sum - antiphase_correlation_sum
                if len(correlation_diff) > correlation_index:
                    correlation_value = correlation_diff[correlation_index]
                    if correlation_value > adaptive_correlation_threshold:
                        correlation_detection_count += 1
                        if correlation_detection_count >= correlation_detection_threshold:
                            start_continuous_beep()  # Или другой метод звукового сигнала
                    else:
                        correlation_detection_count = 0
        else:
            # Логика обнаружения на основе дельта амплитуд
            if delta_amp_15 > adaptive_threshold:
                consecutive_detections += 1
               
                if consecutive_detections >= count_phase:
                    start_continuous_beep()
            else:
                consecutive_detections = 0

except KeyboardInterrupt:
    print("Остановка по Ctrl+C")
    # Очистка ресурсов
    gpio5.off()
    gpio22.close()
    spi0.close()
    print("Все ресурсы освобождены, программа остановлена")
    sys.exit(0)
except Exception as e:
    print(f"Ошибка: {e}")
    traceback.print_exc()
    
finally:
    plt.ioff()
    print("Остановка осциллограммы, завершаем работу...")
    
    # Принудительное сохранение DC компонент перед выходом
    print("Выполняем финальное сохранение DC компонент...")
    save_dc_components()
    
    plt.close(fig)

    gpio5.off()
    gpio22.close()
    spi0.close()
    print("PWM выключен, GPIO5 = 0")



