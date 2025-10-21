import serial_protocol_ld2450

import serial

# Open the serial port
ser = serial.Serial('/dev/ttyAMA0', 256000, timeout=1)

try:
    while True:
        # Read a line from the serial port
        serial_port_line = ser.read_until(serial_protocol_ld2450.REPORT_TAIL)

        all_target_values = serial_protocol_ld2450.read_radar_data(serial_port_line)
        
        if all_target_values is None:
            continue

        target1_x, target1_y, target1_speed, target1_distance_res, \
        target2_x, target2_y, target2_speed, target2_distance_res, \
        target3_x, target3_y, target3_speed, target3_distance_res \
            = all_target_values

        # Print the interpreted information for all targets
        print(f'1: x:{target1_x:5} mm /', f'y:{target1_y:5} mm /', f' V: {target1_speed:4} cm/s /', f'D: {target1_distance_res:5} mm |', f'2: x:{target2_x:5} mm /', f'y:{target2_y:5} mm /', f' V: {target2_speed:4} cm/s /', f'D: {target2_distance_res:5} mm |', f'3: x:{target3_x:5} mm /', f'y:{target3_y:5} mm /', f' V: {target3_speed:4} cm/s /', f'D: {target3_distance_res:5} mm |', end="\r")
        #print(f'Обьект 1: x-: {target1_x:5} mm', f'y-: {target1_y:5} mm', f'скорость: {target1_speed:4} cm/s', f'дистанция: {target1_distance_res:5} mm')
        #print(f'Обьект 2: x-: {target2_x:5} mm', f'y-: {target2_y:5} mm', f'скорость: {target2_speed:4} cm/s', f'дистанция: {target2_distance_res:5} mm')
        #print(f'Обьект 3: x-: {target3_x:5} mm', f'y-: {target3_y:5} mm', f'скорость: {target3_speed:4} cm/s', f'дистанция: {target3_distance_res:5} mm')

        #print('-' * 30)

except KeyboardInterrupt:
    # Close the serial port on keyboard interrupt
    ser.close()
    print("Serial port closed.")