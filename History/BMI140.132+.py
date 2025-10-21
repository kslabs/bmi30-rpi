import serial_protocol_ld2450               # Для радара
import serial                               # Для радара
import gpiod                                # битовое управление портами
import time
#import pwm_adc_101                            
#from gpiozero import PWMLED                 # программный PWM
from rpi_hardware_pwm import HardwarePWM    # Для аппаратного PWM

import matplotlib.pyplot as plt
import numpy as np
import pyaudio

import json
import sys
#sys.exit(1)    - Остановка выполнения программы
from numba import jit
import random


# Пользовательские параметры

allowing_radar_rule = 0         # Разрешение радару управлять системой
waveform_output_display = 1     # Разрешение вывода на экран: 0-без вывода; 1-сырого сигнала; 2-сигнала без постоянной; 3-постоянная составляющая сигнала
                                # 4-сумма по фронту; 5-сумма по спаду; 6-сумма 7 циклов без DC; 7- тест; 8-вторая производная; 9-тест
CHUNK_start_out = 0             # стартовый номер семпла выводимых на экран
CHUNK_out1 = 1920               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;
CHUNK_out2 = 240               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;
CHUNK_out8 = 238

# Конфигурация порта ввода/вывода для индикации состояния вкл/выкл
LED_PIN = 22							# Порт упроавления светодиодом (15 контакт разьема)
LED_PIN_tag = 16
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line_tag = chip.get_line(LED_PIN_tag)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)
led_line_tag.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

CHUNK = 23040        # Устанавливаем количество семлов считывания  (46080 расчетное)  32765  (23041 подобрано опытным путем); 3839: 2 периода 200Гц; 
RATE = 384000       # Equivalent to Human Hearing at 40 kHz

CHUNK0 = int(CHUNK / 2)
CHUNK2 = int(CHUNK * 2)
CHUNK25 = int(CHUNK * 2.5)
CHUNK3 = int(CHUNK * 3)
CHUNK4 = int(CHUNK * 4)

p = pyaudio.PyAudio()
count_inp_ADC = 0
fcount_inp_ADC = 0
start_adr = 0               # Cтартовый адрес для синхронизации
timerP = 0                  # таймер для потока
count_start = 0             # каждое изменение потока данных меняется переменная
start_adress = start_adr + 380
stop_adress = 240 + start_adress
tau_start_adr = 3

#@jit
def callback(in_data, frame_count, time_info, status):
    led_line.set_value(1)
    global dataADC, dataADC1, dataADC2, dataADC3, dataADC4, dataADC5, dataADC6, dataADC7
    global start_adr, count_start, data_to_sum_p, data_to_sum_n, start_adress, stop_adress, tau_start_adr
    flag_synchro = 0
    ADCmax = 0

    # синхронизация
    if len(dataADC1) > CHUNK:

        for i in range(0, CHUNK):
            if flag_synchro or (dataADC1[i] < 7000 and dataADC1[i+1] > 7000 and dataADC1[i+31] < -3000):
                flag_synchro = 1
                if dataADC1[i] > ADCmax:
                    ADCmax = dataADC1[i]
                else:
                    # Удаляем начало массива
                    start_adr = i
                    dataADC7, dataADC6, dataADC5, dataADC4, dataADC3 = np.roll([dataADC6, dataADC5, dataADC4, dataADC3, dataADC2], shift=1) 
                    if i > 16:
                        dataADC2 = np.copy(dataADC1[:CHUNK])
                        dataADC1 = dataADC1[CHUNK + int(i / 1.2):]
                    else:
                        if i > 8:
                            dataADC2 = np.copy(dataADC1[:CHUNK])
                            dataADC1 = dataADC1[CHUNK + 1:]
                        else:
                            if i > 3:
                                dataADC2 = np.copy(dataADC1[:CHUNK])
                                dataADC1 = dataADC1[CHUNK:]
                            else:
                                dataADC2 = np.copy(dataADC1[:CHUNK])
                                dataADC1 = dataADC1[CHUNK - 1:]
                    break 
            if i > CHUNK0:
                dataADC7, dataADC6, dataADC5, dataADC4, dataADC3 = np.roll([dataADC6, dataADC5, dataADC4, dataADC3, dataADC2], shift=1)
                dataADC2 = np.copy(dataADC1[:CHUNK])
                dataADC1 = dataADC1[CHUNK:]
                break
    
    #new_data = np.frombuffer(in_data, dtype=np.int16)
    #dataADC1 = np.concatenate((dataADC1, new_data))

    new_data = np.frombuffer(in_data, dtype=np.int16)
    dataADC1 = np.concatenate((dataADC1, new_data))
    
    
    #print(start_adr,  len(dataADC), len(dataADC1), len(dataADC2),len(dataADC3), len(dataADC4), len(dataADC5),len(dataADC7), count_start)

    if start_adr < 10 and tau_start_adr == 0:
        count_start += 1
        
        dataADC = np.concatenate((dataADC7, dataADC6, dataADC5,dataADC4, dataADC3, dataADC2, dataADC1))
        #print(start_adr, len(dataADC1), count_start)

        #y_indices = np.arange(int(len(dataADC1) / 1920))
        #num_segments = len(dataADC) // 1920
        #y_indices = np.arange(num_segments)

        
        #y_indices = np.array([0, 1, 2])  # ??? ?????????? ?????? ????????
        #print(dataADC[y_indices])  # ??? ????? ????????, ???? y_indices ???????? ?????????? ???????

        #y_indices_start = np.array([0, 1, 2])
        #y_indices_stop = np.array([3, 4, 5])
        #print(dataADC[y_indices_start])     
        #print(dataADC[y_indices_start : y_indices_stop])
        


        y_indices_p = np.arange(int(len(dataADC) / 1920)) * 1920
        y_indices_n = np.arange(int(len(dataADC) / 1920)) * 1920 + 955
        
        #y_indices_start = np.arange((int((len(dataADC) - 1920) / 1920) * 1920) + start_adress)
        #y_indices_start = np.arange(int((len(dataADC) - 0) / 1920)) * 1920 + start_adress
        #y_indices_stop = np.arange(int((len(dataADC) - 0) / 1920)) * 1920 + stop_adress

        #print(start_adr, stop_adress, len(dataADC), len(dataADC1), len(dataADC2),len(dataADC3), count_start, y_indices)
        #print(len(dataADC), 'Start', len(y_indices_p), y_indices_p)
        #print(len(dataADC), 'Stop', len(y_indices_n), y_indices_n)
        
        #print(len(dataADC)

        #data_to_sum_p = np.mean(dataADC[start_adress + (1920 * y_indices) : stop_adress + (1920 * y_indices)], axis=0)
        #data_to_sum_n = np.mean(dataADC[start_adress + 955 + (1920 * y_indices) : stop_adress + 955 + (1920 * y_indices)], axis=0)

        data_to_sum_p = np.mean([dataADC[start_adress + y : stop_adress + y] for y in y_indices_p], axis=0)
        data_to_sum_n = np.mean([dataADC[start_adress + y : stop_adress + y] for y in y_indices_n], axis=0)


        #data_to_sum_p = np.mean(dataADC[start_adress + (1920 * y_indices)[:, None]: stop_adress + (1920 * y_indices)[:, None]], axis=1)
        #data_to_sum_p = np.mean(dataADC[start_adress + (1920 * y_indices[:, None]): stop_adress + (1920 * y_indices[:, None])], axis=1)
        #data_to_sum_n = np.mean(dataADC[start_adress + 955 + (1920 * y_indices)[:, None]: stop_adress + 955 + (1920 * y_indices)[:, None]], axis=1)
        #data_to_sum_n = np.mean(dataADC[start_adress + 955 + (1920 * y_indices[:, None]): stop_adress + 955 + (1920 * y_indices[:, None])], axis=1)

    else:
        count_start = 0

    
    #print(num_chunks,  len(dataADC1))


    led_line.set_value(0)
    return (in_data, pyaudio.paContinue)




stream = p.open(format=pyaudio.paInt16,
                channels=1,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=callback)

#dataADC1 = np.zeros(CHUNK2, dtype=int)       # список принятых данных с первого канала ADC dataADC1
#dataINP1 = np.zeros(CHUNK2, dtype=int)       # массив с компенсации постоянной составляющей и АРУ

dataADC = np.zeros(CHUNK, 'int64')
dataADC1 = np.zeros(CHUNK, 'int64')                           # список принятых данных с первого канала ADC
dataADC2 = np.zeros(CHUNK, 'int64')
dataADC3 = np.zeros(CHUNK, 'int64')
dataADC4 = np.zeros(CHUNK, 'int64')
dataADC5 = np.zeros(CHUNK, 'int64')
dataADC6 = np.zeros(CHUNK, 'int64')
dataADC7 = np.zeros(CHUNK, 'int64')
dataINP1 = np.zeros(CHUNK_out2, 'int64')       # массив с компенсациЕЙ постоянной составляющей и АРУ
dataINP11 = np.zeros(CHUNK_out2, 'int64')       # массив с компенсациЕЙ постоянной составляющей и АРУ
dataINP_result = np.zeros(CHUNK_out2, 'int64')                   # Результирующий массив
dataINP_result1 = np.zeros(CHUNK_out2, 'int64')                   # Результирующий массив
dataINP_res_tau = np.zeros(CHUNK_out2, 'int64')              # массив длительностей роста и спада 

dataDC = np.zeros(CHUNK_out2, 'int64')         # массив с постоянной составляющей 
data_to_sum_p = np.zeros(CHUNK_out2, 'int64')
data_to_sum_n = np.zeros(CHUNK_out2, 'int64')
temp_add20 = np.zeros(20, 'int64')


#print(len(dataADC1), len(dataDC))
#sys.exit(1)


# Загружаем файл DC
try:
    dataDC = np.load('tab_DC.npy')
except FileNotFoundError:
    print('1.2. tab_DC.txt ')
    time.sleep(3)

if allowing_radar_rule:
    # открытие последовательного пота для считывания радара
    ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)

pwm1 = HardwarePWM(pwm_channel=2, hz=200.00920042321, chip=2)    # pwm_channel 1: 3-GPIO_18; 2-GPIO_19; 

if waveform_output_display:
    # инициализируем объекты графика
    fig, ax = plt.subplots(1, 1)
    fig.canvas.manager.set_window_title("Осциллограмма: " + __file__.split('\\')[-1])  # Заголовок окна
    plt.minorticks_on()
    ax = plt.subplot(1, 1, 1)
    plt.grid(which='major', alpha=0.6, color='green', linestyle='--', linewidth=1.4)
    plt.subplots_adjust(left=0.09,
                        right=0.99,
                        top=0.99,
                        bottom=0.0425,
                        wspace=0.3,
                        hspace=0.0)
    # создаем массив равный массиву CHUNK 
    # ось X задается полулогарифмической,
    if waveform_output_display == 1:
        x_axis = np.arange(0, CHUNK_out1 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out1), 'r')
        ax.set_ylim(-17000, 17000)
        ax.ser_xlim = (0, CHUNK_out1)
    
    if waveform_output_display == 2:
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out2), 'r')
        ax.set_ylim(-35000, 35000)
        ax.ser_xlim = (0, CHUNK_out2)

    if waveform_output_display == 4 or waveform_output_display == 5:
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out2), '.-')
        ax.set_ylim(-2500, 2500)
        ax.ser_xlim = (0, CHUNK_out2)
        #ax = np.linspace(100.0, 500.0)

    if waveform_output_display == 6:
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out2), '.-')
        ax.set_ylim(-32000, 32000)
        ax.ser_xlim = (0, CHUNK_out2)
        #ax = np.linspace(100.0, 500.0)

    if waveform_output_display == 7:
        dt = 0.01
        t = np.arange(0, 10, dt)
        nse = np.random.randn(len(t))
        r = np.exp(-t / 0.05)
        cnse = np.convolve(nse, r) * dt
        cnse = cnse[:len(t)]
        display_fft = 0.1 * np.sin(2 * np.pi * t) + cnse
        #print(len(s))
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)

    if waveform_output_display == 8:
        x_axis = np.arange(0, CHUNK_out8 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out8), '.-')
        ax.set_ylim(-100, 100)
        ax.ser_xlim = (0, CHUNK_out8)
        #ax = np.linspace(100.0, 500.0)

    if waveform_output_display == 9:
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out2), '.-')
        ax.set_ylim(-1000, 1000)
        ax.ser_xlim = (0, CHUNK_out2)
        #ax = np.linspace(100.0, 500.0)

        
        #ax.set_ylim(-32000, 32000)
        #ax.ser_xlim = (0, CHUNK_out2)
        #ax = np.linspace(100.0, 500.0)


    fig.show()


# Cистемные переменные
start_time = time.time()  	# сохраняем время старта выполнения программы
timer = start_time			# Для отсчета длительности таймера
timerR = start_time			# Для отсчета таймера детектирования по радару
timerT = start_time			# Для отсчета таймера
time_wr = time.time()       # Для отсчета ВРЕМЕНИ ЗАПИСИ D10C
timer_test = time.time() 
count_time_detect = 0       # Для отсчета НАЧАЛА ДЕТЕКТИРОВАНИЯ МЕТКИ

fled_line = 0
speed = 0                   # детектор наличия скорости в любом из трех обьектов радара
on_off_pwm = 0 				# Для управлениея состоянием PWM
stop_adr = 0                # Cтоповый адрес для синхронизации
flag_stop = 0               # Флаг для тестирования
flag_adc = 0                # Флаг для переключения массива данных с АЦП
count_sample = 0            # количество семплов в массиве

max_mean = 0

tau1 = 1                  # постоянная времени вычисления DC
tau2 = 10
tau3 = 100
tau4 = 1000
trigger_treshold1 =  1500
trigger_treshold2 =  6000
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

mark01 = 100    # начало рабочей границы фронта исходного сигнала
mark02 = 100    # конец рабочей границы фронта исходного сигнала
mark03 = 200    # начало рабочей границы спада исходного сигнала
mark04 = 300    # конец рабочей границы спада исходного сигнала


mark11 =  380   # начало рабочей границы фронта -DC 335         20 31 45 62 73
mark12 =  21   # конец рабочей границы фронта -DC
mark13 =  32   # начало рабочей границы спада -DC
mark14 =  45   # конец рабочей границы спада -DC
mark15 =  61   # 1 метка -DC
mark16 =  73   # 2 метка -DC
mark17 = 575   # 3 метка -DC
mark18 = 1295   # 4 метка -DC

indices_dataINP_result_p = np.array([  0, 1, 2, 3, 4, 5, 6,  7,  8,  9,  10,  11,  12,  13, 14, 15, 16,17,18,19,20,21,22,52,53,54,55,56,57,58,59, 60, 61, 62,  63,  64,  65, 66, 67, 68,69,70,71,72,73,74,75])
indices_dataINP_result_p = indices_dataINP_result_p.astype(int)
# Последовательность Квадратичная
indices_dataINP_result_pk2 = np.array([1, 2, 4, 8,16,32,64,128,256,512,1024,2048,1536,1024,512,256,128,64,32,16, 8, 4, 2, 1, 1, 2, 4, 8,16,32,64,128,256,512,1024,2048,1024,512,256,128,64,32,16, 8, 4, 2, 1])
# Последовательность Фибоначи
indices_dataINP_result_pkf = np.array([1, 1, 2, 3, 5, 8,13, 21, 34, 55,  89, 144, 144,  89, 55, 34, 21,13, 8, 5, 3, 2, 1, 1, 1, 2, 3, 5, 8,13,21, 34, 55, 89, 144, 144, 144, 89, 55, 34,21,13, 8, 5, 3, 2, 1])


indices_dataINP_result_n = np.array([23,24,25,26,27,28,29, 30, 31, 32,  33,  34,  35,  36,  37,  38,  39, 40, 41, 42, 43, 44,45,46,47,48,49,50,51])
indices_dataINP_result_n = indices_dataINP_result_n.astype(int)

indices_dataINP_result_nk2 = np.array([1, 2, 4, 8,16,32,64,128,256,512,1024,2048,4096,3072,2048,1536,1024,768,512,384,256,128,64,32,16, 8, 4, 2, 1])
indices_dataINP_result_nkf = np.array([1, 1, 2, 3, 5, 8,13, 21, 34, 55,  89, 144, 233, 188, 144, 116,  89, 72, 55, 44, 34, 21,13, 8, 5, 3, 2, 1, 1])




#try:                        # для аккуратного принудительного останова программы с закрытием портов
if 1==1:
    pwm1.start(51)			# Включаем передачу 1-го канала

    stream.start_stream()           # Включаем прием АЦП

    while stream.is_active():
        timerT = time.time() - timer        # подсчет длительности выполнения одной итерации цикла
        timer = time.time()

        #start_adr = 0                      # сбрасываем стартовый адрес для нового значения

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

        if start_adr > 9:
            tau_start_adr = 10
        else:
            count_sample = count_start
            #led_line.set_value(1)
                 

            dataINP11 = ((data_to_sum_p - data_to_sum_n) * 500) - dataDC
            dataINP12 = dataINP11 - np.mean(dataINP11)

            dataINP_result = ((dataINP_result + dataINP12) // 2).astype(int)
            #dataINP_result = int((dataINP_result1 + dataINP12) / 2)
            np.copyto(dataINP_result1, dataINP_result)


            # Детектируем метку
            dataINP_max = np.max(abs(dataINP_result))
            if flag_first_alignment and tau_start_adr==0 and dataINP_max > trigger_treshold2 + (int(count_delay_tag / 100) * 10000):
                flag_det_tag += 1
                marked_tau = ' +'
            else:
                if tau_start_adr:
                    tau_start_adr -= 1

                random_number = random.randint(0, 100)
                if count_delay_notag > 100 + random_number:
                    dataDC = np.where(abs(dataINP_result)<trigger_treshold1, np.where(dataINP_result>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP_result)<trigger_treshold2, np.where(dataINP_result>0, dataDC+tau2, dataDC-tau2), np.where(abs(dataINP_result)<trigger_treshold3, np.where(dataINP_result>0, dataDC+tau3, dataDC-tau3),np.where(dataINP_result>0, dataDC+tau4, dataDC-tau4))))
                    #dataDC = np.where(abs(dataINP11)<2000, np.where(dataINP11>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP11)>trigger_treshold, np.where(dataINP11>0, dataDC+tau3, dataDC-tau3), np.where(dataINP11>0, dataDC+tau2,dataDC-tau2)))

                if dataINP_max < trigger_treshold2:
                    flag_det_tag = 0
                    marked_tau = ' -'
                    flag_first_alignment = 1
                else:
                    marked_tau = ' ~'
                


            
            dataINP_count = np.zeros(CHUNK_out2, 'int64')
            # Последовательность Фибоначи 36
            #data_fib = [1,1,2,3,5,8,13,21,34,55,89,144,233,377,610,987,1597,2584,4181,6765,10946,17711,28657,46368,75025,121393,196418,317811,514229,832040,1346269,2178309,3524578,5702887,922746]
            flag_znak= 0
            dataINP_res_tau = np.zeros(CHUNK_out2, 'int64')
            count_y = 0
            
            for i in range(0, CHUNK_out2):
                if dataINP_result[i] > dataINP_result[i-1]:
                    if flag_znak:
                        dataINP_count[i] = int(dataINP_count[i-1] + 1)
                        #if abs(dataINP_count[i]) > 0:
                        dataINP_res_tau[count_y] = dataINP_count[i]
                    else:
                        dataINP_count[i] = int(dataINP_count[i-1] - 1)
                        flag_znak = 1
                        #if abs(dataINP_count[i]) > 0:
                        count_y += 1
                else:
                    if dataINP_result[i] < dataINP_result[i-1]:
                        if flag_znak:
                            dataINP_count[i] = int(dataINP_count[i-1] + 1)
                            flag_znak = 0
                            #if abs(dataINP_count[i]) > 0:
                            count_y += 1
                        else:
                            dataINP_count[i] = int(dataINP_count[i-1] - 1)
                            #if abs(dataINP_count[i]) > 0:
                            dataINP_res_tau[count_y] = dataINP_count[i]
                    else:
                        if flag_znak:
                            dataINP_count[i] = int(dataINP_count[i-1] + 1)
                        else:
                            dataINP_count[i] = int(dataINP_count[i-1] - 1)
            
            
            diff_all2 = np.diff(dataINP_res_tau, n=2)







            mean_dataINP_count = int(np.mean(dataINP_count))
            #max_mean = 0

            if start_adr > 10:
                print('Сбой:', start_adr)

            #dataDC = np.where(abs(dataINP11)<1000, np.where(dataINP11>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP11)>10000, np.where(dataINP11>0, dataDC+tau3, dataDC-tau3), np.where(dataINP11>0, dataDC+tau2,dataDC-tau2)))
            if count_time_detect > 10 and flag_first_alignment: 
                diff_sum_first = int(np.sum(abs(diff_all2[0:7])))
                diff_sum_second = int(np.sum(abs(diff_all2[7:14])))
                #print(diff_sum_first)
                if flag_det_tag > 0 and abs(mean_dataINP_count) < 15 and diff_sum_first > 100:   # первые 10 сек не детектировать и проверять условие: средняя составляющая должна быть меньше 33. 
                    # Метка найдена
                    if count_delay_tag == 0:
                        max_mean = 0
                        print(' ')
                    if abs(max_mean) < abs(mean_dataINP_count):
                        max_mean = mean_dataINP_count
                        
                    print(marked_tau, f'{count_delay_tag:4}', f'Метка определена с максимальным уровнем сигнала:{dataINP_max:6}', f'| Mean:{mean_dataINP_count:4}', f'/{max_mean:4}',f'/{diff_sum_first:4}', '      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!       ', end='\r')
                    #dataDC = np.where(abs(dataINP11)<2000, np.where(dataINP11>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP11)>6000, np.where(dataINP11>0, dataDC+tau1, dataDC-tau1), np.where(dataINP11>0, dataDC+tau1,dataDC-tau1)))
                    count_delay_tag += 1
                    count_delay_notag = 0
                    led_line_tag.set_value(0)
                else:
                    random_number = random.randint(0, 100)
                    if count_delay_notag > random_number:
                        dataDC = np.where(abs(dataINP_result)<trigger_treshold1, np.where(dataINP_result>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP_result)<trigger_treshold2, np.where(dataINP_result>0, dataDC+tau2, dataDC-tau2), np.where(abs(dataINP_result)<trigger_treshold3, np.where(dataINP_result>0, dataDC+tau3, dataDC-tau3),np.where(dataINP_result>0, dataDC+tau4, dataDC-tau4))))
                        #dataDC = np.where(abs(dataINP11)<2000, np.where(dataINP11>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP11)>trigger_treshold2, np.where(dataINP11>0, dataDC+tau3, dataDC-tau3), np.where(dataINP11>0, dataDC+tau2,dataDC-tau2)))

                    if count_delay_tag >0:
                        max_mean = 0
                        print(' ')
                    else:
                        if abs(mean_dataINP_count) > abs(max_mean):
                            max_mean = mean_dataINP_count
                    print(marked_tau, f'{count_delay_notag:4}', f'Метки нет.         Максимальный уровень сигнала:{dataINP_max:6}', f'| Mean:{mean_dataINP_count:4}', f'/{max_mean:4}',f'/{diff_sum_first:4}', '      ----------------------------------------------------------      ', end='\r')
                    count_delay_tag = 0
                    count_delay_notag += 1
                    if count_delay_notag > 10:
                        led_line_tag.set_value(1)

            else:
                dataDC = np.where(abs(dataINP_result)<trigger_treshold1, np.where(dataINP_result>0, dataDC+tau1,dataDC-tau1), np.where(abs(dataINP_result)<trigger_treshold2, np.where(dataINP_result>0, dataDC+tau2, dataDC-tau2), np.where(abs(dataINP_result)<trigger_treshold3, np.where(dataINP_result>0, dataDC+tau3, dataDC-tau3),np.where(dataINP_result>0, dataDC+tau4, dataDC-tau4))))

                if flag_first_alignment and int(time.time() - timer_test) != count_time_detect:
                    print(' Задержка включения детекции метки при старте на:', count_time_detect, '/10 сек', f'| Mean:{mean_dataINP_count:3}', '      ', end='\r')
                    count_time_detect = int(time.time() - timer_test)
                else:
                    if flag_first_alignment == 0:
                        timer_test = time.time() 




            # отображаем осциллограмму
            if waveform_output_display == 1:                         # отображаем осциллограмму сырого входного сигнала

                dataADC1[start_adr+19200] = dataADC1[start_adr+19200] + 5000
                dataADC1[start_adr+21120] = dataADC1[start_adr+21120] + 10000
                dataADC1[start_adr+23040] = dataADC1[start_adr+23040] + 5000
                #dataADC1[start_adr+44160] = dataADC1[start_adr+44160] + 5000
                #dataADC1[start_adr+46080] = dataADC1[start_adr+46080] + 5000

                display_line.set_ydata(dataADC1[CHUNK_start_out:CHUNK_out1+CHUNK_start_out:])
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 2:                         # отображаем осциллограмму входного сигнала с компенсированным DC
                
                dataINP12[mark12] = dataINP12[mark12] - 5000
                dataINP12[mark13] = dataINP12[mark13] + 5000
                dataINP12[mark14] = dataINP12[mark14] - 5000
                dataINP12[mark15] = dataINP12[mark15] + 5000
                dataINP12[mark16] = dataINP12[mark16] - 5000

                display_line.set_ydata(dataINP12)
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 3:                         # отображаем осциллограмму DC
                display_line.set_ydata(dataDC)
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 4:                         # отображаем осциллограмму DC
                display_line.set_ydata(data_to_sum_p)
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 5:                         # отображаем осциллограмму DC
                display_line.set_ydata(data_to_sum_n)
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 6:                         # отображаем результирующую осциллограмму усредненного сигнала 7-х циклов с компенсированным DC
                
                temp = abs(int(np.mean(dataINP_result[0:60]) - np.mean(dataINP_result[180:240]))) 
                
                if temp < 10000:
                    #print(temp, np.sum(dataINP_result[indices_dataINP_result_p], axis=0), np.sum(dataINP_result[indices_dataINP_result_n], axis=0))
                    tau = 1
                else:
                    tau = 10
                dataINP_result1[mark12] = dataINP_result[mark12] - 3000
                dataINP_result1[mark13] = dataINP_result[mark13] + 3000
                dataINP_result1[mark14] = dataINP_result[mark14] - 3000
                dataINP_result1[mark15] = dataINP_result[mark15] + 3000
                dataINP_result1[mark16] = dataINP_result[mark16] - 3000
                dataINP_result1[0] = dataINP_result[0] + 3000


                dataINP_result1[239] = dataINP_result1[239] + 0.0001 * np.sum(dataINP_result[indices_dataINP_result_p] * indices_dataINP_result_pk2, axis=0)
                dataINP_result1[237] = dataINP_result1[237] - 0.0001 * np.sum(dataINP_result[indices_dataINP_result_p] * indices_dataINP_result_pk2, axis=0)
                dataINP_result1[232] = dataINP_result1[232] + 0.0001 * np.sum(dataINP_result[indices_dataINP_result_n] * indices_dataINP_result_nk2, axis=0)
                dataINP_result1[230] = dataINP_result1[230] - 0.0001 * np.sum(dataINP_result[indices_dataINP_result_n] * indices_dataINP_result_nk2, axis=0)

                
                display_line.set_ydata(dataINP_result1)
                fig.canvas.draw()
                fig.canvas.flush_events()

            if waveform_output_display == 7:                         # отображаем осциллограмму DC
                display_fft.psd(data_to_sum_n, 512, 1 / dt)
                fig.canvas.draw()
                fig.canvas.flush_events()

            if waveform_output_display == 8:                         # отображаем осциллограмму DC

                display_line.set_ydata(diff_all2)
                fig.canvas.draw()
                fig.canvas.flush_events()
                #print(temp2[0:20])
            if waveform_output_display == 9:                         # отображаем осциллограмму DC
                display_line.set_ydata(increasing)
                fig.canvas.draw()
                fig.canvas.flush_events()

        

        if time.time() - time_wr > 180:
            time_wr = time.time()
            # Записываем файл каждые 100 сек
            np.save('tab_DC.npy', dataDC)
            print('Save DC:', int(time.time()), '+++++++++++++++++++++++++++++++++++++++++++++++++++++++')



        #pwm_adc_101.stop_pwm()
#except Exception as e:
if 1==0:
    print(f"1. MAIN: Ошибка: {repr(e)}", e)
    pwm1.stop()			    # Выключаем передачу 1-го канала
    stream.stop_stream()
    stream.close()
    p.terminate()

#finally:
if 1==0:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    if allowing_radar_rule:
        ser.close()
    led_line.set_value(1)
    pwm1.stop()			    # Выключаем передачу 1-го канала
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("\n\n1. MAIN: UART порт закрыт и светодиод/pwm выключен")
