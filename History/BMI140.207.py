''' Программа детектирования метки.
151:16.12.2024 добавлено выключение PWM при любом завершении программы
200:06.01.2025 делаем прием стерео ацп
202:14.01.2025 получили фронт и спад правого канала

'''


import serial_protocol_ld2450               # Для радара
import serial                               # Для радара
import gpiod                                # битовое управление портами
import time
from rpi_hardware_pwm import HardwarePWM    # Для аппаратного PWM

import matplotlib.pyplot as plt
import numpy as np
import pyaudio

from numba import jit
import random
import atexit
import subprocess

def stop_pwm():    # Принудительная остановка шим при окончании работы
    print("Останавливаем PWM...")
    try:
        pwm1.change_frequency(9999990) 
        pwm1.stop()
        pwm2.change_frequency(9999990) 
        pwm2.stop()
    except Exception as e:
        print(f"Ошибка при остановке PWM: {e}")

atexit.register(stop_pwm) # регистрируем функцию для остановки PWM перед завершением


# Пользовательские параметры
allowing_radar_rule = 0         # Разрешение радару управлять системой
waveform_output_display = 11    # Разрешение вывода на экран: 0-без вывода; 1-сырого сигнала; 2-сигнала без постоянной; 3-постоянная составляющая сигнала
                                # 4-сумма по фронту; 5-сумма по спаду; 6-сумма 7 циклов без DC; 7- тест; 8-вторая производная; 9-тест; 10-самые сырые данные stereo;
                                # 11-зона фронта/спада правого канала; 12-зона фронта/спада левого канала; 13-DC фронта/спада правого канала; 14-DC фронта/спада левого канала;
                                # 15-фронт/спад правого канала -DC; 16-фронт/спад левого канала -DC;
                                
chunk_start_out = 0             # стартовый номер семпла выводимых на экран
chunk_out1 = 3840               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;
chunk_out2 = 240               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;
chunk_out8 = 238


# Конфигурация порта ввода/вывода для индикации состояния вкл/выкл
led_PIN = 22							# Порт упроавления светодиодом (15 контакт разьема)
led_PIN_tag = 16
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(led_PIN)
led_line_tag = chip.get_line(led_PIN_tag)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)
led_line_tag.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

chunk = 23040           # Устанавливаем исходное количество семлов считывания  (46080 расчетное)  32765  (23040 подобрано опытным путем); 3839: 2 периода 200Гц; 
rate_ADC = 384000       # Частота семплирования АЦП 384 kHz
pwm1_hz = 200           # Исходная частота PWM1
pwm2_hz = 200           # Исходная частота PWM2

chunk0 = int(chunk / 2)
chunk2 = int(chunk * 2)
chunk_period1 = int(rate_ADC / pwm1_hz)    # количество семплов в одном периоде канала 1
chunk_period2 = int(rate_ADC / pwm2_hz)    # количество семплов в одном периоде канала 2
sync_samles1 = chunk - int(chunk_period1 * 0.8)  # количество семплов ИСПОЛЬЗУЕМОЕ ДЛЯ синхронизации в канале 1
sync_samles2 = chunk - int(chunk_period2 * 0.8)  # количество семплов ИСПОЛЬЗУЕМОЕ ДЛЯ синхронизации в канале 1

p = pyaudio.PyAudio()

# Массивы
dataADC = np.zeros(chunk, 'int64')
dataADC01 = np.zeros(chunk, 'int64')
dataADC02 = np.zeros(chunk, 'int64')
dataADC1 = np.zeros(chunk, 'int64')                           # список принятых данных с первого канала ADC
dataADC2 = np.zeros(chunk, 'int64')
dataADC3 = np.zeros(chunk, 'int64')
dataADC4 = np.zeros(chunk, 'int64')
dataADC5 = np.zeros(chunk, 'int64')
dataADC6 = np.zeros(chunk, 'int64')
dataADC7 = np.zeros(chunk, 'int64')
dataADC8 = np.zeros(chunk, 'int64')
dataADC9 = np.zeros(chunk, 'int64')

# Константы
chunk = 23040
chunk_out2 = 240
threshold = 20000
count_accum = 1000
start_index_front = 320
start_index_spad = 1280


# Инициализация массивов
adc_P0 = np.zeros(chunk, dtype=np.int16)    # Сырые данные - правый канал
adc_L0 = np.zeros(chunk, dtype=np.int16)    # Сырые данные - левый канал
adc_P0f = np.zeros(chunk_out2, dtype=np.int16)  # Средние данные - правый канал по фронту
adc_P0s = np.zeros(chunk_out2, dtype=np.int16)  # Средние данные - правый канал по спаду
adc_L0f = np.zeros(chunk_out2, dtype=np.int16)  # Средние данные - левый канал по фронту
adc_L0s = np.zeros(chunk_out2, dtype=np.int16)  # Средние данные - левый канал по спаду
sinhro = 0


@jit(nopython=True)
def process_data(adc_P0, adc_L0, valid_starts, num_events):
    front_values_P = np.empty((num_events, chunk_out2), dtype=np.int16)
    spad_values_P = np.empty((num_events, chunk_out2), dtype=np.int16)
    front_values_L = np.empty((num_events, chunk_out2), dtype=np.int16)
    spad_values_L = np.empty((num_events, chunk_out2), dtype=np.int16)


    for i in range(num_events):
        start_index = valid_starts[i]
        
        front_start_P = start_index + start_index_front
        spad_start_P = start_index + start_index_spad
        front_start_L = start_index + start_index_front
        spad_start_L = start_index + start_index_spad


        # Заполняем массивы, если размер подходит
        if front_start_P + chunk_out2 <= len(adc_P0):
            front_values_P[i, :] = adc_P0[front_start_P:front_start_P + chunk_out2]
        if spad_start_P + chunk_out2 <= len(adc_P0):
            spad_values_P[i, :] = adc_P0[spad_start_P:spad_start_P + chunk_out2]
        if front_start_L + chunk_out2 <= len(adc_L0):
            front_values_L[i, :] = adc_L0[front_start_L:front_start_L + chunk_out2]
        if spad_start_L + chunk_out2 <= len(adc_L0):
            spad_values_L[i, :] = adc_L0[spad_start_L:spad_start_L + chunk_out2]
        
        if i > 4:
            break

    return front_values_P, spad_values_P, front_values_L, spad_values_L


def callback(in_data, frame_count, time_info, status):
    global adc_L0, adc_P0, adc_P0f, adc_P0s, adc_L0f, adc_L0s
    global sinhro


    led_line.set_value(1)
    
    # Извлекаем данные из буфера и разделяем каналы
    data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    data_length = len(data)
    
    adc_L0[:data_length] = data[:, 0]  # Заполняем левый канал
    adc_P0[:data_length] = data[:, 1]  # Заполняем правый канал


    # Условия для обнаружения событий
    condition = (adc_P0[:-35] < threshold) & (adc_P0[1:-34] > threshold) & \
                (adc_P0[28:-7] > threshold) & (adc_P0[35:] < threshold)
    valid_starts = np.where(condition)[0]
    num_events = valid_starts.size
    
    # Если нет действительных событий, возвращаем данные
    if num_events == 0:
        return (in_data, pyaudio.paContinue)

    # Вызываем функцию для обработки данных
    front_values_P, spad_values_P, front_values_L, spad_values_L = process_data(adc_P0, adc_L0, valid_starts, num_events)


    # Вычисляем усреднённые значения каналов
    if front_values_P.shape[0] > 0:
        adc_P0f = np.round(np.mean(front_values_P, axis=0)).astype(int)


    if spad_values_P.shape[0] > 0:
        adc_P0s = np.round(np.mean(spad_values_P, axis=0)).astype(int)


    if front_values_L.shape[0] > 0:
        adc_L0f = np.round(np.mean(front_values_L, axis=0)).astype(int)


    if spad_values_L.shape[0] > 0:
        adc_L0s = np.round(np.mean(spad_values_L, axis=0)).astype(int)


    led_line.set_value(0)
    sinhro = 1


    return (in_data, pyaudio.paContinue)



stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=rate_ADC,
                input=True,
                frames_per_buffer=chunk,
                stream_callback=callback)

# Установка громкости записи с микрофона:
#command = f"amixer set Capture {22}%"
subprocess.run(f"amixer set Capture {22}%", shell=True)

pwm1 = HardwarePWM(pwm_channel=2, hz=pwm1_hz, chip=2)    # pwm_channel 1: 3-GPIO_18; 2-GPIO_19; 
pwm2 = HardwarePWM(pwm_channel=3, hz=pwm2_hz, chip=2)    # pwm_channel 1: 3-GPIO_18; 2-GPIO_19;


if allowing_radar_rule:
    # открытие последовательного пота для считывания радара
    ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)


if waveform_output_display:
    # инициализируем объекты графика
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.canvas.manager.set_window_title("Осциллограмма: " + __file__.split('\\')[-1])  # Заголовок окнаА

    plt.subplots_adjust(left=0.09,
                        right=0.99,
                        top=0.99,
                        bottom=0.0425,
                        wspace=0.3,
                        hspace=0.0)
    
    if waveform_output_display == 10:
        x_axis = np.arange(0, chunk_out1)
        line_p, = ax.plot(x_axis, adc_P0[chunk_start_out:chunk_out1+chunk_start_out:], label='adc_P0', color='blue', linestyle='-')  # ?????? ??? data_to_sum_p
        line_l, = ax.plot(x_axis, adc_L0[chunk_start_out:chunk_out1+chunk_start_out:], label='adc_L0', color='red', linestyle='-')   # ?????? ??? data_to_sum_n
        
        ax.set_ylim(-37000, 37000)
        ax.set_xlim = (0, chunk_out2)
        ax.grid(which='major', alpha=0.6, color='green', linestyle='--', linewidth=1.4)
        
    if waveform_output_display == 11:
        x_axis = np.arange(0, chunk_out2)
        line_p, = ax.plot(x_axis, adc_P0f, label='adc_P0f', color='blue', linestyle='-')  # ?????? ??? data_to_sum_p
        line_l, = ax.plot(x_axis, adc_P0s, label='adc_P0s', color='red', linestyle='-')   # ?????? ??? data_to_sum_n
        
        ax.set_ylim(-34000, 34000)
        ax.set_xlim = (0, chunk_out2)
        ax.grid(which='major', alpha=0.6, color='green', linestyle='--', linewidth=1.4)
        

    fig.show()




# Cистемные переменные
start_time = time.time()  	# сохраняем время старта выполнения программы
timer = start_time			# Для отсчета длительности таймера
timerR = start_time			# Для отсчета таймера детектирования по радару
timerT = start_time			# Для отсчета таймера
time_wr = time.time()       # Для отсчета ВРЕМЕНИ ЗАПИСИ D10C
timer_test = time.time() 
count_time_detect = 0       # Для отсчета НАЧАЛА ДЕТЕКТИРОВАНИЯ МЕТКИ

speed = 0                   # детектор наличия скорости в любом из трех обьектов радара
on_off_pwm = 0 				# Для управлениея состоянием PWM
stop_adr = 0                # Cтоповый адрес для синхронизации
flag_stop = 0               # Флаг для тестирования
flag_adc = 0                # Флаг для переключения массива данных с АЦП


max_mean = 0

tau1 = 1                  # постоянная времени вычисления DC
tau2 = 10
tau3 = 100
tau4 = 1000
trigger_treshold1 =  1500
trigger_treshold2 =  5500
trigger_treshold3 =  24000

max_variable = 0            # максимум переменной составляющей сигнала для АРУ 10%
dataINP_max = 0             # максимум переменной составляющей результирующег сигнала
#plt.show()
temp = 0
flag_det_tag = 0    # флаг детектора меток
count_delay_tag = 1 # счетчик длительности наличия метки
count_delay_notag = 1 # счетчик длительности отсутствия метки
delay100 = 0
marked_tau = '~'
flag_first_alignment = 0    # флаг первого выравнивания сигнала после запуска






try:                          # для аккуратного принудительного останова программы с закрытием портов
#if 1==1:
    running = True
    pwm1.start(51)			# Включаем передачу 1-го канала

    stream.start_stream()           # Включаем прием АЦП

    while running and stream.is_active():
        
        
        if allowing_radar_rule:
            # чтение последовательного порта.
            serial_port_line = ser.read_until(serial_protocol_ld2450.REPORT_TAIL)
            all_target_values = serial_protocol_ld2450.read_radar_data(serial_port_line)
        
            if all_target_values is None:
                continue

            target1_x, target1_y, target1_speed, target1_distance_res, \
            target2_x, target2_y, target2_speed, target2_distance_res, \
            target3_x, target3_y, target3_speed, target3_distance_res \
                = all_target_values

            if target1_speed !=0 or target2_speed != 0 or target3_speed != 0:       # проверка наличия скорости у радара всех обьектов
                speed = 1
            else:
                speed = 0
            
            if (target1_x != 0 and -1000 < target1_x < 800) or (target2_x != 0 and -1000 < target2_x < 800):	# проверка диапазона по координате X, обьектов 1 и 2
                xLed1 = 1
            else:
                xLed1 = 0
            
            if (target1_y !=0 and -1400 < target1_y < 0) or (target2_y !=0 and -1400 < target2_y < 0):		# проверка диапазона по координате Y, обьектов 1 и 2
                yLed1 = 1
            else:
                yLed1 = 0
        
            if speed or xLed1 or yLed1:    	# Обновляем таймер,при выполненных условиях 
                timer = time.time()
            
            if time.time() - timer < 10:	# Управляем светодиодом / генератором передатчика
                led_line.set_value(0)
                timerR = int(time.time() - timer)
                on_off_pwm = 1
                pwm1.start(50)			# Включаем передачу 1-го канала
            else:
                led_line.set_value(1)
                timerR = "~"
                on_off_pwm = 0
                pwm1.stop()			    # Выключаем передачу 1-го канала

            # Вывод результатов радара
            print(f'1-{xLed1}{yLed1}{speed}/{timerR:1}: X:{target1_x:4} /', f'Y:{target1_y:5} /', f' V: {target1_speed:3} cm/s/', f'D: {target1_distance_res:4} |', f'2: X:{target2_x:4} /', f'Y:{target2_y:5} /', f' V: {target2_speed:4} cm/s/', f'D: {target2_distance_res:4} |', f'3: X:{target3_x:5} /', f'Y:{target3_y:5} /', f' V: {target3_speed:4} cm/s/', f'D: {target3_distance_res:4}', end="\r")


        # ------------------------------------------------------------------------------------------------------------------------------

        if sinhro:
            sinhro = 0
            if waveform_output_display == 10:                         # отображаем осциллограмму сырого входного сигнала
                line_p.set_ydata(adc_P0[chunk_start_out:chunk_out1+chunk_start_out:])  # График массива сырых данных adc_P0
                line_l.set_ydata(adc_L0[chunk_start_out:chunk_out1+chunk_start_out:])  # График массива сырых данных adc_L0
            
                fig.canvas.draw()
                fig.canvas.flush_events()
            
            if waveform_output_display == 11:                         # отображаем осциллограмму сырого входного сигнала
                line_p.set_ydata(adc_P0f)  # График массива сырых данных adc_P0
                line_l.set_ydata(adc_P0s)  # График массива сырых данных adc_L0
            
                fig.canvas.draw()
                fig.canvas.flush_events()
            
                


        if time.time() - time_wr > 180:
            time_wr = time.time()
            # Записываем файл каждые 100 сек
            np.save('tab_DC.npy', dataDC)
            np.save('tab_DC_p.npy', dataDC_p)
            np.save('tab_DC_n.npy', dataDC_n)
            print('Save DC:', int(time.time()), '+++++++++++++++++++++++++++++++++++++++++++++++++++++++')

        if not plt.fignum_exists(fig.number):
            running = False

except Exception as e:
#if 1==0:
    print(f"1. MAIN: Ошибка: {repr(e)}", e)
    pwm1.change_frequency(9999990)
    pwm1.stop()			    # Выключаем передачу 1-го канала
    stream.stop_stream()
    stream.close()
    p.terminate()

finally:
#if 1==0:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    if allowing_radar_rule:
        ser.close()
    led_line.set_value(1)
    pwm1.stop()			    # Выключаем передачу 1-го канала
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("\n\n1. MAIN: UART порт закрыт и светодиод/pwm выключен")
    pwm = HardwarePWM(pwm_channel=2, hz=100, chip=2)    # pwm_channel: 3-GPIO_18; 2-GPIO_19; 

    pwm.change_frequency(9999990)
    pwm.stop














