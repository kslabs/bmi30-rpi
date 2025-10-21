import random
import gpiod
import select
import threading
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

# Функции callback (будут вызываться автоматически)
def change_pwm1():
    new_freq = random.randint(FREQ_MIN, FREQ_MAX)
    pwm1.change_frequency(new_freq)
    print(f"PWM1 (GPIO18) -> Новая частота: {new_freq} Гц")

def change_pwm2():
    new_freq = random.randint(FREQ_MIN, FREQ_MAX)
    pwm2.change_frequency(new_freq)
    print(f"PWM2 (GPIO19) -> Новая частота: {new_freq} Гц")

# Обработчик событий GPIO (запускается в отдельном потоке)
def gpio_event_listener():
    poll = select.poll()
    poll.register(line20.event_get_fd(), select.POLLIN)
    poll.register(line21.event_get_fd(), select.POLLIN)

    while True:
        fd, _ = poll.poll()[0]  # Ждём прерывание

        if fd == line20.event_get_fd():
            change_pwm1()

        elif fd == line21.event_get_fd():
            change_pwm2()

# Запускаем поток для обработки прерываний (это наш callback-менеджер)
threading.Thread(target=gpio_event_listener, daemon=True).start()

# Ожидание завершения программы (Ctrl+C)
try:
    print("Ожидание прерываний... (нажмите Ctrl+C для выхода)")
    threading.Event().wait()  # Бесконечно ждём, пока не остановим вручную

except KeyboardInterrupt:
    print("Остановка PWM...")
    pwm1.stop()
    pwm2.stop()
    line20.release()
    line21.release()