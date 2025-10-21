import time
import pyaudio
import numpy as np
import matplotlib.pyplot as plt
import os
import spidev
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button
from rpi_hardware_pwm import HardwarePWM

print("управление аналоговым преобразователем v4.3")

# Устанавливаем исходное состояние всех выводов
def initialize_gpio():
    gpio12 = DigitalOutputDevice(12, initial_value=False, )
    gpio5 = DigitalOutputDevice(5, initial_value=False, )
    gpio6 = DigitalOutputDevice(6, initial_value=False, )  # GPIO6 для инверсии при прерывании
    #print("Исходное состояние GPIO установлено")
    return gpio12, gpio5, gpio6

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = Button(26, pull_up=True)

# Исходные значения цифровых резисторов
resistor_values = {"dr0_0": 200, "dr0_1": 00, "dr1_0": 75, "dr1_1": 255}
print(f"состояние резисторов: {resistor_values}")

# Функция установки значения цифровых резисторов для mcp4251
def set_resistor(spi, channel, value):

    #print(f"Передача SPI: {command}")  # Формируем команду записи в MCP4251
    spi.xfer2([0b00000000 | (channel << 4), value])  # Используем xfer2 для отправки и получения ответа

    response = None
    # print(f"Прием SPI: {command}")  # Формируем команду приема в MCP4251  # Команда для MCP4251
    response = spi.xfer2([0b00001100 | (channel << 4), 0xFF])
    
    # Читаем ответ после записи  # Читаем текущее значение MCP4251
    # print(f"Резистор {channel} установлен в {value}, ответ MCP4251: {response}")

# Функция обработки прерывания
def toggle_gpio6_and_update_resistors():
    gpio6.toggle()
    # print("GPIO6 изменён по фронту прерывания                                                                                                                                                                                                                                ")
  
# Привязываем обработчик прерывания
button.when_pressed = toggle_gpio6_and_update_resistors

# Настраиваем SPI для двух MCP4251
spi0 = spidev.SpiDev()
spi1 = spidev.SpiDev()

spi0.open(0, 0)
spi1.open(0, 1)

spi0.max_speed_hz = 10000000  # 1 МГц
spi1.max_speed_hz = 10000000  # 1 МГц

spi0.mode = 0
spi0.lsbfirst = False

spi1.mode = 0
spi1.lsbfirst = False

# Устанавливаем цифровые резисторы в исходное состояние
set_resistor(spi0, 0, resistor_values["dr0_0"])
set_resistor(spi0, 1, resistor_values["dr0_1"])
set_resistor(spi1, 0, resistor_values["dr1_0"])
set_resistor(spi1, 1, resistor_values["dr1_1"])

# Настройка параметров АЦП
CHUNK = 1024  # Количество сэмплов на буфер
RATE = 44100  # Частота дискретизации

# Создаём экземпляр PyAudio
p = pyaudio.PyAudio()

def audio_callback(in_data, frame_count, time_info, status):
    global dataADC1, dataADC2
    new_data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    dataADC1 = np.concatenate((dataADC1, new_data[:, 0]))
    dataADC2 = np.concatenate((dataADC2, new_data[:, 1]))
    return in_data, pyaudio.paContinue

# Создаём поток захвата аудио
stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback)

# Инициализируем массивы для данных
dataADC1 = np.zeros(CHUNK, dtype=int)
dataADC2 = np.zeros(CHUNK, dtype=int)

# Визуализация осциллограммы
fig, ax = plt.subplots()
ax.grid(color='lightgray', linestyle='--', linewidth=0.5)
x_axis = np.arange(0, CHUNK)
line1, = ax.plot(x_axis, np.zeros(CHUNK), label='Канал 1')
line2, = ax.plot(x_axis, np.zeros(CHUNK), label='Канал 2')
ax.legend()
ax.set_ylim(-3000, 2000)
ax.set_xlim(0, CHUNK)
plt.ion()
plt.show()
pwm3 = HardwarePWM(pwm_channel=3, hz=200, chip=2)  # OnPWR
pwm2 = HardwarePWM(pwm_channel=2, hz=200, chip=2)

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    pwm2.start(25)  # Запускаем pwm с скважностью 50%
    pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    #print("PWM запущен на GPIO19 с частотой 200 Гц и скважностью 50%, GPIO12 = 1, GPIO5 = 1")
    
        
    
    while True:
        if not plt.fignum_exists(fig.number):
            break
        # Обновляем график
        line1.set_ydata(dataADC1[-CHUNK:])
        line2.set_ydata(dataADC2[-CHUNK:])
        fig.canvas.draw()
        fig.canvas.flush_events()


        time.sleep(1)  # Просто держим процесс активным

        
except KeyboardInterrupt:
    print("Остановка PWM")
    pwm2.stop()  # Останавливаем PWM при прерывании
    pwm3.stop()  # Останавливаем PWM при прерывании
except Exception as e:
    print(f"Ошибка: {e}")
finally:
    plt.ioff()
    pwm2.stop()
    pwm3.stop()
    print("Остановка осциллограммы, завершаем работу...")
    
    
    if stream and stream.is_active():
        stream.stop_stream()
    stream.close()
    p.terminate()
    plt.close(fig)  # Закрываем осциллограмму

    gpio12.off()  # Всегда сбрасываем GPIO12 в 0 (выключаем полную мощность передатчика)
    gpio5.off()  # Выключаем индикацию работы передатчика
    gpio6.off()  # Сбрасываем GPIO6 при завершении
    spi0.close()  # Закрываем SPI соединения
    spi1.close()
    time.sleep(0.1)  # Даем время системе обработать изменение состояния
    gpio5.value = False  # Принудительно оставляем GPIO5 в 0 для ускорения разряда датчика наличия сигнала
    print("PWM выключен, GPIO12 = 0, GPIO5 = 0, GPIO6 = 0")
