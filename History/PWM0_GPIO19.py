import time
import gpiod
from rpi_hardware_pwm import HardwarePWM

# Настраиваем GPIO13 через gpiod
chip = gpiod.Chip("gpiochip4")  # Указываем правильный чип
line = chip.get_line(13)
line.request(consumer="PWM_GPIO13_Control", type=gpiod.LINE_REQ_DIR_OUT)

# Создаём экземпляр PWM на канале 3 (соответствует GPIO19)
pwm = HardwarePWM(pwm_channel=3, hz=200, chip=2)

try:
    line.set_value(1)  # Устанавливаем GPIO13 в 1
    pwm.start(50)  # Запускаем с скважностью 50%
    print("PWM запущен на GPIO19 с частотой 200 Гц и скважностью 50%, GPIO13 = 1")
    while True:
        time.sleep(1)  # Просто держим процесс активным
except KeyboardInterrupt:
    print("Остановка PWM")
    pwm.stop()  # Останавливаем PWM при прерывании
    line.set_value(0)  # Устанавливаем GPIO13 в 0
except Exception as e:
    print(f"Ошибка: {e}")
    pwm.stop()
    line.set_value(0)  # Устанавливаем GPIO13 в 0 при ошибке
finally:
    pwm.stop()
    line.set_value(0)  # Устанавливаем GPIO13 в 0 при завершении
    print("PWM выключен, GPIO13 = 0")
