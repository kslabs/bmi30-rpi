import random
import gpiod
from rpi_hardware_pwm import HardwarePWM

# Аппаратные PWM-выходы
PWM_GPIO1 = 18  # Соответствует pwm_channel=3
PWM_GPIO2 = 19  # Соответствует pwm_channel=2

# Входы для обработки прерываний (подключены физически к PWM-выходам)
INPUT_GPIO1 = 20  # Связываем с GPIO18 (вход)
INPUT_GPIO2 = 21  # Связываем с GPIO19 (вход)

# Диапазон частот
FREQ_MIN = 190
FREQ_MAX = 250

new_freq1 = FREQ_MIN
new_freq2 = FREQ_MIN

# Инициализация аппаратного PWM
pwm1 = HardwarePWM(pwm_channel=3, hz=FREQ_MIN, chip=2)  # GPIO18
pwm2 = HardwarePWM(pwm_channel=2, hz=FREQ_MIN, chip=2)  # GPIO19

# Запускаем PWM с 50% скважностью
pwm1.start(50)
pwm2.start(50)

# Открываем gpiochip
chip = gpiod.Chip("gpiochip4")  # Используем gpiochip4 на Raspberry Pi 5

# Настраиваем входы с прерываниями
line20 = chip.get_line(INPUT_GPIO1)
line21 = chip.get_line(INPUT_GPIO2)

line20.request(consumer="pwm_test", type=gpiod.LINE_REQ_EV_RISING_EDGE)
line21.request(consumer="pwm_test", type=gpiod.LINE_REQ_EV_RISING_EDGE)

# Функция для изменения частоты (по прерыванию)
def change_pwm1(new_freq1):
    if new_freq1 == FREQ_MIN:
        new_freq1 = FREQ_MAX
    else:
        new_freq1 = FREQ_MIN
    #new_freq = random.randint(FREQ_MIN, FREQ_MAX)
    pwm1.change_frequency(new_freq1)
    #print(f"PWM1 (GPIO18) -> Новая частота: {new_freq} Гц")
    
def change_pwm2(new_freq2):
    if new_freq2 == FREQ_MIN:
        new_freq2 = FREQ_MAX
    else:
        new_freq2 = FREQ_MIN
    
    #new_freq = random.randint(FREQ_MIN, FREQ_MAX)
    pwm2.change_frequency(new_freq2)
    #print(f"PWM2 (GPIO19) -> Новая частота: {new_freq} Гц")

# Основной цикл ожидания прерываний
try:
    while True:
        event20 = line20.event_read()  # Ожидаем передний фронт на INPUT_GPIO1
        if event20:
            change_pwm1(new_freq1)

        event21 = line21.event_read()  # Ожидаем передний фронт на INPUT_GPIO2
        if event21:
            change_pwm2(new_freq2)

except KeyboardInterrupt:
    print("Остановка PWM...")
    pwm1.stop()
    pwm2.stop()
    line20.release()
    line21.release()