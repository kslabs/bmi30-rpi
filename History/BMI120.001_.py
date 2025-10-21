import threading
from gpiozero import LED
import pyaudio as pa
import time
import struct
import matplotlib.pyplot as plt
import numpy as np
from multiprocessing import Pool

out1 = LED(17)  # Используемый вывод для передтчика OUT1 (GPIO17, 11 вывод разьема)
out2 = LED(27)  # Используемый вывод для передтчика OUT1 (GPIO27, 13 вывод разьема)

start_time = time.time()  # время начала выполнения

CHUNK = 1024  # Устанавливаем количество семлов считывания
RATE = 384000  # in Hz (22050; 24000; 44100; 48000; 96000; 192000, 384000, 768000) Частота семпелирования
p = pa.PyAudio()
stream = p.open(
    format=pa.paInt16,  # Форматы сэмплов Portaudio: paFloat32, paInt32, paInt24, paInt16, paInt8, paUInt8, paCustomFormat
    channels=2,  # количество каналов (1 - моно, 2 - стерео).
    rate=RATE,  # частота дискретизации (обычно это 44100).
    input_device_index=1,  # номер устройства в системе
    input=True,  #
    output=True,  # True, если звук будет проигрываться.
    frames_per_buffer=CHUNK
)

# инициализируем объекты графика
fig, ax1 = plt.subplots(3, 1)
fig.canvas.manager.set_window_title("Осциллограмма: " + __file__.split('\\')[-1])  # Заголовок окна
plt.minorticks_on()
ax1 = plt.subplot(1, 1, 1)
plt.grid(which='major', alpha=0.6, color='green', linestyle='--', linewidth=1.4)
plt.subplots_adjust(left=0.05,
                    right=0.99,
                    top=0.99,
                    bottom=0.029,
                    wspace=0.3,
                    hspace=0.0)
# ось X задается полулогарифмической,
x1 = np.arange(0, CHUNK * 2, 2)
line1, = ax1.plot(x1, np.random.rand(CHUNK), 'r')
ax1.set_ylim(-21000, 21000)
ax1.ser_xlim = (0, CHUNK)

#fig.show()


def audio(a):
    global dataInt1
    data = stream.read(CHUNK)
    dataInt = list(struct.unpack(str(CHUNK * 2) + 'h', data))
    dataInt1 = dataInt[0::2]  # разделяем стереоканалы, это левый канал с синхросигналом первая осциллограмма
    #dataInt2 = dataInt[1::2]  # разделяем стереоканалы, это правый канал с входными данными втроая осциллограмма
    

    #line1.set_ydata(dataInt1)
    #for i in range(0, len(dataInt1)):
     #   print('dataInt1:', dataInt1[i])
    
    print(a, 'data:', len(data), data)

    #fig.canvas.draw()
    #fig.canvas.flush_events()


def print_out():
    global start_time
    if time.time() - start_time > 10:
        start_time = time.time()
        for i in range(0, len(dataInt1)):
            print('dataInt1:', dataInt1[i])

def int_timer():
    global a
    # t = threading.Timer(1.0023, int_timer)     #  0.0023~200Гц; 0.00105~400Гц; 0.00081~500Гц; 0.00034~1кГц;
    if a % 2 == 0:
        # out1.on()
        out2.off()
    else:
        # out1.off()
        out2.on()
    a += 1
    audio(a)
    threading.Timer(0.1, int_timer).start()
    #print_out()
    

# t = threading.Timer(1.0001, int_timer)     # установка частоты прерывания с использованием таймера.

a = 0

# while 1:
#    t.start()
#   print(time.time(), "you're here")
# print(b, 'Start')

int_timer()

        
