import serial_protocol_ld2450
import gpiod
import serial
import time

# открытие последовательного пота
ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)

# Конфигурация порта ввода/вывода.
LED_PIN = 22
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

speed = 0
start_time = time.time()  	# время начала выполнения
timer = start_time			# Для отсчета таймера

try:
    while True:
        # чтение последовательного порта.
        serial_port_line = ser.read_until(serial_protocol_ld2450.REPORT_TAIL)

        all_target_values = serial_protocol_ld2450.read_radar_data(serial_port_line)
        
        if all_target_values is None:
            continue

        target1_x, target1_y, target1_speed, target1_distance_res, \
        target2_x, target2_y, target2_speed, target2_distance_res, \
        target3_x, target3_y, target3_speed, target3_distance_res \
            = all_target_values

        # Управление светодиодом
        if target1_speed !=0 or target2_speed != 0 or target3_speed != 0:
            speed = 1
        else:
            speed = 0
            
        if -1500 < target1_x < 700:		# диапазон по координате X
            xLed1 = 1
        else:
            xLed1 = 0
            
        if -1400 < target1_y < 0:		# диапазон по координате Y
            yLed1 = 1
        else:
            yLed1 = 0
        
        if speed or xLed1 or yLed1:    	# Обновляем таймер
            timer = time.time()
            
        if time.time() - timer < 10:
            led_line.set_value(0)
        else:
            led_line.set_value(1)
        

        # Вывод результатов
        print(f'1-{xLed1}{yLed1}{speed}: X:{target1_x:4} mm /', f'Y:{target1_y:5} mm /', f' V: {target1_speed:3} cm/s /', f'D: {target1_distance_res:5} mm |', f'2: x:{target2_x:4} mm /', f'y:{target2_y:5} mm /', f' V: {target2_speed:4} cm/s /', f'D: {target2_distance_res:5} mm |', f'3: x:{target3_x:5} mm /', f'y:{target3_y:5} mm /', f' V: {target3_speed:4} cm/s /', f'D: {target3_distance_res:5} mm |', end="\r")
        #print(f'Обьект 1: x-: {target1_x:5} mm', f'y-: {target1_y:5} mm', f'скорость: {target1_speed:4} cm/s', f'дистанция: {target1_distance_res:5} mm')
        #print(f'Обьект 2: x-: {target2_x:5} mm', f'y-: {target2_y:5} mm', f'скорость: {target2_speed:4} cm/s', f'дистанция: {target2_distance_res:5} mm')
        #print(f'Обьект 3: x-: {target3_x:5} mm', f'y-: {target3_y:5} mm', f'скорость: {target3_speed:4} cm/s', f'дистанция: {target3_distance_res:5} mm')

        #print('-' * 30)

except KeyboardInterrupt:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    ser.close()
    print("Serial port closed.")