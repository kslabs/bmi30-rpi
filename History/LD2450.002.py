import serial_protocol_ld2450
import gpiod
import serial
import time

# открытие последовательного пота
ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)

# Конфигурация порта ввода/вывода.
LED_PIN = 22							# Порт упроавления светодиодом (15 контакт разьема)
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

speed = 0
start_time = time.time()  	# время начала выполнения
timer = start_time			# Для отсчета таймера
timerP = start_time			# Для отсчета таймера

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
            
        if (target1_x != 0 and -1000 < target1_x < 800) or (target2_x != 0 and -1000 < target2_x < 800):		# диапазон по координате X, обьектов 1 и 2
            xLed1 = 1
        else:
            xLed1 = 0
            
        if (target1_y !=0 and -1400 < target1_y < 0) or (target2_y !=0 and -1400 < target2_y < 0):		# диапазон по координате Y, обьектов 1 и 2
            yLed1 = 1
        else:
            yLed1 = 0
        
        if speed or xLed1 or yLed1:    	# Обновляем таймер,при выполненных условиях 
            timer = time.time()
            
        if time.time() - timer < 10:	# Управляем светодиодом / генератором передатчика
            led_line.set_value(0)
            timerP = int(time.time() - timer)
        else:
            led_line.set_value(1)
            timerP = "~"

        # Вывод результатов
        print(f'1-{xLed1}{yLed1}{speed}/{timerP:1}: X:{target1_x:4} /', f'Y:{target1_y:5} /', f' V: {target1_speed:3} cm/s/', f'D: {target1_distance_res:4} |', f'2: X:{target2_x:4} /', f'Y:{target2_y:5} /', f' V: {target2_speed:4} cm/s/', f'D: {target2_distance_res:4} |', f'3: X:{target3_x:5} /', f'Y:{target3_y:5} /', f' V: {target3_speed:4} cm/s/', f'D: {target3_distance_res:4}', end="\r")
        #print(f'Обьект 1: x-: {target1_x:5} mm', f'y-: {target1_y:5} mm', f'скорость: {target1_speed:4} cm/s', f'дистанция: {target1_distance_res:5} mm')
        #print(f'Обьект 2: x-: {target2_x:5} mm', f'y-: {target2_y:5} mm', f'скорость: {target2_speed:4} cm/s', f'дистанция: {target2_distance_res:5} mm')
        #print(f'Обьект 3: x-: {target3_x:5} mm', f'y-: {target3_y:5} mm', f'скорость: {target3_speed:4} cm/s', f'дистанция: {target3_distance_res:5} mm')

        #print('-' * 30)

except KeyboardInterrupt:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    ser.close()
    led_line.set_value(1)
    print("\n\nUART порт закрыт и светодиод/генератор выключен")