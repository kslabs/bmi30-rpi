#!/usr/bin/env python3
"""
Hardware reset pulse generator for BMI30.

Open-collector behavior:
- active pulse: drive GPIO LOW for pulse duration
- idle state: release line to Hi-Z (input mode, no pull)

Default pattern:
- LOW for 0.1 s
- repeat every 10 s
"""

from __future__ import annotations

import argparse
import importlib
import os
import signal
import sys
import time
from dataclasses import dataclass


@dataclass
class PulseConfig:
    gpio: int = 17
    pulse_s: float = 0.1
    period_s: float = 10.0
    count: int = 0  # 0 means infinite
    active_level: str = "low"  # low|high
    idle_mode: str = "hiz"  # hiz|low|high


def _import_gpio_module(module_name: str):
    """Import GPIO module from venv or fall back to system dist-packages."""
    try:
        return importlib.import_module(module_name)
    except Exception:
        pass

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    extra_paths = (
        "/usr/lib/python3/dist-packages",
        f"/usr/local/lib/python{py_ver}/dist-packages",
    )
    for p in extra_paths:
        try:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.append(p)
        except Exception:
            pass

    return importlib.import_module(module_name)


class ResetLineDriver:
    """GPIO driver that emulates open-collector pulses (LOW -> Hi-Z)."""

    def __init__(self, gpio: int):
        self.gpio = int(gpio)
        self.backend = "none"

        self._pigpio = None
        self._pi = None

        self._lgpio = None
        self._chip = None

        self._rpi_gpio = None

        self._init_backend()

    def _init_backend(self) -> None:
        errors = []

        try:
            lgpio = _import_gpio_module("lgpio")  # type: ignore

            chip_idx = int(os.getenv("BMI30_GPIOCHIP", "0") or "0")
            chip = lgpio.gpiochip_open(chip_idx)
            self._lgpio = lgpio
            self._chip = chip
            self.backend = "lgpio"
            return
        except Exception as exc:
            errors.append(f"lgpio: {exc}")

        try:
            pigpio = _import_gpio_module("pigpio")  # type: ignore

            pi = pigpio.pi()
            if pi is not None and getattr(pi, "connected", False):
                self._pigpio = pigpio
                self._pi = pi
                self.backend = "pigpio"
                return
            errors.append("pigpio daemon not connected")
        except Exception as exc:
            errors.append(f"pigpio: {exc}")

        try:
            GPIO = _import_gpio_module("RPi.GPIO")  # type: ignore

            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            self._rpi_gpio = GPIO
            self.backend = "rpi_gpio"
            return
        except Exception as exc:
            errors.append(f"RPi.GPIO: {exc}")

        raise RuntimeError(
            "No GPIO backend available. Tried: " + " | ".join(errors)
        )

    def drive_low(self) -> None:
        if self.backend == "pigpio":
            assert self._pigpio is not None and self._pi is not None
            self._pi.set_mode(self.gpio, self._pigpio.OUTPUT)
            self._pi.write(self.gpio, 0)
            return

        if self.backend == "lgpio":
            assert self._lgpio is not None and self._chip is not None
            self._lgpio.gpio_claim_output(self._chip, self.gpio, 0)
            return

        if self.backend == "rpi_gpio":
            assert self._rpi_gpio is not None
            self._rpi_gpio.setup(self.gpio, self._rpi_gpio.OUT, initial=self._rpi_gpio.LOW)
            return

        raise RuntimeError("GPIO backend is not initialized")

    def drive_high(self) -> None:
        if self.backend == "pigpio":
            assert self._pigpio is not None and self._pi is not None
            self._pi.set_mode(self.gpio, self._pigpio.OUTPUT)
            self._pi.write(self.gpio, 1)
            return

        if self.backend == "lgpio":
            assert self._lgpio is not None and self._chip is not None
            self._lgpio.gpio_claim_output(self._chip, self.gpio, 1)
            return

        if self.backend == "rpi_gpio":
            assert self._rpi_gpio is not None
            self._rpi_gpio.setup(self.gpio, self._rpi_gpio.OUT, initial=self._rpi_gpio.HIGH)
            return

        raise RuntimeError("GPIO backend is not initialized")

    def release_hiz(self) -> None:
        if self.backend == "pigpio":
            assert self._pigpio is not None and self._pi is not None
            self._pi.set_mode(self.gpio, self._pigpio.INPUT)
            return

        if self.backend == "lgpio":
            assert self._lgpio is not None and self._chip is not None
            self._lgpio.gpio_claim_input(self._chip, self.gpio)
            return

        if self.backend == "rpi_gpio":
            assert self._rpi_gpio is not None
            self._rpi_gpio.setup(self.gpio, self._rpi_gpio.IN, pull_up_down=self._rpi_gpio.PUD_OFF)
            return

        raise RuntimeError("GPIO backend is not initialized")

    def close(self) -> None:
        try:
            self.release_hiz()
        except Exception:
            pass

        if self.backend == "pigpio" and self._pi is not None:
            try:
                self._pi.stop()
            except Exception:
                pass

        if self.backend == "lgpio" and self._lgpio is not None and self._chip is not None:
            try:
                self._lgpio.gpiochip_close(self._chip)
            except Exception:
                pass

        if self.backend == "rpi_gpio" and self._rpi_gpio is not None:
            try:
                self._rpi_gpio.cleanup(self.gpio)
            except Exception:
                pass


def parse_args() -> PulseConfig:
    parser = argparse.ArgumentParser(
        description="Generate periodic open-collector reset pulses on RPi GPIO"
    )
    parser.add_argument("--gpio", type=int, default=int(os.getenv("BMI30_HW_RESET_GPIO", "17")))
    parser.add_argument(
        "--pulse-s",
        type=float,
        default=float(os.getenv("BMI30_HW_RESET_PULSE_S", "0.1")),
        help="LOW pulse duration in seconds",
    )
    parser.add_argument(
        "--period-s",
        type=float,
        default=float(os.getenv("BMI30_HW_RESET_PERIOD_S", "10.0")),
        help="Start-to-start period in seconds",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("BMI30_HW_RESET_COUNT", "0")),
        help="Number of pulses (0 = infinite)",
    )
    parser.add_argument(
        "--active-level",
        choices=["low", "high"],
        default=str(os.getenv("BMI30_HW_RESET_ACTIVE_LEVEL", "low")).lower(),
        help="Pulse active level (default: low)",
    )
    parser.add_argument(
        "--idle-mode",
        choices=["hiz", "low", "high"],
        default=str(os.getenv("BMI30_HW_RESET_IDLE_MODE", "hiz")).lower(),
        help="Idle level after pulse: hiz (open collector), low, or high",
    )
    args = parser.parse_args()

    cfg = PulseConfig(
        gpio=args.gpio,
        pulse_s=args.pulse_s,
        period_s=args.period_s,
        count=args.count,
        active_level=args.active_level,
        idle_mode=args.idle_mode,
    )

    if cfg.gpio < 0:
        parser.error("--gpio must be >= 0")
    if cfg.pulse_s <= 0:
        parser.error("--pulse-s must be > 0")
    if cfg.period_s <= 0:
        parser.error("--period-s must be > 0")
    if cfg.pulse_s >= cfg.period_s:
        parser.error("--pulse-s must be < --period-s")
    if cfg.count < 0:
        parser.error("--count must be >= 0")

    return cfg


def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run_pulses(cfg: PulseConfig) -> int:
    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        stop["flag"] = True
        print(f"[{ts()}] signal={signum}, stopping...", flush=True)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    driver = ResetLineDriver(cfg.gpio)
    print(
        f"[{ts()}] backend={driver.backend} gpio={cfg.gpio} pulse={cfg.pulse_s:.3f}s period={cfg.period_s:.3f}s count={cfg.count or 'inf'} active={cfg.active_level} idle={cfg.idle_mode}",
        flush=True,
    )

    sent = 0
    start_time = time.monotonic()

    try:
        while not stop["flag"]:
            if cfg.count and sent >= cfg.count:
                break

            cycle_start = time.monotonic()
            sent += 1
            print(f"[{ts()}] pulse #{sent}: ACTIVE={cfg.active_level.upper()}", flush=True)

            if cfg.active_level == "high":
                driver.drive_high()
            else:
                driver.drive_low()
            time.sleep(cfg.pulse_s)

            if cfg.idle_mode == "hiz":
                driver.release_hiz()
                idle_text = "Hi-Z"
            elif cfg.idle_mode == "high":
                driver.drive_high()
                idle_text = "HIGH"
            else:
                driver.drive_low()
                idle_text = "LOW"
            print(f"[{ts()}] pulse #{sent}: IDLE={idle_text}", flush=True)

            elapsed = time.monotonic() - cycle_start
            sleep_left = cfg.period_s - elapsed
            if sleep_left > 0:
                time.sleep(sleep_left)

        total = time.monotonic() - start_time
        print(f"[{ts()}] done, pulses={sent}, total={total:.2f}s", flush=True)
        return 0
    except Exception as exc:
        print(f"[{ts()}] ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        driver.close()


if __name__ == "__main__":
    config = parse_args()
    raise SystemExit(run_pulses(config))
