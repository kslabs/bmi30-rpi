import spidev
from gpiozero import DigitalOutputDevice, Button as GPIOButton

# Устанавливаем исходное состояние всех выводов
def initialize_gpio():
    gpio12 = DigitalOutputDevice(12, initial_value=False)
    gpio5 = DigitalOutputDevice(5, initial_value=False)
    gpio6 = DigitalOutputDevice(6, initial_value=False)  # GPIO6 для инверсии при прерываниях
    return gpio12, gpio5, gpio6

# Функция установки значения цифровых резисторов для mcp4251
def set_resistor(spi, channel, value):
    spi.xfer2([0b00000000 | (channel << 4), value])  # Используем xfer2 для отправки и получения ответа
    response = spi.xfer2([0b00001100 | (channel << 4), 0xFF])

# Функция обработки прерывания
def toggle_gpio6_and_update_resistors(gpio6):
    gpio6.toggle()

# Функция обновления графика при изменении ползунков
def update_plot(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax, CHUNK):
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
    return start_sample, num_samples

# Обработчик для ползунка "Старт"
def update_start(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax, CHUNK):
    start_sample = int(start_sample_slider.val)
    max_length = CHUNK - start_sample
    num_samples_slider.valmax = max_length
    num_samples_slider.ax.set_xlim(num_samples_slider.valmin, max_length)
    num_samples_slider.set_val(min(num_samples_slider.val, max_length))
    return update_plot(val, start_sample_slider, num_samples_slider, dataADC1, dataADC2, line1, line2, ax, CHUNK)
