import time
import os
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button
from rpi_hardware_pwm import HardwarePWM

# Убираем перезапуск pigpio, так как он отсутствует
print("Переферийный контроллер не требует перезапуска")

# Устанавливаем исходное состояние всех выводов
def initialize_gpio():
    gpio12 = DigitalOutputDevice(12, initial_value=False)
    gpio5 = DigitalOutputDevice(5, initial_value=False)
    gpio6 = DigitalOutputDevice(6, initial_value=False)  # GPIO6 для инверсии при прерывании
    print("Исходное состояние GPIO установлено")
    return gpio12, gpio5, gpio6

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = Button(26, pull_up=True)

# Функция обработки прерывания
def toggle_gpio6():
    gpio6.toggle()
    #print("Прерывание: GPIO6 изменён")

# Привязываем обработчик прерывания
button.when_pressed = toggle_gpio6

# Создаём экземпляр PWM на канале 3 (соответствует GPIO19)
pwm = HardwarePWM(pwm_channel=3, hz=200, chip=2)  # OnPWR

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1
    gpio5.on()  # GPIO5 включается ТОЛЬКО при работе PWM
    pwm.start(50)  # Запускаем с скважностью 50%
    print("PWM запущен на GPIO19 с частотой 200 Гц и скважностью 50%, GPIO12 = 1, GPIO5 = 1")
    while True:
        time.sleep(1)  # Просто держим процесс активным
except KeyboardInterrupt:
    print("Остановка PWM")
    pwm.stop()  # Останавливаем PWM при прерывании
finally:
    gpio12.off()  # Всегда сбрасываем GPIO12 в 0
    gpio5.off()  # ГАРАНТИРУЕМ, что GPIO5 выключен при выходе
    gpio6.off()  # Сбрасываем GPIO6 при завершении
    time.sleep(0.1)  # Даем время системе обработать изменение состояния
    gpio5.value = False  # Принудительно оставляем GPIO5 в 0
    print("PWM выключен, GPIO12 = 0, GPIO5 = 0, GPIO6 = 0")
