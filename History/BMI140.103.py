import serial_protocol_ld2450               # Для радара
import serial                               # Для радара
import gpiod                                # битовое управление портами
import time
import pwm_adc_101                            
from gpiozero import PWMLED                 # программный PWM

import matplotlib.pyplot as plt
import numpy as np

import json




# Пользовательские параметры

allowing_radar_rule = 0         # Разрешение радару управлять системой
waveform_output_display = 1     # Разрешение вывода на экран: 1-сырого сигнала; 2-сигнала без постоянной;

# Конфигурация порта ввода/вывода для индикации состояния вкл/выкл
LED_PIN = 22							# Порт упроавления светодиодом (15 контакт разьема)
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

CHUNK = 23041      # Устанавливаем количество семлов считывания  (46080 расчетное)  32765  (23041 подобрано опытным путем)
pwm_adc_101.conf(CHUNK)
dataADC1 = []       # список принятых данных с первого канала ADC
dataINP1 = []       # массив с компенсации постоянной составляющей и АРУ
dataDC = []         # массив с постоянной составляющей 
for i in range(0, int(CHUNK)):
    dataINP1.append(0)                                                                                                                                                                   
    dataDC.append(0)

# Загружаем файл DC
try:
    with open('tab_DC.txt', 'r', encoding='utf-8') as fr:
        length_file = len(fr.read())
        if length_file > 10:
            with open('tab_DC.txt', 'r', encoding='utf-8') as fr:
                dataDC = json.load(fr)
        else:
            print('1.1. tab_DC.txt ??????!')
except FileNotFoundError:
    print('1.2. tab_DC.txt c ?????? ????????')
    time.sleep(3)


if allowing_radar_rule:
    # открытие последовательного пота для считывания радара
    ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)

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
# создаем массив равный массивуCHUNK 
# ось X задается полулогарифмической,
x_axis = np.arange(0, CHUNK * 2, 2)
display_line, = ax.plot(x_axis, np.random.rand(CHUNK), 'r')
ax.set_ylim(-17000, 17000)
ax.ser_xlim = (0, CHUNK)

fig.show()

# Cистемные переменные
start_time = time.time()  	# сохраняем время старта выполнения программы
timer = start_time			# Для отсчета длительности таймера
timerP = start_time			# Для отсчета таймера детектирования по радару
timerT = start_time			# Для отсчета таймера
time_wr = int(time.time() / 100)

speed = 0                   # детектор наличия скорости в любом из трех обьектов радара
on_off_pwm = 0 				# Для управлениея состоянием PWM
start_adr = 0               # Cтартовый адрес для синхронизации
stop_adr = 0                # Cтоповый адрес для синхронизации
flag_stop = 0               # Флаг для тестирования
flag_adc = 0                # Флаг для переключения массива данных с АЦП
CHUNK = int(CHUNK)
CHUNK2 = int(CHUNK * 2)
CHUNK4 = int(CHUNK * 4)

tau = 1                     # постоянная времени вычисления DC
max_variable = 0            # максимум переменной составляющей сигнала для АРУ 10%


#plt.show()
temp = 0

# try:                        # для аккуратного принудительного останова программы с закрытием портов
if 1==1:
    pwm_adc_101.start_pwm()			# Включаем передачу

    while True:
        timerT = time.time() - timer        # подсчет длительности выполнения одной итерации цикла
        timer = time.time()

        start_adr = -1                      # сбрасываем стартовый адрес для нового значения

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
                timerP = int(time.time() - timer)
                on_off_pwm = 1
                pwm_adc_101.start_pwm()			# Включаем передачу PWM
            else:
                led_line.set_value(1)
                timerP = "~"
                on_off_pwm = 0
                pwm_adc_101.stop_pwm()			# Выключаем передачу PWM

            # Вывод результатов радара
            print(f'1-{xLed1}{yLed1}{speed}/{timerP:1}: X:{target1_x:4} /', f'Y:{target1_y:5} /', f' V: {target1_speed:3} cm/s/', f'D: {target1_distance_res:4} |', f'2: X:{target2_x:4} /', f'Y:{target2_y:5} /', f' V: {target2_speed:4} cm/s/', f'D: {target2_distance_res:4} |', f'3: X:{target3_x:5} /', f'Y:{target3_y:5} /', f' V: {target3_speed:4} cm/s/', f'D: {target3_distance_res:4}', end="\r")
        #else:  
        
        #data = stream.read(CHUNK)
        #dataInt = list(struct.unpack(str(CHUNK * 2) + 'h', data))
        #dataInt1 = dataInt[0::2]  # разделяем стереоканалы, это левый канал с синхросигналом первая осциллограмма
        #dataInt2 = dataInt[1::2]  # разделяем стереоканалы, это правый канал с входными данными втроая осциллограмма
        
        #data = pwm_adc.start_adc(CHUNK)



        #dataInt = list(struct.unpack(str((CHUNK) * 4) + 'h', pwm_adc_101.start_adc(CHUNK * 2)))
        dataADC1.extend(pwm_adc_101.start_adc(CHUNK))           # добавляем новые данные от первого канала АЦП в конец списка
        if len(dataADC1) > CHUNK2:                               # количество данных больше чем одно считывание
        #if 1==1:
            for i in range(0, CHUNK):                      # находим начало цикла 12 периодов первому встреченному переходу меньше/больше нуля
                if start_adr < 0 and dataADC1[i] < -10 and dataADC1[i+1] > 10 and dataADC1[i+300] > 1 and dataADC1[i+1200] < -100:     # находим стартовый адрес, если его нет (-1)
                    start_adr = i
                    dataADC1[i+1200] = dataADC1[i+1200] + 15000
                    break       
            for i in range(start_adr, CHUNK + start_adr):   # вычисляем постоянную составляющую DC c АРУ на 10% от максимума переменной составляющей
                if dataADC1[i] > 0: 
                    if dataADC1[i] > max_variable:          # вычисляем максимум по +AC
                        max_variable = dataADC1[i]
                    
                    if dataADC1[i] > dataDC[i - start_adr]:
                        dataDC[i - start_adr] = dataDC[i - start_adr] + tau
                    else:
                        dataDC[i - start_adr] = dataDC[i - start_adr] - tau
                    dataINP1[i - start_adr] = dataADC1[i] - dataDC[i - start_adr] 
                else:
                    if (dataADC1[i] * -1) > max_variable:   # вычисляем максимум по -AC        
                        max_variable = -1 * dataADC1[i] 
                    if dataADC1[i] < dataDC[i - start_adr]:
                        dataDC[i - start_adr] = dataDC[i - start_adr] - tau
                    else:
                        dataDC[i - start_adr] = dataDC[i - start_adr] + tau
                    dataINP1[i - start_adr] = dataADC1[i] - dataDC[i - start_adr] 


            if waveform_output_display == 1:                         # отображаем осциллограмму сырого входного сигнала
                display_line.set_ydata(dataADC1[start_adr:(CHUNK + start_adr):])
                fig.canvas.draw()
                fig.canvas.flush_events()
            if waveform_output_display == 2:                         # отображаем осциллограмму сырого входного сигнала
                display_line.set_ydata(dataINP1)
                fig.canvas.draw()
                fig.canvas.flush_events()

            # Удаляем данные в начале списка длиной: стартовый адрес + CHUNK
            
            if start_adr > 8:
                del dataADC1[0:CHUNK + start_adr]
            else:
                del dataADC1[0:CHUNK]
            if start_adr < 8:
                del dataADC1[0:CHUNK - start_adr]
            else:
                del dataADC1[0:CHUNK]
            
            
            #if start_adr == 10:
                #del dataADC1[0:CHUNK]

        

        
        if start_adr > temp:
            stop_adr += 1
            temp = stop_adr
        else:
            stop_adr = 1
            temp = 0

        print(f't:{timerT:.3f}', f'start:{start_adr:5}', stop_adr, len(dataADC1))

        if time_wr != int(time.time() / 100):
            time_wr = int(time.time() / 100)
            # Записываем файл каждые 100 сек
            with open('tab_DC.txt', 'w', encoding='utf-8') as fw:
                json.dump(dataDC, fw)  # , indent=4)



        #pwm_adc_101.stop_pwm()
# except Exception as e:
if 1==0:
    print(f"1. MAIN: Ошибка: {repr(e)}", e)
    pwm_adc_101.stop_pwm()

# finally:
if 1==0:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    if allowing_radar_rule:
        ser.close()
    led_line.set_value(1)
    pwm_adc_101.stop_pwm()
    print("\n\n1. MAIN: UART порт закрыт и светодиод/pwm выключен")
