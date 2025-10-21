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


# Пользовательские параметры

allowing_radar_rule = 0         # Разрешение радару управлять системой
waveform_output_display = 1     # Разрешение вывода на экран: 0-без вывода; 1-сырого сигнала; 2-сигнала без постоянной; 3-постоянная составляющая сигнала
CHUNK_start_out = 0             # стартовый номер семпла выводимых на экран
CHUNK_out1 = 1920               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;
CHUNK_out2 = 220               # Количество выводимых на экран семплов: 1920-1 период; 2880-1.5 периода; 3840-2 периода;

# Конфигурация порта ввода/вывода для индикации состояния вкл/выкл
LED_PIN = 22							# Порт упроавления светодиодом (15 контакт разьема)
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

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
#print(chip.input(22))

#@jit
def callback(in_data, frame_count, time_info, status):
    #if led_line.get_value():
    #    led_line.set_value(0)
    #else:
    led_line.set_value(1)
    #timerP = time.time_ns()
    #global dataADC1
    #global count_inp_ADC
    global start_adr
    global count_start
    global dataADC1
    flag_synchro = 0
    ADCmax = 0
    new_array = np.zeros(0)
    
    # синхронизация
    if len(dataADC1) > CHUNK2:                               # количество данных больше чем одно считывание
        for i in range(0, CHUNK):
            if flag_synchro or (dataADC1[i] < 7000 and dataADC1[i+1] > 7000 and dataADC1[i+31] < -3000):
                flag_synchro = 1
                if dataADC1[i] > ADCmax:
                    ADCmax = dataADC1[i]
                else:
                    start_adr = i
                    if i > 12:
                        new_array = dataADC1[CHUNK + int(i/1.2):]
                        #dataADC1 = np.delete(dataADC1, dataADC1[0:CHUNK + int(i/1.2):])
                        #del dataADC1[0:CHUNK + 1]
                    else:
                        if i > 8:
                            new_array = dataADC1[CHUNK + 1:]
                        else:
                            if i > 4:
                                new_array = dataADC1[CHUNK:]
                            else:
                                new_array = dataADC1[CHUNK - 1:]
                    
                    break 
            if i > CHUNK0:
                new_array = dataADC1[0:CHUNK]
                break
    else:
        new_data = np.fromstring(in_data, dtype=np.int16)
        dataADC1 = np.concatenate((dataADC1, new_data))
        return (in_data, pyaudio.paContinue)
    
    if start_adr < 10:
        count_start += 1
    else:
        count_start = 0
    #print(start_adr, len(dataADC1), count_start)    

    new_data = np.fromstring(in_data, dtype=np.int16)
    dataADC1 = np.concatenate((new_array, new_data))

    #print(start_adr, len(dataADC1), count_start) 
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


dataADC1 = np.zeros(0)                         # список принятых данных с первого канала ADC
dataINP1 = np.zeros(CHUNK_out2, 'int64')       # массив с компенсациЕЙ постоянной составляющей и АРУ
dataINP11 = np.zeros(CHUNK_out2, 'int64')       # массив с компенсациЕЙ постоянной составляющей и АРУ
dataINP_result = np.zeros(0)                    # Результирующий массив

dataDC = np.zeros(CHUNK_out2, 'int64')         # массив с постоянной составляющей 
data_to_sum_p = np.zeros(CHUNK_out2, 'int64')
data_to_sum_n = np.zeros(CHUNK_out2, 'int64')


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
    if waveform_output_display > 1:
        x_axis = np.arange(0, CHUNK_out2 * 2, 2)
        display_line, = ax.plot(x_axis, np.random.rand(CHUNK_out2), 'r')
        ax.set_ylim(-67000, 67000)
        ax.ser_xlim = (0, CHUNK_out2)


    fig.show()


# Cистемные переменные
start_time = time.time()  	# сохраняем время старта выполнения программы
timer = start_time			# Для отсчета длительности таймера
timerR = start_time			# Для отсчета таймера детектирования по радару
timerT = start_time			# Для отсчета таймера
time_wr = time.time()       # Для отсчета ВРЕМЕНИ ЗАПИСИ DC

fled_line = 0
speed = 0                   # детектор наличия скорости в любом из трех обьектов радара
on_off_pwm = 0 				# Для управлениея состоянием PWM
stop_adr = 0                # Cтоповый адрес для синхронизации
flag_stop = 0               # Флаг для тестирования
flag_adc = 0                # Флаг для переключения массива данных с АЦП
count_sample = 0            # количество семплов в массиве

tau = 10                     # постоянная времени вычисления DC
max_variable = 0            # максимум переменной составляющей сигнала для АРУ 10%


#plt.show()
temp = 0


mark01 = 100    # начало рабочей границы фронта исходного сигнала
mark02 = 100    # конец рабочей границы фронта исходного сигнала
mark03 = 200    # начало рабочей границы спада исходного сигнала
mark04 = 300    # конец рабочей границы спада исходного сигнала

mark11 =  360   # начало рабочей границы фронта -DC 335
mark12 =  45   # конец рабочей границы фронта -DC
mark13 =  200   # начало рабочей границы спада -DC
mark14 =  300   # конец рабочей границы спада -DC
mark15 =  386   # 1 метка -DC
mark16 = 335   # 2 метка -DC
mark17 = 575   # 3 метка -DC
mark18 = 1295   # 4 метка -DC

y_indices = np.arange(12)  # индексы от 0 до 11
start_address = start_adr + mark11
stop_address = 220 + start_address


#try:                        # для аккуратного принудительного останова программы с закрытием портов
if 1==1:
    pwm1.start(51)			# Включаем передачу 1-го канала
#    stream.stop_stream()
#    stream.close()
#    p.terminate()
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
        #else:  
        
        #data = stream.read(CHUNK)
        #dataInt = list(struct.unpack(str(CHUNK * 2) + 'h', data))
        #dataInt1 = dataInt[0::2]  # разделяем стереоканалы, это левый канал с синхросигналом первая осциллограмма
        #dataInt2 = dataInt[1::2]  # разделяем стереоканалы, это правый канал с входными данными втроая осциллограмма
        
        #data = pwm_adc.start_adc(CHUNK)

        #print(len(dataADC1), len(dataDC))

        #dataInt = list(struct.unpack(str((CHUNK) * 4) + 'h', pwm_adc_101.start_adc(CHUNK * 2)))
        #dataADC1.extend(pwm_adc_101.start_adc(CHUNK))           # добавляем новые данные от первого канала АЦП в конец списка

        #print(count_inp_ADC, len(dataADC1))

        if count_sample != count_start and len(dataADC1) > CHUNK:                               # количество данных больше чем одно считывание
        #if 1==1:
            count_sample = count_start
            #led_line.set_value(1)
                 
            #for i in range(0, CHUNK):                      # находим начало цикла 12 периодов первому встреченному переходу меньше/больше нуля
            #    if dataADC1[i] < 7000 and dataADC1[i+1] > 7000 and dataADC1[i+36] < -5000: 
            #        start_adr = i
            #        break


            #print(start_adr, len(dataADC1), count_start, '!')      #, dataADC1[1], dataADC1[2], dataADC1[3], dataADC1[4], dataADC1[5] ) 
            #print(count_inp_ADC, start_adr, len(dataADC1))


            #print (len(dataINP1), dataINP1[0:50])
            
            # массив одного периода исходных данных
            #dataINP1 = np.array(np.concatenate([dataADC1[start_adress + (960*i):stop_adress + (960*i)] for i in range(2)])) - dataDC
            #for y in range (12):
            #    dataINP1 = dataINP1 + np.array(np.concatenate([dataADC1[start_adress+(960*i)+(1920*y):stop_adress+(960*i)+(1920*y)] for i in range(2)])) - dataDC
            
            #dataINP1 = np.array(np.concatenate([dataINP1 + np.array(np.concatenate([dataADC1[start_adress+(960*i)+(1920*y):stop_adress+(960*i)+(1920*y)] for i in range(2)])) - dataDC] for y in range (12)))
                   



            # Генерируем все индексы для 12 сумм
            #y_indices = np.arange(12).reshape(-1, 1)  # 12 строк B 1 столбец
            #i_indices = np.arange(2)  # индексы для 2-х диапазонов

            # извлекаем данные с добавлением смещения (получили двумерный массив 24 х 220)
            #data_to_sum_p = np.sum([dataADC1[start_adress + (1920 * y) : stop_adress + (1920 * y)] for y in range(12)], axis=0)
            #data_to_sum_n = np.sum([dataADC1[start_adress + 955 + (1920 * y) : stop_adress + 955 + (1920 * y)] for y in range(12)], axis=0)

            #-----------------------------

            # создадим мощности от общих индексов для облегчения выборки
            #y_indices = np.arange(12) * 1920
            # для data_to_sum_p
            #data_to_sum_p = np.sum(dataADC1[start_adress + y_indices[:, None]: stop_adress + y_indices[:, None]], axis=0)

            # для data_to_sum_n
            #data_to_sum_n = np.sum(dataADC1[start_adress + 955 + y_indices[:, None]: stop_adress + 955 + y_indices[:, None]], axis=0)
            # --------------------------------


            #data_to_sum_p = np.sum(dataADC1[start_adress + (1920 * y_indices[:, None]): stop_adress + (1920 * y_indices[:, None])], axis=0)
            #data_to_sum_n = np.sum(dataADC1[start_adress + 955 + (1920 * y_indices[:, None]): stop_adress + 955 + (1920 * y_indices[:, None])], axis=0)


            #data_to_sum_p = np.sum(dataADC1[np.arange(start_adress, stop_adress)[:, None] + (1920 * y_indices)], axis=0)
            #data_to_sum_n = np.sum(dataADC1[np.arange(start_adress + 955, stop_adress + 955)[:, None] + (1920 * y_indices)], axis=0)

            # ??????? ??????? ??? data_to_sum_p
            #indices_p = np.r_[start_adress + (1920 * y_indices)[:, None]: stop_adress + (1920 * y_indices)[:, None]]

            # ??????? ??????? ??? data_to_sum_n
            #indices_n = np.r_[start_adress + 955 + (1920 * y_indices)[:, None]: stop_adress + 955 + (1920 * y_indices)[:, None]]

            #------------------------------------------

            #indices_p = start_adress + (1920 * y_indices)[:, None] + np.arange(stop_adress - start_adress)
            #indices_n = start_adress + 955 + (1920 * y_indices)[:, None] + np.arange(stop_adress - start_adress)

            #print(indices_p)

            #-----------------------------------------------

            #indices_p = start_adress + (1920 * y_indices[:, None]) + np.arange(stop_adress - start_adress)  # ??????? ??????? ??? data_to_sum_p
            #indices_n = (start_adress + 955) + (1920 * y_indices[:, None]) + np.arange(stop_adress - start_adress)  # ??????? ??? data_to_sum_n


            # ????????? ??????
            #data_to_sum_p = np.sum(dataADC1[indices_p], axis=0)
            #data_to_sum_n = np.sum(dataADC1[indices_n], axis=0)

            #---------------------------------------------------------

            indices_p = np.arange(start_address, stop_address)[:, None] + (1920 * y_indices)

            # ????????? ??????? ??? ????????????? ??????
            indices_n = np.arange(start_address + 955, stop_address + 955)[:, None] + (1920 * y_indices)

            #print(indices_p)

            #data_to_sum_p = np.sum(dataADC1[start_address + (1920 * y_indices[:, None]): stop_address + (1920 * y_indices[:, None])], axis=0)
            #data_to_sum_n = np.sum(dataADC1[start_address + 955 + (1920 * y_indices[:, None]): stop_address + 955 + (1920 * y_indices[:, None])], axis=0)

            data_to_sum_p = np.sum(dataADC1[indices_p], axis=0)
            data_to_sum_n = np.sum(dataADC1[indices_n], axis=0)

            dataINP11 = (data_to_sum_p - data_to_sum_n - dataDC)

            #dataINP_result = (dataINP_result + dataINP11) / 2
            #dataINP_result = dataINP11
            
            
            
            # конкатенируем полученные данные и вычитаем dataDC
            #data_sum = np.sum(data_to_sum_p, axis=0)

            #print (len(data_to_sum))

            #dataINP11 = dataINP1 - dataDC

            dataDC = np.where(dataINP11 > 0, dataDC + 1, dataDC - 1)
            
            #result = np.array([np.sum(arr[i::5][:3]) for i in range(3)])

            
            #print (len(dataINP1), dataINP1[0:50])
            #print (len(dataDC), dataDC[0:300])

            #dataDC = np.where(dataADC1[start_adress:stop_adress:] > dataDC, 1,  1)
            
            #print (dataDC[0:300])
            #dataADC1[start_adress: stop_adress:]


            # отображаем осциллограмму
            if waveform_output_display == 1:                         # отображаем осциллограмму сырого входного сигнала

                dataADC1[start_adr+19200] = dataADC1[start_adr+19200] + 5000
                dataADC1[start_adr+21120] = dataADC1[start_adr+21120] + 10000
                dataADC1[start_adr+23040] = dataADC1[start_adr+23040] + 5000
                dataADC1[start_adr+44160] = dataADC1[start_adr+44160] + 5000
                dataADC1[start_adr+46080] = dataADC1[start_adr+46080] + 5000

                display_line.set_ydata(dataADC1[CHUNK_start_out:CHUNK_out1+CHUNK_start_out].tolist())
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 2:                         # отображаем осциллограмму входного сигнала с компенсированным DC
                
                dataINP11[mark12] = dataINP1[mark12] + 100
                dataINP11[mark13] = dataINP1[mark13] - 100
                
                display_line.set_ydata(dataINP11 * 200)
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 3:                         # отображаем осциллограмму DC
                display_line.set_ydata(dataDC)
                fig.canvas.draw()
                fig.canvas.flush_events()


        #dataADC1[start_adr]
        #print(count_inp_ADC, f't:{timerT:.3f}', f'start:{start_adr:5}', stop_adr, len(dataADC1))
        

        if time.time() - time_wr > 100:
            time_wr = time.time()
            # Записываем файл каждые 100 сек
            np.save('tab_DC.npy', dataDC)
            print('Save DC:', int(time.time()))



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
