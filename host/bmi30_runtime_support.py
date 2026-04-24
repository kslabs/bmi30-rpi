from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bmi30_config.json")


def import_gpio_module(module_name: str):
    """Import GPIO-related module, falling back to system dist-packages from venv."""
    try:
        return importlib.import_module(module_name)
    except Exception:
        pass
    for extra_path in (
        "/usr/lib/python3/dist-packages",
        f"/usr/local/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
    ):
        try:
            if os.path.isdir(extra_path) and extra_path not in sys.path:
                sys.path.append(extra_path)
        except Exception:
            pass
    return importlib.import_module(module_name)


class PwmBeeper:
    """Best-effort beeper for RPi PWM0 (GPIO12)."""

    def __init__(self, gpio_pin: int = 12):
        self.gpio_pin = int(gpio_pin)
        self._backend = None
        self._pi = None
        self._lg = None
        self._lg_h = None
        self._gpio = None
        self._pwm = None
        self._lock = threading.Lock()
        self._enabled = str(os.getenv("BMI30_BEEP_ENABLE", "1")).lower() not in ("0", "false", "no")
        self._continuous_on = False
        self._last_freq = 0
        self._init_backend()

    def status(self) -> str:
        """Return backend status for UI/logging."""
        try:
            if not bool(self._enabled):
                return "OFF"
            b = str(self._backend or "none")
            if b == "none":
                return "none"
            try:
                if bool(getattr(self, "_continuous_on", False)) and int(getattr(self, "_last_freq", 0) or 0) > 0:
                    return f"{b}@GPIO{int(self.gpio_pin)} f={int(self._last_freq)}"
            except Exception:
                pass
            return f"{b}@GPIO{int(self.gpio_pin)}"
        except Exception:
            return "unknown"

    def _init_backend(self):
        if not self._enabled:
            return
        try:
            lgpio = import_gpio_module("lgpio")  # type: ignore
            chip = 0
            try:
                chip = int(os.getenv("BMI30_GPIOCHIP", "0") or 0)
            except Exception:
                chip = 0
            h = lgpio.gpiochip_open(chip)
            try:
                lgpio.gpio_claim_output(h, self.gpio_pin, 0)
            except Exception:
                pass
            self._backend = "lgpio"
            self._lg = lgpio
            self._lg_h = h
            return
        except Exception:
            self._lg = None
            self._lg_h = None
        try:
            pigpio = import_gpio_module("pigpio")  # type: ignore
            pi = pigpio.pi()
            if getattr(pi, "connected", False):
                self._backend = "pigpio"
                self._pi = pi
                pi.set_mode(self.gpio_pin, pigpio.OUTPUT)
                pi.write(self.gpio_pin, 0)
                return
        except Exception:
            pass
        try:
            gpio = import_gpio_module("RPi.GPIO")  # type: ignore
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            gpio.setup(self.gpio_pin, gpio.OUT, initial=gpio.LOW)
            self._backend = "rpi_gpio"
            self._gpio = gpio
            return
        except Exception:
            self._backend = None
            self._gpio = None
            self._pi = None
            self._lg = None
            self._lg_h = None

    def _start(self, freq_hz: float):
        if not self._enabled or self._backend is None:
            return
        freq = int(max(1, float(freq_hz)))
        if self._backend == "pigpio" and self._pi is not None:
            try:
                self._pi.hardware_PWM(self.gpio_pin, freq, 500_000)
            except Exception:
                pass
            return
        if self._backend == "lgpio" and self._lg is not None and self._lg_h is not None:
            try:
                self._lg.tx_pwm(self._lg_h, self.gpio_pin, freq, 50)
            except Exception:
                pass
            return
        if self._backend == "rpi_gpio" and self._gpio is not None:
            try:
                if self._pwm is None:
                    self._pwm = self._gpio.PWM(self.gpio_pin, freq)
                    self._pwm.start(50.0)
                else:
                    self._pwm.ChangeFrequency(freq)
                    self._pwm.ChangeDutyCycle(50.0)
            except Exception:
                pass

    def _stop(self):
        if not self._enabled or self._backend is None:
            return
        if self._backend == "pigpio" and self._pi is not None:
            try:
                self._pi.hardware_PWM(self.gpio_pin, 0, 0)
            except Exception:
                pass
            return
        if self._backend == "lgpio" and self._lg is not None and self._lg_h is not None:
            try:
                self._lg.tx_pwm(self._lg_h, self.gpio_pin, 0, 0)
            except Exception:
                pass
            return
        if self._backend == "rpi_gpio" and self._pwm is not None:
            try:
                self._pwm.ChangeDutyCycle(0.0)
            except Exception:
                pass

    def set_continuous(self, freq_hz: float | None):
        """Enable/disable continuous tone."""
        if not self._enabled or self._backend is None:
            return
        try:
            freq = int(max(0, float(freq_hz or 0.0)))
        except Exception:
            freq = 0
        with self._lock:
            if freq <= 0:
                self._continuous_on = False
                self._last_freq = 0
                self._stop()
                return
            if self._continuous_on and self._last_freq == int(freq):
                return
            self._continuous_on = True
            self._last_freq = int(freq)
            self._start(float(freq))

    def play_pattern(self, f1: float, f2: float, t_on1: float = 0.150, t_gap: float = 0.050, t_on2: float = 0.150):
        """Play: ON(f1) -> OFF -> ON(f2)."""
        if not self._enabled or self._backend is None:
            return
        try:
            if bool(getattr(self, "_continuous_on", False)):
                return
        except Exception:
            pass

        def _run():
            with self._lock:
                try:
                    self._start(f1)
                    time.sleep(max(0.0, float(t_on1)))
                    self._stop()
                    time.sleep(max(0.0, float(t_gap)))
                    self._start(f2)
                    time.sleep(max(0.0, float(t_on2)))
                finally:
                    self._stop()

        threading.Thread(target=_run, daemon=True).start()


def save_config(desired_profile, desired_freq=None):
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["desired_profile"] = desired_profile
        if desired_freq is not None:
            data["desired_freq"] = desired_freq
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def load_config():
    """Load desired_profile from config file. Default=1."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        val = int(data.get("desired_profile", 1))
        if val not in (1, 2):
            return 1
        return val
    except Exception:
        return 1


def load_freq():
    """Load desired_freq from config file. Default=200."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return int(data.get("desired_freq", 200))
    except Exception:
        return 200


def save_det_ratio(det_ratio: float):
    """Save detector ratio to config file (best-effort merge)."""
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["det_ratio"] = float(det_ratio)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def load_det_ratio() -> float:
    """Load detector ratio from config/env. Default=2.0."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        if "det_ratio" in data:
            return float(data.get("det_ratio", 2.0))
    except Exception:
        pass
    try:
        return float(os.getenv("BMI30_DETECT_RATIO", "2.0"))
    except Exception:
        return 2.0


def load_avg_n():
    """Load avg_n from config file (fallback 20)."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        val = int(data.get("avg_n", 20))
        if val < 2:
            return 20
        return val
    except Exception:
        return 20


def env_bool(name: str, default: bool = False) -> bool:
    """Parse common boolean env var values."""
    try:
        val = os.getenv(name)
        if val is None:
            return bool(default)
        return str(val).strip().lower() in ("1", "true", "yes", "y", "on", "t")
    except Exception:
        return bool(default)


def save_avg_n(avg_n: int):
    """Save avg_n to config file alongside other settings (best-effort merge)."""
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["avg_n"] = int(avg_n)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass
