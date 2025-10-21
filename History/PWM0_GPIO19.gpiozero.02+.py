import time
import os
import spidev
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button
from rpi_hardware_pwm import HardwarePWM

# Убираем перезапуск pigpio, так как он отсутствует
print("Переферийный контроллер не требует перезапуска (v4.0)")

# Устанавливаем исходное состояние всех выводов
def initialize_gpio():
    gpio12 = DigitalOutputDevice(12, initial_value=False, )
    gpio5 = DigitalOutputDevice(5, initial_value=False, )
    gpio6 = DigitalOutputDevice(6, initial_value=False, )  # GPIO6 для инверсии при прерывании
    print("Исходное состояние GPIO установлено")
    return gpio12, gpio5, gpio6

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = Button(26, pull_up=True)

# Переменные для значений резисторов
resistor_values = {"spi0_0": 100, "spi0_1": 100, "spi1_0": 100, "spi1_1": 100}

# Функция установки значения цифровых резисторов mcp4251
def set_resistor(spi, channel, value):
    # cs = spi  # Убрано, так как spi не является CS
    command = [0b00000000 | (channel << 4), value]
    print(f"Передача SPI: {command}")  # Формируем команду записи в MCP4251  # Команда для MCP4251
    time.sleep(0.0005)  # Оптимизированная задержка
    spi.xfer2(command)  # Используем xfer2 для отправки и получения ответа
    time.sleep(0.0005)
    
    # Убираем лишний SPI вызов
    time.sleep(0.0005)

    # Оставляем только один SPI вызов
    response = None
    command = [0b00001100 | (channel << 4), 0xFF]
    print(f"Прием SPI: {command}")  # Формируем команду приема в MCP4251  # Команда для MCP4251
    response = spi.xfer2(command)
    
      # Читаем ответ после записи  # Читаем текущее значение MCP4251
    print(f"Резистор {channel} установлен в {value}, ответ MCP4251: {response} (v3.9)")

# Функция обработки прерывания
def toggle_gpio6_and_update_resistors():
    gpio6.toggle()
    print("Прерывание: GPIO6 изменён")
    
    # Обновляем значения резисторов, изменяя их на 1 в пределах 0-255
    for key in resistor_values:
        resistor_values[key] = (resistor_values[key] + 1) % 256
  
    # Устанавливаем новые значения резисторам
    set_resistor(spi0, 0, resistor_values["spi0_0"]) # Запись и чтение совмещены 
    set_resistor(spi0, 1, resistor_values["spi0_1"]) # Запись и чтение совмещены
    set_resistor(spi1, 0, resistor_values["spi1_0"]) # Запись и чтение совмещены
    set_resistor(spi1, 1, resistor_values["spi1_1"]) # Запись и чтение совмещены
  
# Привязываем обработчик прерывания
button.when_pressed = toggle_gpio6_and_update_resistors

# Настраиваем SPI для MCP4251
spi0 = spidev.SpiDev()
spi1 = spidev.SpiDev()
# SPI управляет CS аппаратно, убираем принудительное управление
# spi0_cs = DigitalOutputDevice(8, initial_value=False)
spi0.open(0, 0)
# spi0.no_cs = True  # Убрано, так как вызывает ошибку  # SPI0, CE0 (физический вывод 24)
# SPI управляет CS аппаратно, убираем принудительное управление
# spi1_cs = DigitalOutputDevice(7, initial_value=False)
spi1.open(0, 1)
# spi1.no_cs = True  # Убрано, так как вызывает ошибку  # SPI0, CE1 (физический вывод 26)
spi0.max_speed_hz = 10000000  # 1 МГц
spi1.max_speed_hz = 10000000  # 1 МГц
spi0.mode = 0
spi0.lsbfirst = False
# spi0.cshigh = True  # Убрано, так как вызывает ошибку  # MCP4251 поддерживает SPI Mode 0
spi1.mode = 0
spi1.lsbfirst = False
# spi1.cshigh = True  # Убрано, так как вызывает ошибку

# Устанавливаем резисторы в 100
set_resistor(spi0, 0, resistor_values["spi0_0"])
set_resistor(spi0, 1, resistor_values["spi0_1"])
set_resistor(spi1, 0, resistor_values["spi1_0"])
set_resistor(spi1, 1, resistor_values["spi1_1"])

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
      # Устанавливаем CS в 1 при завершении
    
    gpio12.off()  # Всегда сбрасываем GPIO12 в 0
    gpio5.off()  # ГАРАНТИРУЕМ, что GPIO5 выключен при выходе
    gpio6.off()  # Сбрасываем GPIO6 при завершении
    spi0.close()  # Закрываем SPI соединения
    spi1.close()
    time.sleep(0.1)  # Даем время системе обработать изменение состояния
    gpio5.value = False  # Принудительно оставляем GPIO5 в 0
    print("PWM выключен, GPIO12 = 0, GPIO5 = 0, GPIO6 = 0")
