import gpiod
import time
from rpi_hardware_pwm import HardwarePWM

# Настройка пинов
PWM_PIN1_CHANNEL = 3  # GPIO_18
PWM_PIN2_CHANNEL = 2  # GPIO_19
CONTROL_PIN = 23      # Управляющий вывод

# Инициализация линий GPIO
chip = gpiod.Chip('gpiochip0')
control_line = chip.get_line(CONTROL_PIN)
control_line.request(consumer='my_consumer', type=gpiod.LINE_REQ_DIR_OUT)

# Настройка PWM
pwm1 = HardwarePWM(pwm_channel=3, hz=200, chip=2)  # 200 Гц для PWM1 (GPIO_18)
pwm2 = HardwarePWM(pwm_channel=2, hz=200, chip=2)  # 200 Гц для PWM2 (GPIO_19)
pwm1.start(50)  # 50% скважность
pwm2.start(50)  # 50% скважность

# Переменные для отслеживания состояния
interrupt_count = 0
output_state = 0  # Начальное состояние

def interrupt_handler():
    global interrupt_count, output_state

    interrupt_count += 1

    # Каждые 12 импульсов
    if interrupt_count > 12:
        interrupt_count = 1  # Ресет счетчика, начинаем заново

    # Логика состояния
    if interrupt_count <= 1:
        output_state = 0  # Первые два импульса - 0
    else:
        output_state = 1  # Остальные 10 импульсов - 1

    control_line.set_value(output_state)  # Устанавливаем значение на выводе 23

# Основной цикл
try:
    print("Ожидание изменений состояния...")
    while True:
        # Ожидание события на входном пине (прерывание)
        time.sleep(0.005)  # 5 мс задержка (примерно 200 Гц)

        # Вызов обработчика прерываний
        interrupt_handler()

except KeyboardInterrupt:
    # Выход при нажатии Ctrl+C
    pass

finally:
    # Остановка PWM и освобождение линий при выходе
    pwm1.stop()
    pwm2.stop()
    control_line.release()
    print("Программа завершена.")