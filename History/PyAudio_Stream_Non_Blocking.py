import pyaudio
import time
import numpy as np

"""Simple Non Blocking Stream PyAudio"""

CHUNK = 8192  # Samples: 1024,  512, 256, 128 frames per buffer
RATE = 384000  # Equivalent to Human Hearing at 40 kHz
# INTERVAL = 1  # Sampling Interval in Seconds

start_time = time.time()  	# сохраняем время старта выполнения программы
timer = start_time			# Для отсчета длительности таймера
timerP = start_time			# Для отсчета таймера детектирования по радару
timerT = start_time			# Для отсчета таймера
timer_MAX = 0
count = 0

p = pyaudio.PyAudio()

# This callback gets called by the stream

def callback(in_data, frame_count, time_info, status):
    # print(in_data)
    global timer
    global timer_MAX
    global count
    data = np.fromstring(in_data, dtype=np.int16)
    timerT = time.time() - timer        # подсчет длительности выполнения одной итерации цикла
    timer = time.time()
    if count and timer_MAX < timerT:
        timer_MAX = timerT
    print(f't:{timer_MAX:.3f}', f't:{timerT:.3f}', np.amax(data), count)
    count += 1
    return (in_data, pyaudio.paContinue)


# Notice the extra stream callback...
stream = p.open(format=pyaudio.paInt16,
                channels=1,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=callback)

stream.start_stream()

# The loop is different as well...
while stream.is_active():
    time.sleep(0.1)

# Exit with ctrl+C"
# This still doesn't run.

stream.stop_stream()
stream.close()
p.terminate()