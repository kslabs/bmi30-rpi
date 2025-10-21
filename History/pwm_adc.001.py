from rpi_hardware_pwm import HardwarePWM    # Для аппаратного PWM
import pyaudio as pa
from time import sleep
import struct

def conf(CHUNK):
    # Конфигурируем выводы PWM
    global pwm1
    global pwm2
    pwm1 = HardwarePWM(pwm_channel=2, hz=200, chip=2)    # pwm_channel 1: 3-GPIO_18; 2-GPIO_19; 
    pwm2 = HardwarePWM(pwm_channel=3, hz=200, chip=2)    # pwm_channel 2: 3-GPIO_18; 2-GPIO_19;


    # Конфигурируем ADC
    #global CHUNK
    global RATE
    global stream
    RATE = 384000       # in Hz (22050; 24000; 44100; 48000; 96000; 192000, 384000, 768000) Частота семпелирования
    p = pa.PyAudio()
    stream = p.open(
        format=pa.paInt16,  # Форматы сэмплов Portaudio: paFloat32, paInt32, paInt24, paInt16, paInt8, paUInt8, paCustomFormat
        channels=2,  # количество каналов (1 - моно, 2 - стерео).
        rate=RATE,  # частота дискретизации (обычно это 44100).
        input_device_index=1,  # номер устройства в системе
        input=True,  #
        output=True,  # True, если звук будет проигрываться.
        frames_per_buffer=0
    )

def start_pwm():
    global pwm1
    global pwm2
    pwm1.start(50)			# Включаем передачу 1-го канала
    #pwm2.start(50)			# Включаем передачу 2-го канала

def stop_pwm():
    global pwm1
    global pwm2
    pwm1.stop()			    # Выключаем передачу 1-го канала
    pwm2.stop()			    # Выключаем передачу 2-го канала

def start_adc(CHUNK):
    #global dataInt1
    start_pwm()
    #sleep(0.11741)          # 0.07718  = 16имп; 0.11741 = 24имп
    sleep(0.01675)          # 0.07718  = 16имп; 0.11741 = 24имп   0.01675
    stop_pwm()
    data = stream.read(CHUNK)
    dataInt = list(struct.unpack(str((CHUNK) * 4) + 'h', start_adc(CHUNK * 2)))
    return data
