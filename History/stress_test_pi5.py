import threading
import subprocess
import time
import signal
import sys
import os
import logging
from collections import deque
import matplotlib.pyplot as plt
import numpy as np
import psutil
import multiprocessing  # добавлено для создания процессов-воркеров

# --- Конфигурация ---
STRESS_DURATION_SECONDS = 0
TEMP_CHECK_INTERVAL_SECONDS = 0.2 # Интервал сбора данных (5 Гц)
ENABLE_GPU_TEST = True
ENABLE_GPIO_TEST = True
ENABLE_SPI_TEST = True
GPIO_PIN_OUT = 17
SPI_DEVICE = 0
SPI_BUS = 0
PLOT_MAX_POINTS = 150 # Уменьшим немного, т.к. частота ниже
# PLOT_UPDATE_INTERVAL_SECONDS больше не используется напрямую для паузы
TARGET_CPU_LOAD = 95

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Глобальные переменные ---
processes = []
threads = []
stop_event = threading.Event()
temperature_data = deque(maxlen=PLOT_MAX_POINTS)
cpu_usage_data = deque(maxlen=PLOT_MAX_POINTS)
noise_data = deque(maxlen=PLOT_MAX_POINTS) # Очередь для шума
time_data = deque(maxlen=PLOT_MAX_POINTS)
plot_lock = threading.Lock()
monitor_loop_counter = 0 # Счетчик для редкого логирования

# --- Функции для стресс-тестов ---

def run_command(command, name="Command"):
    """Запускает команду как подпроцесс."""
    try:
        logging.info(f"Запуск {name}: {' '.join(command)}")
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append(proc)
        return proc
    except FileNotFoundError:
        logging.error(f"Ошибка: Команда '{command[0]}' не найдена. Убедитесь, что она установлена.")
        return None
    except Exception as e:
        logging.error(f"Ошибка при запуске {name}: {e}")
        return None

def cpu_worker():
    """Рабочий процесс, загружающий 100% CPU своего ядра."""
    while True:
        pass  # непрерывный цикл без пауз для полной загрузки

def cpu_stress():
    """Создает нагрузку на все ядра CPU через multiprocessing.Process."""
    logging.info("Запуск CPU Stress: создаем рабочие процессы для каждого ядра")
    cpu_count = multiprocessing.cpu_count()
    workers = []
    for i in range(cpu_count):
        p = multiprocessing.Process(target=cpu_worker)
        p.start()
        workers.append(p)
    # Ждем сигнала остановки
    stop_event.wait()
    # Останавливаем все воркеры
    logging.info("Остановка CPU Stress: завершаем рабочие процессы")
    for p in workers:
        p.terminate()
        p.join()
    logging.info("CPU Stress завершен")

def gpu_stress():
    """Создает нагрузку на GPU с помощью glxgears."""
    if not ENABLE_GPU_TEST:
        logging.info("GPU тест отключен.")
        return
    logging.info("Запуск потока GPU Stress")
    if 'DISPLAY' not in os.environ:
        logging.warning("Переменная окружения DISPLAY не установлена. GPU тест (glxgears) может не запуститься.")
        logging.warning("Попробуйте запустить скрипт напрямую с монитора или установить DISPLAY=:0")
        os.environ['DISPLAY'] = ':0'

    command = ["glxgears"]
    proc = run_command(command, "GPU Stress (glxgears)")
    if proc:
        while not stop_event.is_set() and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
             try:
                 proc.terminate()
                 proc.wait(timeout=2)
                 logging.info("GPU Stress (glxgears) остановлен.")
             except subprocess.TimeoutExpired:
                 proc.kill()
                 logging.warning("GPU Stress (glxgears) принудительно завершен.")
             except Exception as e:
                 logging.error(f"Ошибка при остановке glxgears: {e}")

    logging.info("Поток GPU Stress завершен")

def gpio_stress():
    """Создает нагрузку на GPIO быстрым переключением пина (без пауз)."""
    if not ENABLE_GPIO_TEST:
        logging.info("GPIO тест отключен.")
        return
    logging.info(f"Запуск потока GPIO Stress (Pin {GPIO_PIN_OUT}) - Макс. скорость")
    pin = None
    try:
        from gpiozero import DigitalOutputDevice
        pin = DigitalOutputDevice(GPIO_PIN_OUT)
        logging.info(f"GPIO Pin {GPIO_PIN_OUT} инициализирован.")
        while not stop_event.is_set():
            pin.on()
            pin.off() # Максимально быстрое переключение
        logging.info(f"GPIO Pin {GPIO_PIN_OUT} остановлен.")
    except ImportError:
        logging.error("Библиотека gpiozero не найдена. GPIO тест невозможен.")
    except Exception as e:
        logging.error(f"Ошибка в потоке GPIO Stress: {e}")
    finally:
        if pin:
            pin.close()
            logging.info(f"GPIO Pin {GPIO_PIN_OUT} освобожден.")
    logging.info("Поток GPIO Stress завершен")

def spi_stress():
    """Создает нагрузку на SPI непрерывной передачей данных (без пауз)."""
    if not ENABLE_SPI_TEST:
        logging.info("SPI тест отключен.")
        return
    logging.info(f"Запуск потока SPI Stress (Bus {SPI_BUS}, Device {SPI_DEVICE}) - Макс. скорость")
    spi = None
    try:
        import spidev
        spi = spidev.SpiDev()
        spi.open(SPI_BUS, SPI_DEVICE)
        spi.max_speed_hz = 10000000 # 10 MHz
        spi.mode = 0
        logging.info(f"SPI Bus {SPI_BUS}, Device {SPI_DEVICE} инициализирован.")
        dummy_data = [0xAA] * 32
        while not stop_event.is_set():
            spi.xfer2(dummy_data) # Непрерывная передача
    except ImportError:
        logging.error("Библиотека spidev не найдена. SPI тест невозможен. Установите: pip install spidev")
    except FileNotFoundError:
         logging.error(f"Ошибка: SPI устройство /dev/spidev{SPI_BUS}.{SPI_DEVICE} не найдено. Проверьте настройки SPI в raspi-config.")
    except PermissionError:
         logging.error(f"Ошибка: Нет прав доступа к /dev/spidev{SPI_BUS}.{SPI_DEVICE}. Запустите скрипт с sudo или добавьте пользователя в группу spi.")
    except Exception as e:
        logging.error(f"Ошибка в потоке SPI Stress: {e}")
    finally:
        if spi:
            spi.close()
            logging.info(f"SPI Bus {SPI_BUS}, Device {SPI_DEVICE} закрыт.")
    logging.info("Поток SPI Stress завершен")

def monitor_temperature_and_cpu():
    """Периодически проверяет температуру, CPU и генерирует шум (интервал 0.2с)."""
    global monitor_loop_counter
    logging.info("Запуск потока мониторинга (T, CPU, Шум) - Интервал ~0.2с")
    start_time = time.time()
    psutil_ok = False
    try:
        psutil.cpu_percent(interval=None)
        psutil_ok = True
        time.sleep(0.1)
    except ImportError:
        logging.error("Библиотека psutil не найдена. Мониторинг CPU недоступен.")
    except Exception as e:
         logging.error(f"Ошибка инициализации psutil: {e}")


    while not stop_event.is_set():
        loop_start_time = time.perf_counter()
        current_temp = None
        current_cpu_usage = None
        current_noise = None

        # --- Температура ---
        try:
            # Увеличим таймаут на всякий случай, если система тормозит
            result = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True, check=True, timeout=1.0)
            temp_str = result.stdout.strip()
            current_temp = float(temp_str.split('=')[1].split('\'')[0])
        except Exception:
            pass

        # --- Загрузка CPU ---
        if psutil_ok:
            try:
                current_cpu_usage = psutil.cpu_percent(interval=None)
            except Exception:
                 pass

        # --- Генерация шума ---
        current_noise = np.random.rand() * 100

        # --- Добавляем данные в очереди ---
        with plot_lock:
            current_time = time.time() - start_time
            time_data.append(current_time)
            temperature_data.append(current_temp if current_temp is not None else np.nan)
            cpu_usage_data.append(current_cpu_usage if current_cpu_usage is not None else np.nan)
            noise_data.append(current_noise)

        # --- Редкое логирование ---
        monitor_loop_counter += 1
        # Логируем примерно каждые 2 секунды (10 * 0.2)
        if monitor_loop_counter % 10 == 0:
             logging.info(f"T: {current_temp if current_temp is not None else 'N/A'}°C, CPU: {current_cpu_usage if current_cpu_usage is not None else 'N/A'}%, Шум: {current_noise:.1f}")

        # --- Ожидание до следующего интервала ---
        loop_end_time = time.perf_counter()
        elapsed_time = loop_end_time - loop_start_time
        sleep_time = TEMP_CHECK_INTERVAL_SECONDS - elapsed_time
        if sleep_time > 0:
            time.sleep(sleep_time) # Точно выдерживаем интервал сбора данных

    logging.info("Поток мониторинга завершен")

# --- Функция для построения графика ---
def plot_temperature_live():
    """Отображает графики температуры, загрузки CPU и шума."""
    logging.info("Запуск потока отрисовки графиков")
    logging.warning("Частота обновления графика ограничена скоростью отрисовки matplotlib.")

    # ... (проверка DISPLAY - без изменений) ...
    if 'DISPLAY' not in os.environ:
        logging.error("Переменная окружения DISPLAY не установлена. Графики не могут быть отображены.")
        return

    fig = None

    try:
        plt.ion()
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, figsize=(8, 9))

        # --- Настройка графиков (как раньше) ---
        line_temp, = ax1.plot([], [], 'r-', label='Температура')
        ax1.set_ylabel("Температура (°C)")
        ax1.set_title("Мониторинг Raspberry Pi 5")
        ax1.grid(True)
        ax1.legend(loc='upper left')

        line_cpu, = ax2.plot([], [], 'b-', label='Загрузка CPU')
        ax2.set_ylabel("Загрузка CPU (%)")
        ax2.set_ylim(0, 105)
        ax2.grid(True)
        ax2.legend(loc='upper left')

        line_noise, = ax3.plot([], [], 'g-', label='Шум')
        ax3.set_xlabel("Время (секунды)")
        ax3.set_ylabel("Шум (у.е.)")
        ax3.set_ylim(0, 105)
        ax3.grid(True)
        ax3.legend(loc='upper left')

        fig.tight_layout(pad=2.0)
        fig.show()

        while not stop_event.is_set():
            current_times = []
            current_temps = []
            current_cpus = []
            current_noises = []

            with plot_lock:
                if len(time_data) > 0:
                    # Копируем текущие данные
                    current_times = list(time_data)
                    current_temps = list(temperature_data)
                    current_cpus = list(cpu_usage_data)
                    current_noises = list(noise_data)

            if current_times: # Если есть новые данные
                # Обновляем данные линий
                line_temp.set_data(current_times, current_temps)
                line_cpu.set_data(current_times, current_cpus)
                line_noise.set_data(current_times, current_noises)

                # Пересчитываем пределы осей
                ax1.relim()
                ax1.autoscale_view()
                ax2.relim()
                ax2.autoscale_view()
                ax2.set_ylim(0, 105)
                ax3.relim()
                ax3.autoscale_view()
                ax3.set_ylim(0, 105)

                # Перерисовываем график
                try:
                    fig.canvas.draw_idle()
                    fig.canvas.flush_events()
                except Exception as e:
                    logging.warning(f"Ошибка при отрисовке графика: {e}")
                    break

            # Используем минимальную паузу, чтобы GUI не зависал
            # Реальная частота обновления будет зависеть от скорости отрисовки
            plt.pause(0.01) # Очень маленькая пауза

    # ... (обработка ошибок и finally - без изменений) ...
    except ImportError:
        logging.error("Библиотека matplotlib, numpy или psutil не найдена. График невозможен.")
    except Exception as e:
        logging.error(f"Ошибка в потоке отрисовки графика: {e}")
    finally:
        if 'plt' in locals() or 'plt' in globals():
             plt.ioff()
             if fig is not None:
                 try:
                     plt.close(fig)
                     logging.info("Окно графика закрыто.")
                 except Exception as e:
                     logging.warning(f"Не удалось корректно закрыть окно графика: {e}")
        logging.info("Поток отрисовки графика завершен")

def signal_handler(sig, frame):
    """Обрабатывает сигнал завершения (Ctrl+C)."""
    logging.warning(f"Получен сигнал {signal.Signals(sig).name}. Завершение работы...")
    stop_event.set()

def cleanup():
    """Останавливает все запущенные процессы и потоки."""
    logging.info("Начало очистки ресурсов...")

    for proc in processes:
        if proc.poll() is None:
            try:
                logging.info(f"Остановка процесса PID {proc.pid}...")
                proc.terminate()
                proc.wait(timeout=2)
                logging.info(f"Процесс PID {proc.pid} остановлен.")
            except subprocess.TimeoutExpired:
                logging.warning(f"Процесс PID {proc.pid} не ответил на terminate, принудительное завершение (kill)...")
                proc.kill()
                proc.wait()
                logging.info(f"Процесс PID {proc.pid} принудительно завершен.")
            except Exception as e:
                 logging.error(f"Ошибка при остановке процесса PID {proc.pid}: {e}")

    logging.info("Ожидание завершения потоков...")
    main_thread = threading.current_thread()
    for thread in threads:
        if thread is not main_thread and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                 logging.warning(f"Поток {thread.name} не завершился вовремя.")

    logging.info("Очистка завершена.")

if __name__ == "__main__":
    logging.info("=== Запуск стресс-теста Raspberry Pi 5 ===")
    logging.warning("!!! Убедитесь, что у Pi достаточное охлаждение !!!")
    if os.geteuid() != 0:
        logging.warning("Скрипт запущен не от имени root (sudo). Доступ к GPIO/SPI может быть ограничен.")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    monitor_thread = threading.Thread(target=monitor_temperature_and_cpu, name="Monitor")
    threads.append(monitor_thread)

    plot_thread = threading.Thread(target=plot_temperature_live, name="Plotter")
    threads.append(plot_thread)

    cpu_thread = threading.Thread(target=cpu_stress, name="Stress")
    threads.append(cpu_thread)

    gpu_thread = None
    if ENABLE_GPU_TEST:
        gpu_thread = threading.Thread(target=gpu_stress, name="GPUStress")
        threads.append(gpu_thread)

    gpio_thread = None
    if ENABLE_GPIO_TEST:
        gpio_thread = threading.Thread(target=gpio_stress, name="GPIOStress")
        threads.append(gpio_thread)

    spi_thread = None
    if ENABLE_SPI_TEST:
        spi_thread = threading.Thread(target=spi_stress, name="SPIStress")
        threads.append(spi_thread)

    monitor_thread.start()
    plot_thread.start()
    time.sleep(1)
    cpu_thread.start()
    if gpu_thread: gpu_thread.start()
    if gpio_thread: gpio_thread.start()
    if spi_thread: spi_thread.start()

    try:
        stop_event.wait()
        logging.info("Событие остановки получено основным потоком.")
    except KeyboardInterrupt:
        logging.warning("Обнаружено прерывание с клавиатуры (основной поток).")
        if not stop_event.is_set():
             stop_event.set()
    finally:
        if not stop_event.is_set():
            stop_event.set()
        cleanup()
        logging.info("=== Стресс-тест завершен ===")
