#!/usr/bin/env python3
"""
test_gpio_led_blink.py — тест непрерывного мигания неадресных светодиодных линеек
Выводы: GPIO22 и GPIO27 (BCM-нумерация)

Использование:
    python3 test_gpio_led_blink.py [--hz 2] [--duty 50] [--count N]

    --hz    частота мигания, Гц (по умолчанию 2.0)
    --duty  скважность в % (по умолчанию 50, т.е. равное on/off)
    --count количество миганий (по умолчанию 0 = бесконечно, Ctrl+C для остановки)

Поддерживаемые бэкенды GPIO (пробуются по порядку):
    1. lgpio     — рекомендуется для Pi 5 / современных дистрибутивов
    2. pigpio    — требует запущенного pigpiod
    3. RPi.GPIO  — программный ШИМ / простое переключение
"""

import sys
import os
import time
import importlib
import argparse
import threading

# ─── GPIO пины (BCM) ────────────────────────────────────────────────────────
LED_PINS = [22, 27]

# ─── вспомогательная загрузка модуля ────────────────────────────────────────
def _import_gpio(name: str):
    try:
        return importlib.import_module(name
                                       )
    except Exception:
        pass
    for extra in (
        "/usr/lib/python3/dist-packages",
        f"/usr/local/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
    ):
        if os.path.isdir(extra) and extra not in sys.path:
            sys.path.append(extra)
    return importlib.import_module(name)

# ─── класс управления одним пином ───────────────────────────────────────────
class LedPin:
    """Управление одним GPIO-пином (HIGH=on, LOW=off)."""

    def __init__(self, pin: int, backend: str, ctx):
        self.pin = pin
        self.backend = backend
        self._ctx = ctx          # pigpio.pi | lgpio_handle | GPIO module
        self._is_on = False

    def on(self):
        self._set(1)

    def off(self):
        self._set(0)

    def _set(self, level: int):
        try:
            if self.backend == 'pigpio':
                self._ctx.write(self.pin, level)
            elif self.backend == 'lgpio':
                lg, h = self._ctx
                lg.gpio_write(h, self.pin, level)
            elif self.backend == 'rpi_gpio':
                self._ctx.output(self.pin, level)
        except Exception as exc:
            print(f"  [WARN] GPIO{self.pin} set {level}: {exc}", file=sys.stderr)
        self._is_on = bool(level)

    def cleanup(self):
        try:
            self._set(0)
        except Exception:
            pass

# ─── инициализация бэкенда ───────────────────────────────────────────────────
def init_leds(pins: list) -> tuple:
    """Пробует бэкенды по порядку, возвращает (backend_name, [LedPin, ...])."""

    # 1. lgpio
    try:
        lgpio = _import_gpio('lgpio')
        chip = int(os.getenv('BMI30_GPIOCHIP', '0') or 0)
        h = lgpio.gpiochip_open(chip)
        led_objs = []
        for p in pins:
            lgpio.gpio_claim_output(h, p, 0)
            led_objs.append(LedPin(p, 'lgpio', (lgpio, h)))
        print(f"[backend] lgpio (chip {chip})")
        return 'lgpio', led_objs, lambda: lgpio.gpiochip_close(h)
    except Exception as e:
        print(f"[backend] lgpio недоступен: {e}", file=sys.stderr)

    # 2. pigpio
    try:
        pigpio = _import_gpio('pigpio')
        pi = pigpio.pi()
        if not getattr(pi, 'connected', False):
            raise RuntimeError("pigpiod не запущен")
        led_objs = []
        for p in pins:
            pi.set_mode(p, pigpio.OUTPUT)
            pi.write(p, 0)
            led_objs.append(LedPin(p, 'pigpio', pi))
        print("[backend] pigpio")
        return 'pigpio', led_objs, lambda: pi.stop()
    except Exception as e:
        print(f"[backend] pigpio недоступен: {e}", file=sys.stderr)

    # 3. RPi.GPIO
    try:
        GPIO = _import_gpio('RPi.GPIO')
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        led_objs = []
        for p in pins:
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
            led_objs.append(LedPin(p, 'rpi_gpio', GPIO))
        print("[backend] RPi.GPIO")
        return 'rpi_gpio', led_objs, lambda: GPIO.cleanup()
    except Exception as e:
        print(f"[backend] RPi.GPIO недоступен: {e}", file=sys.stderr)

    raise RuntimeError(
        "Ни один GPIO-бэкенд не доступен. "
        "Установите lgpio / pigpio / RPi.GPIO и убедитесь в правах доступа к /dev/gpiochip*"
    )

# ─── основной цикл мигания ───────────────────────────────────────────────────
def blink_loop(leds: list, hz: float, duty: float, count: int):
    """
    hz    — частота мигания (Гц)
    duty  — скважность 0..100 (%)
    count — количество циклов; 0 = бесконечно
    """
    period = 1.0 / max(0.01, hz)
    t_on  = period * max(0.0, min(1.0, duty / 100.0))
    t_off = period - t_on

    pin_names = ", ".join(f"GPIO{l.pin}" for l in leds)
    print(f"[blink] пины: {pin_names}")
    print(f"[blink] {hz:.2f} Гц  |  скважность {duty:.0f}%  |  "
          f"on={t_on*1000:.1f} мс  off={t_off*1000:.1f} мс")
    if count:
        print(f"[blink] циклов: {count}")
    else:
        print("[blink] Ctrl+C для остановки")

    cycle = 0
    try:
        while True:
            # ── включить ──
            for led in leds:
                led.on()
            time.sleep(t_on)

            # ── выключить ──
            for led in leds:
                led.off()
            time.sleep(t_off)

            cycle += 1
            print(f"  цикл {cycle:>5}", end="\r", flush=True)

            if count and cycle >= count:
                break

    except KeyboardInterrupt:
        print("\n[blink] остановлено пользователем")

    print(f"\n[blink] всего циклов: {cycle}")

# ─── точка входа ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Тест непрерывного мигания светодиодных линеек GPIO22 и GPIO27"
    )
    parser.add_argument("--hz",    type=float, default=2.0,
                        help="Частота мигания в Гц (по умолчанию 2.0)")
    parser.add_argument("--duty",  type=float, default=50.0,
                        help="Скважность в %% (по умолчанию 50)")
    parser.add_argument("--count", type=int,   default=0,
                        help="Количество циклов (0 = бесконечно)")
    parser.add_argument("--pins",  type=str,   default="22,27",
                        help="BCM-номера пинов через запятую (по умолчанию 22,27)")
    args = parser.parse_args()

    pins = [int(p.strip()) for p in args.pins.split(",") if p.strip().isdigit()]
    if not pins:
        print("Ошибка: не указаны корректные номера пинов", file=sys.stderr)
        sys.exit(1)

    print("=" * 50)
    print("  Тест мигания неадресных светодиодных линеек")
    print("=" * 50)

    try:
        backend, leds, cleanup = init_leds(pins)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    try:
        blink_loop(leds, hz=args.hz, duty=args.duty, count=args.count)
    finally:
        for led in leds:
            led.cleanup()
        try:
            cleanup()
            print("[GPIO] ресурсы освобождены")
        except Exception:
            pass

if __name__ == "__main__":
    main()
