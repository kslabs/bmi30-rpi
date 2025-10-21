import time
import pyaudio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
import os
import spidev
from gpiozero import DigitalOutputDevice, PWMOutputDevice, Button as GPIOButton
from rpi_hardware_pwm import HardwarePWM
from bmi30_def import initialize_gpio, set_resistor, toggle_gpio6_and_update_resistors, update_plot
from bmi30_plt import initialize_plot, update_start, switch_graph  # Импортируем функцию switch_graph

version = 6.00  # Обновляем версию

# Инициализируем GPIO
gpio12, gpio5, gpio6 = initialize_gpio()

# Настраиваем GPIO26 как вход для прерывания
button = GPIOButton(26, pull_up=True)

# Исходные значения цифровых резисторов
resistor_values = {"dr0_0": 200, "dr0_1": 00, "dr1_0": 75, "dr1_1": 255}
print(f"состояние резисторов: {resistor_values}")

# Привязываем обработчик прерывания
button.when_pressed = lambda: toggle_gpio6_and_update_resistors(gpio6)

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
CHUNK = 23400  # Количество сэмплов на буфер
RATE = 384000  # Частота дискретизации

# Создаём экземпляр PyAudio
p = pyaudio.PyAudio()

# Инициализируем массивы для данных
dataADC1 = np.zeros(CHUNK, dtype=int)
dataADC2 = np.zeros(CHUNK, dtype=int)

# Функция обратного вызова для аудио
def audio_callback(in_data, frame_count, time_info, status):
    global dataADC1, dataADC2
    new_data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, 2)
    dataADC1 = np.concatenate((dataADC1[-CHUNK:], new_data[:, 0]))  # Ограничиваем размер
    dataADC2 = np.concatenate((dataADC2[-CHUNK:], new_data[:, 1]))  # Ограничиваем размер
    return in_data, pyaudio.paContinue

# Создаём поток захвата аудио
stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback)

# Переменные управления осциллограммами
current_oscilloscope = 1  # Указывает, какая осциллограмма отображается
start_sample = 0  # Начало отображаемого диапазона
num_samples = CHUNK  # Количество отображаемых семплов
update_needed = False  # Флаг для отслеживания необходимости обновления графика
show_plot = True  # Флаг для отображения осциллограммы

# Визуализация осциллограммы
fig, ax, line1, line2 = initialize_plot(CHUNK, dataADC1, dataADC2)

# Функция обновления графика при изменении ползунков
def update_plot(val):
    global start_sample, num_samples, update_needed
    start_sample = int(start_sample_slider.val)
    num_samples = int(num_samples_slider.val)
    
    # Ограничиваем значения
    start_sample = max(0, min(start_sample, len(dataADC1) - num_samples))
    num_samples = max(10, min(num_samples, len(dataADC1) - start_sample))
    
    if start_sample + num_samples > len(dataADC1):
        num_samples = len(dataADC1) - start_sample
    
    x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
    line1.set_data(x_axis, dataADC1[start_sample:start_sample+num_samples])
    line2.set_data(x_axis, dataADC2[start_sample:start_sample+num_samples])
    
    ax.set_xlim(start_sample, start_sample + num_samples)
    ax.relim()
    ax.autoscale_view()
    update_needed = True  # Устанавливаем флаг для обновления графика

# Обработчик для ползунка "Старт"
def update_start_handler(val):
    global start_sample, num_samples, update_needed
    start_sample, num_samples = update_start(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax, CHUNK)
    update_needed = True

# Добавляем ползунки для изменения отображаемого диапазона
ax_slider1 = plt.axes([0.1, 0.01, 0.81, 0.03])
ax_slider2 = plt.axes([0.1, 0.05, 0.81, 0.03])

start_sample_slider = Slider(ax_slider1, 'Старт', 0, CHUNK, valinit=start_sample, valstep=10)
num_samples_slider = Slider(ax_slider2, 'Длина', 10, CHUNK, valinit=num_samples, valstep=10)

start_sample_slider.on_changed(update_start_handler)
num_samples_slider.on_changed(update_plot)

# Добавляем текстовое поле для отображения названия активной кнопки
ax_text = plt.axes([0.1, 0.95, 0.48, 0.03])  # Укорачиваем текстовое поле еще на 20%
ax_text.spines['top'].set_linestyle(':')  # Делаем рамку точечной
ax_text.spines['top'].set_color('lightgray')  # Делаем рамку светлее
ax_text.spines['bottom'].set_color('none')  # Удаляем нижнюю рамку
ax_text.spines['left'].set_color('none')  # Удаляем левую рамку
ax_text.spines['right'].set_color('none')  # Удаляем правую рамку
ax_text.xaxis.set_visible(False)  # Удаляем подписи снизу рамки
ax_text.yaxis.set_visible(False)  # Удаляем подписи слева рамки
text_box = plt.text(0.5, 0.5, '', horizontalalignment='center', verticalalignment='center', transform=ax_text.transAxes)

# Добавляем кнопки для переключения графиков
button_width = 0.05  # Уменьшаем ширину кнопок в 2 раза

ax_button0 = plt.axes([0.1, 0.9, button_width, 0.05])
button0 = Button(ax_button0, '0')

ax_button1 = plt.axes([0.16, 0.9, button_width, 0.05])
button1 = Button(ax_button1, '1')

ax_button2 = plt.axes([0.22, 0.9, button_width, 0.05])
button2 = Button(ax_button2, '2')

ax_button3 = plt.axes([0.28, 0.9, button_width, 0.05])
button3 = Button(ax_button3, '3')

ax_button4 = plt.axes([0.34, 0.9, button_width, 0.05])
button4 = Button(ax_button4, '4')

ax_button5 = plt.axes([0.40, 0.9, button_width, 0.05])
button5 = Button(ax_button5, '5')

ax_button6 = plt.axes([0.46, 0.9, button_width, 0.05])
button6 = Button(ax_button6, '6')

ax_button7 = plt.axes([0.52, 0.9, button_width, 0.05])
button7 = Button(ax_button7, '7')

ax_button8 = plt.axes([0.58, 0.9, button_width, 0.05])
button8 = Button(ax_button8, '8')

ax_button9 = plt.axes([0.64, 0.9, button_width, 0.05])
button9 = Button(ax_button9, '9')

buttons = [button0, button1, button2, button3, button4, button5, button6, button7, button8, button9]

# Устанавливаем цвет активной кнопки при запуске
light_green = '#90EE90'  # Светло-зеленый цвет

if current_oscilloscope == 1:
    button1.ax.set_facecolor(light_green)
    button1.color = light_green
    button1.hovercolor = light_green
    text_box.set_text('Верхняя и нижняя антенны')
elif current_oscilloscope == 2:
    button2.ax.set_facecolor(light_green)
    button2.color = light_green
    button2.hovercolor = light_green
    text_box.set_text('Верхняя антенна')
elif current_oscilloscope == 3:
    button3.ax.set_facecolor(light_green)
    button3.color = light_green
    button3.hovercolor = light_green
    text_box.set_text('Нижняя антенна')
elif current_oscilloscope == 4:
    button4.ax.set_facecolor(light_green)
    button4.color = light_green
    button4.hovercolor = light_green
    text_box.set_text('Резерв')
elif current_oscilloscope == 5:
    button5.ax.set_facecolor(light_green)
    button5.color = light_green
    button5.hovercolor = light_green
    text_box.set_text('Резерв')
elif current_oscilloscope == 6:
    button6.ax.set_facecolor(light_green)
    button6.color = light_green
    button6.hovercolor = light_green
    text_box.set_text('Резерв')
elif current_oscilloscope == 7:
    button7.ax.set_facecolor(light_green)
    button7.color = light_green
    button7.hovercolor = light_green
    text_box.set_text('Резерв')
elif current_oscilloscope == 8:
    button8.ax.set_facecolor(light_green)
    button8.color = light_green
    button8.hovercolor = light_green
    text_box.set_text('Резерв')
elif current_oscilloscope == 9:
    button9.ax.set_facecolor(light_green)
    button9.color = light_green
    button9.hovercolor = light_green
    text_box.set_text('Резерв')
else:
    button0.ax.set_facecolor(light_green)
    button0.color = light_green
    button0.hovercolor = light_green
    text_box.set_text('Выключаем вывод, но работаем')

fig.canvas.draw_idle()  # Обновляем отображение

# Функция переключения графиков
def switch_graph_handler(label):
    global current_oscilloscope, update_needed, show_plot
    current_oscilloscope, update_needed, show_plot = switch_graph(label, buttons, light_green, text_box, [current_oscilloscope], [update_needed], [show_plot], fig)

button0.on_clicked(lambda event: switch_graph_handler('0'))
button1.on_clicked(lambda event: switch_graph_handler('1'))
button2.on_clicked(lambda event: switch_graph_handler('2'))
button3.on_clicked(lambda event: switch_graph_handler('3'))
button4.on_clicked(lambda event: switch_graph_handler('4'))
button5.on_clicked(lambda event: switch_graph_handler('5'))
button6.on_clicked(lambda event: switch_graph_handler('6'))
button7.on_clicked(lambda event: switch_graph_handler('7'))
button8.on_clicked(lambda event: switch_graph_handler('8'))
button9.on_clicked(lambda event: switch_graph_handler('9'))

plt.show()

# Конфигурируем pwm
pwm3 = HardwarePWM(pwm_channel=3, hz=200, chip=2)  # OnPWR
pwm2 = HardwarePWM(pwm_channel=2, hz=200, chip=2)

print("BMI30.100 version: v", version)

try:
    gpio12.on()  # Устанавливаем GPIO12 в 1 (включение FULL_PWR)
    gpio5.on()  # GPIO5 LED индикации, включаем ТОЛЬКО при работе PWM
    pwm2.start(50)  # Запускаем pwm с скважностью 50%
    pwm3.start(50)  # Запускаем pwm с скважностью 50%
    
    while True:
        if show_plot and update_needed:
            if current_oscilloscope == 1:
                x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
                line1.set_data(x_axis, dataADC1[start_sample:start_sample+num_samples])
                line2.set_data(x_axis, dataADC2[start_sample:start_sample+num_samples])
                ax.relim()
                ax.autoscale_view()
            elif current_oscilloscope == 2:
                x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
                line1.set_data(x_axis, dataADC1[start_sample:start_sample+num_samples])
                line2.set_data(x_axis, np.zeros(num_samples))  # Очищаем данные для второй антенны
                ax.relim()
                ax.autoscale_view()
            elif current_oscilloscope == 3:
                x_axis = np.linspace(start_sample, start_sample + num_samples - 1, num_samples)
                line1.set_data(x_axis, np.zeros(num_samples))  # Очищаем данные для первой антенны
                line2.set_data(x_axis, dataADC2[start_sample:start_sample+num_samples])
                ax.relim()
                ax.autoscale_view()
            update_needed = False  # Сбрасываем флаг после обновления графика
        if not plt.fignum_exists(fig.number):
            break
        if show_plot:
            # Обновляем данные осциллограммы
            if current_oscilloscope == 1:
                line1.set_ydata(dataADC1[start_sample:start_sample+num_samples])
                line2.set_ydata(dataADC2[start_sample:start_sample+num_samples])
            elif current_oscilloscope == 2:
                line1.set_ydata(dataADC1[start_sample:start_sample+num_samples])
                line2.set_ydata(np.zeros(num_samples))  # Очищаем данные для второй антенны
            elif current_oscilloscope == 3:
                line1.set_ydata(np.zeros(num_samples))  # Очищаем данные для первой антенны
                line2.set_ydata(dataADC2[start_sample:start_sample+num_samples])
            if np.any(dataADC1[start_sample:start_sample+num_samples]) or np.any(dataADC2[start_sample:start_sample+num_samples]):
                fig.canvas.flush_events()
        time.sleep(0.1)  # Уменьшаем частоту обновления графика
        if show_plot:
            fig.canvas.flush_events()

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
