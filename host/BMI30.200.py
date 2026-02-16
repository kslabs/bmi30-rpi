"""BMI30.200.py — единая точка входа: сразу открывает живую осциллограмму Vendor Bulk двухканального потока."""

from __future__ import annotations
import os
import sys, time, json, os as _os_alias, struct
import threading
import datetime
import zlib
from collections import deque
# Qt env: avoid GTK theme/plugin conflicts on RPi (Bookworm)
# Choose backend safely:
# - if user set QT_QPA_PLATFORM explicitly, respect it
# - prefer xcb when DISPLAY exists
# - prefer wayland when WAYLAND_DISPLAY exists
# - otherwise use offscreen (headless smoke-tests)
if "QT_QPA_PLATFORM" not in os.environ:
	if os.getenv("DISPLAY"):
		os.environ["QT_QPA_PLATFORM"] = "xcb"
	elif os.getenv("WAYLAND_DISPLAY"):
		os.environ["QT_QPA_PLATFORM"] = "wayland"
	else:
		os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")
os.environ.pop("QT_QPA_PLATFORMTHEME", None)
import numpy as np  # type: ignore
import serial, glob
import threading, queue

try:
	from usb_vendor.usb_stream import USBStream, CMD_SET_PROFILE, CMD_STOP_STREAM, CMD_START_STREAM, CMD_SOFT_RESET, CMD_DEEP_RESET, CMD_SET_WINDOWS, CMD_SET_STREAM_MODE, CMD_ASYNC, CMD_SET_TIM2_ENABLE  # type: ignore
except Exception:
	from usb_vendor.usb_stream import USBStream  # type: ignore
	CMD_SET_PROFILE = 0x14
	CMD_STOP_STREAM = 0x21
	CMD_START_STREAM = 0x20
	CMD_GET_STATUS = 0x30
	CMD_FULL_MODE = 0x13
	CMD_CHMODE = 0x19
	CMD_ASYNC = 0x18
	CMD_BLOCK_HZ = 0x11
	CMD_SET_WINDOWS = 0x10
	CMD_SET_STREAM_MODE = 0x1A
	CMD_SOFT_RESET = 0x7E
	CMD_DEEP_RESET = 0x7F
	CMD_SET_ALT = 0x31
	CMD_SET_TIM2_ENABLE = 0x1E
	CMD_SET_TX_ENABLE = 0x33

# Optional: device-side DC adaptation toggle (not present in older usb_stream.py)
try:
	from usb_vendor.usb_stream import CMD_SET_DC_ADAPT  # type: ignore
except Exception:
	try:
		CMD_SET_DC_ADAPT = int(os.getenv("BMI30_CMD_SET_DC_ADAPT", "0x1B"), 0)
	except Exception:
		CMD_SET_DC_ADAPT = 0x1B

# Optional: device-side fast DC calibration (firmware-dependent)
try:
	from usb_vendor.usb_stream import CMD_CALIB_DC_FAST  # type: ignore
except Exception:
	try:
		CMD_CALIB_DC_FAST = int(os.getenv("BMI30_CMD_CALIB_DC_FAST", "0x1E"), 0)
	except Exception:
		CMD_CALIB_DC_FAST = 0x1E

# Optional: sync mode (master/slave/off)
try:
	from usb_vendor.usb_stream import CMD_SET_SYNC_MODE  # type: ignore
except Exception:
	try:
		CMD_SET_SYNC_MODE = int(os.getenv("BMI30_CMD_SET_SYNC_MODE", "0x1D"), 0)
	except Exception:
		CMD_SET_SYNC_MODE = 0x1D


class PwmBeeper:
	"""Best-effort beeper for RPi PWM0 (GPIO12).

	Backends:
	- pigpio.hardware_PWM (preferred)
	- lgpio.tx_pwm (direct, works on Pi5 without pigpiod)
	- RPi.GPIO.PWM (software PWM fallback)
	
	If no backend available, all methods become no-ops.
	"""
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
		self._pattern_token = 0
		self._init_backend()

	def status(self) -> str:
		"""Return backend status for UI/logging."""
		try:
			if not bool(self._enabled):
				return 'OFF'
			b = str(self._backend or 'none')
			if b == 'none':
				return 'none'
			# include minimal runtime state to debug "no variable signal"
			try:
				if bool(getattr(self, '_continuous_on', False)) and int(getattr(self, '_last_freq', 0) or 0) > 0:
					return f"{b}@GPIO{int(self.gpio_pin)} f={int(self._last_freq)}"
			except Exception:
				pass
			return f"{b}@GPIO{int(self.gpio_pin)}"
		except Exception:
			return 'unknown'

	def _init_backend(self):
		if not self._enabled:
			return
		# Try pigpio first
		try:
			import pigpio  # type: ignore
			pi = pigpio.pi()
			if getattr(pi, 'connected', False):
				self._backend = 'pigpio'
				self._pi = pi
				# Установить начальное состояние LOW (0)
				pi.set_mode(self.gpio_pin, pigpio.OUTPUT)
				pi.write(self.gpio_pin, 0)
				return
		except Exception:
			pass
		# Try lgpio (recommended on Pi5 / modern distros)
		try:
			import lgpio  # type: ignore
			chip = 0
			try:
				chip = int(os.getenv('BMI30_GPIOCHIP', '0') or 0)
			except Exception:
				chip = 0
			h = lgpio.gpiochip_open(chip)
			# Claim as output (initial low). PWM will override level.
			try:
				lgpio.gpio_claim_output(h, self.gpio_pin, 0)
			except Exception:
				# Some kernels/drivers don't require claim for tx_pwm; proceed anyway.
				pass
			self._backend = 'lgpio'
			self._lg = lgpio
			self._lg_h = h
			return
		except Exception:
			self._lg = None
			self._lg_h = None
		# Fallback: RPi.GPIO software PWM
		try:
			import RPi.GPIO as GPIO  # type: ignore
			GPIO.setwarnings(False)
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(self.gpio_pin, GPIO.OUT, initial=GPIO.LOW)  # Явно LOW при инициализации
			self._backend = 'rpi_gpio'
			self._gpio = GPIO
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
		if self._backend == 'pigpio' and self._pi is not None:
			# dutycycle: 0..1_000_000
			try:
				self._pi.hardware_PWM(self.gpio_pin, freq, 500_000)
			except Exception:
				pass
			return
		if self._backend == 'lgpio' and self._lg is not None and self._lg_h is not None:
			# dutycycle: 0..100 (percentage)
			try:
				self._lg.tx_pwm(self._lg_h, self.gpio_pin, freq, 50)
			except Exception:
				pass
			return
		if self._backend == 'rpi_gpio' and self._gpio is not None:
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
		if self._backend == 'pigpio' and self._pi is not None:
			try:
				self._pi.hardware_PWM(self.gpio_pin, 0, 0)
			except Exception:
				pass
			return
		if self._backend == 'lgpio' and self._lg is not None and self._lg_h is not None:
			try:
				self._lg.tx_pwm(self._lg_h, self.gpio_pin, 0, 0)
			except Exception:
				pass
			return
		if self._backend == 'rpi_gpio' and self._pwm is not None:
			try:
				self._pwm.ChangeDutyCycle(0.0)
			except Exception:
				pass

	def set_continuous(self, freq_hz: float | None):
		"""Enable/disable continuous tone (for scope/measurement).

		- freq_hz=None or <=0: stop output
		- else: set PWM frequency and keep running
		"""
		if not self._enabled or self._backend is None:
			return
		try:
			freq = int(max(0, float(freq_hz or 0.0)))
		except Exception:
			freq = 0
		with self._lock:
			if freq <= 0:
				# Invalidate pending pattern threads and stop immediately.
				self._pattern_token = int(getattr(self, '_pattern_token', 0)) + 1
				self._continuous_on = False
				self._last_freq = 0
				self._stop()
				return
			# avoid needless reprogramming
			if self._continuous_on and self._last_freq == int(freq):
				return
			self._continuous_on = True
			self._last_freq = int(freq)
			self._start(float(freq))

	def stop_now(self):
		"""Hard stop PWM and cancel any pending/active pattern playback."""
		if not self._enabled or self._backend is None:
			return
		with self._lock:
			self._pattern_token = int(getattr(self, '_pattern_token', 0)) + 1
			self._continuous_on = False
			self._last_freq = 0
			self._stop()

	def play_pattern(self, f1: float, f2: float, t_on1: float = 0.150, t_gap: float = 0.050, t_on2: float = 0.150):
		"""Play: ON(f1) -> OFF -> ON(f2). Non-blocking for callers (spawns a daemon thread)."""
		if not self._enabled or self._backend is None:
			return
		# If continuous mode is active, do not interrupt it with patterns.
		try:
			if bool(getattr(self, '_continuous_on', False)):
				return
		except Exception:
			pass
		# Invalidate older pattern requests; only latest should continue.
		with self._lock:
			self._pattern_token = int(getattr(self, '_pattern_token', 0)) + 1
			token = int(self._pattern_token)

		def _run():
			with self._lock:
				try:
					if int(getattr(self, '_pattern_token', 0)) != int(token):
						return
					self._start(f1)
					time.sleep(max(0.0, float(t_on1)))
					if int(getattr(self, '_pattern_token', 0)) != int(token):
						self._stop()
						return
					self._stop()
					time.sleep(max(0.0, float(t_gap)))
					if int(getattr(self, '_pattern_token', 0)) != int(token):
						self._stop()
						return
					self._start(f2)
					time.sleep(max(0.0, float(t_on2)))
					if int(getattr(self, '_pattern_token', 0)) != int(token):
						self._stop()
						return
				finally:
					self._stop()

		threading.Thread(target=_run, daemon=True).start()

# Qt/pyqtgraph bootstrap: enforce PyQt5 first to keep binding consistent
PG_IMPORT_ERR = None
try:
    # Tell pyqtgraph which Qt lib to use
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
    from PyQt5 import QtWidgets, QtCore  # type: ignore
    import pyqtgraph as pg  # type: ignore
except Exception as e1:  # pragma: no cover
    try:
        os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
        from PySide6 import QtWidgets, QtCore  # type: ignore
        import pyqtgraph as pg  # type: ignore
    except Exception:
        PG_IMPORT_ERR = e1


def save_config(desired_profile, desired_freq=None):
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		data = {}
		if os.path.exists(config_file):
			try:
				with open(config_file, "r") as f:
					data = json.load(f) or {}
			except Exception:
				data = {}
		data["desired_profile"] = desired_profile
		if desired_freq is not None:
			data["desired_freq"] = desired_freq
		with open(config_file, "w") as f:
			json.dump(data, f)
	except Exception:
		pass

def load_config():
	"""Load desired_profile from config file. Default=1."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			data = json.load(f) or {}
		val = int(data.get("desired_profile", 1))
		if val not in (1, 2):
			return 1
		return val
	except Exception:
		return 1

def load_freq():
	"""Load desired_freq from config file. Default=200."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			data = json.load(f) or {}
		return int(data.get("desired_freq", 200))
	except Exception:
		return 200

def save_det_params(det_ratio0: float, det_ratio1: float, det_add0: int, det_add1: int):
	"""Save detector params to config file (best-effort merge)."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		data = {}
		if os.path.exists(config_file):
			try:
				with open(config_file, "r") as f:
					data = json.load(f) or {}
			except Exception:
				data = {}
		data["det_ratio0"] = float(det_ratio0)
		data["det_ratio1"] = float(det_ratio1)
		data["det_add0"] = int(det_add0)
		data["det_add1"] = int(det_add1)
		# Backward-compat key (optional): keep det_ratio in sync with ADC1
		data["det_ratio"] = float(det_ratio0)
		with open(config_file, "w") as f:
			json.dump(data, f)
	except Exception:
		pass

def load_det_ratio() -> float:
	"""Load detector ratio from config/env. Default=2.0."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			data = json.load(f) or {}
		if "det_ratio" in data:
			return float(data.get("det_ratio", 2.0))
	except Exception:
		pass
	try:
		return float(os.getenv("BMI30_DETECT_RATIO", "2.0"))
	except Exception:
		return 2.0

def load_det_ratio_pair():
	"""Load detector ratios for ADC1/ADC2. Default=load_det_ratio()."""
	default_ratio = load_det_ratio()
	r0 = default_ratio
	r1 = default_ratio
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			data = json.load(f) or {}
		if "det_ratio0" in data:
			r0 = float(data.get("det_ratio0", r0))
		if "det_ratio1" in data:
			r1 = float(data.get("det_ratio1", r1))
	except Exception:
		pass
	try:
		env0 = os.getenv("BMI30_DETECT_RATIO0")
		if env0 is not None:
			r0 = float(env0)
	except Exception:
		pass
	try:
		env1 = os.getenv("BMI30_DETECT_RATIO1")
		if env1 is not None:
			r1 = float(env1)
	except Exception:
		pass
	return r0, r1

def load_det_add_pair():
	"""Load detector additive offsets for ADC1/ADC2. Default=100."""
	try:
		default_add = int(float(os.getenv("BMI30_DETECT_ADD", "100")))
	except Exception:
		default_add = 100
	a0 = default_add
	a1 = default_add
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			data = json.load(f) or {}
		if "det_add0" in data:
			a0 = int(data.get("det_add0", a0))
		if "det_add1" in data:
			a1 = int(data.get("det_add1", a1))
	except Exception:
		pass
	try:
		env0 = os.getenv("BMI30_DETECT_ADD0")
		if env0 is not None:
			a0 = int(float(env0))
	except Exception:
		pass
	try:
		env1 = os.getenv("BMI30_DETECT_ADD1")
		if env1 is not None:
			a1 = int(float(env1))
	except Exception:
		pass
	return a0, a1

def load_avg_n():
    """Load avg_n from config file (fallback 20)."""
    config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
    try:
        with open(config_file, "r") as f:
            data = json.load(f) or {}
        val = int(data.get("avg_n", 20))
        if val < 2:
            return 20
        return val
    except Exception:
        return 20


def _env_bool(name: str, default: bool = False) -> bool:
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
    config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
    try:
        data = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["avg_n"] = int(avg_n)
        with open(config_file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _load_config_json() -> dict:
	"""Load bmi30_config.json as dict (best-effort)."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		with open(config_file, "r") as f:
			obj = json.load(f) or {}
		if isinstance(obj, dict):
			return obj
	except Exception:
		pass
	return {}


def _save_config_json_merge(patch: dict):
	"""Merge keys into bmi30_config.json (best-effort)."""
	config_file = os.path.join(os.path.dirname(__file__), "bmi30_config.json")
	try:
		data = _load_config_json()
		for k, v in (patch or {}).items():
			data[k] = v
		with open(config_file, "w") as f:
			json.dump(data, f)
	except Exception:
		pass


def load_ui_state() -> dict:
	"""Load persisted GUI-only state from config file."""
	return _load_config_json()


def save_ui_state(**kwargs):
	"""Persist GUI-only state to config file."""
	_save_config_json_merge(kwargs)


def _cfg_bool(value, default: bool = False) -> bool:
	"""Best-effort bool parsing for values loaded from JSON/env."""
	if value is None:
		return bool(default)
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	try:
		return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "t")
	except Exception:
		return bool(default)


# Optional background worker for non-blocking USB mode switches.
# In some builds this class may be absent; keep a placeholder to avoid
# static-analysis errors and safely fall back to synchronous mode switching.
_ModeWorker = None


class ScopeWindow:
	def __init__(self):
		# Logging flags (quiet by default)
		self.debug = _env_bool("BMI30_DEBUG", False)
		self.xcorr_debug = _env_bool("BMI30_XCORR_DEBUG", self.debug)
		self.reader_debug = _env_bool("BMI30_READER_DEBUG", self.debug)
		# Легенда: по умолчанию компактная (без "мусора"); подробная — только по флагу.
		self.legend_verbose = _env_bool("BMI30_LEGEND_VERBOSE", self.debug)
		# Загружаем сохранённое состояние GUI (best-effort)
		self._ui_state = load_ui_state()
		# Автозахват осциллограмм (инициализируем рано для GUI кнопки)
		self._auto_capture_enabled = _cfg_bool(self._ui_state.get('auto_capture_enabled', None), _env_bool('BMI30_AUTO_CAPTURE', False))
		if self.debug:
			print("[INIT] BMI30 GUI starting...", flush=True)
		if PG_IMPORT_ERR:
			print(f"[ERR] pyqtgraph/Qt import failed: {PG_IMPORT_ERR}")
			sys.exit(2)
		self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
		self.win = QtWidgets.QMainWindow()
		self.win.setWindowTitle("BMI30 Vendor Bulk Oscilloscope - Thread Mode")
		if self.debug:
			print("[INIT] Window created", flush=True)
		central = QtWidgets.QWidget()
		self.win.setCentralWidget(central)
		layout = QtWidgets.QVBoxLayout(central)
		# Загружаем desired_profile из config
		self.desired_profile = load_config()
		# Загружаем частоту из конфига
		self.desired_freq = load_freq()
		# По умолчанию — DC-вычитание не применяется в GUI (встроено в устройство)
		self.dc_removal_enabled = False
		# Переключатель нормализации XCorr (привязан к кнопке "звук")
		# True  -> авто-масштаб/центрированный продукт (текущая логика)
		# False -> фиксированная шкала 0..65535 для просмотра слабых сигналов
		self.xcorr_norm_enabled = _cfg_bool(self._ui_state.get('xcorr_norm_enabled', None), False)
		# ADC commutation mode: 0=оба, 1=только ADC1, 2=только ADC2
		try:
			self.adc_comm_mode = int(self._ui_state.get('adc_comm_mode', os.getenv("BMI30_ADC_COMM_MODE", "0")))
		except Exception:
			self.adc_comm_mode = 0
		try:
			if self.adc_comm_mode not in (0, 1, 2):
				self.adc_comm_mode = 0
		except Exception:
			self.adc_comm_mode = 0
		# legend (вместо верхних кнопок)
		self.legend_lbl = QtWidgets.QLabel("--")
		font = self.legend_lbl.font()
		font.setPointSize(font.pointSize()+1)
		self.legend_lbl.setFont(font)
		# ВАЖНО: wordWrap=True, иначе QLabel может задрать minimum width и раздувать окно.
		try:
			self.legend_lbl.setWordWrap(True)
		except Exception:
			pass
		# Минимизируем влияние длинного текста на минимальную ширину окна
		try:
			sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
			sp.setHorizontalStretch(1)
			self.legend_lbl.setSizePolicy(sp)
			self.legend_lbl.setMinimumWidth(0)
		except Exception:
			pass
		self._last_full_status: str = ""
		# legend_lbl остаётся основным статусным лейблом; цветные метки 1/0
		# отображаются в заголовках каждого графика (локально), поэтому
		# не создаём глобальный mapping-widget в легенде.
		legend_bar = QtWidgets.QHBoxLayout()
		legend_bar.addWidget(self.legend_lbl, 1)
		# no global mapping widget - per-plot colored titles are used
		# выбор количества усреднённых буферов (avg_n)
		self.avg_n = load_avg_n()  # Load avg_n from config file
		self.avg_box = QtWidgets.QComboBox()
		avg_items = ["8","16","24","32","40","48","56","64"]
		self.avg_box.addItems(avg_items)
		# Не триггерить обработчик при установке значения по умолчанию
		try:
			self.avg_box.blockSignals(True)
		except Exception:
			pass
		# установим индекс на текущее значение avg_n
		try:
			if str(self.avg_n) in avg_items:
				self.avg_box.setCurrentIndex(avg_items.index(str(self.avg_n)))
			else:
				# если значение не в списке, добавим его и выберем
				self.avg_box.addItem(str(self.avg_n))
				self.avg_box.setCurrentIndex(self.avg_box.count()-1)
		except Exception:
			pass
		try:
			self.avg_box.blockSignals(False)
		except Exception:
			pass
		self.avg_box.currentIndexChanged.connect(self._on_avg_change)
		
		# Выбор частоты буферов
		self.freq_box = QtWidgets.QComboBox()
		self.freq_box.addItems(["200 Hz", "204 Hz", "205 Hz", "208 Hz", "210 Hz", "220 Hz", "225 Hz", "240 Hz", "250 Hz"])
		# Блокируем сигналы при установке начального значения
		try:
			self.freq_box.blockSignals(True)
		except Exception:
			pass
		# Устанавливаем загруженную частоту
		self.freq_box.setCurrentText(f"{self.desired_freq} Hz")
		try:
			self.freq_box.blockSignals(False)
		except Exception:
			pass
		self.freq_box.setToolTip("Частота следования буферов")
		self.freq_box.currentTextChanged.connect(self._on_freq_change)
		
		# Тип метки (3 позиции: Б/М/С) — заглушка, полная логика будет добавлена позже
		try:
			self._mark_type_mode = int(self._ui_state.get('mark_type_mode', os.getenv('BMI30_MARK_TYPE_MODE', '2')))
		except Exception:
			self._mark_type_mode = 2
		try:
			if self._mark_type_mode not in (0, 1, 2):
				self._mark_type_mode = 2
		except Exception:
			self._mark_type_mode = 2
		self.btn_mark_type = QtWidgets.QPushButton(["Б", "М", "С"][self._mark_type_mode])
		self.btn_mark_type.setToolTip("Тип метки: Б/М/С")
		try:
			self.btn_mark_type.setFixedSize(32, 21)
		except Exception:
			pass
		self.btn_mark_type.clicked.connect(self._cycle_mark_type)
		
		# Количество детектирования (позиции: 1..6)
		try:
			self._det_count = int(self._ui_state.get('det_count', os.getenv('BMI30_DET_COUNT', '1')))
		except Exception:
			self._det_count = 1
		try:
			if self._det_count not in (1, 2, 3, 4, 5, 6):
				self._det_count = 1
		except Exception:
			self._det_count = 1
		self.btn_det_count = QtWidgets.QPushButton(str(self._det_count))
		self.btn_det_count.setToolTip("Количество детектирования подряд: 1..6")
		try:
			self.btn_det_count.setFixedSize(32, 21)
		except Exception:
			pass
		self.btn_det_count.clicked.connect(self._cycle_det_count)
		
		# Коэффициенты срабатывания (det_ratio) и добавочный порог (det_add) по ADC
		add_values = [str(v) for v in range(0, 701, 100)]
		self.det_ratio_box0 = QtWidgets.QComboBox()
		self.det_ratio_box1 = QtWidgets.QComboBox()
		self.det_add_box0 = QtWidgets.QComboBox()
		self.det_add_box1 = QtWidgets.QComboBox()
		for _box in (self.det_add_box0, self.det_add_box1):
			_box.addItems(add_values)
		# Блокируем сигналы при установке начальных значений
		try:
			self.det_ratio_box0.blockSignals(True)
			self.det_ratio_box1.blockSignals(True)
			self.det_add_box0.blockSignals(True)
			self.det_add_box1.blockSignals(True)
		except Exception:
			pass
		# Заполним коэффициенты с учетом типа метки
		self._refresh_det_ratio_options()
		try:
			cur_add0 = int(getattr(self, '_det_add0', 100))
		except Exception:
			cur_add0 = 100
		try:
			cur_add1 = int(getattr(self, '_det_add1', 100))
		except Exception:
			cur_add1 = 100
		cur_add0 = max(0, min(700, int(round(cur_add0 / 100.0) * 100)))
		cur_add1 = max(0, min(700, int(round(cur_add1 / 100.0) * 100)))
		self.det_add_box0.setCurrentText(str(cur_add0))
		self.det_add_box1.setCurrentText(str(cur_add1))
		try:
			self.det_ratio_box0.blockSignals(False)
			self.det_ratio_box1.blockSignals(False)
			self.det_add_box0.blockSignals(False)
			self.det_add_box1.blockSignals(False)
		except Exception:
			pass
		# Подсказки для коэффициентов задаются в _refresh_det_ratio_options()
		self.det_add_box0.setToolTip("ADC1: добавочный порог (100–700)")
		self.det_add_box1.setToolTip("ADC2: добавочный порог (100–700)")
		self.det_ratio_box0.currentTextChanged.connect(lambda text, ch=0: self._on_det_ratio_change(text, ch))
		self.det_ratio_box1.currentTextChanged.connect(lambda text, ch=1: self._on_det_ratio_change(text, ch))
		self.det_add_box0.currentTextChanged.connect(lambda text, ch=0: self._on_det_add_change(text, ch))
		self.det_add_box1.currentTextChanged.connect(lambda text, ch=1: self._on_det_add_change(text, ch))
		
		self.btn_reconnect = QtWidgets.QPushButton("↻")
		self.btn_reconnect.setToolTip("Ручное переподключение к устройству")
		self.btn_reconnect.clicked.connect(self._manual_reconnect)
		# уменьшить ширину трёх правых кнопок вдвое
		for _btn in (self.btn_reconnect,):
			try:
				_btn.setFixedSize(21, 21)
			except Exception:
				pass
		# Кнопка перезапитки USB-порта (через uhubctl)
		self.btn_power = QtWidgets.QPushButton("⚡")
		self.btn_power.setToolTip("Сбросить адаптацию порога (ускорить стартовую подстройку)")
		self.btn_power.clicked.connect(self._reset_det_adapt)
		try:
			self.btn_power.setFixedSize(21, 21)
		except Exception:
			pass
		# правый клик по кнопке питания копирует заголовок в буфер обмена
		try:
			self.btn_power.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
			self.btn_power.customContextMenuRequested.connect(self._copy_legend_from_btn)
		except Exception:
			pass
		# Кнопка автозахвата осциллограмм
		self.btn_capture = QtWidgets.QPushButton("⏺")
		self.btn_capture.setToolTip("Автозахват осциллограмм при срабатывании детектора")
		self.btn_capture.setCheckable(True)
		self.btn_capture.setChecked(self._auto_capture_enabled)
		self.btn_capture.clicked.connect(self._toggle_capture)
		try:
			self.btn_capture.setFixedSize(21, 21)
		except Exception:
			pass
		self._update_capture_btn_style()
		# Кнопка переключения метки (3 состояния: неизвестно / с меткой / без метки)
		self.btn_label = QtWidgets.QPushButton("?")
		self.btn_label.setToolTip("Метка сигнала: ? = неизвестно, ✓ = с меткой, ✗ = без метки")
		self.btn_label.clicked.connect(self._cycle_label_state)
		try:
			self.btn_label.setFixedSize(21, 21)
		except Exception:
			pass
		self._update_label_btn_style()
		# Кнопка-индикатор состояния GPIO23 (без влияния на детекцию)
		self.btn_det_gate = QtWidgets.QPushButton("G")
		self.btn_det_gate.setToolTip("GPIO23: индикатор состояния бита")
		self.btn_det_gate.clicked.connect(self._toggle_det_gate_gpio23)
		try:
			self.btn_det_gate.setFixedSize(21, 21)
		except Exception:
			pass
		try:
			self._init_det_gate_gpio23_input()
		except Exception:
			pass
		self._poll_det_gate_gpio23(force=True)
		self._update_det_gate_btn_style()
		# Кнопка диагностики и мягкого рестарта
		# Диагностика: делаем кнопку переключаемой и используем её для
		# включения/выключения DC-вычитания (фиксация состояния).
		self.btn_diag = QtWidgets.QPushButton("🩺")
		self.btn_diag.setToolTip("XCorr: нормализация/автомасштаб (кнопка звука)")
		self.btn_diag.setCheckable(True)
		# отобразим текущее состояние нормализации XCorr
		try:
			self.btn_diag.setChecked(bool(self.xcorr_norm_enabled))
		except Exception:
			pass
		self.btn_diag.toggled.connect(self._on_toggle_xcorr_norm)
		try:
			self.btn_diag.setFixedSize(21, 21)
		except Exception:
			pass
		# синхронизируем визуальный вид кнопки с текущим состоянием
		try:
			self._on_toggle_xcorr_norm(bool(self.xcorr_norm_enabled))
		except Exception:
			pass
		# Кнопка принудительного включения PWM (GPIO12) для проверки выхода ("динамик").
		# Не зависит от детекции. По умолчанию выключена.
		self.btn_pwm = QtWidgets.QPushButton("♪")
		self.btn_pwm.setToolTip("PWM: работа / принудительно ВКЛ / принудительно ВЫКЛ")
		try:
			self.btn_pwm.setFixedSize(21, 21)
		except Exception:
			pass
		# 3 состояния PWM: 0=работа, 1=принудительно ВКЛ, -1=принудительно ВЫКЛ
		self._beep_force_mode = 0
		self._update_pwm_btn_style()
		self.btn_pwm.clicked.connect(self._on_toggle_force_pwm)
		# Кнопка коммутации ADC (1/2/оба)
		self.btn_sync = QtWidgets.QPushButton("")
		self.btn_sync.setToolTip("ADC: 1/2/1+2")
		try:
			self.btn_sync.setFixedSize(32, 21)
		except Exception:
			pass
		# Inline labels for per-letter sizing (avoid HTML rendering issues)
		try:
			self._btn_sync_m = QtWidgets.QLabel("1")
			self._btn_sync_slash = QtWidgets.QLabel("/")
			self._btn_sync_s = QtWidgets.QLabel("2")
			for _lb in (self._btn_sync_m, self._btn_sync_slash, self._btn_sync_s):
				try:
					_lb.setAlignment(QtCore.Qt.AlignCenter)
					_lb.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
				except Exception:
					pass
			_inner = QtWidgets.QHBoxLayout(self.btn_sync)
			_inner.setContentsMargins(0, 0, 0, 0)
			_inner.setSpacing(0)
			_inner.addWidget(self._btn_sync_m)
			_inner.addWidget(self._btn_sync_slash)
			_inner.addWidget(self._btn_sync_s)
		except Exception:
			self._btn_sync_m = None
			self._btn_sync_slash = None
			self._btn_sync_s = None
		self.btn_sync.clicked.connect(self._cycle_sync_mode)
		self._update_sync_btn_style()
		# Кнопка передачи (TIM2 enable)
		self.tim2_enabled = _cfg_bool(self._ui_state.get('tim2_enabled', None), str(os.getenv("BMI30_TIM2_ENABLE", "1")).lower() not in ("0", "false", "no"))
		self.btn_tim2 = QtWidgets.QPushButton("TX")
		self.btn_tim2.setToolTip("Передача TIM2: ВКЛ/ВЫКЛ")
		self.btn_tim2.setCheckable(True)
		try:
			self.btn_tim2.setChecked(bool(self.tim2_enabled))
		except Exception:
			pass
		try:
			self.btn_tim2.setFixedSize(28, 21)
		except Exception:
			pass
		self.btn_tim2.toggled.connect(self._on_toggle_tim2)
		self._update_tim2_btn_style()
		
		# --- Компоновка кнопок/переключателей в 2 ряда, прижато вправо ---
		ctrl_box = QtWidgets.QWidget()
		ctrl_v = QtWidgets.QVBoxLayout(ctrl_box)
		ctrl_v.setContentsMargins(0, 0, 0, 0)
		ctrl_v.setSpacing(2)
		top_row = QtWidgets.QHBoxLayout()
		top_row.setContentsMargins(0, 0, 0, 0)
		top_row.setSpacing(4)
		bot_row = QtWidgets.QHBoxLayout()
		bot_row.setContentsMargins(0, 0, 0, 0)
		bot_row.setSpacing(4)
		# прижать содержимое рядов к правому краю
		top_row.addStretch(1)
		bot_row.addStretch(1)
		# Порядок задан пользователем справа→налево; здесь добавляем слева→направо
		# Верхний ряд: Тип метки, Частота, ADC1 коэффициент, ADC1 добавочный,
		#             Ручное переподключение, Автозахват, Нормализация, TX
		top_row.addWidget(self.btn_mark_type, 0)
		top_row.addWidget(self.freq_box, 0)
		top_row.addWidget(self.det_ratio_box0, 0)
		top_row.addWidget(self.det_add_box0, 0)
		top_row.addWidget(self.btn_reconnect, 0)
		top_row.addWidget(self.btn_capture, 0)
		top_row.addWidget(self.btn_diag, 0)
		top_row.addWidget(self.btn_tim2, 0)
		# Нижний ряд: Кол-во детектирования, Кол-во буферов среднего, ADC2 коэффициент,
		#             ADC2 добавочный, Сброс адаптации, Метка сигнала, G23, Нотка, 1/2
		bot_row.addWidget(self.btn_det_count, 0)
		bot_row.addWidget(self.avg_box, 0)
		bot_row.addWidget(self.det_ratio_box1, 0)
		bot_row.addWidget(self.det_add_box1, 0)
		bot_row.addWidget(self.btn_power, 0)
		bot_row.addWidget(self.btn_label, 0)
		bot_row.addWidget(self.btn_det_gate, 0)
		bot_row.addWidget(self.btn_pwm, 0)
		bot_row.addWidget(self.btn_sync, 0)
		ctrl_v.addLayout(top_row)
		ctrl_v.addLayout(bot_row)
		legend_bar.addWidget(ctrl_box, 0)
		layout.addLayout(legend_bar)
		# plots
		self.plotw = pg.GraphicsLayoutWidget()
		layout.addWidget(self.plotw, 1)
		self.p0 = self.plotw.addPlot(row=0, col=0)
		# set colored title mapping for ADC1: 1 / 0
		try:
			self.p0.setTitle("<span style='font-weight:bold; font-size:12pt; color:#ffb86b'>ADC1 1</span> / <span style='font-weight:bold; font-size:12pt; color:#00e5ff'>0</span>")
		except Exception:
			try:
				self.p0.setTitle("ADC1 (1/0)")
			except Exception:
				pass
		self.p1 = self.plotw.addPlot(row=1, col=0)
		# set colored title mapping for ADC2: 1 / 0
		try:
			self.p1.setTitle("<span style='font-weight:bold; font-size:12pt; color:#ff6b6b'>ADC2 1</span> / <span style='font-weight:bold; font-size:12pt; color:#00ffd5'>0</span>")
		except Exception:
			try:
				self.p1.setTitle("ADC2 (1/0)")
			except Exception:
				pass
		# Use fast line plots instead of many symbols to reduce CPU and increase FPS
		# Two packets per channel => draw even/odd oscillograms per plot (different colors)
		# ADC0: более контрастные цвета для тёмной темы
		self.curve0_a = self.p0.plot(pen=pg.mkPen('#ffb86b', width=1.5), symbol=None)  # even (яркий оранжевый)
		self.curve0_b = self.p0.plot(pen=pg.mkPen('#00e5ff', width=1.5), symbol=None)  # odd (яркий циановый)
		# ADC1: повышенная яркость для лучшей видимости на тёмной теме
		self.curve1_a = self.p1.plot(pen=pg.mkPen('#ff6b6b', width=1.5), symbol=None)  # even (яркий красный)
		self.curve1_b = self.p1.plot(pen=pg.mkPen('#00ffd5', width=1.5), symbol=None)  # odd (яркий мятный)
		# Корреляционные кривые — отображать в отдельном ViewBox справа (масштаб вокруг нуля)
		try:
			# create right-side viewbox for corr on p0
			self.p0.showAxis('right')
			self.vb_corr0 = pg.ViewBox()
			self.p0.scene().addItem(self.vb_corr0)
			self.p0.getAxis('right').linkToView(self.vb_corr0)
			self.vb_corr0.setXLink(self.p0)
			# create plot item inside that viewbox
			self.corr0 = pg.PlotDataItem(pen=pg.mkPen('#ffff00', width=1.2), symbol=None)
			self.vb_corr0.addItem(self.corr0)
			# keep right viewbox geometry in sync
			def _update_vb_corr0():
				self.vb_corr0.setGeometry(self.p0.getViewBox().sceneBoundingRect())
			self.p0.getViewBox().sigResized.connect(_update_vb_corr0)

			# create right-side viewbox for corr on p1
			self.p1.showAxis('right')
			self.vb_corr1 = pg.ViewBox()
			self.p1.scene().addItem(self.vb_corr1)
			self.p1.getAxis('right').linkToView(self.vb_corr1)
			self.vb_corr1.setXLink(self.p1)
			self.corr1 = pg.PlotDataItem(pen=pg.mkPen('#00ff00', width=1.2), symbol=None)
			self.vb_corr1.addItem(self.corr1)
			def _update_vb_corr1():
				self.vb_corr1.setGeometry(self.p1.getViewBox().sceneBoundingRect())
			self.p1.getViewBox().sigResized.connect(_update_vb_corr1)

			# hide correlation curves by default
			self.corr0.setVisible(False)
			self.corr1.setVisible(False)
		except Exception:
			# fallback to simple plots if ViewBox API unavailable
			self.corr0 = self.p0.plot(pen=pg.mkPen('#ffff00', width=1.2), symbol=None)
			self.corr1 = self.p1.plot(pen=pg.mkPen('#00ff00', width=1.2), symbol=None)
			try:
				self.corr0.setVisible(False)
				self.corr1.setVisible(False)
			except Exception:
				pass

		self.p0.showGrid(x=True, y=True, alpha=0.3)
		self.p1.showGrid(x=True, y=True, alpha=0.3)
		# Синхронизируем X-оси между графиками
		try:
			self.p1.setXLink(self.p0)
		except Exception:
			pass
		# отключим авто-растягивание по X (будем сами задавать диапазон)
		self.p0.disableAutoRange(axis=pg.ViewBox.XAxis)
		self.p1.disableAutoRange(axis=pg.ViewBox.XAxis)
		self.p0.enableAutoRange(y=True)
		self.p1.enableAutoRange(y=True)
		# Обновлённые размеры кадров: профиль 1 ~1360 семплов, профиль 2 ~912
		# Не полагаемся на жёсткие размеры: устройство авто-фиксирует total_samples по первому рабочему кадру.
		# Эти значения используются только как "подсказка"/резерв.
		self.expected_len_map = {1: 912, 2: 912}
		self.initial_expected = self.expected_len_map.get(1, 912)
		# Рекомендуемые FRAME_SAMPLES для стабильных ~20 FPS (используем фактические длины кадров)
		self.ns_map = {1: 912, 2: 912}
		# По умолчанию не навязываем Ns устройству (макс. FPS). Включить подсказку Ns: BMI30_SEND_NS=1
		try:
			# Важно: SET_FRAME_SAMPLES ломает профиль 1, поэтому по умолчанию НЕ отправляем.
			self.send_ns = str(os.getenv("BMI30_SEND_NS", "0")).lower() not in ("0","false","no")
		except Exception:
			self.send_ns = True
		# Тестовые кадры как данные выключены по умолчанию (включить: BMI30_TEST_AS_DATA=1)
		try:
			self.test_as_data = str(os.getenv("BMI30_TEST_AS_DATA", "0")).lower() not in ("0","false","no")
		except Exception:
			self.test_as_data = False
		# Показывать ли нулевые сигналы (по умолчанию ВКЛЮЧЕНО, чтобы видеть семплы "как есть")
		try:
			self.show_zero = str(os.getenv("BMI30_SHOW_ZERO", "1")).lower() not in ("0","false","no")
		except Exception:
			self.show_zero = True
		# Управление шкалой Y: по умолчанию авто-ПОДСТРОЙКА ВЫКЛЮЧЕНА — фиксируем диапазон
		try:
			self.y_auto = str(os.getenv("BMI30_Y_AUTO", "0")).lower() not in ("0","false","no")
		except Exception:
			self.y_auto = False
		try:
			self.y_min = float(os.getenv("BMI30_Y_MIN", "0"))
		except Exception:
			self.y_min = 0.0
		try:
			self.y_max = float(os.getenv("BMI30_Y_MAX", "65535"))
		except Exception:
			self.y_max = 65535.0
		# Применим параметры Y сразу
		try:
			self.p0.enableAutoRange(y=self.y_auto)
			self.p1.enableAutoRange(y=self.y_auto)
			if not self.y_auto:
				self.p0.setYRange(self.y_min, self.y_max, padding=0.02)
				self.p1.setYRange(self.y_min, self.y_max, padding=0.02)
		except Exception:
			pass
		# plots идут здесь, нижние элементы добавим после
		# data - shared buffers между reader thread и GUI thread
		self.base_buf_len: int | None = None  # будет 1200 (или иное) после первого кадра
		self.base_buf_len_bytes: int | None = None
		self.freq_hz: int | None = None
		self.ring_factor = 1  # фиксированный один буфер (последний кадр)
		# Shared buffers для двух каналов - инициализируем сразу с максимальным размером
		# Резерв под максимальный буфер (не жёстко завязан на профиль)
		self.max_samples = 2048
		# saved best per-sample product arrays and peaks (persist until larger peak found)
		self._xcorr_saved_prod0 = np.zeros(self.max_samples, dtype=np.float64)
		self._xcorr_saved_prod1 = np.zeros(self.max_samples, dtype=np.float64)
		self._xcorr_saved_peak0 = 0.0
		self._xcorr_saved_peak1 = 0.0
		# Two buffers per channel: even/odd packets keyed by seq&1
		self.data0 = np.zeros(self.max_samples, dtype=np.int32)  # совместимость (используем как even)
		self.data1 = np.zeros(self.max_samples, dtype=np.int32)  # совместимость (используем как even)
		self.data0_even = self.data0
		self.data0_odd = np.zeros(self.max_samples, dtype=np.int32)
		self.data1_even = self.data1
		self.data1_odd = np.zeros(self.max_samples, dtype=np.int32)
		# phase diagnostics (even/odd should be same magnitude, opposite phase)
		self.seq0_even = None
		self.seq0_odd = None
		self.seq1_even = None
		self.seq1_odd = None
		
		# Отслеживание текущего STREAM_MODE
		self.stream_mode = 0  # 0 = LATEST (600 семплов, last-buffer-wins), 1 = LOSSLESS_ROI (200 семплов, FIFO)
		
		# DC offset removal: адаптивная коррекция DC по каждому семплу (накопление при STREAM_MODE=1)
		self.dc_removal_enabled = False  # Флаг: применять ли DC removal (вычитание)
		# Усреднение осциллограмм (последние N кадров) поверх DC removal
		self.avg20_enabled = False
		self.avg20_nframes = 20
		# Кольцевые буферы усреднения: 2 канала × even/odd
		self._avg0_even = np.zeros((self.avg20_nframes, self.max_samples), dtype=np.float32)
		self._avg0_odd = np.zeros((self.avg20_nframes, self.max_samples), dtype=np.float32)
		self._avg1_even = np.zeros((self.avg20_nframes, self.max_samples), dtype=np.float32)
		self._avg1_odd = np.zeros((self.avg20_nframes, self.max_samples), dtype=np.float32)
		self._avg0_even_pos = 0
		self._avg0_odd_pos = 0
		self._avg1_even_pos = 0
		self._avg1_odd_pos = 0
		self._avg0_even_cnt = 0
		self._avg0_odd_cnt = 0
		self._avg1_even_cnt = 0
		self._avg1_odd_cnt = 0
		# Массивы DC offset для каждого семпла (инициализируем нулями, будут обновляться адаптивно)
		self.dc_offset_ch0_even = np.zeros(self.max_samples, dtype=np.float32)
		self.dc_offset_ch0_odd = np.zeros(self.max_samples, dtype=np.float32)
		self.dc_offset_ch1_even = np.zeros(self.max_samples, dtype=np.float32)
		self.dc_offset_ch1_odd = np.zeros(self.max_samples, dtype=np.float32)
		self.dc_last_save = time.time()  # Время последнего сохранения DC offset в файл
		try:
			self.dc_save_interval = float(os.getenv('BMI30_DC_SAVE_INTERVAL', '600'))
		except Exception:
			self.dc_save_interval = 600.0
		# Основной файл (по умолчанию рядом со скриптом), можно переопределить через BMI30_DC_FILE
		self.dc_save_file = os.getenv('BMI30_DC_FILE', os.path.join(os.path.dirname(__file__), 'dc_offset_samples.npz'))
		self.dc_save_file_bak = self.dc_save_file + '.bak'
		try:
			self.dc_update_step = float(os.getenv('BMI30_DC_UPDATE_STEP', '1.0'))
		except Exception:
			self.dc_update_step = 1.0
		# В каких STREAM_MODE учим DC (1=LOSSLESS_ROI, 2=AVG_ROI). По умолчанию: 1,2.
		# Disable host-side DC adaptation: device performs DC compensation.
		# Keep empty set to avoid any adaptive updates or host DC logic.
		try:
			self.dc_adapt_modes = set()
		except Exception:
			self.dc_adapt_modes = set()
		# DC компенсация встроена в устройство — не загружаем локальные офсеты
		# (раньше вызывали self._load_dc_offset())
		
		# How to split packets into two phases (even/odd).
		# Firmware may encode phase in seq LSB, timestamp LSB, or reserved fields.
		try:
			# IMPORTANT: On RPi we must split even/odd strictly by reserved2&1.
			# (Do NOT use seq&1 or timestamp&1; those can drift or be reused by firmware.)
			requested = str(os.getenv('BMI30_PHASE_KEY', 'reserved2')).strip().lower()
			allow_legacy = str(os.getenv('BMI30_PHASE_ALLOW_LEGACY', '0')).lower() not in ('0','false','no')
			# Normalize common aliases
			if requested in ('r2', 'reserved2_lsb', 'reserved2&1'):
				requested = 'reserved2'
			if (requested not in ('reserved2',)) and not allow_legacy:
				if bool(getattr(self, 'debug', False)):
					print(f"[PHASE_KEY] forcing reserved2&1 (ignoring BMI30_PHASE_KEY={requested}); set BMI30_PHASE_ALLOW_LEGACY=1 to override", flush=True)
				requested = 'reserved2'
			self.phase_key = requested
			if bool(getattr(self, 'debug', False)):
				print(f"[PHASE_KEY] using {self.phase_key}&1", flush=True)
		except Exception:
			self.phase_key = 'reserved2'
			try:
				if bool(getattr(self, 'debug', False)):
					print(f"[PHASE_KEY] using {self.phase_key}&1", flush=True)
			except Exception:
				pass
		self._phase_key_chosen = None
		self._phase_key_stats = {}
		self._phase_key_seen = 0
		# Stable per-channel phase togglers (used when phase_key=='toggle')
		self._phase_last_seq_a = None
		self._phase_last_seq_b = None
		self._phase_last_ts_a = None
		self._phase_last_ts_b = None
		self._phase_toggle_a = 0
		self._phase_toggle_b = 0
		self._phase_last_par_a = None
		self._phase_last_par_b = None
		self._phase_repeat_a = 0
		self._phase_repeat_b = 0
		self._phase_trace_n = 0
		try:
			self.phase_trace = str(os.getenv('BMI30_PHASE_TRACE', '0')).lower() not in ('0','false','no')
		except Exception:
			self.phase_trace = False
		try:
			self.phase_trace_limit = int(os.getenv('BMI30_PHASE_TRACE_LIMIT', '400'))
		except Exception:
			self.phase_trace_limit = 400
		try:
			self.phase_diag = str(os.getenv('BMI30_PHASE_DIAG', '0')).lower() not in ('0','false','no')
		except Exception:
			self.phase_diag = False
		try:
			self.phase_diag_every = int(os.getenv('BMI30_PHASE_DIAG_EVERY', '50'))
		except Exception:
			self.phase_diag_every = 50
		try:
			self.phase_diag_maxlag = int(os.getenv('BMI30_PHASE_DIAG_MAXLAG', '20'))
		except Exception:
			self.phase_diag_maxlag = 20
		self._phase_diag_frames = 0
		self.timestamps = np.zeros(self.max_samples, dtype=np.float64)
		# Re-entrant: reader thread may call helpers that also need data_lock.
		# (Avoids deadlock when phase-search is enabled and triggered from inside the reader's locked section.)
		self.data_lock = threading.RLock()  # защита shared buffers
		self.reader_thread = None
		self.reader_running = False
		# USB error tracking for auto-recovery
		self._usb_err_count = 0
		self._usb_err_last_t = 0.0
		self._usb_err_need_hw_reset = False
		# One-time hardware reset on startup (optional)
		self._hw_reset_on_start_done = False
		# Flag set by reader when new data copied; polled in GUI tick to trigger xcorr compute
		self._need_xcorr = False
		# Флаг для немедленного детектирования при получении новых пакетов
		self._need_detect = False
		# Optimal phase shift computation results (global variables for next task)
		# ADC0 results
		self._phase_shift_adc0 = 0  # optimal phase shift in samples for ADC0
		self._phase_peak_idx_adc0 = 0  # sample index of maximum in optimal product array for ADC0
		self._phase_max_sum_adc0 = 0.0  # maximum sum of products for ADC0
		self._phase_prod_adc0 = None  # optimal product array for ADC0 (N samples)
		# ADC1 results
		self._phase_shift_adc1 = 0  # optimal phase shift in samples for ADC1
		self._phase_peak_idx_adc1 = 0  # sample index of maximum in optimal product array for ADC1
		self._phase_max_sum_adc1 = 0.0  # maximum sum of products for ADC1
		self._phase_prod_adc1 = None  # optimal product array for ADC1 (N samples)
		# Phase shift search thread state
		self._phase_search_thread = None
		self._phase_search_running = False
		self._phase_search_event = threading.Event()
		self._phase_search_req_lock = threading.Lock()
		self._phase_search_latest = None  # (N, e0, o0, e1, o1)
		self._phase_search_stop = False
		# Run phase-shift search only in GUI modes 6+ (set in _num_clicked).
		# This flag is read from the USB reader thread; do NOT access Qt widgets there.
		self._phase_search_enabled = False
		# By default compute phase shift after every new packet (user requirement).
		# Can be disabled via env to save CPU.
		try:
			self.phase_search_each_packet = str(os.getenv('BMI30_PHASE_SEARCH_EACH_PACKET', '1')).lower() not in ('0', 'false', 'no')
		except Exception:
			self.phase_search_each_packet = True
		# Optional performance knob: limit maximum absolute shift scanned.
		# 0 => full range (-(N-1)..(N-1)). Default=50 to reduce workload.
		try:
			self.phase_search_max_shift = int(os.getenv('BMI30_PHASE_MAX_SHIFT', '50'))
		except Exception:
			self.phase_search_max_shift = 50
		# Инициализируем view параметры сразу чтобы показывать данные
		self.view_start = 0
		self.view_len = self.max_samples
		try:
			self.initial_view_mult = float(os.getenv("BMI30_INITIAL_VIEW_MULT", "0.25"))  # сколько буферов показывать изначально (0.25 для ~340 семплов, но для осциллографа - последние)
		except Exception:
			self.initial_view_mult = 0.25
		# Диагностику остановки выводим в консоль (а не в GUI) по умолчанию
		self.diag_to_console = str(os.getenv("BMI30_DIAG_TO_CONSOLE", "1")).lower() not in ("0","false","no")
		# Всегда показываем полный кадр (start=0, len=buf)
		self.lock_full_view = True
		# По умолчанию не инвертируем сигнал в GUI (включить старую инверсию можно через BMI30_INVERT=1)
		self.no_invert = str(os.getenv("BMI30_INVERT", "0")).lower() in ("0","false","no")
		# Отладочные маркеры: каждые 100-й семпл отмечаем линейкой [-30000..30000] для проверки целостности буфера
		try:
			self.debug_markers = str(os.getenv("BMI30_DEBUG_MARKERS", "0")).lower() not in ("0","false","no")
		except Exception:
			self.debug_markers = False
		# Режим независимых каналов: по умолчанию ВКЛЮЧЕН — прошивка может вести независимые seq для A/B.
		try:
			self.independent_channels = str(os.getenv('BMI30_INDEPENDENT_CHANNELS', '1')).lower() not in ('0','false','no')
		except Exception:
			self.independent_channels = False
		# Диагностика размеров кадров: включить лог seq/lenA/lenB через BMI30_LOG_FRAME_LEN=1
		try:
			self.log_frame_len = str(os.getenv('BMI30_LOG_FRAME_LEN', '0')).lower() not in ('0','false','no')
		except Exception:
			self.log_frame_len = False
		try:
			self.log_frame_len_limit = int(os.getenv('BMI30_LOG_FRAME_LEN_LIMIT', '200'))
		except Exception:
			self.log_frame_len_limit = 200
		self._log_frame_len_count = 0
		# Трассировка содержимого по блокам (каждые 100 семплов): BMI30_CHUNK_TRACE=1, лимит кадров BMI30_CHUNK_TRACE_LIMIT
		try:
			self.chunk_trace = str(os.getenv('BMI30_CHUNK_TRACE', '0')).lower() not in ('0','false','no')
		except Exception:
			self.chunk_trace = False
		try:
			self.chunk_trace_limit = int(os.getenv('BMI30_CHUNK_TRACE_LIMIT', '50'))
		except Exception:
			self.chunk_trace_limit = 50
		self._chunk_trace_count = 0
		# Явная инициализация по последовательности разработчика (STOP→FULL→PROFILE→CHMODE→ASYNC→BLOCK_HZ→START)
		try:
			self.apply_init_sequence = str(os.getenv('BMI30_INIT_SEQUENCE', '1')).lower() not in ('0','false','no')
		except Exception:
			self.apply_init_sequence = True
		try:
			self.block_hz = int(os.getenv('BMI30_BLOCK_HZ', '200'))
		except Exception:
			self.block_hz = 200
		# Мониторинг конкретного семпла для ловли редких сбоев: BMI30_MON_SAMPLE=1, индекс BMI30_MON_INDEX (по умолчанию 300)
		try:
			self.monitor_sample = str(os.getenv('BMI30_MON_SAMPLE', '0')).lower() not in ('0','false','no')
		except Exception:
			self.monitor_sample = False
		try:
			self.monitor_index = int(os.getenv('BMI30_MON_INDEX', '300'))
		except Exception:
			self.monitor_index = 300
		self._last_mon_a = None
		self._last_mon_b = None
		# Опционально: срезать хвост внутренней очереди ассемблера (независимые каналы) чтобы не было лага
		try:
			self.flush_asm_queue = str(os.getenv('BMI30_FLUSH_ASM_QUEUE', '1')).lower() not in ('0','false','no')
		except Exception:
			self.flush_asm_queue = False
		# Capture diagnostic mode: write a short capture file when the first mismatch occurs
		try:
			cap_env = os.getenv('BMI30_CAPTURE_DIAG', None)
			if cap_env is None:
				self.capture_diag_path = None
			elif isinstance(cap_env, str) and cap_env.strip() == '1':
				self.capture_diag_path = os.path.join('/tmp', f'bmi30_capture_{int(time.time())}.log')
			else:
				self.capture_diag_path = cap_env
		except Exception:
			self.capture_diag_path = None
		try:
			self.capture_diag_seconds = float(os.getenv('BMI30_CAPTURE_SECONDS', '10'))
		except Exception:
			self.capture_diag_seconds = 10.0
		try:
			self.capture_diag_limit = int(os.getenv('BMI30_CAPTURE_LIMIT', '2000'))
		except Exception:
			self.capture_diag_limit = 2000
		self._capture_diag_fp = None
		self._capture_diag_started = 0.0
		self._capture_diag_lines = 0
		# GAP capture: отдельный лог по событиям delta!=step (в т.ч. реальные пропуски) — включается только по env
		try:
			gcap_env = os.getenv('BMI30_GAP_CAPTURE', None)
			if gcap_env is None:
				self.gap_capture_path = None
			elif isinstance(gcap_env, str) and gcap_env.strip() == '1':
				self.gap_capture_path = os.path.join('/tmp', f'bmi30_gap_{int(time.time())}.csv')
			else:
				self.gap_capture_path = gcap_env
		except Exception:
			self.gap_capture_path = None
		try:
			self.gap_capture_seconds = float(os.getenv('BMI30_GAP_CAPTURE_SECONDS', '10'))
		except Exception:
			self.gap_capture_seconds = 10.0
		try:
			self.gap_capture_limit = int(os.getenv('BMI30_GAP_CAPTURE_LIMIT', '2000'))
		except Exception:
			self.gap_capture_limit = 2000
		self._gap_capture_fp = None
		self._gap_capture_started = 0.0
		self._gap_capture_lines = 0
		# Скрывать полностью нулевые кадры (если это артефакт отображения/потока): по умолчанию ВКЛ (BMI30_HIDE_ALL_ZERO=1)
		try:
			self.hide_all_zero = str(os.getenv("BMI30_HIDE_ALL_ZERO", "1")).lower() not in ("0","false","no")
		except Exception:
			self.hide_all_zero = True
		# Ось X всегда в семплах (по ТЗ): фиксируем индексную шкалу, без времени
		self.use_time_axis = False
		# Оригинальные форматтеры оси X, чтобы можно было восстанавливать режим времени
		self._axis0_tickStrings_orig = None
		self._axis1_tickStrings_orig = None
		# max_samples, data0, data1, timestamps уже инициализированы выше для shared buffers
		self.last_seq = None
		self.gap_count = 0
		# Оценка шага seq (некоторые прошивки инкрементируют seq не на 1 на стерео-пару).
		self.seq_step = 1
		self._seq_step_hist = {}
		self._seq_step_hist_n = 0
		self.seq_reorder_count = 0
		# Пер-канальные seq/gap (важно, если A/B имеют независимые seq или relaxed-паринг склеивает разные seq).
		self.last_seq_a = None
		self.last_seq_b = None
		self.gap_a = 0
		self.gap_b = 0
		self.step_a = 1
		self.step_b = 1
		self.reord_a = 0
		self.reord_b = 0
		self._step_hist_a = {}
		self._step_hist_b = {}
		self._step_hist_a_n = 0
		self._step_hist_b_n = 0
		try:
			self.auto_independent = str(os.getenv('BMI30_AUTO_INDEPENDENT', '0')).lower() not in ('0','false','no')
		except Exception:
			self.auto_independent = False
		# GAP-логирование может само провоцировать пропуски на FS (console I/O). По умолчанию включено, но с throttling.
		try:
			self.gap_log_enabled = str(os.getenv('BMI30_GAP_LOG', '1')).lower() not in ('0', 'false', 'no')
		except Exception:
			self.gap_log_enabled = True
		try:
			# печатать не чаще, чем раз в N секунд; 0 = без ограничения
			self.gap_log_every = float(os.getenv('BMI30_GAP_LOG_EVERY', '1.0'))
		except Exception:
			self.gap_log_every = 1.0
		self._gap_log_last_t = 0.0
		self._gap_log_pending = 0
		self._gap_log_last_exp = None
		self._gap_log_last_got = None
		self.frames_sec = 0
		self.frames_a = 0  # счетчик кадров канала A (ADC0)
		self.frames_b = 0  # счетчик кадров канала B (ADC1)
		# Per-phase (even/odd) counters to validate rhythm (especially in AVG_ROI)
		self.frames_a_even = 0
		self.frames_a_odd = 0
		self.frames_b_even = 0
		self.frames_b_odd = 0
		self.afps_even = 0.0
		self.afps_odd = 0.0
		self.bfps_even = 0.0
		self.bfps_odd = 0.0
		# Timestamp delta diagnostics per phase (in seconds, last observed)
		self._dt_a_even = None
		self._dt_a_odd = None
		self._dt_b_even = None
		self._dt_b_odd = None
		self._ts_a_even = None
		self._ts_a_odd = None
		self._ts_b_even = None
		self._ts_b_odd = None
		self.zero_blocks = 0  # счётчик полностью нулевых кадров, скрытых из отображения
		self.last_fps_t = time.time()
		self.fps = 0.0  # общая частота кадров (для совместимости)
		self.afps = 0.0  # частота кадров канала A
		self.bfps = 0.0  # частота кадров канала B
		# Measured GUI overlay FPS (for button 6 XCorr/product rendering)
		self._xcorr_fps = 0.0
		self._xcorr_frames = 0
		self._xcorr_fps_t0 = time.time()
		self.last_range_t = 0.0
		self.max_int16_span = 33000  # предельное окно по амплитуде
		self._y_span_smooth = None  # сглаженный спан по Y
		# окно отображения
		self.view_start = 0
		self.view_len = 0  # выставим когда узнаем длину буфера
		self.connect_t = 0.0
		self.last_frame_t = 0.0
		self.no_data_warned = False
		self.last_diag_t = 0.0
		# отслеживание общего приёма данных (по транспорту), чтобы не ругаться на "остановку" при отсутствии пар
		self._last_rx_seen = 0.0
		# Предыдущие transport rx-счётчики (для вычисления реального Afps/Bfps в GUI)
		self._rx_cnt_a_prev = None
		self._rx_cnt_b_prev = None
		self._last_sample_ts: float | None = None
		# Таймаут устаревания по чет/нечет (для отображения без буферизации)
		try:
			self.parity_stale_s = float(os.getenv("BMI30_PARITY_STALE_S", "0.2"))
		except Exception:
			self.parity_stale_s = 0.2
		self._last_a_even_t = 0.0
		self._last_a_odd_t = 0.0
		self._last_b_even_t = 0.0
		self._last_b_odd_t = 0.0
		# счётчики диагностики парирования (чтобы не падать при отсутствии mismatch)
		self._pair_mismatch_count = 0
		self._last_pair_mismatch_t = 0.0
		# интервалы можно настроить через переменные окружения
		try:
			self.diag_interval = float(os.getenv("BMI30_DIAG_INTERVAL", "10"))  # не спамить предупреждением чаще, чем раз в 10с
		except Exception:
			self.diag_interval = 10.0
		try:
			self.stop_warn_after = float(os.getenv("BMI30_STOP_WARN_AFTER", "5"))  # порог простоя для предупреждения, сек
		except Exception:
			self.stop_warn_after = 5.0
		try:
			self.seq_stall_after = float(os.getenv("BMI30_SEQ_STALL_AFTER", "3"))  # сек, если seq не меняется
		except Exception:
			self.seq_stall_after = 3.0
		self._last_seq_advance_t = time.time()
		self._last_seq_value = None
		try:
			self.seq_cycle_max = int(os.getenv("BMI30_SEQ_CYCLE_MAX", "12"))  # макс. длина цикла повторения seq
		except Exception:
			self.seq_cycle_max = 12
		self._seq_recent = deque(maxlen=64)
		self._instr = (
			"Инструкция: 1) Прошивка должна обрабатывать START_STREAM (0x20) и слать кадры vendor bulk на EP IN 0x83. "
			"SET_PROFILE (0x14) переключает профиль устройства (используйте через GUI). "
			"Частота задается отдельно через CMD_BLOCK_HZ (0x11). "
			"Каждый кадр: заголовок 32 байта (magic 0xA55A LE), флаги 0x01 (ADC0) и 0x02 (ADC1); total_samples авто-фиксируется по первому рабочему кадру, payload = total_samples*2 байт. "
			"Тестовый кадр (flag 0x80) может быть один в начале и пропускается. 4) Проверьте права доступа (udev) если устройство не открывается. 5) Кнопка 1 в GUI запускает поток."
		)
		# статус: удержание сообщений, чтобы не мигали
		self._status_hold_text: str | None = None
		self._status_hold_until: float = 0.0
		self._last_status_text: str | None = None
		self._last_default_update_t: float = 0.0
		self._legend_last_runtime_t: float = 0.0
		# --- Signal detection (per-channel) over correlation/product array ---
		self._det_enabled = str(os.getenv("BMI30_DETECT_ENABLE", "1")).lower() not in ("0", "false", "no")
		# Detection gate by external marker input GPIO23:
		# 1) dependency ON  -> GPIO23=1 allows detection, GPIO23=0 blocks detection
		# 2) dependency OFF -> ignore GPIO23 and detect as usual
		self._det_gate_use_gpio23 = True
		self._det_gate_gpio23_value = None
		self._det_gate_block_active = False
		self._det_gate_gpio23_poll_last_t = 0.0
		self._det_gate_seen_high = False
		# Detector input source:
		# - "norm": use normalized product max (0..1) mapped to u16 (0..65535) -> slow/stable adaptation
		# - "prod": use raw centered product max scaled down by BMI30_DETECT_LEVEL_SCALE/BMI30_PROD_SCALE -> legacy/raw mode
		try:
			# Default is 'prod' because user-visible correlation/product graph operates in this domain.
			self._det_source = str(os.getenv("BMI30_DETECT_SOURCE", "prod")).strip().lower()
			if self._det_source in ("raw", "product"):
				self._det_source = "prod"
			if self._det_source not in ("norm", "prod"):
				self._det_source = "prod"
		except Exception:
			self._det_source = "prod"
		try:
			self._det_thr_init = int(os.getenv("BMI30_DETECT_THR_INIT", "0"))
		except Exception:
			self._det_thr_init = 0
		self._det_thr0 = int(self._det_thr_init)
		self._det_thr1 = int(self._det_thr_init)
		self._det_exceed0 = 0
		self._det_exceed1 = 0
		self._det_start_consec0 = 0
		self._det_start_consec1 = 0
		self._det_hits0 = deque(maxlen=12)
		self._det_hits1 = deque(maxlen=12)
		self._det_last_pair_key0 = None
		self._det_last_pair_key1 = None
		self._det_exceed_peak0 = None
		self._det_exceed_peak1 = None
		self._det_hold0 = False
		self._det_hold1 = False
		self._det_last_fire_t = 0.0
		self._det_last_seen_t0 = 0.0
		self._det_last_seen_t1 = 0.0
		self._det_last_present_t0 = 0.0
		self._det_last_present_t1 = 0.0
		self._det_last_lvl0 = 0
		self._det_last_lvl1 = 0
		# Raw amplitude estimates (abs(u16-32768)) for display/debug
		self._det_last_amp0 = 0
		self._det_last_amp1 = 0
		# Raw product maxima (abs(prod)) and scale used for detector level
		self._det_last_prodmax0 = 0.0
		self._det_last_prodmax1 = 0.0
		self._det_last_level_scale = 0.0
		self._det_last_source = str(getattr(self, '_det_source', 'norm'))
		self._det_last_shift0 = 0
		self._det_last_shift1 = 0
		# Device DC adapt control (freeze on detect, resume on loss)
		self._det_dc_frozen = False
		# Threshold snapshots at freeze time (used to decide loss reliably even if adaptive thr drifts)
		self._det_freeze_thr0 = 0
		self._det_freeze_thr1 = 0
		# Сохраненные пороговые уровни (при переходе с кнопок 6+ на другие)
		self._det_saved_thr0 = 0  # сохраненный порог канала 0
		self._det_saved_thr1 = 0  # сохраненный порог канала 1
		self._det_last_mode_idx = None  # последний номер кнопки режима
		# Счетчики срабатываний для статистики
		self._beep_fire_count = 0  # счетчик включений динамика
		self._freeze_fire_count = 0  # счетчик включений заморозки
		# Предыдущие состояния для отслеживания переходов 0->1
		self._prev_beep_state = False  # предыдущее состояние динамика
		self._prev_freeze_state = False  # предыдущее состояние заморозки
		# Счетчики последовательных срабатываний для динамика (нужно 2 подряд)
		self._beep_consecutive0 = 0  # последовательные срабатывания канала 0
		self._beep_consecutive1 = 0  # последовательные срабатывания канала 1
		# Detector warmup: during the first seconds after startup, thresholds adapt but
		# we ignore any early "fire" (no freeze, no hold, no beep) to avoid false startup freezes.
		try:
			self._det_warmup_sec = float(os.getenv('BMI30_DETECT_WARMUP_SEC', '2.0'))
			if (not np.isfinite(self._det_warmup_sec)) or self._det_warmup_sec < 0.0:
				self._det_warmup_sec = 2.0
		except Exception:
			self._det_warmup_sec = 2.0
		# Во время прогрева ускоряем адаптацию порога, чтобы быстрее уйти от 65535.
		try:
			self._det_warmup_step_mul = float(os.getenv('BMI30_DETECT_WARMUP_STEP_MUL', '10'))
			if (not np.isfinite(self._det_warmup_step_mul)) or self._det_warmup_step_mul < 1.0:
				self._det_warmup_step_mul = 10.0
		except Exception:
			self._det_warmup_step_mul = 10.0
		# Окно ручной быстрой адаптации (например, по кнопке сброса)
		self._det_fast_adapt_until = 0.0
		# IMPORTANT: warmup is armed on stream start/connect, not on GUI launch.
		# Otherwise, if user waits before pressing "1", the warmup window expires and
		# the first frames may immediately freeze.
		self._det_warmup_until = 0.0
		self._det_warmup_dc_fix_last_t = 0.0
		# Beeper: PWM0/GPIO12 best-effort (no-op if not available)
		try:
			gpio_pin = int(os.getenv("BMI30_BEEP_GPIO", "12"))
		except Exception:
			gpio_pin = 12
		self._beeper = PwmBeeper(gpio_pin=gpio_pin)
		# Optional continuous PWM output (useful for measuring "variable signal" on the pin)
		# Modes: pattern (default), continuous, sweep
		try:
			self._beep_mode = str(os.getenv('BMI30_BEEP_MODE', 'pattern')).strip().lower()
			if self._beep_mode not in ('pattern', 'continuous', 'sweep'):
				self._beep_mode = 'pattern'
		except Exception:
			self._beep_mode = 'pattern'
		# Explicit sweep mode (guaranteed variable PWM frequency on GPIO12 for scope/debug)
		try:
			self._beep_sweep_enabled = _env_bool('BMI30_BEEP_SWEEP', False) or (self._beep_mode == 'sweep')
		except Exception:
			self._beep_sweep_enabled = (self._beep_mode == 'sweep')
		try:
			self._beep_sweep_min = float(os.getenv('BMI30_BEEP_SWEEP_MIN', '1000'))
			self._beep_sweep_max = float(os.getenv('BMI30_BEEP_SWEEP_MAX', '4000'))
			self._beep_sweep_period_s = float(os.getenv('BMI30_BEEP_SWEEP_PERIOD', '2.0'))
			if not np.isfinite(self._beep_sweep_min) or not np.isfinite(self._beep_sweep_max):
				raise ValueError('bad sweep range')
			if self._beep_sweep_max <= self._beep_sweep_min:
				self._beep_sweep_max = self._beep_sweep_min + 1.0
			if (not np.isfinite(self._beep_sweep_period_s)) or self._beep_sweep_period_s <= 0.1:
				self._beep_sweep_period_s = 2.0
		except Exception:
			self._beep_sweep_min = 1000.0
			self._beep_sweep_max = 4000.0
			self._beep_sweep_period_s = 2.0
		self._beep_sweep_t0 = time.time()
		# Detector GPIO outputs (ADC1/ADC2 hit): best-effort
		try:
			self._init_det_gpio()
		except Exception:
			pass
		# Detection parameters (u16 domain 0..65535)
		try:
			# Default is x2 threshold (can be overridden via config/env).
			r0, r1 = load_det_ratio_pair()
		except Exception:
			r0, r1 = 2.0, 2.0
		try:
			a0, a1 = load_det_add_pair()
		except Exception:
			a0, a1 = 100, 100
		# Clamp to broad range (mark-type specific UI will refine)
		try:
			self._det_ratio0 = max(1.0, min(20.0, float(r0)))
			self._det_ratio1 = max(1.0, min(20.0, float(r1)))
		except Exception:
			self._det_ratio0 = 2.0
			self._det_ratio1 = 2.0
		try:
			self._det_add0 = max(100, min(700, int(round(float(a0) / 100.0) * 100)))
			self._det_add1 = max(100, min(700, int(round(float(a1) / 100.0) * 100)))
		except Exception:
			self._det_add0 = 100
			self._det_add1 = 100
		# If GUI already built, sync the combo boxes to the loaded values
		try:
			self._refresh_det_ratio_options()
			if getattr(self, 'det_add_box0', None) is not None:
				self.det_add_box0.blockSignals(True)
				self.det_add_box0.setCurrentText(str(self._det_add0))
				self.det_add_box0.blockSignals(False)
			if getattr(self, 'det_add_box1', None) is not None:
				self.det_add_box1.blockSignals(True)
				self.det_add_box1.setCurrentText(str(self._det_add1))
				self.det_add_box1.blockSignals(False)
		except Exception:
			pass
		try:
			# Slightly longer default to avoid rapid re-trigger; does not block unfreeze while frozen.
			self._det_cooldown_s = float(os.getenv("BMI30_DETECT_COOLDOWN", "1.0"))
		except Exception:
			self._det_cooldown_s = 1.0
		try:
			# Faster default unfreeze once signal is lost.
			self._det_loss_s = float(os.getenv("BMI30_DETECT_LOSS_SEC", "1.0"))
		except Exception:
			self._det_loss_s = 1.0
		try:
			# Slightly stricter loss criterion => быстрее считаться "потерянным".
			self._det_loss_ratio = float(os.getenv("BMI30_DETECT_LOSS_RATIO", "1.4"))
		except Exception:
			self._det_loss_ratio = 1.4
		# Beep frequencies
		try:
			self._beep_adc0_base = float(os.getenv("BMI30_BEEP_ADC0_BASE", "4000"))
			self._beep_adc1_base = float(os.getenv("BMI30_BEEP_ADC1_BASE", "1000"))
		except Exception:
			self._beep_adc0_base = 4000.0
			self._beep_adc1_base = 1000.0
		try:
			self._beep_adc0_min = float(os.getenv("BMI30_BEEP_ADC0_MIN", "1000"))
			self._beep_adc0_max = float(os.getenv("BMI30_BEEP_ADC0_MAX", "3000"))
			self._beep_adc1_min = float(os.getenv("BMI30_BEEP_ADC1_MIN", "2000"))
			self._beep_adc1_max = float(os.getenv("BMI30_BEEP_ADC1_MAX", "4000"))
		except Exception:
			self._beep_adc0_min, self._beep_adc0_max = 1000.0, 3000.0
			self._beep_adc1_min, self._beep_adc1_max = 2000.0, 4000.0
		# Optional: keep PWM running while detection HOLD is active.
		# This is OFF by default to avoid changing behavior unexpectedly.
		self._beep_hold_enabled = _env_bool('BMI30_BEEP_HOLD_ENABLE', False)
		try:
			self._beep_hold_delay_s = float(os.getenv('BMI30_BEEP_HOLD_DELAY', '0.40'))
			if (not np.isfinite(self._beep_hold_delay_s)) or self._beep_hold_delay_s < 0.0:
				self._beep_hold_delay_s = 0.40
		except Exception:
			self._beep_hold_delay_s = 0.40
		self._beep_hold_active = False
		self._beep_hold_freq = 0.0
		self._beep_hold_after_t = 0.0
		# Forced PWM from GUI button (independent from detection)
		self._beep_force_enabled = False
		try:
			self._beep_force_freq = float(os.getenv('BMI30_BEEP_FORCE_FREQ', '2000'))
			if (not np.isfinite(self._beep_force_freq)) or self._beep_force_freq <= 0.0:
				self._beep_force_freq = 2000.0
		except Exception:
			self._beep_force_freq = 2000.0
		
		# --- Automatic capture system for signal analysis ---
		# Circular buffer holds recent frames; on detection trigger, saves PRE+HOLD+POST frames to NPZ
		# Примечание: self._auto_capture_enabled уже инициализирован в начале __init__
		try:
			self._capture_pre_frames = int(os.getenv('BMI30_CAPTURE_PRE', '36'))
		except Exception:
			self._capture_pre_frames = 36
		try:
			self._capture_post_frames = int(os.getenv('BMI30_CAPTURE_POST', '5'))
		except Exception:
			self._capture_post_frames = 5
		# Максимальное общее количество фреймов для записи (PRE + HOLD + POST)
		try:
			self._capture_max_frames = int(os.getenv('BMI30_CAPTURE_MAX', '41'))
		except Exception:
			self._capture_max_frames = 41
		# Состояние метки: 0=неизвестно, 1=с меткой, 2=без метки
		try:
			self._capture_label_state = int(self._ui_state.get('capture_label_state', 0))
		except Exception:
			self._capture_label_state = 0
		try:
			if self._capture_label_state not in (0, 1, 2):
				self._capture_label_state = 0
		except Exception:
			self._capture_label_state = 0
		try:
			self._capture_dir = str(os.getenv('BMI30_CAPTURE_DIR', './captures'))
		except Exception:
			self._capture_dir = './captures'
		# Ensure capture directory exists
		if self._auto_capture_enabled:
			try:
				os.makedirs(self._capture_dir, exist_ok=True)
			except Exception as e:
				print(f"[CAPTURE] Failed to create capture directory {self._capture_dir}: {e}")
				self._auto_capture_enabled = False
		
		# Circular buffer: stores last N frames (even/odd for both channels)
		# Buffer size = PRE frames (to have enough history before trigger)
		self._capture_buffer_size = max(self._capture_pre_frames + 5, 50)
		self._capture_buffer = []  # list of frame dicts
		self._capture_buffer_lock = threading.Lock()
		
		# Capture session state machine
		# States: 'idle' -> 'triggered' -> 'recording' -> 'finalizing' -> 'idle'
		self._capture_state = 'idle'
		self._capture_session = None  # dict with session metadata
		self._capture_frames_recorded = 0
		self._capture_post_countdown = 0
		# capture de-duplication: only store new frames when seq/timestamp changes
		self._capture_last_key = None
		self._capture_last_record_key = None
		self._capture_trigger_index = None
		# post phase timing guard (finalize if no new frames for too long)
		try:
			self._capture_post_timeout_s = float(os.getenv('BMI30_CAPTURE_POST_TIMEOUT', '2.0'))
		except Exception:
			self._capture_post_timeout_s = 2.0
		self._capture_post_started = 0.0
		
		# stream (ленивый запуск)
		self.stream = None
		self._connecting = False
		self.usb_retry_timer = QtCore.QTimer()
		self.usb_retry_timer.setInterval(1500)
		self.usb_retry_timer.timeout.connect(self._try_connect)
		self._set_status("Поток запускается автоматически при выборе любой кнопки кроме 0")
		# Сохраним порт info для power cycle без stream
		self.last_port_info = None
		# timer
		self.timer = QtWidgets.QApplication.instance().thread()  # dummy keep
		self.qtimer = QtCore.QTimer()
		# Настраиваемая частота GUI: BMI30_GUI_FPS (по умолчанию 16 FPS для снижения нагрузки)
		try:
			gui_fps = int(os.getenv("BMI30_GUI_FPS", "16"))
		except Exception:
			gui_fps = 16
		interval = max(10, int(1000 / gui_fps))  # минимум 10мс
		self.qtimer.setInterval(interval)
		self.qtimer.timeout.connect(self._tick)
		self.qtimer.start()

		# Start background mode-switch worker to avoid blocking GUI on USB commands
		try:
			mw = globals().get('_ModeWorker', None)
			if mw is not None:
				self._mode_worker = mw(self)
				self._mode_worker.start()
			else:
				self._mode_worker = None
		except Exception:
			self._mode_worker = None
		# авто-кик при зависании
		self.auto_soft_kick = str(os.getenv("BMI30_AUTO_SOFT_KICK", "1")).lower() not in ("0","false","no")
		self.last_soft_kick_t = 0.0
		# авто-сброс STM32 при пропаже потока
		self.auto_reset_on_stall = str(os.getenv("BMI30_AUTO_RESET_ON_STALL", "1")).lower() not in ("0","false","no")
		try:
			self.stall_reset_after = float(os.getenv("BMI30_STALL_RESET_AFTER", "15"))
		except Exception:
			self.stall_reset_after = 15.0
		try:
			self.stall_reset_cooldown = float(os.getenv("BMI30_STALL_RESET_COOLDOWN", "30"))
		except Exception:
			self.stall_reset_cooldown = 30.0
		self._stall_reset_last_t = 0.0
		self._stall_reset_inflight = False
		# Флаг: поток остановлен пользователем (не выполнять автопинки)
		self._stream_user_stopped = False
		# нижняя панель: слева слайдеры, справа цифровые кнопки
		bottom = QtWidgets.QHBoxLayout()
		layout.addLayout(bottom)
		sliders_box = QtWidgets.QVBoxLayout()
		bottom.addLayout(sliders_box, 1)
		# Ось X уже зафиксирована как индексы семплов
		# Старт
		row_start = QtWidgets.QHBoxLayout()
		self.lbl_start_value = QtWidgets.QLabel(str(self.view_start))
		self.slider_start = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
		self.slider_start.setEnabled(True)
		self.slider_start.setMinimum(0)
		self.slider_start.setMaximum(max(0, self.max_samples - self.view_len))
		self.slider_start.setValue(self.view_start)
		lbl_start_name = QtWidgets.QLabel("Старт")
		row_start.addWidget(self.lbl_start_value)
		row_start.addWidget(self.slider_start, 1)
		row_start.addWidget(lbl_start_name)
		sliders_box.addLayout(row_start)
		# Семплов
		row_len = QtWidgets.QHBoxLayout()
		self.lbl_len_value = QtWidgets.QLabel(str(self.view_len))
		self.slider_len = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
		self.slider_len.setEnabled(True)
		self.slider_len.setMinimum(1)
		self.slider_len.setMaximum(self.max_samples)
		self.slider_len.setValue(self.view_len)
		lbl_len_name = QtWidgets.QLabel("Семплов")
		row_len.addWidget(self.lbl_len_value)
		row_len.addWidget(self.slider_len, 1)
		row_len.addWidget(lbl_len_name)
		sliders_box.addLayout(row_len)
		# цифровые кнопки справа
		self.state_file = os.path.join(os.path.dirname(__file__), 'bmi30_sel.json')
		self.sel_saved = self._load_saved_sel()
		try:
			if int(self.sel_saved or 0) == 6:
				self.sel_saved = 5
		except Exception:
			pass
		self.num_group = QtWidgets.QButtonGroup()
		self.num_group.setExclusive(True)
		self.num_buttons = []
		btns_layout = QtWidgets.QHBoxLayout()
		for i in range(8):
			b = QtWidgets.QToolButton()
			b.setText(str(i))
			b.setCheckable(True)
			b.setAutoExclusive(True)
			b.setFixedSize(42, 42)
			b.setStyleSheet("QToolButton {background:#333; color:#ddd; border:1px solid #555; padding:2px;} "
				"QToolButton:checked {background:#ffb400; color:#000; border:2px solid #ffea8a; font-weight:bold;}" )
			self.num_group.addButton(b, i)
			btns_layout.addWidget(b)
			self.num_buttons.append(b)
			# Ensure special handlers run even when clicking an already-checked button
			try:
				# connect per-button clicked to extra handler (passes index)
				from functools import partial
				b.clicked.connect(partial(self._on_num_clicked_extra, i))
			except Exception:
				# if partial import fails for any reason, ignore
				pass
		# без stretch — слайдеры тянутся до кнопок
		bottom.addLayout(btns_layout)
		# apply saved selection
		if self.sel_saved and 1 <= self.sel_saved <=7:
			self.num_buttons[self.sel_saved].setChecked(True)
		else:
			self.num_buttons[0].setChecked(True)
		self.num_group.idClicked.connect(self._num_clicked)
		# Дополнительный обработчик для специальных режимов (например кнопка 6 — корреляция)
		self.num_group.idClicked.connect(self._on_num_clicked_extra)
		self.win.closeEvent = self._on_close  # type: ignore
		# slider signals
		self.slider_start.valueChanged.connect(self._on_slider_start)
		self.slider_len.valueChanged.connect(self._on_slider_len)

		# Сбросим состояние слайдеров, чтобы при переподключениях они переинициализировались под свежую длину буфера
		self._reset_sliders()

		# Применим режим оси X после создания всех элементов
		self._apply_x_axis_mode()

		# Тестовый режим без устройства (нужно знать до автозапуска)
		try:
			_test_mode = str(os.getenv("BMI30_TEST_MODE", "0")).lower() not in ("0","false","no")
		except Exception:
			_test_mode = False

		# Восстановление режима и отправка параметров на устройство
		try:
			_autostart = str(os.getenv("BMI30_AUTOSTART", "1")).lower() not in ("0","false","no")
		except Exception:
			_autostart = True
		if not _test_mode:
			self.view_mode = 0
			try:
				idx = int(self.num_group.checkedId())
			except Exception:
				idx = 3
			# Если выбран режим != 0 — применяем его и отправляем настройки
			if idx != 0:
				self._num_clicked(idx)
				# also trigger extra handler (e.g., button 6 correlation)
				try:
					self._on_num_clicked_extra(idx)
				except Exception:
					pass
		# режим отображения: 0=оба, 1=только канал 1, 2=только канал 2
		self.view_mode = 0
		
		# Тестовый режим без устройства
		if _test_mode:
			print("[TEST] Test mode enabled - simulating data")
			self._test_mode = True
			# Имитируем получение данных исходя из текущего профиля
			self.base_buf_len = self.expected_len_map.get(self.desired_profile, self.initial_expected)
			self.base_buf_len_bytes = self.base_buf_len * 2
			self.freq_hz = getattr(self, 'desired_freq', 200)
			# Заполняем тестовыми данными
			import math
			for i in range(self.base_buf_len):
				self.data0[i] = int(1000 * math.sin(2 * math.pi * i / 100))
				self.data1[i] = int(800 * math.cos(2 * math.pi * i / 150))
			self._set_status("Тестовый режим - данные сгенерированы")

	# (кнопки управления стримом удалены по ТЗ)

	def _find_cdc_port(self):
		ports = sorted(glob.glob('/dev/ttyACM*'))
		if not ports:
			return None
		return ports[0]

	def _send_soft_reset_via_cdc(self):
		try:
			port = self._find_cdc_port()
			if port is None:
				print("[RESET] CDC порт не найден, пропускаем SOFT_RESET")
				return
			with serial.Serial(port, 115200, timeout=1) as ser:
				ser.write(bytes([CMD_SOFT_RESET]))
				time.sleep(0.1)
				print("[RESET] SOFT_RESET sent via CDC")
		except Exception as e:
			print(f"[RESET] SOFT_RESET via CDC failed: {e}")

	def _hardware_reset_device(self) -> bool:
		"""Аппаратный сброс через GPIO (open-collector): краткий LOW, затем Hi-Z."""
		try:
			gpio_pin = int(os.getenv("BMI30_HW_RESET_GPIO", "17"))
		except Exception:
			gpio_pin = 17
		try:
			pulse_ms = int(os.getenv("BMI30_HW_RESET_PULSE_MS", "100"))
		except Exception:
			pulse_ms = 100
		try:
			wait_s = float(os.getenv("BMI30_HW_RESET_WAIT_S", "3.0"))
		except Exception:
			wait_s = 3.0
		if gpio_pin <= 0:
			return False
		if pulse_ms <= 0:
			pulse_ms = 100
		if wait_s < 0:
			wait_s = 0.0
		try:
			self._set_status(f"Аппаратный сброс GPIO{gpio_pin}…", hold_sec=1.5)
		except Exception:
			pass
		# Try pigpio first
		try:
			import pigpio  # type: ignore
			pi = pigpio.pi()
			if getattr(pi, 'connected', False):
				pi.set_mode(gpio_pin, pigpio.OUTPUT)
				pi.write(gpio_pin, 0)
				time.sleep(max(0.01, pulse_ms / 1000.0))
				pi.set_mode(gpio_pin, pigpio.INPUT)  # Hi-Z
				pi.stop()
				time.sleep(wait_s)
				return True
		except Exception:
			pass
		# Try lgpio (Pi5-friendly)
		try:
			import lgpio  # type: ignore
			chip = lgpio.gpiochip_open(0)
			lgpio.gpio_claim_output(chip, gpio_pin, 0)
			time.sleep(max(0.01, pulse_ms / 1000.0))
			lgpio.gpio_claim_input(chip, gpio_pin)
			lgpio.gpiochip_close(chip)
			time.sleep(wait_s)
			return True
		except Exception:
			pass
		# Fallback: RPi.GPIO
		try:
			import RPi.GPIO as GPIO  # type: ignore
			GPIO.setwarnings(False)
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(gpio_pin, GPIO.OUT, initial=GPIO.LOW)
			time.sleep(max(0.01, pulse_ms / 1000.0))
			GPIO.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
			GPIO.cleanup(gpio_pin)
			time.sleep(wait_s)
			return True
		except Exception:
			return False

	def _init_det_gpio(self):
		"""Инициализировать GPIO для индикации срабатывания ADC1/ADC2."""
		self._det_gpio_backend = None
		self._det_gpio_chip = None
		self._det_gpio_last_a = None
		self._det_gpio_last_b = None
		try:
			self._det_gpio_pin_a = int(os.getenv("BMI30_DET_GPIO_A", "27"))
		except Exception:
			self._det_gpio_pin_a = 27
		try:
			self._det_gpio_pin_b = int(os.getenv("BMI30_DET_GPIO_B", "22"))
		except Exception:
			self._det_gpio_pin_b = 22
		# Try lgpio first
		try:
			import lgpio  # type: ignore
			chip = lgpio.gpiochip_open(0)
			lgpio.gpio_claim_output(chip, int(self._det_gpio_pin_a), 0)
			lgpio.gpio_claim_output(chip, int(self._det_gpio_pin_b), 0)
			self._det_gpio_backend = 'lgpio'
			self._det_gpio_chip = chip
			return
		except Exception:
			pass
		# Fallback: RPi.GPIO
		try:
			import RPi.GPIO as GPIO  # type: ignore
			GPIO.setwarnings(False)
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(int(self._det_gpio_pin_a), GPIO.OUT, initial=GPIO.LOW)
			GPIO.setup(int(self._det_gpio_pin_b), GPIO.OUT, initial=GPIO.LOW)
			self._det_gpio_backend = 'rpi'
			self._det_gpio_chip = GPIO
			return
		except Exception:
			self._det_gpio_backend = None
			self._det_gpio_chip = None

	def _set_det_gpio(self, a_on: bool, b_on: bool):
		"""Установить уровни GPIO для ADC1(A)/ADC2(B)."""
		try:
			if self._det_gpio_backend is None:
				return
			a_on = bool(a_on)
			b_on = bool(b_on)
			if (self._det_gpio_last_a == a_on) and (self._det_gpio_last_b == b_on):
				return
			self._det_gpio_last_a = a_on
			self._det_gpio_last_b = b_on
			if self._det_gpio_backend == 'lgpio':
				import lgpio  # type: ignore
				chip = self._det_gpio_chip
				lgpio.gpio_write(chip, int(self._det_gpio_pin_a), 1 if a_on else 0)
				lgpio.gpio_write(chip, int(self._det_gpio_pin_b), 1 if b_on else 0)
				return
			if self._det_gpio_backend == 'rpi':
				GPIO = self._det_gpio_chip
				GPIO.output(int(self._det_gpio_pin_a), GPIO.HIGH if a_on else GPIO.LOW)
				GPIO.output(int(self._det_gpio_pin_b), GPIO.HIGH if b_on else GPIO.LOW)
				return
		except Exception:
			pass

	def _cleanup_det_gpio(self):
		"""Освободить GPIO для ADC1/ADC2 индикации."""
		try:
			if self._det_gpio_backend == 'lgpio':
				import lgpio  # type: ignore
				try:
					lgpio.gpio_write(self._det_gpio_chip, int(self._det_gpio_pin_a), 0)
					lgpio.gpio_write(self._det_gpio_chip, int(self._det_gpio_pin_b), 0)
				except Exception:
					pass
				try:
					lgpio.gpiochip_close(self._det_gpio_chip)
				except Exception:
					pass
			elif self._det_gpio_backend == 'rpi':
				GPIO = self._det_gpio_chip
				try:
					GPIO.output(int(self._det_gpio_pin_a), GPIO.LOW)
					GPIO.output(int(self._det_gpio_pin_b), GPIO.LOW)
				except Exception:
					pass
				try:
					GPIO.cleanup(int(self._det_gpio_pin_a))
					GPIO.cleanup(int(self._det_gpio_pin_b))
				except Exception:
					pass
		except Exception:
			pass

	def _init_det_gate_gpio23_input(self):
		"""Инициализировать вход GPIO23 для внешней метки детекции (best-effort)."""
		self._det_gate_gpio_backend = None
		self._det_gate_gpio_chip = None
		self._det_gate_gpio_module = None
		self._det_gate_seen_high = False
		try:
			self._det_gate_gpio_pin = int(os.getenv("BMI30_DET_GATE_GPIO", "23"))
		except Exception:
			self._det_gate_gpio_pin = 23
		# Try lgpio first (Pi5-friendly)
		try:
			import lgpio  # type: ignore
			chip = lgpio.gpiochip_open(0)
			# Prefer pull-up to avoid floating LOW when source is disconnected.
			try:
				lgpio.gpio_claim_input(chip, int(getattr(lgpio, 'SET_PULL_UP', 0x20)), int(self._det_gate_gpio_pin))
			except Exception:
				lgpio.gpio_claim_input(chip, int(self._det_gate_gpio_pin))
			self._det_gate_gpio_backend = 'lgpio'
			self._det_gate_gpio_chip = chip
			self._det_gate_gpio_module = lgpio
			return
		except Exception:
			pass
		# Fallback: RPi.GPIO
		try:
			import RPi.GPIO as GPIO  # type: ignore
			GPIO.setwarnings(False)
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(int(self._det_gate_gpio_pin), GPIO.IN, pull_up_down=GPIO.PUD_UP)
			self._det_gate_gpio_backend = 'rpi'
			self._det_gate_gpio_module = GPIO
			return
		except Exception:
			self._det_gate_gpio_backend = None
			self._det_gate_gpio_chip = None
			self._det_gate_gpio_module = None

	def _read_det_gate_gpio23(self):
		"""Считать GPIO23 (0/1) или None при недоступности."""
		try:
			if getattr(self, '_det_gate_gpio_backend', None) == 'lgpio':
				lgpio = getattr(self, '_det_gate_gpio_module', None)
				chip = getattr(self, '_det_gate_gpio_chip', None)
				if lgpio is None or chip is None:
					return None
				v = int(lgpio.gpio_read(chip, int(self._det_gate_gpio_pin)))
				return 1 if v == 1 else 0
			if getattr(self, '_det_gate_gpio_backend', None) == 'rpi':
				GPIO = getattr(self, '_det_gate_gpio_module', None)
				if GPIO is None:
					return None
				v = int(GPIO.input(int(self._det_gate_gpio_pin)))
				return 1 if v == 1 else 0
		except Exception:
			return None
		return None

	def _poll_det_gate_gpio23(self, force: bool = False):
		"""Обновить кэш GPIO23 и стиль кнопки (с троттлингом)."""
		now = time.time()
		try:
			last_t = float(getattr(self, '_det_gate_gpio23_poll_last_t', 0.0) or 0.0)
		except Exception:
			last_t = 0.0
		if (not force) and (now - last_t) < 0.05:
			return getattr(self, '_det_gate_gpio23_value', None)
		self._det_gate_gpio23_poll_last_t = now
		val = self._read_det_gate_gpio23()
		if val == 1:
			self._det_gate_seen_high = True
		if val != getattr(self, '_det_gate_gpio23_value', None):
			self._det_gate_gpio23_value = val
			self._update_det_gate_btn_style()
		return val

	def _is_det_gate_blocked(self) -> bool:
		"""Temporary: GPIO23 is indicator-only, no detection blocking."""
		return False

	def _apply_det_gate_state(self):
		"""Применить состояние гейта: при GPIO23=0 форсировать детекцию в RUN."""
		blocked = bool(self._is_det_gate_blocked())
		was_blocked = bool(getattr(self, '_det_gate_block_active', False))
		self._det_gate_block_active = blocked
		if not blocked:
			return
		# Если уже были заблокированы и состояние стабильно — лишний раз не дёргаем команды.
		if was_blocked and (not bool(getattr(self, '_det_dc_frozen', False))) and (not bool(getattr(self, '_det_hold0', False))) and (not bool(getattr(self, '_det_hold1', False))):
			try:
				self._set_det_gpio(False, False)
			except Exception:
				pass
			return
		try:
			self._det_dc_frozen = False
			self._det_hold0 = False
			self._det_hold1 = False
			self._det_exceed0 = 0
			self._det_exceed1 = 0
			self._det_start_consec0 = 0
			self._det_start_consec1 = 0
			self._det_hits0 = deque(maxlen=12)
			self._det_hits1 = deque(maxlen=12)
			self._det_last_pair_key0 = None
			self._det_last_pair_key1 = None
			self._det_exceed_peak0 = None
			self._det_exceed_peak1 = None
			self._prev_freeze_state = False
			self._prev_beep_state = False
		except Exception:
			pass
		try:
			self._device_set_dc_adapt(True)
		except Exception:
			pass
		try:
			self._beep_hold_stop()
		except Exception:
			pass
		try:
			self._set_det_gpio(False, False)
		except Exception:
			pass

	def _update_det_gate_btn_style(self):
		"""Обновить вид кнопки-индикатора GPIO23."""
		try:
			if not hasattr(self, 'btn_det_gate'):
				return
			self.btn_det_gate.setText("G")
			val = getattr(self, '_det_gate_gpio23_value', None)
			if val is None:
				self.btn_det_gate.setStyleSheet("background-color: #d9d9d9; color: #303030; border:1px solid #a6a6a6;")
				self.btn_det_gate.setToolTip("GPIO23: состояние недоступно")
			elif int(val) == 1:
				self.btn_det_gate.setStyleSheet("background-color: #5fd35f; color: #0f2d0f; border:1px solid #3aa93a;")
				self.btn_det_gate.setToolTip("GPIO23: 1")
			else:
				self.btn_det_gate.setStyleSheet("background-color: #ff6b6b; color: #3b0000; border:1px solid #c94c4c;")
				self.btn_det_gate.setToolTip("GPIO23: 0")
		except Exception:
			pass

	def _toggle_det_gate_gpio23(self):
		"""Обновить индикацию GPIO23 (без влияния на детекцию)."""
		try:
			self._poll_det_gate_gpio23(force=True)
		except Exception:
			pass
		self._update_det_gate_btn_style()
		try:
			val = getattr(self, '_det_gate_gpio23_value', None)
			if val is None:
				self._set_status("GPIO23: состояние недоступно", hold_sec=1.5)
			elif int(val) == 1:
				self._set_status("GPIO23: 1", hold_sec=1.5)
			else:
				self._set_status("GPIO23: 0", hold_sec=1.5)
		except Exception:
			pass

	def _cleanup_det_gate_gpio23_input(self):
		"""Освободить ресурсы чтения GPIO23."""
		try:
			if getattr(self, '_det_gate_gpio_backend', None) == 'lgpio':
				lgpio = getattr(self, '_det_gate_gpio_module', None)
				chip = getattr(self, '_det_gate_gpio_chip', None)
				if lgpio is not None and chip is not None:
					try:
						lgpio.gpiochip_close(chip)
					except Exception:
						pass
			elif getattr(self, '_det_gate_gpio_backend', None) == 'rpi':
				GPIO = getattr(self, '_det_gate_gpio_module', None)
				if GPIO is not None:
					try:
						GPIO.cleanup(int(getattr(self, '_det_gate_gpio_pin', 23)))
					except Exception:
						pass
		except Exception:
			pass

	def _reset_phase_splitter(self, reason: str = ""):
		"""Reset host-side even/odd splitter state.
		
		Why:
		- Stream restarts (STOP/START, reconnects) can re-anchor the device phase.
		- If we keep toggling across restarts, the displayed even/odd can appear to swap.
		
		We bias the *first* new frame after reset to be EVEN (par=0).
		"""
		try:
			# Make first non-duplicate return par=0:
			# toggle starts at 1, then toggles to 0 on first frame.
			self._phase_toggle_a = 1
			self._phase_toggle_b = 1
			self._phase_last_seq_a = None
			self._phase_last_seq_b = None
			self._phase_last_ts_a = None
			self._phase_last_ts_b = None
			self._phase_last_par_a = None
			self._phase_last_par_b = None
			self._phase_repeat_a = 0
			self._phase_repeat_b = 0
			self._phase_trace_n = 0
			# Also reset validity markers so GUI won't show stale phase buffers.
			self.seq0_even = None
			self.seq0_odd = None
			self.seq1_even = None
			self.seq1_odd = None
			# Clear buffers (optional but helps avoid confusing stale plots)
			try:
				self.data0_even[:] = 0
				self.data0_odd[:] = 0
				self.data1_even[:] = 0
				self.data1_odd[:] = 0
			except Exception:
				pass
			if getattr(self, 'phase_trace', False):
				msg = f"[PHASE_RESET] {reason}".strip()
				print(msg, flush=True)
		except Exception:
			pass

	def _xcorr_even_inverted(self, even: np.ndarray, odd: np.ndarray):
		"""Compute cross-correlation between `even` and inverted `odd`.
		Returns (best_shift, best_sum, norm_corr_full, best_prod_array).
		- even, odd: 1D arrays of equal length N
		- best_shift: integer in [-(N-1)..(N-1)] (odd index = i + shift)
		- best_sum: raw (un-normalized) sum at best_shift
		- norm_corr_full: float array length 2N-1 (normalized correlation)
		- best_prod_array: length N array with per-sample products for best_shift,
		  zeros outside overlap.
		"""
		try:
			N = int(len(even))
			if N != len(odd):
				raise ValueError("even and odd must have same length")
			# convert to signed centered values (0..65535 -> around 0)
			even_s = even.astype(np.int64) - 32767
			odd_s = odd.astype(np.int64) - 32767
			# invert odd arithmetically
			odd_inv = -odd_s

			# raw cross-correlation (lags -(N-1)..(N-1))
			corr = np.correlate(even_s, odd_inv, mode='full')  # int64

			# energy for normalization: sliding sums of squared samples
			even_sq = (even_s * even_s).astype(np.int64)
			odd_sq = (odd_inv * odd_inv).astype(np.int64)
			ones = np.ones(N, dtype=np.int64)
			sum_even_sq = np.convolve(even_sq, ones, mode='full').astype(np.float64)
			sum_odd_sq = np.convolve(odd_sq, ones, mode='full').astype(np.float64)
			den = np.sqrt(sum_even_sq * sum_odd_sq)
			# avoid div by zero
			with np.errstate(invalid='ignore', divide='ignore'):
				norm_corr = corr.astype(np.float64) / (den + 1e-12)

			# choose best lag by absolute normalized correlation (scan full range)
			# this avoids selecting edge zeros and finds strongest match magnitude
			with np.errstate(invalid='ignore'):
				abs_norm = np.abs(norm_corr)
			# if all NaN/zero, fall back to raw corr
			if np.all(np.isnan(abs_norm)) or np.nanmax(abs_norm) == 0:
				best_idx = int(np.argmax(corr))
				best_sum = float(corr[best_idx])
			else:
				best_idx = int(np.nanargmax(abs_norm))
				best_sum = float(norm_corr[best_idx])
			best_shift = best_idx - (N - 1)

			# build per-sample product array for that shift (zeros outside overlap)
			prod = np.zeros(N, dtype=np.float64)
			L = best_shift
			if L >= 0:
				# odd index = i + L in [0..N-1] => i in [0..N-1-L]
				end = N - L
				if end > 0:
					_i = np.arange(0, end)
					prod[_i] = (even_s[_i].astype(np.float64) * odd_inv[_i + L].astype(np.float64))
			else:
				# L < 0: odd index = i + L => i starts at -L
				start = -L
				if start < N:
					_i = np.arange(start, N)
					prod[_i] = (even_s[_i].astype(np.float64) * odd_inv[_i + L].astype(np.float64))

			return best_shift, best_sum, norm_corr, prod
		except Exception:
			# on error, return safe defaults
			N = int(len(even)) if hasattr(even, '__len__') else 0
			return 0, 0.0, np.zeros(2 * N - 1, dtype=np.float64), np.zeros(N, dtype=np.float64)

	def _find_optimal_phase_shift(self, even: np.ndarray, odd: np.ndarray, channel_name: str = ""):
		"""Find optimal phase shift between even and inverted odd by iterating all shifts.
		
		For each shift, compute element-wise product of even and shifted inverted odd,
		then find the shift that gives maximum positive sum of all products.
		
		Args:
			even: 1D array of even samples (0..65535)
			odd: 1D array of odd samples (0..65535)
			channel_name: "ADC0" or "ADC1" for debug output
		
		Returns:
			tuple: (best_shift, peak_idx, max_sum, best_prod_array)
			- best_shift: integer shift in samples (negative = shift odd left, positive = shift odd right)
			- peak_idx: sample index of maximum in best_prod_array
			- max_sum: sum of all products at best_shift
			- best_prod_array: length N array with per-sample products at best_shift
		"""
		try:
			N = int(len(even))
			if N != len(odd) or N == 0:
				return 0, 0, 0.0, np.zeros(N, dtype=np.float64)

			# Convert to signed centered values (0..65535 -> around 0)
			even_s = even.astype(np.int64) - 32767
			odd_s = odd.astype(np.int64) - 32767
			# Invert odd arithmetically
			odd_inv = -odd_s

			# Scan range: either full or limited by env
			max_shift = int(getattr(self, 'phase_search_max_shift', 0) or 0)
			if max_shift <= 0:
				shift_start = -(N - 1)
				shift_end = N - 1
			else:
				max_shift = min(max_shift, N - 1)
				shift_start = -max_shift
				shift_end = max_shift

			best_shift = 0
			max_sum = -np.inf

			# Compute sum for each shift WITHOUT allocating full prod array per shift
			for shift in range(shift_start, shift_end + 1):
				if shift >= 0:
					end = N - shift
					if end <= 0:
						continue
					current_sum = float(np.dot(even_s[:end], odd_inv[shift:shift + end]))
				else:
					start = -shift
					if start >= N:
						continue
					# overlap length = N-start
					current_sum = float(np.dot(even_s[start:], odd_inv[:N - start]))

				if current_sum > max_sum:
					max_sum = current_sum
					best_shift = shift

			# Build product array only once for best_shift
			best_prod = np.zeros(N, dtype=np.float64)
			if best_shift >= 0:
				end = N - best_shift
				if end > 0:
					best_prod[:end] = (even_s[:end].astype(np.float64) * odd_inv[best_shift:best_shift + end].astype(np.float64))
			else:
				start = -best_shift
				if start < N:
					best_prod[start:] = (even_s[start:].astype(np.float64) * odd_inv[:N - start].astype(np.float64))

			# Peak index: maximum POSITIVE value (as per requirement)
			best_peak_idx = int(np.argmax(best_prod)) if best_prod.size else 0

			if bool(getattr(self, 'xcorr_debug', False)):
				print(f"[PHASE_SHIFT_{channel_name}] best_shift={best_shift} peak_idx={best_peak_idx} max_sum={max_sum:.2e}", flush=True)

			return best_shift, best_peak_idx, max_sum, best_prod
		except Exception as e:
			if bool(getattr(self, 'xcorr_debug', False)):
				print(f"[PHASE_SHIFT_{channel_name}] ERROR: {e}", flush=True)
			N = int(len(even)) if hasattr(even, '__len__') else 0
			return 0, 0, 0.0, np.zeros(N, dtype=np.float64)

	def _phase_search_thread_main(self):
		"""Single long-lived worker: always processes the latest requested buffers.

		Important: this avoids spawning a new thread per packet. If packets arrive faster
		than computation, intermediate requests are dropped and only the latest snapshot
		is processed (which is what we want for live oscilloscope).
		"""
		try:
			if bool(getattr(self, 'xcorr_debug', False)):
				print("[PHASE_WORKER] thread started", flush=True)
			while True:
				self._phase_search_event.wait()
				self._phase_search_event.clear()
				if getattr(self, '_phase_search_stop', False):
					return
				with self._phase_search_req_lock:
					payload = self._phase_search_latest
					self._phase_search_latest = None
				if payload is None:
					continue
				N, e0, o0, e1, o1 = payload
				self._phase_search_running = True

				# Compute optimal phase shift for ADC0/ADC1
				shift0, peak_idx0, max_sum0, prod0 = self._find_optimal_phase_shift(e0, o0, "ADC0")
				shift1, peak_idx1, max_sum1, prod1 = self._find_optimal_phase_shift(e1, o1, "ADC1")

				with self.data_lock:
					self._phase_shift_adc0 = shift0
					self._phase_peak_idx_adc0 = peak_idx0
					self._phase_max_sum_adc0 = max_sum0
					if self._phase_prod_adc0 is None or len(self._phase_prod_adc0) != N:
						self._phase_prod_adc0 = np.zeros(N, dtype=np.float64)
					self._phase_prod_adc0[:N] = prod0[:N]

					self._phase_shift_adc1 = shift1
					self._phase_peak_idx_adc1 = peak_idx1
					self._phase_max_sum_adc1 = max_sum1
					if self._phase_prod_adc1 is None or len(self._phase_prod_adc1) != N:
						self._phase_prod_adc1 = np.zeros(N, dtype=np.float64)
					self._phase_prod_adc1[:N] = prod1[:N]

				if bool(getattr(self, 'xcorr_debug', False)):
					print(
						f"[PHASE_WORKER] done: ADC0 shift={shift0} sum={max_sum0:.2e} peak={peak_idx0}; "
						f"ADC1 shift={shift1} sum={max_sum1:.2e} peak={peak_idx1}",
						flush=True,
					)
				self._phase_search_running = False
		except Exception as e:
			self._phase_search_running = False
			if bool(getattr(self, 'xcorr_debug', False)):
				print(f"[PHASE_WORKER] ERROR: {e}", flush=True)

	def _ensure_phase_search_thread(self):
		if self._phase_search_thread is not None and self._phase_search_thread.is_alive():
			return
		self._phase_search_stop = False
		self._phase_search_thread = threading.Thread(target=self._phase_search_thread_main, daemon=True)
		self._phase_search_thread.start()

	def _request_phase_shift_search(self):
		"""Request (enqueue) phase shift search for the latest buffers.

		Called after each packet reception. This does not block and does not start
		new threads; it only updates the 'latest' snapshot for the worker.
		"""
		if not bool(getattr(self, 'phase_search_each_packet', True)):
			return
		if not bool(getattr(self, '_phase_search_enabled', False)):
			return
		# Copy current data under lock
		with self.data_lock:
			N = int(self.base_buf_len) if getattr(self, 'base_buf_len', None) else int(getattr(self, 'view_len', self.max_samples))
			N = max(1, min(N, self.max_samples))
			e0 = np.array(self.data0_even[:N], copy=True)
			o0 = np.array(self.data0_odd[:N], copy=True)
			e1 = np.array(self.data1_even[:N], copy=True)
			o1 = np.array(self.data1_odd[:N], copy=True)
		if N <= 1:
			return
		self._ensure_phase_search_thread()
		with self._phase_search_req_lock:
			self._phase_search_latest = (N, e0, o0, e1, o1)
		self._phase_search_event.set()

	def _on_num_clicked_extra(self, idx: int):
		"""Extra handler for numeric buttons — button 6 triggers cross-correlation display."""
		try:
			if int(idx) != 6:
				return
		except Exception:
			return

		# lazy-init timer for continuous recompute
		if not hasattr(self, '_corr_timer') or self._corr_timer is None:
			self._corr_timer = QtCore.QTimer()
			# call compute every 200 ms (5 Hz) — responsive but light
			self._corr_timer.setInterval(200)
			self._corr_timer.timeout.connect(self._compute_and_plot_xcorr)

		# if button is checked -> start continuous recompute, else stop
		try:
			if self.num_buttons[6].isChecked():
				# immediate compute once, then start timer
				# make correlation curves visible and compute
				try:
					self.corr0.setVisible(True)
					self.corr1.setVisible(True)
				except Exception:
					pass
				self._compute_and_plot_xcorr()
				self._corr_timer.start()
				self._set_status('XCorr: continuous', hold_sec=1.0)
			else:
				if hasattr(self, '_corr_timer'):
					self._corr_timer.stop()
				# hide and clear corr plots
				try:
					self.corr0.setData([], [])
					self.corr1.setData([], [])
					self.corr0.setVisible(False)
					self.corr1.setVisible(False)
				except Exception:
					pass
					# reset saved bests
					try:
						self._xcorr_saved_peak0 = 0.0
						self._xcorr_saved_peak1 = 0.0
						self._xcorr_saved_prod0.fill(0)
						self._xcorr_saved_prod1.fill(0)
					except Exception:
						pass
					self._set_status('XCorr: stopped', hold_sec=1.0)
		except Exception:
			pass

	def _compute_and_plot_xcorr(self):
		"""Compute cross-correlation for both channels and update plots/legend."""
		# Measure real update rate of this overlay (how often we actually redraw in mode 6)
		try:
			_now = time.time()
			self._xcorr_frames = int(getattr(self, '_xcorr_frames', 0)) + 1
			t0 = float(getattr(self, '_xcorr_fps_t0', _now))
			if (_now - t0) >= 1.0:
				self._xcorr_fps = float(self._xcorr_frames) / max(1e-6, (_now - t0))
				self._xcorr_frames = 0
				self._xcorr_fps_t0 = _now
		except Exception:
			pass

		with self.data_lock:
			N = int(self.base_buf_len) if getattr(self, 'base_buf_len', None) else int(getattr(self, 'view_len', self.max_samples))
			N = max(1, min(N, self.max_samples))
			# copy raw buffers (unsigned 0..65535 stored as ints) and keep as float for DC ops
			e0_raw = np.array(self.data0_even[:N], copy=True).astype(np.float64)
			o0_raw = np.array(self.data0_odd[:N], copy=True).astype(np.float64)
			e1_raw = np.array(self.data1_even[:N], copy=True).astype(np.float64)
			o1_raw = np.array(self.data1_odd[:N], copy=True).astype(np.float64)

		if N <= 1:
			return

		# Use raw inputs as-is (0..65535). Device already provides DC-compensated signals.
		# Keep *_raw arrays for computations and diagnostics; do not center/subtract DC here.
		e0 = e0_raw
		o0 = o0_raw
		e1 = e1_raw
		o1 = o1_raw

		# Diagnostic (optional): show means/std
		if bool(getattr(self, 'xcorr_debug', False)):
			try:
				print(f"[XCORR] N={N} stream_mode={getattr(self,'stream_mode',None)} avg_n={getattr(self,'avg_n',None)} avg20_enabled={getattr(self,'avg20_enabled',False)} dc_removal={getattr(self,'dc_removal_enabled',False)}")
				print(f"[XCORR] ch0 mean_even={float(np.mean(e0)):.2f} std_even={float(np.std(e0)):.2f} mean_odd={float(np.mean(o0)):.2f} std_odd={float(np.std(o0)):.2f}")
				print(f"[XCORR] ch1 mean_even={float(np.mean(e1)):.2f} std_even={float(np.std(e1)):.2f} mean_odd={float(np.mean(o1)):.2f} std_odd={float(np.std(o1)):.2f}")
			except Exception:
				pass

		# ---- Use optimal phase shift if available, otherwise simple per-sample product (no lag) ----
		# Compute centered signed product so sign/doubling behavior is correct.
		# В режиме XCorr-norm=ON показываем центрированный продукт и авто-масштабируем.
		# В режиме XCorr-norm=OFF фиксируем шкалу 0..65535 и сдвигаем данные в этот диапазон.
		try:
			# Check if optimal phase shift results are available
			with self.data_lock:
				use_optimal = (self._phase_prod_adc0 is not None and self._phase_prod_adc1 is not None)
				if use_optimal:
					# Use pre-computed optimal phase-shifted products
					prod0_center = np.array(self._phase_prod_adc0[:N], copy=True)
					prod1_center = np.array(self._phase_prod_adc1[:N], copy=True)
					shift0 = self._phase_shift_adc0
					shift1 = self._phase_shift_adc1
				else:
					shift0 = 0
					shift1 = 0
			
			if not use_optimal:
				# Fallback: compute simple per-sample product with no shift
				# centered (signed) signals: 0..65535 -> roughly -32767..+32768
				even0_c = e0_raw.astype(np.float64) - 32767.0
				odd0_c = o0_raw.astype(np.float64) - 32767.0
				even1_c = e1_raw.astype(np.float64) - 32767.0
				odd1_c = o1_raw.astype(np.float64) - 32767.0

				# inverted odd (signed)
				odd0_inv_c = -odd0_c
				odd1_inv_c = -odd1_c

				# centered per-sample product (can be negative)
				prod0_center = even0_c * odd0_inv_c
				prod1_center = even1_c * odd1_inv_c

			# normalize centered product to approx [-1..1] dividing by max possible (32768^2)
			denom = (32768.0 * 32768.0)
			prod0_norm = prod0_center / (denom + 1e-12)
			prod1_norm = prod1_center / (denom + 1e-12)

			xcorr_norm = bool(getattr(self, 'xcorr_norm_enabled', True))
			if xcorr_norm:
				# авто-масштаб вокруг 0
				self._xcorr_prod_scale = 1.0
				prod0_raw = prod0_center
				prod1_raw = prod1_center
			else:
				# фиксированная шкала 0..65535: продукт слишком большой, поэтому масштабируем.
				# По умолчанию делим на 100 (можно переопределить BMI30_PROD_SCALE).
				try:
					scale = float(os.getenv('BMI30_PROD_SCALE', '100'))
					if not np.isfinite(scale) or scale == 0.0:
						scale = 100.0
				except Exception:
					scale = 100.0
				self._xcorr_prod_scale = float(scale)
				prod0_raw = (prod0_center / scale) + 32767.0
				prod1_raw = (prod1_center / scale) + 32767.0
				try:
					prod0_raw = np.clip(prod0_raw, 0.0, 65535.0)
					prod1_raw = np.clip(prod1_raw, 0.0, 65535.0)
				except Exception:
					pass

			# keep centered product for diagnostics/legend
			prod0 = prod0_center
			prod1 = prod1_center
		except Exception:
			prod0_raw = np.zeros_like(e0_raw)
			prod1_raw = np.zeros_like(e1_raw)
			prod0 = np.zeros_like(e0_raw)
			prod1 = np.zeros_like(e1_raw)
			use_optimal = False
			shift0 = 0
			shift1 = 0

		# Only display correlation when button 6 is active; otherwise clear/hide
		try:
			if not (hasattr(self, 'num_buttons') and len(self.num_buttons) > 6 and self.num_buttons[6].isChecked()):
				# ensure cleared
				try:
					self.corr0.setData([], [])
					self.corr1.setData([], [])
				except Exception:
					pass
				return
		except Exception:
			# if anything goes wrong, bail safely
			return

		# prod0_raw/prod1_raw are currently centered per-sample products (can be negative); sanitize NaNs
		try:
			prod0_raw = np.nan_to_num(prod0_raw)
			prod1_raw = np.nan_to_num(prod1_raw)
		except Exception:
			prod0_raw = np.zeros(N, dtype=np.float64)
			prod1_raw = np.zeros(N, dtype=np.float64)
		# display length (pad to at least 200 for consistency)
		try:
			min_display = max(200, N)
			pad0 = np.zeros(min_display, dtype=np.float64)
			pad1 = np.zeros(min_display, dtype=np.float64)
			# fill with centered products (can be negative)
			pad0[:N] = prod0_raw[:N]
			pad1[:N] = prod1_raw[:N]
			self._xcorr_saved_prod0[:min_display] = pad0
			self._xcorr_saved_prod1[:min_display] = pad1
		except Exception:
			min_display = N

		# diagnostic: show current prod stats (optional)
		if bool(getattr(self, 'xcorr_debug', False)):
			try:
				print(f"[XCORR-PROD] centered ch0 min={float(np.min(prod0)):.3f} max={float(np.max(prod0)):.3f} mean={float(np.mean(prod0)):.3f}")
				print(f"[XCORR-PROD] centered ch1 min={float(np.min(prod1)):.3f} max={float(np.max(prod1)):.3f} mean={float(np.mean(prod1)):.3f}")
				print(f"[XCORR-DISP] ch0 disp prod min={float(np.min(prod0_raw)):.3f} max={float(np.max(prod0_raw)):.3f} mean={float(np.mean(prod0_raw)):.3f}")
				print(f"[XCORR-DISP] ch1 disp prod min={float(np.min(prod1_raw)):.3f} max={float(np.max(prod1_raw)):.3f} mean={float(np.mean(prod1_raw)):.3f}")
			except Exception:
				pass

		# plot raw-domain simple-product arrays (0..65535) on same scale as inputs
		try:
			x = np.arange(0, min_display, dtype=np.int32)
			self.corr0.setData(x, self._xcorr_saved_prod0[:min_display])
			self.corr1.setData(x, self._xcorr_saved_prod1[:min_display])
			try:
				xcorr_norm = bool(getattr(self, 'xcorr_norm_enabled', True))
				# В режиме OFF фиксируем шкалу для обоих каналов.
				if hasattr(self, 'vb_corr0'):
					if xcorr_norm:
						# symmetric around 0 based on a *stable* magnitude (leaky peak) to avoid flicker
						vals = self._xcorr_saved_prod0[:min_display]
						mag_cur = float(np.max(np.abs(vals))) if vals.size else 1.0
						mag_cur = max(1.0, mag_cur)
						mag_prev = float(getattr(self, '_xcorr_mag0', mag_cur))
						mag = max(mag_cur, mag_prev * 0.90)
						self._xcorr_mag0 = mag
						try:
							self.vb_corr0.setYRange(-mag * 1.05, mag * 1.05, padding=0.0)
						except Exception:
							self.vb_corr0.autoRange()
					else:
						self.vb_corr0.setYRange(0.0, 65535.0, padding=0.0)
			except Exception:
				pass
			try:
				if hasattr(self, 'vb_corr1'):
					if xcorr_norm:
						vals = self._xcorr_saved_prod1[:min_display]
						mag_cur = float(np.max(np.abs(vals))) if vals.size else 1.0
						mag_cur = max(1.0, mag_cur)
						mag_prev = float(getattr(self, '_xcorr_mag1', mag_cur))
						mag = max(mag_cur, mag_prev * 0.90)
						self._xcorr_mag1 = mag
						try:
							self.vb_corr1.setYRange(-mag * 1.05, mag * 1.05, padding=0.0)
						except Exception:
							self.vb_corr1.autoRange()
					else:
						self.vb_corr1.setYRange(0.0, 65535.0, padding=0.0)
			except Exception:
				pass
		except Exception:
			try:
				self.corr0.setData([], [])
				self.corr1.setData([], [])
			except Exception:
				pass

		# legend text is updated centrally in _tick (stable 3 lines)
		try:
			xcorr_norm = bool(getattr(self, 'xcorr_norm_enabled', True))
			mode = "norm" if xcorr_norm else "0..65535"
			try:
				_sc = float(getattr(self, '_xcorr_prod_scale', 1.0))
				if not np.isfinite(_sc) or _sc == 0.0:
					_sc = 1.0
			except Exception:
				_sc = 1.0
			mean0 = float(np.mean(prod0))
			mean1 = float(np.mean(prod1))
			if not xcorr_norm:
				mean0 = mean0 / _sc
				mean1 = mean1 / _sc
			if use_optimal:
				self._xcorr_last_summary = f"XCORR[{mode}] sh0={int(shift0)} sh1={int(shift1)} mean0={mean0:.1f} mean1={mean1:.1f}"
			else:
				self._xcorr_last_summary = f"XCORR[{mode}] no-shift mean0={mean0:.1f} mean1={mean1:.1f}"
		except Exception:
			self._xcorr_last_summary = "XCORR: error"

		# --- Signal detection hook: use product-array maximum (same data as corr graph) ---
		try:
			# Robust fallback: if centered product arrays are not available (due to earlier error),
			# fall back to whatever `prod0/prod1` contain (zeros-safe).
			try:
				prod0c = prod0_center
				prod1c = prod1_center
			except NameError:
				prod0c = prod0
				prod1c = prod1
			# Also track raw amplitude (what you visually see on the oscilloscope): abs(u16-32768)
			try:
				amp0 = float(max(np.nanmax(np.abs(e0_raw - 32767.0)), np.nanmax(np.abs(o0_raw - 32767.0))))
				amp1 = float(max(np.nanmax(np.abs(e1_raw - 32767.0)), np.nanmax(np.abs(o1_raw - 32767.0))))
				self._det_last_amp0 = int(max(0, min(32768, int(amp0))))
				self._det_last_amp1 = int(max(0, min(32768, int(amp1))))
			except Exception:
				pass
			# Always record raw product maxima for diagnostics (centered product units).
			try:
				with np.errstate(invalid='ignore'):
					self._det_last_prodmax0 = float(np.nanmax(np.abs(prod0c))) if prod0c is not None and getattr(prod0c, 'size', 0) else 0.0
					self._det_last_prodmax1 = float(np.nanmax(np.abs(prod1c))) if prod1c is not None and getattr(prod1c, 'size', 0) else 0.0
			except Exception:
				pass
			# Feed detector with selected source (default: raw product max).
			src = str(getattr(self, '_det_source', 'norm') or 'norm').strip().lower()
			if src in ('raw', 'product'):
				src = 'prod'
			if src == 'prod':
				self._update_signal_detection(prod0c, prod1c, int(shift0), int(shift1), source='prod')
			else:
				self._update_signal_detection(prod0_norm, prod1_norm, int(shift0), int(shift1), source='norm')
			# Optional: continuous PWM output proportional to current phase shift while correlation view is active.
			try:
				if str(getattr(self, '_beep_mode', 'pattern')) == 'continuous':
					try:
						if int(getattr(self, '_beep_force_mode', 0)) == -1:
							return
					except Exception:
						pass
					# Choose a representative shift (largest magnitude) and map into a frequency band.
					s0 = int(shift0)
					s1 = int(shift1)
					use_s = s0 if abs(s0) >= abs(s1) else s1
					# If shift is near zero, silence output to avoid constant tone.
					if abs(int(use_s)) <= 0:
						self._beeper.set_continuous(None)
					else:
						# Use a broad band so it's visible on scope.
						f = self._shift_to_beep_freq(use_s, 1000.0, 4000.0)
						self._beeper.set_continuous(float(f))
			except Exception:
				pass
		except Exception:
			pass

	def _device_set_dc_adapt(self, enabled: bool):
		"""Toggle device-side DC adaptation if supported by firmware."""
		try:
			if self.stream is None:
				return
			payload = b"\x01" if bool(enabled) else b"\x00"
			self.stream.send_cmd(CMD_SET_DC_ADAPT, payload)
		except Exception:
			pass

	def _device_calib_dc_fast(self, frames: int):
		"""Trigger fast device-side DC calibration for a number of frames."""
		try:
			if self.stream is None:
				return
			f = int(frames)
			if f <= 0:
				return
			if f > 255:
				f = 255
			self.stream.send_cmd(CMD_CALIB_DC_FAST, bytes([f & 0xFF]))
		except Exception:
			pass

	def _det_reset_and_arm_warmup(self, reason: str = ""):
		"""Force detector into RUN state and arm warmup window.

		Goal: right after startup/connect, we should never remain FROZEN.
		Warmup starts from the first connection/stream start (not from GUI launch).
		"""
		_now = time.time()
		try:
			warm = float(getattr(self, '_det_warmup_sec', 2.0) or 0.0)
			if (not np.isfinite(warm)) or warm < 0.0:
				warm = 2.0
		except Exception:
			warm = 2.0
		try:
			self._det_warmup_until = float(_now + warm)
		except Exception:
			self._det_warmup_until = float(_now)
		try:
			self._det_warmup_dc_fix_last_t = 0.0
			self._det_dc_frozen = False
			self._det_hold0 = False
			self._det_hold1 = False
			self._det_exceed0 = 0
			self._det_exceed1 = 0
			self._det_start_consec0 = 0
			self._det_start_consec1 = 0
			self._det_hits0 = deque(maxlen=12)
			self._det_hits1 = deque(maxlen=12)
			self._det_last_pair_key0 = None
			self._det_last_pair_key1 = None
			self._det_exceed_peak0 = None
			self._det_exceed_peak1 = None
			self._det_freeze_thr0 = 0
			self._det_freeze_thr1 = 0
			# Reset threshold adaptation to avoid inheriting stale values across reconnects.
			# НО: если пороги уже были восстановлены (>0), сохраняем их для быстрой подстройки
			if not (hasattr(self, '_det_thr0') and self._det_thr0 > 0):
				self._det_thr0 = int(getattr(self, '_det_thr_init', 0) or 0)
			if not (hasattr(self, '_det_thr1') and self._det_thr1 > 0):
				self._det_thr1 = int(getattr(self, '_det_thr_init', 0) or 0)
			self._det_last_fire_t = 0.0
			self._det_last_present_t0 = float(_now)
			self._det_last_present_t1 = float(_now)
		except Exception:
			pass
		# Best effort: ensure device DC adaptation is ON immediately.
		try:
			self._device_set_dc_adapt(True)
		except Exception:
			pass
		try:
			self._beep_hold_stop()
		except Exception:
			pass

	def _shift_to_beep_freq(self, shift: int, f_min: float, f_max: float) -> float:
		"""Map absolute phase shift into a frequency within [f_min..f_max]."""
		try:
			max_shift = int(getattr(self, 'phase_search_max_shift', 0) or 0)
		except Exception:
			max_shift = 0
		den = float(max_shift) if max_shift > 0 else 32.0
		frac = min(1.0, max(0.0, float(abs(int(shift))) / den))
		return float(f_min + frac * (float(f_max) - float(f_min)))

	def _beep_hold_start(self, fired0: bool, fired1: bool, shift0: int, shift1: int, lvl0: int, lvl1: int):
		"""Optionally enable continuous PWM while in detection HOLD."""
		try:
			try:
				if int(getattr(self, '_beep_force_mode', 0)) == -1:
					return
			except Exception:
				pass
			if not bool(getattr(self, '_beep_hold_enabled', False)):
				return
			# Do not interfere with explicit debug modes
			bm = str(getattr(self, '_beep_mode', 'pattern') or 'pattern')
			if bm in ('continuous', 'sweep'):
				return
			if bool(getattr(self, '_beep_sweep_enabled', False)):
				return
			# Choose the channel to represent when both fire
			use_ch = None
			if fired0 and fired1:
				use_ch = 0 if int(lvl0) >= int(lvl1) else 1
			elif fired0:
				use_ch = 0
			elif fired1:
				use_ch = 1
			if use_ch is None:
				return
			# Use the same mapping as the second tone (phase-dependent)
			if use_ch == 0:
				freq = float(self._shift_to_beep_freq(int(shift0), float(self._beep_adc0_min), float(self._beep_adc0_max)))
			else:
				freq = float(self._shift_to_beep_freq(int(shift1), float(self._beep_adc1_min), float(self._beep_adc1_max)))
			self._beep_hold_active = True
			self._beep_hold_freq = float(freq)
			now = time.time()
			delay = float(getattr(self, '_beep_hold_delay_s', 0.40) or 0.40)
			self._beep_hold_after_t = now + max(0.0, delay)
		except Exception:
			pass

	def _beep_hold_stop(self):
		"""Stop continuous PWM used for HOLD."""
		try:
			self._beep_hold_active = False
			self._beep_hold_freq = 0.0
			self._beep_hold_after_t = 0.0
			# Do not stop PWM if user forced it ON from the GUI.
			_force_mode = int(getattr(self, '_beep_force_mode', 0) or 0)
			if _force_mode == -1:
				try:
					self._beeper.set_continuous(None)
				except Exception:
					pass
			elif not bool(getattr(self, '_beep_force_enabled', False)):
				try:
					self._beeper.set_continuous(None)
				except Exception:
					pass
		except Exception:
			pass

	def _fire_beep(self, fired0: bool, fired1: bool, shift0: int, shift1: int):
		"""Generate PWM beeps. Single PWM output -> play patterns sequentially if both channels fire."""
		try:
			try:
				if int(getattr(self, '_beep_force_mode', 0)) == -1:
					return
			except Exception:
				pass
			# Compute second-tone frequencies
			f2_0 = self._shift_to_beep_freq(shift0, self._beep_adc0_min, self._beep_adc0_max)
			f2_1 = self._shift_to_beep_freq(shift1, self._beep_adc1_min, self._beep_adc1_max)
			# If both fired and phase shifts equal, enforce equal second-tone frequency (within intersection)
			if fired0 and fired1 and int(shift0) == int(shift1):
				f2_common = self._shift_to_beep_freq(shift0, 2000.0, 3000.0)
				f2_0 = float(np.clip(f2_common, self._beep_adc0_min, self._beep_adc0_max))
				f2_1 = float(np.clip(f2_common, self._beep_adc1_min, self._beep_adc1_max))
			# Play patterns (sequential)
			if fired0:
				self._beeper.play_pattern(self._beep_adc0_base, f2_0)
				if fired1:
					time.sleep(0.25)
			if fired1:
				self._beeper.play_pattern(self._beep_adc1_base, f2_1)
		except Exception:
			pass

	def _capture_current_key(self):
		"""Return a key that changes only when a new frame arrives."""
		try:
			se0 = getattr(self, 'seq0_even', None)
			so0 = getattr(self, 'seq0_odd', None)
			se1 = getattr(self, 'seq1_even', None)
			so1 = getattr(self, 'seq1_odd', None)
			lf = float(getattr(self, 'last_frame_t', 0.0) or 0.0)
			if se0 is None and so0 is None and se1 is None and so1 is None and lf <= 0.0:
				return None
			return (se0, so0, se1, so1, lf)
		except Exception:
			return None

	def _capture_push_frame(self):
		"""Push current frame data to circular buffer (called from _tick after data update)."""
		if not bool(getattr(self, '_auto_capture_enabled', False)):
			return
		try:
			# Skip if no new frame since last push (prevents duplicate ticks)
			cur_key = self._capture_current_key()
			if cur_key is None:
				return
			if cur_key == getattr(self, '_capture_last_key', None):
				return
			with self.data_lock:
				# Копируем корреляционные массивы (уже вычисленные в _xcorr_compute)
				prod0_arr = None
				prod1_arr = None
				if hasattr(self, '_xcorr_saved_prod0') and hasattr(self, '_xcorr_saved_prod1'):
					try:
						# Копируем корреляционные данные
						prod0_arr = np.copy(self._xcorr_saved_prod0[:self.base_buf_len]) if self.base_buf_len else None
						prod1_arr = np.copy(self._xcorr_saved_prod1[:self.base_buf_len]) if self.base_buf_len else None
					except Exception:
						pass
				
				# Copy current frame data (all 4 arrays: even/odd for both channels)
				frame = {
					'timestamp': time.time(),
					'seq0_even': getattr(self, 'seq0_even', None),
					'seq0_odd': getattr(self, 'seq0_odd', None),
					'seq1_even': getattr(self, 'seq1_even', None),
					'seq1_odd': getattr(self, 'seq1_odd', None),
					'data0_even': np.copy(self.data0_even[:self.base_buf_len]) if self.base_buf_len else None,
					'data0_odd': np.copy(self.data0_odd[:self.base_buf_len]) if self.base_buf_len else None,
					'data1_even': np.copy(self.data1_even[:self.base_buf_len]) if self.base_buf_len else None,
					'data1_odd': np.copy(self.data1_odd[:self.base_buf_len]) if self.base_buf_len else None,
					'prod0': prod0_arr,  # Корреляционный массив ch0
					'prod1': prod1_arr,  # Корреляционный массив ch1
					'base_buf_len': self.base_buf_len,
					'freq_hz': self.freq_hz,
					'avg_n': getattr(self, 'avg_n', 20),
					'stream_mode': getattr(self, 'stream_mode', 0),
					# Detector state
					'det_thr0': getattr(self, '_det_thr0', 0),
					'det_thr1': getattr(self, '_det_thr1', 0),
					'det_lvl0': getattr(self, '_det_last_lvl0', 0),
					'det_lvl1': getattr(self, '_det_last_lvl1', 0),
					'det_shift0': getattr(self, '_det_last_shift0', 0),
					'det_shift1': getattr(self, '_det_last_shift1', 0),
					'det_amp0': getattr(self, '_det_last_amp0', 0),
					'det_amp1': getattr(self, '_det_last_amp1', 0),
					'det_hold0': getattr(self, '_det_hold0', False),
					'det_hold1': getattr(self, '_det_hold1', False),
					'det_frozen': getattr(self, '_det_dc_frozen', False),
				}
			with self._capture_buffer_lock:
				self._capture_buffer.append(frame)
				# Keep only last N frames
				max_size = int(getattr(self, '_capture_buffer_size', 50))
				if len(self._capture_buffer) > max_size:
					self._capture_buffer.pop(0)
			# Mark last pushed key
			self._capture_last_key = cur_key
		except Exception as e:
			if bool(getattr(self, 'debug', False)):
				print(f"[CAPTURE] Error pushing frame: {e}", flush=True)

	def _capture_trigger(self, reason: str = ''):
		"""Trigger capture session on detection fire."""
		auto_cap = bool(getattr(self, '_auto_capture_enabled', False))
		print(f"\n*** [CAPTURE] Trigger called: enabled={auto_cap}, reason={reason} ***\n", flush=True)
		if not auto_cap:
			print(f"[CAPTURE] Trigger skipped - disabled", flush=True)
			return
		try:
			state = str(getattr(self, '_capture_state', 'idle'))
			if state != 'idle':
				print(f"[CAPTURE] Trigger skipped - state={state}", flush=True)
				return  # Already capturing
			self._capture_state = 'triggered'
			print(f"[CAPTURE] Session starting...", flush=True)
			# Initialize session
			self._capture_session = {
				'trigger_time': time.time(),
				'reason': str(reason),
				'frames': [],  # Will collect PRE + HOLD + POST frames
				'metadata': {
					'profile': getattr(self, 'desired_profile', 1),
					'freq_hz': getattr(self, 'freq_hz', 200),
					'avg_n': getattr(self, 'avg_n', 20),
					'stream_mode': getattr(self, 'stream_mode', 0),
					'det_source': getattr(self, '_det_source', 'norm'),
					'det_ratio': getattr(self, '_det_ratio0', 2.0),
					'det_ratio0': getattr(self, '_det_ratio0', 2.0),
					'det_ratio1': getattr(self, '_det_ratio1', 2.0),
					'det_add0': getattr(self, '_det_add0', 100),
					'det_add1': getattr(self, '_det_add1', 100),
					'pre_frames': int(getattr(self, '_capture_pre_frames', 30)),
				}
			}
			# Copy PRE frames from circular buffer
			with self._capture_buffer_lock:
				pre_count = min(len(self._capture_buffer), int(getattr(self, '_capture_pre_frames', 30)))
				if pre_count > 0:
					self._capture_session['frames'].extend(self._capture_buffer[-pre_count:])
			# Mark trigger index (frame after PRE)
			self._capture_trigger_index = len(self._capture_session['frames'])
			self._capture_last_record_key = None
			self._capture_frames_recorded = len(self._capture_session['frames'])
			self._capture_post_countdown = 0
			self._capture_state = 'recording'
			print(f"\n*** [CAPTURE] ✓✓✓ Session started: PRE={self._capture_frames_recorded} frames ***\n", flush=True)
		except Exception as e:
			print(f"[CAPTURE] Error triggering session: {e}", flush=True)
			self._capture_state = 'idle'

	def _capture_record_frame(self) -> bool:
		"""Record current frame during active capture session (HOLD phase)."""
		if not bool(getattr(self, '_auto_capture_enabled', False)):
			return False
		try:
			state = str(getattr(self, '_capture_state', 'idle'))
			if state not in ('recording', 'finalizing'):
				return False
			# Skip if no new frame since last record
			cur_key = self._capture_current_key()
			if cur_key is None:
				return False
			if cur_key == getattr(self, '_capture_last_record_key', None):
				return False
			# Проверка: если достигли максимума фреймов, переходим в POST фазу (только в recording)
			if state == 'recording':
				max_frames = int(getattr(self, '_capture_max_frames', 41))
				current_count = len(self._capture_session.get('frames', []))
				if current_count >= max_frames:
					# Переходим в POST фазу (досрочно)
					print(f"[CAPTURE] Max frames reached ({current_count}/{max_frames}), starting POST phase", flush=True)
					self._capture_start_post()
					return False
			# Copy current frame (same as _capture_push_frame but directly to session)
			with self.data_lock:
				# Копируем корреляционные массивы (уже вычисленные в _xcorr_compute)
				prod0_arr = None
				prod1_arr = None
				if hasattr(self, '_xcorr_saved_prod0') and hasattr(self, '_xcorr_saved_prod1'):
					try:
						# Копируем корреляционные данные
						prod0_arr = np.copy(self._xcorr_saved_prod0[:self.base_buf_len]) if self.base_buf_len else None
						prod1_arr = np.copy(self._xcorr_saved_prod1[:self.base_buf_len]) if self.base_buf_len else None
					except Exception:
						pass
				
				frame = {
					'timestamp': time.time(),
					'seq0_even': getattr(self, 'seq0_even', None),
					'seq0_odd': getattr(self, 'seq0_odd', None),
					'seq1_even': getattr(self, 'seq1_even', None),
					'seq1_odd': getattr(self, 'seq1_odd', None),
					'data0_even': np.copy(self.data0_even[:self.base_buf_len]) if self.base_buf_len else None,
					'data0_odd': np.copy(self.data0_odd[:self.base_buf_len]) if self.base_buf_len else None,
					'data1_even': np.copy(self.data1_even[:self.base_buf_len]) if self.base_buf_len else None,
					'data1_odd': np.copy(self.data1_odd[:self.base_buf_len]) if self.base_buf_len else None,
					'prod0': prod0_arr,  # Корреляционный массив ch0
					'prod1': prod1_arr,  # Корреляционный массив ch1
					'base_buf_len': self.base_buf_len,
					'freq_hz': self.freq_hz,
					'avg_n': getattr(self, 'avg_n', 20),
					'stream_mode': getattr(self, 'stream_mode', 0),
					'det_thr0': getattr(self, '_det_thr0', 0),
					'det_thr1': getattr(self, '_det_thr1', 0),
					'det_lvl0': getattr(self, '_det_last_lvl0', 0),
					'det_lvl1': getattr(self, '_det_last_lvl1', 0),
					'det_shift0': getattr(self, '_det_last_shift0', 0),
					'det_shift1': getattr(self, '_det_last_shift1', 0),
					'det_amp0': getattr(self, '_det_last_amp0', 0),
					'det_amp1': getattr(self, '_det_last_amp1', 0),
					'det_hold0': getattr(self, '_det_hold0', False),
					'det_hold1': getattr(self, '_det_hold1', False),
					'det_frozen': getattr(self, '_det_dc_frozen', False),
				}
			if hasattr(self, '_capture_session') and self._capture_session:
				self._capture_session['frames'].append(frame)
				self._capture_frames_recorded += 1
				self._capture_last_record_key = cur_key
				return True
		except Exception as e:
			if bool(getattr(self, 'debug', False)):
				print(f"[CAPTURE] Error recording frame: {e}", flush=True)
		return False

	def _capture_start_post(self):
		"""Start POST frame countdown (signal lost, capture last N frames)."""
		if not bool(getattr(self, '_auto_capture_enabled', False)):
			return
		try:
			state = str(getattr(self, '_capture_state', 'idle'))
			if state != 'recording':
				return
			self._capture_state = 'finalizing'
			post_frames = int(getattr(self, '_capture_post_frames', 10))
			# enforce at least 4 post frames
			self._capture_post_countdown = max(4, post_frames)
			self._capture_post_started = time.time()
			print(f"\n*** [CAPTURE] → POST phase, countdown={self._capture_post_countdown} ***\n", flush=True)
		except Exception as e:
			if bool(getattr(self, 'debug', False)):
				print(f"[CAPTURE] Error starting POST: {e}", flush=True)

	def _capture_finalize(self):
		"""Finalize and save capture session to NPZ file."""
		auto_cap = bool(getattr(self, '_auto_capture_enabled', False))
		print(f"\n*** [CAPTURE] Finalize called: enabled={auto_cap} ***\n", flush=True)
		if not auto_cap:
			print(f"[CAPTURE] Finalize skipped - disabled", flush=True)
			return
		try:
			has_session = hasattr(self, '_capture_session') and bool(self._capture_session)
			print(f"[CAPTURE] Has session: {has_session}", flush=True)
			if not has_session:
				print(f"[CAPTURE] No session to finalize", flush=True)
				self._capture_state = 'idle'
				return
			# Generate filename with timestamp and label
			ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
			label_state = int(getattr(self, '_capture_label_state', 0))
			label_suffix = ["_unk", "_lbl", "_nolbl"][label_state]  # unknown/labeled/no-label
			filename = f"capture_{ts}{label_suffix}.npz"
			capture_dir = str(getattr(self, '_capture_dir', './captures'))
			# Ensure directory exists before saving
			try:
				os.makedirs(capture_dir, exist_ok=True)
			except Exception as e:
				print(f"[CAPTURE] Не удалось создать папку {capture_dir}: {e}", flush=True)
				self._capture_state = 'idle'
				self._capture_session = None
				return
			filepath = os.path.join(capture_dir, filename)
			
			# Prepare arrays for NPZ
			frames = self._capture_session.get('frames', [])
			n_frames = len(frames)
			if n_frames == 0:
				self._capture_state = 'idle'
				self._capture_session = None
				return
			
			# Determine max buffer length
			max_len = max((f.get('base_buf_len', 0) or 0) for f in frames)
			if max_len == 0:
				max_len = 2048  # fallback
			
			# Allocate arrays
			data0_even_arr = np.zeros((n_frames, max_len), dtype=np.uint16)
			data0_odd_arr = np.zeros((n_frames, max_len), dtype=np.uint16)
			data1_even_arr = np.zeros((n_frames, max_len), dtype=np.uint16)
			data1_odd_arr = np.zeros((n_frames, max_len), dtype=np.uint16)
			prod0_arr = np.zeros((n_frames, max_len), dtype=np.float32)  # Корреляция ch0
			prod1_arr = np.zeros((n_frames, max_len), dtype=np.float32)  # Корреляция ch1
			timestamps_arr = np.zeros(n_frames, dtype=np.float64)
			seq0_even_arr = np.zeros(n_frames, dtype=np.int32)
			seq0_odd_arr = np.zeros(n_frames, dtype=np.int32)
			seq1_even_arr = np.zeros(n_frames, dtype=np.int32)
			seq1_odd_arr = np.zeros(n_frames, dtype=np.int32)
			det_thr0_arr = np.zeros(n_frames, dtype=np.int32)
			det_thr1_arr = np.zeros(n_frames, dtype=np.int32)
			det_lvl0_arr = np.zeros(n_frames, dtype=np.int32)
			det_lvl1_arr = np.zeros(n_frames, dtype=np.int32)
			det_shift0_arr = np.zeros(n_frames, dtype=np.int32)
			det_shift1_arr = np.zeros(n_frames, dtype=np.int32)
			det_amp0_arr = np.zeros(n_frames, dtype=np.int32)
			det_amp1_arr = np.zeros(n_frames, dtype=np.int32)
			det_hold0_arr = np.zeros(n_frames, dtype=bool)
			det_hold1_arr = np.zeros(n_frames, dtype=bool)
			det_frozen_arr = np.zeros(n_frames, dtype=bool)
			
			# Fill arrays
			for i, frame in enumerate(frames):
				timestamps_arr[i] = frame.get('timestamp', 0.0)
				seq0_even_arr[i] = frame.get('seq0_even', -1) or -1
				seq0_odd_arr[i] = frame.get('seq0_odd', -1) or -1
				seq1_even_arr[i] = frame.get('seq1_even', -1) or -1
				seq1_odd_arr[i] = frame.get('seq1_odd', -1) or -1
				buf_len = frame.get('base_buf_len', 0) or 0
				if buf_len > 0:
					d0e = frame.get('data0_even')
					d0o = frame.get('data0_odd')
					d1e = frame.get('data1_even')
					d1o = frame.get('data1_odd')
					p0 = frame.get('prod0')  # Корреляция ch0
					p1 = frame.get('prod1')  # Корреляция ch1
					if d0e is not None:
						data0_even_arr[i, :buf_len] = d0e[:buf_len].astype(np.uint16)
					if d0o is not None:
						data0_odd_arr[i, :buf_len] = d0o[:buf_len].astype(np.uint16)
					if d1e is not None:
						data1_even_arr[i, :buf_len] = d1e[:buf_len].astype(np.uint16)
					if d1o is not None:
						data1_odd_arr[i, :buf_len] = d1o[:buf_len].astype(np.uint16)
					if p0 is not None:
						prod0_arr[i, :buf_len] = p0[:buf_len].astype(np.float32)
					if p1 is not None:
						prod1_arr[i, :buf_len] = p1[:buf_len].astype(np.float32)
				det_thr0_arr[i] = frame.get('det_thr0', 0)
				det_thr1_arr[i] = frame.get('det_thr1', 0)
				det_lvl0_arr[i] = frame.get('det_lvl0', 0)
				det_lvl1_arr[i] = frame.get('det_lvl1', 0)
				det_shift0_arr[i] = frame.get('det_shift0', 0)
				det_shift1_arr[i] = frame.get('det_shift1', 0)
				det_amp0_arr[i] = frame.get('det_amp0', 0)
				det_amp1_arr[i] = frame.get('det_amp1', 0)
				det_hold0_arr[i] = frame.get('det_hold0', False)
				det_hold1_arr[i] = frame.get('det_hold1', False)
				det_frozen_arr[i] = frame.get('det_frozen', False)
			
			# Save to NPZ
			metadata = self._capture_session.get('metadata', {})
			# Peak sample = номер сэмпла где был максимум при срабатывании
			peak_sample = int(getattr(self, '_capture_peak_sample', 0))
			peak_shift = int(getattr(self, '_capture_peak_shift', 0))
			peak_value = float(getattr(self, '_capture_peak_value', 0.0))
			# Trigger sample = PRE phase length (триггер случился перед началом HOLD)
			trigger_sample = int(metadata.get('pre_frames', 0))
			# Trigger frame index (first frame after PRE)
			trigger_frame_index = int(getattr(self, '_capture_trigger_index', -1) or -1)
			# Label state: 0=unknown, 1=labeled, 2=no-label
			label_state = int(getattr(self, '_capture_label_state', 0))
			np.savez_compressed(
				filepath,
				# Frame data
				data0_even=data0_even_arr,
				data0_odd=data0_odd_arr,
				data1_even=data1_even_arr,
				data1_odd=data1_odd_arr,
				prod0=prod0_arr,  # Корреляция ch0
				prod1=prod1_arr,  # Корреляция ch1
				timestamps=timestamps_arr,
				seq0_even=seq0_even_arr,
				seq0_odd=seq0_odd_arr,
				seq1_even=seq1_even_arr,
				seq1_odd=seq1_odd_arr,
				# Detector state
				det_thr0=det_thr0_arr,
				det_thr1=det_thr1_arr,
				det_lvl0=det_lvl0_arr,
				det_lvl1=det_lvl1_arr,
				det_shift0=det_shift0_arr,
				det_shift1=det_shift1_arr,
				det_amp0=det_amp0_arr,
				det_amp1=det_amp1_arr,
				det_hold0=det_hold0_arr,
				det_hold1=det_hold1_arr,
				det_frozen=det_frozen_arr,
				# Metadata
				n_frames=np.array([n_frames]),
				trigger_sample=np.array([trigger_sample]),
				trigger_frame_index=np.array([trigger_frame_index]),
				peak_sample=np.array([peak_sample]),  # Номер сэмпла с пиком в prod массиве
				peak_shift=np.array([peak_shift]),  # Фазовый сдвиг при котором найден пик
				peak_value=np.array([peak_value]),  # Значение корреляции в точке пика
				label_state=np.array([label_state]),  # Метка: 0=неизвестно, 1=с меткой, 2=без метки
				buf_len=np.array([max_len]),
				trigger_time=np.array([self._capture_session.get('trigger_time', 0.0)]),
				reason=np.array([self._capture_session.get('reason', '')], dtype='U256'),
				profile=np.array([metadata.get('profile', 1)]),
				freq_hz=np.array([metadata.get('freq_hz', 200)]),
				avg_n=np.array([metadata.get('avg_n', 20)]),
				stream_mode=np.array([metadata.get('stream_mode', 0)]),
				det_source=np.array([metadata.get('det_source', 'norm')], dtype='U16'),
				det_ratio=np.array([metadata.get('det_ratio', 2.0)]),
				det_ratio0=np.array([metadata.get('det_ratio0', 2.0)]),
				det_ratio1=np.array([metadata.get('det_ratio1', 2.0)]),
				det_add0=np.array([metadata.get('det_add0', 100)]),
				det_add1=np.array([metadata.get('det_add1', 100)]),
			)
			
			print(f"[CAPTURE] Saved {n_frames} frames to {filepath}", flush=True)
			self._set_status(f"Capture saved: {filename} ({n_frames} frames)", hold_sec=3.0)
		except Exception as e:
			print(f"[CAPTURE] Error finalizing session: {e}", flush=True)
		finally:
			self._capture_state = 'idle'
			self._capture_session = None
			self._capture_frames_recorded = 0
			self._capture_post_countdown = 0

	def _quick_detect(self):
		"""Быстрое детектирование без полного вычисления корреляции.
		
		Вызывается немедленно при получении новых пакетов для минимизации задержки.
		Вычисляет простое произведение even * (-odd) без оптимизации сдвига фазы.
		"""
		try:
			with self.data_lock:
				N = int(self.base_buf_len) if getattr(self, 'base_buf_len', None) else int(getattr(self, 'view_len', self.max_samples))
				N = max(1, min(N, self.max_samples))
				if N <= 1:
					return
				# Копируем буферы
				e0 = np.array(self.data0_even[:N], copy=True).astype(np.float64)
				o0 = np.array(self.data0_odd[:N], copy=True).astype(np.float64)
				e1 = np.array(self.data1_even[:N], copy=True).astype(np.float64)
				o1 = np.array(self.data1_odd[:N], copy=True).astype(np.float64)
			
			# Центрируем сигналы (0..65535 -> -32767..+32768)
			e0_c = e0 - 32767.0
			o0_c = o0 - 32767.0
			e1_c = e1 - 32767.0
			o1_c = o1 - 32767.0
			
			# Инвертируем нечетные
			o0_inv = -o0_c
			o1_inv = -o1_c
			
			# Вычисляем произведение (без сдвига фазы для скорости)
			prod0_center = e0_c * o0_inv
			prod1_center = e1_c * o1_inv
			
			# Нормализуем к [-1..1]
			denom = 32768.0 * 32768.0
			prod0_norm = prod0_center / (denom + 1e-12)
			prod1_norm = prod1_center / (denom + 1e-12)
			
			# Вызываем детектирование
			self._update_signal_detection(prod0_norm, prod1_norm, 0, 0, source='norm')
		except Exception:
			pass

	def _update_signal_detection(self, prod0_arr: np.ndarray, prod1_arr: np.ndarray, shift0: int, shift1: int, source: str = 'norm'):
		"""Per-channel signal detection.

		By default (source='norm'), we use normalized product max (0..1) mapped to a u16-like level (0..65535).
		This keeps threshold adaptation stable/slow even when raw product magnitudes swing a lot.

		Alternative (source='prod'): use raw centered product max scaled by BMI30_DETECT_LEVEL_SCALE (or BMI30_PROD_SCALE).

		Threshold adaptation is ALWAYS active, but uses two sets of step sizes:
		- no-detect: +20 / -5
		- detect/hold: +2 / -1
		"""
		if not bool(getattr(self, '_det_enabled', False)):
			return
		# Optional gate: when dependency is enabled and GPIO23=0, disable ONLY detection fire,
		# but continue level/threshold computation for UI and adaptation.
		gate_blocked = False
		try:
			gate_blocked = bool(self._is_det_gate_blocked())
			if gate_blocked:
				self._apply_det_gate_state()
		except Exception:
			pass
		try:
			source = str(source or 'norm').strip().lower()
			if source in ('raw', 'product'):
				source = 'prod'
			if source not in ('norm', 'prod'):
				source = 'norm'
		except Exception:
			source = 'norm'
		try:
			self._det_last_source = str(source)
		except Exception:
			pass
		_now = time.time()
		# Warmup period after startup: adapt thresholds, but suppress any early fire/freeze/beep.
		try:
			warmup_until = float(getattr(self, '_det_warmup_until', 0.0) or 0.0)
		except Exception:
			warmup_until = 0.0
		in_warmup = (warmup_until > 0.0) and (_now < warmup_until)
		try:
			fast_until = float(getattr(self, '_det_fast_adapt_until', 0.0) or 0.0)
		except Exception:
			fast_until = 0.0
		in_fast = (fast_until > 0.0) and (_now < fast_until)
		try:
			step_mul = float(getattr(self, '_det_warmup_step_mul', 1.0) or 1.0)
			if (not np.isfinite(step_mul)) or step_mul < 1.0:
				step_mul = 1.0
		except Exception:
			step_mul = 1.0
		if not (in_warmup or in_fast):
			step_mul = 1.0
		# If anything ended up frozen during warmup (should not), force resume.
		if in_warmup and bool(getattr(self, '_det_dc_frozen', False)):
			try:
				# throttle USB commands
				last_fix = float(getattr(self, '_det_warmup_dc_fix_last_t', 0.0) or 0.0)
			except Exception:
				last_fix = 0.0
			if (_now - last_fix) >= 0.50:
				try:
					self._det_warmup_dc_fix_last_t = _now
				except Exception:
					pass
				try:
					self._det_dc_frozen = False
					self._det_hold0 = False
					self._det_hold1 = False
					self._det_exceed0 = 0
					self._det_exceed1 = 0
				except Exception:
					pass
				try:
					self._device_set_dc_adapt(True)
				except Exception:
					pass
				try:
					self._beep_hold_stop()
				except Exception:
					pass
		# cooldown to avoid rapid retrigger
		# IMPORTANT: do not block unfreeze logic while DC is frozen.
		try:
			in_freeze = bool(getattr(self, '_det_dc_frozen', False))
		except Exception:
			in_freeze = False
		if (not in_freeze) and ((_now - float(getattr(self, '_det_last_fire_t', 0.0))) < float(getattr(self, '_det_cooldown_s', 1.0))):
			return

		def _level_u16(arr: np.ndarray) -> int:
			"""Return detector level (0..65535) from product array magnitude."""
			try:
				if arr is None or (not hasattr(arr, 'size')) or (arr.size == 0):
					return 0
				with np.errstate(invalid='ignore'):
					mx = float(np.nanmax(np.abs(arr)))
			except Exception:
				mx = 0.0
			if not np.isfinite(mx) or mx <= 0.0:
				return 0
			if source == 'norm':
				# Normalized product magnitude is ~[0..1]. Map to u16 for stable adaptation.
				try:
					self._det_last_level_scale = 0.0
				except Exception:
					pass
				v = int(mx * 65535.0)
				return int(max(0, min(65535, v)))
			# Raw product mode: scale down to u16-like range.
			try:
				level_scale = float(getattr(self, '_det_level_scale', 0.0) or 0.0)
			except Exception:
				level_scale = 0.0
			if level_scale <= 0.0:
				try:
					level_scale = float(os.getenv('BMI30_DETECT_LEVEL_SCALE', '') or 0.0)
				except Exception:
					level_scale = 0.0
			if level_scale <= 0.0:
				try:
					level_scale = float(os.getenv('BMI30_PROD_SCALE', '100') or 100.0)
				except Exception:
					level_scale = 100.0
			if not np.isfinite(level_scale) or level_scale <= 0.0:
				level_scale = 100.0
			try:
				self._det_last_level_scale = float(level_scale)
			except Exception:
				pass
			v = int(mx / level_scale)
			return int(max(0, min(65535, v)))
		lvl0 = _level_u16(prod0_arr)
		lvl1 = _level_u16(prod1_arr)
		try:
			self._det_last_lvl0 = int(lvl0)
			self._det_last_lvl1 = int(lvl1)
			self._det_last_shift0 = int(shift0)
			self._det_last_shift1 = int(shift1)
		except Exception:
			pass

		# init thresholds quickly on first valid data
		if int(getattr(self, '_det_thr0', 0)) <= 0 and lvl0 > 0:
			self._det_thr0 = int(lvl0)
		if int(getattr(self, '_det_thr1', 0)) <= 0 and lvl1 > 0:
			self._det_thr1 = int(lvl1)

		def _peak_idx(arr: np.ndarray) -> int:
			try:
				if arr is None or (not hasattr(arr, 'size')) or arr.size == 0:
					return -1
				with np.errstate(invalid='ignore'):
					return int(np.nanargmax(np.abs(arr)))
			except Exception:
				return -1

		def _detect_b_algorithm(arr: np.ndarray, lvl: int, ratio_thr: float) -> tuple[bool, float, int, float, float]:
			"""Return (exceed_now, ratio, peak_idx, mean_signal, mean_noise) for mark type Б."""
			try:
				if arr is None or (not hasattr(arr, 'size')) or arr.size == 0:
					return False, 0.0, -1, 0.0, 0.0
			except Exception:
				return False, 0.0, -1, 0.0, 0.0
			try:
				arr_abs = np.abs(arr).astype(np.float64, copy=False)
			except Exception:
				arr_abs = np.abs(np.array(arr, dtype=np.float64))
			try:
				peak_idx = int(np.nanargmax(arr_abs))
			except Exception:
				peak_idx = -1
			if peak_idx < 0:
				return False, 0.0, -1, 0.0, 0.0
			# Immediate detect if amplitude hits max scale (u16-like).
			if int(lvl) >= 65535:
				return True, float('inf'), int(peak_idx), float(arr_abs[peak_idx]), 0.0
			N = int(arr_abs.size)
			# Mean around peak (±2)
			p0 = max(0, int(peak_idx) - 2)
			p1 = min(N, int(peak_idx) + 3)
			try:
				mean_max = float(np.mean(arr_abs[p0:p1])) if p1 > p0 else 0.0
			except Exception:
				mean_max = 0.0
			if not np.isfinite(mean_max) or mean_max <= 0.0:
				return False, 0.0, int(peak_idx), 0.0, 0.0
			half = 0.5 * float(mean_max)
			side_means = []
			side_idxs = []
			for off in (-21, 21):
				idx = int(peak_idx) + int(off)
				if 0 <= idx < N and float(arr_abs[idx]) > float(half):
					s0 = max(0, idx - 2)
					s1 = min(N, idx + 3)
					if s1 > s0:
						try:
							side_means.append(float(np.mean(arr_abs[s0:s1])))
						except Exception:
							side_means.append(0.0)
						side_idxs.append(int(idx))
			if not side_means:
				return False, 0.0, int(peak_idx), 0.0, 0.0
			try:
				mean_signal = float(np.mean(side_means))
			except Exception:
				mean_signal = 0.0
			# Noise region: outside humps ±21
			hump_min = int(min(side_idxs))
			hump_max = int(max(side_idxs))
			noise_chunks = []
			left_end = max(0, hump_min - 21)
			right_start = min(N, hump_max + 21)
			if left_end > 0:
				noise_chunks.append(arr_abs[:left_end])
			if right_start < N:
				noise_chunks.append(arr_abs[right_start:])
			if noise_chunks:
				try:
					noise_arr = np.concatenate(noise_chunks)
					mean_noise = float(np.mean(noise_arr)) if noise_arr.size > 0 else 0.0
				except Exception:
					mean_noise = 0.0
			else:
				mean_noise = 0.0
			if (not np.isfinite(mean_noise)) or mean_noise <= 0.0:
				mean_noise = 1e-9
			ratio = float(mean_signal) / float(mean_noise)
			exceed_now = bool(ratio > float(ratio_thr))
			return exceed_now, ratio, int(peak_idx), float(mean_signal), float(mean_noise)

		# Apply B-mark specific detection algorithm only when mark type is Б.
		try:
			mark_type_b = int(getattr(self, '_mark_type_mode', 2)) == 0
		except Exception:
			mark_type_b = False
		b0 = None
		b1 = None
		if mark_type_b:
			try:
				r0 = float(getattr(self, '_det_ratio0', 2.0))
			except Exception:
				r0 = 2.0
			try:
				r1 = float(getattr(self, '_det_ratio1', 2.0))
			except Exception:
				r1 = 2.0
			try:
				r0 = float(min(20.0, max(1.0, round(r0))))
				r1 = float(min(20.0, max(1.0, round(r1))))
			except Exception:
				pass
			b0 = _detect_b_algorithm(prod0_arr, int(lvl0), r0)
			b1 = _detect_b_algorithm(prod1_arr, int(lvl1), r1)
			try:
				self._det_last_ratio0 = float(b0[1])
				self._det_last_ratio1 = float(b1[1])
				self._det_last_mean_signal0 = float(b0[3])
				self._det_last_mean_signal1 = float(b1[3])
				self._det_last_mean_noise0 = float(b0[4])
				self._det_last_mean_noise1 = float(b1[4])
			except Exception:
				pass

		peak0 = int(b0[2]) if (mark_type_b and b0 is not None and int(b0[2]) >= 0) else _peak_idx(prod0_arr)
		peak1 = int(b1[2]) if (mark_type_b and b1 is not None and int(b1[2]) >= 0) else _peak_idx(prod1_arr)

		def _step_one(ch: int, lvl: int, peak_idx: int, b_ctx=None, new_pair: bool = True):
			thr_key = '_det_thr0' if ch == 0 else '_det_thr1'
			hold_key = '_det_hold0' if ch == 0 else '_det_hold1'
			peak_key = '_det_exceed_peak0' if ch == 0 else '_det_exceed_peak1'
			seen_key = '_det_last_seen_t0' if ch == 0 else '_det_last_seen_t1'
			present_key = '_det_last_present_t0' if ch == 0 else '_det_last_present_t1'
			thr = int(getattr(self, thr_key, 1))
			thr_prev = max(1, thr)
			setattr(self, seen_key, _now)
			# Update presence timestamp when level is meaningfully above threshold.
			# IMPORTANT: while DC is frozen, use the snapshot threshold from the moment of freeze,
			# otherwise the adaptive threshold may drift down into the noise floor and keep extending "present".
			try:
				loss_ratio = float(getattr(self, '_det_loss_ratio', 1.2))
			except Exception:
				loss_ratio = 1.2
			base_thr = thr_prev
			try:
				if bool(getattr(self, '_det_dc_frozen', False)):
					ref = int(getattr(self, '_det_freeze_thr0' if ch == 0 else '_det_freeze_thr1', 0) or 0)
					if ref > 0:
						base_thr = max(base_thr, ref)
			except Exception:
				pass
			if float(lvl) >= loss_ratio * float(base_thr):
				setattr(self, present_key, _now)
			# Per-channel ratio/add with UI constraints
			try:
				ratio = float(getattr(self, '_det_ratio0' if ch == 0 else '_det_ratio1', 2.0))
			except Exception:
				ratio = 2.0
			try:
				ratio = float(min(3.0, max(1.0, ratio)))
				ratio = round(ratio, 1)
			except Exception:
				ratio = 2.0
			try:
				add = int(getattr(self, '_det_add0' if ch == 0 else '_det_add1', 100))
			except Exception:
				add = 100
			try:
				add = int(round(float(add) / 100.0) * 100)
			except Exception:
				add = 100
			add = max(0, min(700, int(add)))
			# Decide whether we currently have "detection":
			# - HOLD means we previously fired and are still in detected/present state.
			# - exceed_now means current level is above ratio*threshold + add (default)
			#   or B-mark algorithm result when enabled.
			if mark_type_b and b_ctx is not None:
				try:
					exceed_now = bool(b_ctx[0])
				except Exception:
					exceed_now = (float(lvl) > (ratio * float(thr_prev) + float(add)))
			else:
				exceed_now = (float(lvl) > (ratio * float(thr_prev) + float(add)))
			in_detect = bool(getattr(self, hold_key, False)) or bool(exceed_now)
			# Step sizes per user requirement:
			# - detect: +4 / -1
			# - no detect: +40 / -10
			# Во время прогрева/быстрого сброса умножаем шаги для ускорения адаптации.
			up = (5 if in_detect else 200) * step_mul
			down = (1 if in_detect else 10) * step_mul
			if int(lvl) > thr_prev:
				thr_new = thr_prev + int(up)
			else:
				thr_new = thr_prev - int(down)
			thr_new = int(max(1, min(65535, thr_new)))
			setattr(self, thr_key, thr_new)
			# Detect exceed vs previous threshold
			exceed = bool(exceed_now)
			if not bool(new_pair):
				# Не считаем повторно одно и то же состояние пары even/odd.
				return None
			if not exceed:
				setattr(self, peak_key, None)
			else:
				try:
					first_idx = getattr(self, peak_key, None)
					if first_idx is None:
						setattr(self, peak_key, int(peak_idx))
					elif abs(int(peak_idx) - int(first_idx)) > 12:
						# Новый пик далеко от прошлого: сдвигаем опорный индекс.
						setattr(self, peak_key, int(peak_idx))
				except Exception:
					setattr(self, peak_key, int(peak_idx))
			return bool(exceed)

		# Одно детектирование = изменение ЛЮБОГО из пакетов (even ИЛИ odd) на конкретном ADC.
		# ВАЖНО: для повторного детектирования достаточно получить ОДИН новый пакет!
		try:
			k0_even = getattr(self, 'seq0_even', None)
			k0_odd = getattr(self, 'seq0_odd', None)
			last_even0 = getattr(self, '_det_last_seq0_even', None)
			last_odd0 = getattr(self, '_det_last_seq0_odd', None)
			# Новое детектирование если изменился ЛЮБОЙ из пакетов
			new_pair0 = (k0_even != last_even0) or (k0_odd != last_odd0)
			if new_pair0:
				self._det_last_seq0_even = k0_even
				self._det_last_seq0_odd = k0_odd
		except Exception:
			new_pair0 = True
		try:
			k1_even = getattr(self, 'seq1_even', None)
			k1_odd = getattr(self, 'seq1_odd', None)
			last_even1 = getattr(self, '_det_last_seq1_even', None)
			last_odd1 = getattr(self, '_det_last_seq1_odd', None)
			# Новое детектирование если изменился ЛЮБОЙ из пакетов
			new_pair1 = (k1_even != last_even1) or (k1_odd != last_odd1)
			if new_pair1:
				self._det_last_seq1_even = k1_even
				self._det_last_seq1_odd = k1_odd
		except Exception:
			new_pair1 = True

		ex0 = _step_one(0, lvl0, peak0, b0 if mark_type_b else None, new_pair=new_pair0)
		ex1 = _step_one(1, lvl1, peak1, b1 if mark_type_b else None, new_pair=new_pair1)

		# При закрытом GPIO23-гейте не накапливаем детект и не даём fire,
		# но уровни/пороги выше уже вычислены и обновлены.
		if gate_blocked:
			ex0 = None
			ex1 = None
			self._det_exceed0 = 0
			self._det_exceed1 = 0
			self._det_start_consec0 = 0
			self._det_start_consec1 = 0
			self._det_hits0 = deque(maxlen=12)
			self._det_hits1 = deque(maxlen=12)
			self._det_last_seq0_even = None
			self._det_last_seq0_odd = None
			self._det_last_seq1_even = None
			self._det_last_seq1_odd = None

		try:
			need_n = int(getattr(self, '_det_count', 1) or 1)
		except Exception:
			need_n = 1
		need_n = max(1, min(6, int(need_n)))
		win_n = int(2 * need_n)
		try:
			hits0 = getattr(self, '_det_hits0', None)
			if hits0 is None:
				hits0 = deque(maxlen=12)
				self._det_hits0 = hits0
			hits1 = getattr(self, '_det_hits1', None)
			if hits1 is None:
				hits1 = deque(maxlen=12)
				self._det_hits1 = hits1
		except Exception:
			hits0 = deque(maxlen=12)
			hits1 = deque(maxlen=12)
			self._det_hits0 = hits0
			self._det_hits1 = hits1
		if ex0 is not None:
			if bool(ex0):
				self._det_start_consec0 = int(getattr(self, '_det_start_consec0', 0)) + 1
			else:
				self._det_start_consec0 = 0
			hits0.append(1 if bool(ex0) else 0)
		if ex1 is not None:
			if bool(ex1):
				self._det_start_consec1 = int(getattr(self, '_det_start_consec1', 0)) + 1
			else:
				self._det_start_consec1 = 0
			hits1.append(1 if bool(ex1) else 0)
		cnt0 = int(sum(list(hits0)[-win_n:])) if len(hits0) > 0 else 0
		cnt1 = int(sum(list(hits1)[-win_n:])) if len(hits1) > 0 else 0
		self._det_exceed0 = cnt0
		self._det_exceed1 = cnt1
		start_fire0 = int(getattr(self, '_det_start_consec0', 0)) >= need_n
		start_fire1 = int(getattr(self, '_det_start_consec1', 0)) >= need_n
		hold0_prev = bool(getattr(self, '_det_hold0', False))
		hold1_prev = bool(getattr(self, '_det_hold1', False))
		cont_fire0 = hold0_prev and (cnt0 >= 1)
		cont_fire1 = hold1_prev and (cnt1 >= 1)
		# Если окно полностью пустое, выключаем HOLD по каналу.
		if hold0_prev and cnt0 <= 0:
			self._det_hold0 = False
		if hold1_prev and cnt1 <= 0:
			self._det_hold1 = False
		fire0 = bool(start_fire0 or cont_fire0)
		fire1 = bool(start_fire1 or cont_fire1)
		# Учитываем включение ADC (выключенный канал не может вызвать FROZEN)
		try:
			adc1_en, adc2_en = self._adc_enable_flags()
		except Exception:
			adc1_en, adc2_en = True, True
		if not adc1_en:
			fire0 = False
			self._det_hold0 = False
			self._det_exceed0 = 0
			self._det_start_consec0 = 0
			self._det_hits0 = deque(maxlen=12)
			self._det_last_pair_key0 = None
			self._det_exceed_peak0 = None
		if not adc2_en:
			fire1 = False
			self._det_hold1 = False
			self._det_exceed1 = 0
			self._det_start_consec1 = 0
			self._det_hits1 = deque(maxlen=12)
			self._det_last_pair_key1 = None
			self._det_exceed_peak1 = None
		
		if fire0 or fire1:
			# During startup warmup we intentionally ignore the first (and any) early fires.
			if in_warmup:
				try:
					self._det_exceed0 = 0
					self._det_exceed1 = 0
					self._det_start_consec0 = 0
					self._det_start_consec1 = 0
					self._det_hits0 = deque(maxlen=12)
					self._det_hits1 = deque(maxlen=12)
					self._det_last_pair_key0 = None
					self._det_last_pair_key1 = None
					self._det_exceed_peak0 = None
					self._det_exceed_peak1 = None
					self._det_hold0 = False
					self._det_hold1 = False
					# Ensure we don't show/keep a frozen state during warmup.
					self._det_dc_frozen = False
					# Сбрасываем счетчики динамика
					self._beep_consecutive0 = 0
					self._beep_consecutive1 = 0
				except Exception:
					pass
				try:
					# Best effort: keep device adapt enabled during warmup.
					self._device_set_dc_adapt(True)
				except Exception:
					pass
				try:
					self._beep_hold_stop()
				except Exception:
					pass
				return
			# freeze further adaptations
			if fire0:
				self._det_hold0 = True
			if fire1:
				self._det_hold1 = True
			# freeze device DC adapt
			if not bool(getattr(self, '_det_dc_frozen', False)):
				# snapshot thresholds at the moment of freeze to make later loss detection stable
				try:
					self._det_freeze_thr0 = int(getattr(self, '_det_thr0', 0) or 0)
					self._det_freeze_thr1 = int(getattr(self, '_det_thr1', 0) or 0)
				except Exception:
					pass
				# Отслеживаем переход 0->1 для счетчика заморозки
				if not self._prev_freeze_state:
					self._freeze_fire_count += 1
				self._det_dc_frozen = True
				self._prev_freeze_state = True
				self._device_set_dc_adapt(False)
		# also ensure host DC removal is off
		try:
			self.dc_removal_enabled = False
		except Exception:
			pass
		# beep при срабатывании fire (уже требует 2 последовательных превышения)
		if fire0 or fire1:
			# Отслеживаем переход 0->1 для счетчика динамика
			if not self._prev_beep_state:
				self._beep_fire_count += 1
				self._prev_beep_state = True
				# Trigger capture session on first fire
				try:
					thr0 = int(getattr(self, '_det_thr0', 0))
					thr1 = int(getattr(self, '_det_thr1', 0))
					# Находим номер сэмпла где пик (максимум) в корреляционных массивах
					# ВАЖНО: используем pre-computed peak_idx из оптимального поиска фазового сдвига
					peak_sample = 0
					shift_val = 0
					peak_value = 0.0
					try:
						if fire0:
							# Используем уже вычисленный peak_idx из optimal phase search
							if hasattr(self, '_phase_peak_idx_adc0'):
								peak_sample = int(getattr(self, '_phase_peak_idx_adc0', 0))
								shift_val = int(getattr(self, '_phase_shift_adc0', 0))
								# Получаем значение в точке пика
								if hasattr(self, '_phase_prod_adc0'):
									prod_arr = self._phase_prod_adc0
									if peak_sample < len(prod_arr):
										peak_value = float(prod_arr[peak_sample])
								# Детальная диагностика окрестности пика
								print(f"\n*** [CAPTURE] ADC0 PEAK ANALYSIS ***", flush=True)
								print(f"  Shift={shift_val}, Peak_idx={peak_sample}, Peak_value={peak_value:.2e}", flush=True)
								if hasattr(self, '_phase_prod_adc0'):
									prod = self._phase_prod_adc0
									# Показываем 5 сэмплов до и после пика
									start = max(0, peak_sample - 5)
									end = min(len(prod), peak_sample + 6)
									print(f"  Values around peak [{start}..{end-1}]:", flush=True)
									for i in range(start, end):
										marker = " <-- PEAK" if i == peak_sample else ""
										print(f"    [{i}] = {prod[i]:.2e}{marker}", flush=True)
							elif hasattr(self, '_xcorr_saved_prod0'):
								# Fallback: простой поиск максимума
								peak_sample = int(np.argmax(np.abs(self._xcorr_saved_prod0)))
								peak_value = float(self._xcorr_saved_prod0[peak_sample])
								print(f"\n*** [CAPTURE] ADC0 FALLBACK (no optimal shift) ***", flush=True)
								print(f"  Peak_idx={peak_sample}, Peak_value={peak_value:.2e}", flush=True)
							
							# Дополнительно: проверим синхронность - покажем even и inverted odd в точке пика
							if peak_sample > 0:
								try:
									with self.data_lock:
										N = int(self.base_buf_len) if getattr(self, 'base_buf_len', None) else 0
										if N > 0 and peak_sample < N:
											even_val = int(self.data0_even[peak_sample])
											odd_val = int(self.data0_odd[peak_sample])
											# С учетом сдвига
											shifted_idx = peak_sample + shift_val
											if 0 <= shifted_idx < N:
												odd_shifted_val = int(self.data0_odd[shifted_idx])
												# Инвертированное значение (после центрирования)
												odd_inv = -(odd_shifted_val - 32767)
												even_centered = even_val - 32767
												product = even_centered * odd_inv
												print(f"  SYNC CHECK at peak_sample={peak_sample}:", flush=True)
												print(f"    even[{peak_sample}] = {even_val} (centered: {even_centered})", flush=True)
												print(f"    odd[{shifted_idx}] = {odd_shifted_val} (inv: {odd_inv})", flush=True)
												print(f"    product = {product:.2e}", flush=True)
								except Exception as e:
									print(f"  SYNC CHECK failed: {e}", flush=True)
						elif fire1:
							if hasattr(self, '_phase_peak_idx_adc1'):
								peak_sample = int(getattr(self, '_phase_peak_idx_adc1', 0))
								shift_val = int(getattr(self, '_phase_shift_adc1', 0))
								if hasattr(self, '_phase_prod_adc1'):
									prod_arr = self._phase_prod_adc1
									if peak_sample < len(prod_arr):
										peak_value = float(prod_arr[peak_sample])
								print(f"\n*** [CAPTURE] ADC1 PEAK ANALYSIS ***", flush=True)
								print(f"  Shift={shift_val}, Peak_idx={peak_sample}, Peak_value={peak_value:.2e}", flush=True)
								if hasattr(self, '_phase_prod_adc1'):
									prod = self._phase_prod_adc1
									start = max(0, peak_sample - 5)
									end = min(len(prod), peak_sample + 6)
									print(f"  Values around peak [{start}..{end-1}]:", flush=True)
									for i in range(start, end):
										marker = " <-- PEAK" if i == peak_sample else ""
										print(f"    [{i}] = {prod[i]:.2e}{marker}", flush=True)
							elif hasattr(self, '_xcorr_saved_prod1'):
								peak_sample = int(np.argmax(np.abs(self._xcorr_saved_prod1)))
								peak_value = float(self._xcorr_saved_prod1[peak_sample])
								print(f"\n*** [CAPTURE] ADC1 FALLBACK (no optimal shift) ***", flush=True)
								print(f"  Peak_idx={peak_sample}, Peak_value={peak_value:.2e}", flush=True)
							
							# Проверка синхронности для ADC1
							if peak_sample > 0:
								try:
									with self.data_lock:
										N = int(self.base_buf_len) if getattr(self, 'base_buf_len', None) else 0
										if N > 0 and peak_sample < N:
											even_val = int(self.data1_even[peak_sample])
											odd_val = int(self.data1_odd[peak_sample])
											shifted_idx = peak_sample + shift_val
											if 0 <= shifted_idx < N:
												odd_shifted_val = int(self.data1_odd[shifted_idx])
												odd_inv = -(odd_shifted_val - 32767)
												even_centered = even_val - 32767
												product = even_centered * odd_inv
												print(f"  SYNC CHECK at peak_sample={peak_sample}:", flush=True)
												print(f"    even[{peak_sample}] = {even_val} (centered: {even_centered})", flush=True)
												print(f"    odd[{shifted_idx}] = {odd_shifted_val} (inv: {odd_inv})", flush=True)
												print(f"    product = {product:.2e}", flush=True)
								except Exception as e:
									print(f"  SYNC CHECK failed: {e}", flush=True)
					except Exception as e:
						print(f"*** [CAPTURE] ERROR in peak analysis: {e} ***", flush=True)
						peak_sample = 0
						shift_val = 0
						peak_value = 0.0
					# Сохраняем для использования в метаданных
					self._capture_peak_sample = peak_sample
					self._capture_peak_shift = shift_val
					self._capture_peak_value = peak_value
					reason = f"ADC0={fire0} ADC1={fire1} thr0={thr0 if fire0 else 0} thr1={thr1 if fire1 else 0} peak_sample={peak_sample} shift={shift_val}"
					print(f"*** [CAPTURE] Detection fired: fire0={fire0}, fire1={fire1}, peak_sample={peak_sample}, shift={shift_val}, value={peak_value:.2e} ***\n", flush=True)
					self._capture_trigger(reason)
				except Exception as e:
					print(f"*** [CAPTURE] ERROR in trigger call: {e} ***", flush=True)
					import traceback
					traceback.print_exc()
			self._det_last_fire_t = _now
			self._fire_beep(fire0, fire1, shift0, shift1)
			# optional: keep PWM running while in HOLD
			self._beep_hold_start(fire0, fire1, shift0, shift1, int(lvl0), int(lvl1))
			# GPIO indication during HOLD
			try:
				self._set_det_gpio(bool(getattr(self, '_det_hold0', False)), bool(getattr(self, '_det_hold1', False)))
			except Exception:
				pass
			# Record frame during HOLD phase
			try:
				self._capture_record_frame()
			except Exception as e:
				print(f"*** [CAPTURE] ERROR in record_frame: {e} ***", flush=True)
				import traceback
				traceback.print_exc()
			return

		# If previously frozen and signal "lost" for long enough -> resume device DC adapt
		if bool(getattr(self, '_det_dc_frozen', False)):
			loss_s = float(getattr(self, '_det_loss_s', 2.0))
			loss_ratio = float(getattr(self, '_det_loss_ratio', 1.2))
			# consider each channel lost if below loss_ratio*thr
			thr0 = max(1, int(getattr(self, '_det_thr0', 1)))
			thr1 = max(1, int(getattr(self, '_det_thr1', 1)))
			# While frozen, use the snapshot threshold (moment of freeze) as a stable reference.
			# This prevents adaptive thresholds drifting down in noise and delaying unfreeze.
			try:
				ref0 = int(getattr(self, '_det_freeze_thr0', 0) or 0)
				ref1 = int(getattr(self, '_det_freeze_thr1', 0) or 0)
				if ref0 > 0:
					thr0 = max(thr0, ref0)
				if ref1 > 0:
					thr1 = max(thr1, ref1)
			except Exception:
				pass
			lost0 = float(lvl0) < loss_ratio * float(thr0)
			lost1 = float(lvl1) < loss_ratio * float(thr1)
			# if both are lost for > loss_s, resume
			lastp0 = float(getattr(self, '_det_last_present_t0', 0.0))
			lastp1 = float(getattr(self, '_det_last_present_t1', 0.0))
			if (lost0 and lost1) and ((_now - max(lastp0, lastp1)) >= loss_s):
				self._det_dc_frozen = False
				self._prev_freeze_state = False
				self._prev_beep_state = False
				self._det_hold0 = False
				self._det_hold1 = False
				try:
					self._det_freeze_thr0 = 0
					self._det_freeze_thr1 = 0
				except Exception:
					pass
				self._device_set_dc_adapt(True)
				# stop HOLD PWM
				self._beep_hold_stop()
				# clear GPIO indication
				try:
					self._set_det_gpio(False, False)
				except Exception:
					pass
				# Start POST capture phase
				try:
					self._capture_start_post()
				except Exception:
					pass

	def _switch_to_latest_mode(self):
		"""Возврат в режим LATEST (STREAM_MODE=0): 600 семплов, допускаются пропуски"""
		# prevent concurrent mode switches which block GUI (USB send_cmd is synchronous)
		if getattr(self, '_mode_switch_in_progress', False):
			self._set_status('Реж.переключения в процессе, подождите...', hold_sec=1.0)
			return
		self._mode_switch_in_progress = True
		try:
			if self.stream is None:
				return
			# Если уходим из LOSSLESS_ROI, постараемся сохранить DC offset сразу (на выходе/перезапусках это критично)
			try:
				if getattr(self, 'stream_mode', 0) == 1:
					self._save_dc_offset(force=True)
			except Exception:
				pass
			
			# Отключаем DC removal если был включен
			if getattr(self, 'dc_removal_enabled', False):
				self.dc_removal_enabled = False
				# Восстанавливаем нормальную частоту GUI
				try:
					gui_fps = int(os.getenv("BMI30_GUI_FPS", "16"))
				except Exception:
					gui_fps = 16
				interval = max(10, int(1000 / gui_fps))
				self.qtimer.setInterval(interval)
				if bool(getattr(self, 'debug', False)):
					print(f"[LATEST] GUI восстановлен до {gui_fps} FPS")
			
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] Переключение в режим LATEST (600 семплов, STREAM_MODE=0)...")
			
			# Остановка потока
			self._send_stop_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] STOP отправлен")
			
			# SET_WINDOWS: (0,0,0,0) - полный буфер
			windows_data = struct.pack('<HHHH', 0, 0, 0, 0)
			self.stream.send_cmd(CMD_SET_WINDOWS, windows_data)
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] SET_WINDOWS(0, 0, 0, 0) отправлен")
			
			# SET_STREAM_MODE: 0 (LATEST)
			self.stream.send_cmd(CMD_SET_STREAM_MODE, b"\x00")
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] SET_STREAM_MODE=0 отправлен")
			
			# SET_ASYNC_MODE: 1 (независимые A/B для быстрого режима)
			self.stream.send_cmd(CMD_ASYNC, b"\x01")
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] SET_ASYNC_MODE=1 отправлен")
			
			# Сбросить параметры буфера для переинициализации с новым размером (600 семплов)
			with self.data_lock:
				self._reset_phase_splitter("switch_to_latest")
				self.base_buf_len = None
				self.base_buf_len_bytes = None
				self.freq_hz = None
				self._sliders_initialized = False
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] Параметры буфера сброшены для переинициализации с 600 семплами")
			
			# Запуск потока
			self._send_start_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] START отправлен")
			
			# Устанавливаем stream_mode=0
			self.stream_mode = 0
			if bool(getattr(self, 'debug', False)):
				print("[LATEST] Режим активирован: 600 семплов, STREAM_MODE=0")
			
		except Exception as e:
			print(f"[LATEST] Ошибка переключения: {e}")
		finally:
			self._mode_switch_in_progress = False

	def _switch_to_lossless_roi(self, restart: bool = True):
		"""Переключение в режим LOSSLESS_ROI (STREAM_MODE=1): строгий FIFO, ROI 200 семплов.
		Старт ROI зависит от "тип метки" (Б/M/С) и вычисляется в _get_mark_type_roi_window().
		Если `restart`=False и уже в STREAM_MODE=1, не перезапускаем поток/окна — только переключаем отображение/статус.
		"""
		# If caller requested no restart and already in desired mode, do light update only
		if not restart and getattr(self, 'stream_mode', 0) == 1 and self.stream is not None:
			self._set_view_mode(0)
			self.qtimer.setInterval(200)
			self._set_status("LOSSLESS_ROI (active)", hold_sec=1.0)
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] Already active — no restart performed")
			return

		# If background worker available, enqueue non-blocking job
		if getattr(self, '_mode_worker', None) is not None:
			if self.stream is None:
				self._set_status("Запуск потока для LOSSLESS_ROI...", hold_sec=1.0)
				self._activate_stream()
				time.sleep(0.5)
				if self.stream is None:
					self._set_status("Ошибка запуска потока", hold_sec=2.0)
					return
			self._set_status("Переключение в LOSSLESS_ROI (в очереди)...", hold_sec=1.0)
			self._enqueue_mode_action('lossless')
			return
		
		try:
			# Отключаем DC removal если был включен (режим LOSSLESS_ROI без DC)
			if getattr(self, 'dc_removal_enabled', False):
				self.dc_removal_enabled = False
				# Восстанавливаем нормальную частоту GUI
				try:
					gui_fps = int(os.getenv("BMI30_GUI_FPS", "16"))
				except Exception:
					gui_fps = 16
				interval = max(10, int(1000 / gui_fps))
				self.qtimer.setInterval(interval)
				if bool(getattr(self, 'debug', False)):
					print(f"[LOSSLESS_ROI] GUI восстановлен до {gui_fps} FPS")
			
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] Переключение в режим LOSSLESS_ROI (200 семплов из окна 280..480)...")
			self._set_status("Переключение в LOSSLESS_ROI...", hold_sec=1.0)
			
			# Остановка потока
			self._send_stop_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] STOP отправлен")
			
			roi_start, roi_len = self._get_mark_type_roi_window()
			# SET_WINDOWS: одинаковое ROI для обоих каналов
			# Формат: u16 start0 + u16 len0 + u16 start1 + u16 len1 (little-endian)
			windows_data, sent_len = self._pack_set_windows_start(int(roi_start) & 0xFFFF, default_len=int(roi_len))
			self.stream.send_cmd(CMD_SET_WINDOWS, windows_data)
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print(f"[LOSSLESS_ROI] SET_WINDOWS(start={int(roi_start)}, len={int(sent_len)}) отправлен")
			
			# SET_STREAM_MODE: 1 (LOSSLESS_ROI)
			self.stream.send_cmd(CMD_SET_STREAM_MODE, b"\x01")
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] SET_STREAM_MODE=1 отправлен")
			
			# SET_ASYNC_MODE: 0 (строгие пары A/B)
			self.stream.send_cmd(CMD_ASYNC, b"\x00")
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] SET_ASYNC_MODE=0 отправлен")
			
			# Запуск потока
			self._send_start_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] START отправлен")
			
			# Сбросить параметры буфера для переинициализации с новым размером (200 семплов)
			with self.data_lock:
				self._reset_phase_splitter("switch_to_lossless_roi")
				self.base_buf_len = None
				self.base_buf_len_bytes = None
				self.freq_hz = None
				self._sliders_initialized = False
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] Параметры буфера сброшены для переинициализации с 200 семплами")
			
			# Переключить на отображение обоих каналов
			self._set_view_mode(0)  # 0 = оба канала
			
			# Устанавливаем stream_mode=1 (накопление DC offset активно)
			self.stream_mode = 1
			
			# Снижаем частоту отрисовки GUI для уменьшения блокировок data_lock
			# В LOSSLESS_ROI не нужна быстрая отрисовка (5 FPS достаточно для накопления DC)
			self.qtimer.setInterval(200)  # 200 мс = 5 FPS
			if bool(getattr(self, 'debug', False)):
				print("[LOSSLESS_ROI] GUI снижен до 5 FPS для минимизации блокировок")
			
			self._set_status(f"LOSSLESS_ROI: ROI={int(roi_len)} start={int(roi_start)} (тип метки)", hold_sec=3.0)
			if bool(getattr(self, 'debug', False)):
				print(f"[LOSSLESS_ROI] Режим активирован: ROI start={int(roi_start)} len={int(roi_len)}")
			
		except Exception as e:
			print(f"[LOSSLESS_ROI] Ошибка переключения: {e}")
			self._set_status(f"Ошибка LOSSLESS_ROI: {e}", hold_sec=3.0)
		finally:
			self._mode_switch_in_progress = False

	def _switch_to_dc_removal_mode(self, restart: bool = True):
		"""Переключение в режим LOSSLESS_ROI с удалением постоянной составляющей (DC removal).
		Если `restart`=False и уже в STREAM_MODE=1, не перезапускаем поток/окна — только обновляем отображение/статус.
		"""
		# Guard against concurrent switches
		if getattr(self, '_mode_switch_in_progress', False):
			self._set_status('Реж.переключения в процессе, подождите...', hold_sec=1.0)
			return
		self._mode_switch_in_progress = True
		try:
			# Если уже в LOSSLESS_ROI и restart=False — сделаем лёгкое обновление без STOP/START
			if not restart and getattr(self, 'stream_mode', 0) == 1 and self.stream is not None:
				self._set_view_mode(0)
				self.qtimer.setInterval(200)
				self._set_status("LOSSLESS_ROI (active)", hold_sec=1.0)
				if bool(getattr(self, 'debug', False)):
					print("[DC_REMOVAL] Already in LOSSLESS_ROI — no restart performed")
				return

			# Иначе — переключаемся полноценно
			if getattr(self, 'stream_mode', 0) != 1 or self.stream is None:
				self._switch_to_lossless_roi(restart=restart)

			# Host-side DC removal is disabled; device performs DC compensation.
			self._set_status("LOSSLESS_ROI (device DC compensation)", hold_sec=2.0)
		finally:
			self._mode_switch_in_progress = False

	def _switch_to_avg_roi(self, avg_n: int = 20, restart: bool = True):
		"""Переключение в режим усреднения на устройстве (STREAM_MODE=2, AVG_ROI).
		Устройство усредняет ROI по N входным буферам и выдаёт усреднённые ROI-кадры.
		См. HOST_RPI.md: STOP -> SET_WINDOWS -> SET_STREAM_MODE(mode, avg_n) -> SET_ASYNC(0) -> START.
		"""
		# If background worker available, enqueue non-blocking avg switch
		if getattr(self, '_mode_worker', None) is not None:
			try:
				avg_n = int(avg_n)
			except Exception:
				avg_n = 20
			avg_n = max(2, min(32, avg_n))
			if self.stream is None:
				self._set_status("Запуск потока для AVG_ROI...", hold_sec=1.0)
				self._activate_stream()
				time.sleep(0.5)
				if self.stream is None:
					self._set_status("Ошибка запуска потока", hold_sec=2.0)
					return
			self._set_status(f"Переключение в AVG_ROI (в очереди) avg_n={avg_n}", hold_sec=1.0)
			self._enqueue_mode_action('avg', avg_n)
			return

		# Fallback synchronous path (guarded)
		if getattr(self, '_mode_switch_in_progress', False):
			self._set_status('Реж.переключения в процессе, подождите...', hold_sec=1.0)
			return
		self._mode_switch_in_progress = True
		try:
			# Ensure stream is running
			if self.stream is None:
				if bool(getattr(self, 'debug', False)):
					print("[AVG_ROI] Поток не запущен, запускаем...")
				self._set_status("Запуск потока для AVG_ROI...", hold_sec=1.0)
				self._activate_stream()
				time.sleep(0.5)
				if self.stream is None:
					if bool(getattr(self, 'debug', False)):
						print("[AVG_ROI] Не удалось запустить поток")
					self._set_status("Ошибка запуска потока", hold_sec=2.0)
					return

			# If caller requested no restart and device already in AVG_ROI, update avg_n in-place
			if not restart and getattr(self, 'stream_mode', 0) == 2 and self.stream is not None:
				try:
					avg_n = int(avg_n)
				except Exception:
					avg_n = 20
				avg_n = max(2, min(32, avg_n))
				self.stream.send_cmd(CMD_SET_STREAM_MODE, bytes([0x02, avg_n & 0xFF]))
				if bool(getattr(self, 'debug', False)):
					print(f"[AVG_ROI] Updated avg_n in-place to {avg_n} (no restart)")
				self.stream_mode = 2
				self.qtimer.setInterval(200)
				self._set_status(f"AVG_ROI updated (avg_n={avg_n})", hold_sec=1.5)
				return

			# Full switch path
			try:
				avg_n = int(avg_n)
			except Exception:
				avg_n = 20
			avg_n = max(2, min(32, avg_n))
			if bool(getattr(self, 'debug', False)):
				print(f"[AVG_ROI] Переключение в AVG_ROI (STREAM_MODE=2, avg_n={avg_n})...")
			self._set_status(f"Переключение в AVG_ROI (avg_n={avg_n})...", hold_sec=1.0)

			# STOP
			self._send_stop_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] STOP отправлен")

			roi_start, _roi_len = self._get_mark_type_roi_window()
			# SET_WINDOWS: both channels ROI with same start/len
			windows_data, sent_len = self._pack_set_windows_start(int(roi_start) & 0xFFFF, default_len=int(_roi_len))
			self.stream.send_cmd(CMD_SET_WINDOWS, windows_data)
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print(f"[AVG_ROI] SET_WINDOWS(start={int(roi_start)}, len={int(sent_len)}) отправлен")

			# SET_STREAM_MODE: 2 (AVG_ROI) + avg_n
			self.stream.send_cmd(CMD_SET_STREAM_MODE, bytes([0x02, avg_n & 0xFF]))
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] SET_STREAM_MODE=2 (AVG_ROI) отправлен")

			# SET_ASYNC_MODE: 1 (independent A/B) — как в стабильной версии с нормальным FPS
			self.stream.send_cmd(CMD_ASYNC, b"\x01")
			time.sleep(0.02)
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] SET_ASYNC_MODE=1 отправлен")

			# START
			self._send_start_stream()
			time.sleep(0.05)
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] START отправлен")

			# Reset buffers for reinitialization
			with self.data_lock:
				self._reset_phase_splitter(f"switch_to_avg_roi avg_n={avg_n}")
				self.base_buf_len = None
				self.base_buf_len_bytes = None
				self.freq_hz = None
				self._sliders_initialized = False
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] Параметры буфера сброшены для переинициализации")

			self._set_view_mode(0)
			self.stream_mode = 2
			self.qtimer.setInterval(200)
			self._set_status(f"AVG_ROI: avg_n={avg_n}, ROI={int(sent_len)} start={int(roi_start)} (тип метки)", hold_sec=3.0)
			if bool(getattr(self, 'debug', False)):
				print("[AVG_ROI] Режим активирован")
		except Exception as e:
			print(f"[AVG_ROI] Ошибка переключения: {e}")
			self._set_status(f"Ошибка AVG_ROI: {e}", hold_sec=3.0)
		finally:
			self._mode_switch_in_progress = False

	def _seed_avg20_buffers_locked(self):
		"""Заполнить буферы AVG20 текущим кадром, чтобы при включении 6 не было 'разгона с нуля'.
		Ожидает, что data_lock уже удерживается.
		"""
		try:
			n = int(self.base_buf_len or 0)
			n = max(0, min(n, int(getattr(self, 'max_samples', 0) or 0)))
			if n <= 0:
				# сброс счётчиков, данные придут и сами заполнится
				self._avg0_even_pos = self._avg0_odd_pos = 0
				self._avg1_even_pos = self._avg1_odd_pos = 0
				self._avg0_even_cnt = self._avg0_odd_cnt = 0
				self._avg1_even_cnt = self._avg1_odd_cnt = 0
				return
			def _dc_out(raw_i32, dc_f32):
				# Device provides DC compensation — do not apply host-side DC offsets.
				out = raw_i32.astype(np.float32)
				# Preserve optional inversion logic (legacy visual inversion), but do not alter DC level
				if not getattr(self, 'debug_markers', False) and not getattr(self, 'no_invert', False):
					out = np.float32(32767.5) - (out - np.float32(32767.5))
				return out
			# Сформируем 4 кривые
			ch0e = _dc_out(self.data0_even[:n], self.dc_offset_ch0_even[:n])
			ch0o = _dc_out(self.data0_odd[:n], self.dc_offset_ch0_odd[:n])
			ch1e = _dc_out(self.data1_even[:n], self.dc_offset_ch1_even[:n])
			ch1o = _dc_out(self.data1_odd[:n], self.dc_offset_ch1_odd[:n])
			# Заполним все N кадров одним и тем же значением
			for i in range(int(self.avg20_nframes)):
				self._avg0_even[i, :n] = ch0e
				self._avg0_odd[i, :n] = ch0o
				self._avg1_even[i, :n] = ch1e
				self._avg1_odd[i, :n] = ch1o
				if n < self.max_samples:
					self._avg0_even[i, n:] = 0
					self._avg0_odd[i, n:] = 0
					self._avg1_even[i, n:] = 0
					self._avg1_odd[i, n:] = 0
			self._avg0_even_pos = self._avg0_odd_pos = 0
			self._avg1_even_pos = self._avg1_odd_pos = 0
			self._avg0_even_cnt = self._avg0_odd_cnt = int(self.avg20_nframes)
			self._avg1_even_cnt = self._avg1_odd_cnt = int(self.avg20_nframes)
		except Exception as e:
			print(f"[AVG20] seed ошибка: {e}")
	
	def _update_dc_offset_adaptive(self, data_arr, dc_arr, length):
		"""Host-side DC adaptation disabled: device handles DC compensation.
		This is intentionally a no-op to avoid any host-side DC changes.
		If called, emit a diagnostic message to help track unexpected invocations.
		"""
		try:
			if bool(getattr(self, 'debug', False)) and getattr(self, 'diag_to_console', False):
				print("[DC_REMOVAL] _update_dc_offset_adaptive was called (host adaptation disabled)")
		except Exception:
			pass
		return
	
	def _save_dc_offset(self, force: bool = False):
			"""Host-side DC save disabled: device handles DC; this is a no-op."""
			try:
				# no-op, but keep a debug print for visibility
				if bool(getattr(self, 'debug', False)) and getattr(self, 'diag_to_console', False):
					print("[DC_REMOVAL] _save_dc_offset called but host DC save is disabled")
			except Exception:
				pass
			return
	
	def _load_dc_offset(self):
		"""Загрузить сохраненные DC offset массивы из файла"""
		try:
			# кандидаты: основной, backup, и запасной (cwd) на случай запуска из другой папки
			candidates = []
			try:
				candidates.append(self.dc_save_file)
			except Exception:
				pass
			try:
				candidates.append(self.dc_save_file_bak)
			except Exception:
				pass
			try:
				cwd_alt = os.path.join(os.getcwd(), os.path.basename(self.dc_save_file))
				if cwd_alt not in candidates:
					candidates.append(cwd_alt)
			except Exception:
				pass
			loaded_from = None
			payload = None
			last_err = None
			for path in candidates:
				try:
					if not path or not os.path.exists(path):
						continue
					with np.load(path, allow_pickle=False) as data:
						need = ('dc_offset_ch0_even', 'dc_offset_ch0_odd', 'dc_offset_ch1_even', 'dc_offset_ch1_odd')
						if not all(k in data for k in need):
							raise ValueError(f"missing keys in {path}")
						payload = {k: np.array(data[k], dtype=np.float32, copy=True) for k in need}
						ts = float(np.array(data['timestamp'])[0]) if 'timestamp' in data else 0.0
						payload['timestamp'] = ts
					loaded_from = path
					break
				except Exception as e:
					last_err = e
					continue
			if payload is None:
				if last_err is not None:
					print(f"[DC_REMOVAL] Ошибка загрузки DC offset (candidates={candidates}): {last_err}")
				else:
					print(f"[DC_REMOVAL] Файл DC offset не найден (candidates={candidates}), используются нулевые массивы")
				return
			# Валидируем размеры и применяем только если всё ок
			for k in ('dc_offset_ch0_even', 'dc_offset_ch0_odd', 'dc_offset_ch1_even', 'dc_offset_ch1_odd'):
				arr = payload.get(k)
				if arr is None or arr.ndim != 1:
					raise ValueError(f"invalid array {k}")
			# Применяем (обрезаем/расширяем до max_samples)
			self.dc_offset_ch0_even[:] = 0
			self.dc_offset_ch0_odd[:] = 0
			self.dc_offset_ch1_even[:] = 0
			self.dc_offset_ch1_odd[:] = 0
			n = min(len(payload['dc_offset_ch0_even']), self.max_samples)
			self.dc_offset_ch0_even[:n] = payload['dc_offset_ch0_even'][:n]
			n = min(len(payload['dc_offset_ch0_odd']), self.max_samples)
			self.dc_offset_ch0_odd[:n] = payload['dc_offset_ch0_odd'][:n]
			n = min(len(payload['dc_offset_ch1_even']), self.max_samples)
			self.dc_offset_ch1_even[:n] = payload['dc_offset_ch1_even'][:n]
			n = min(len(payload['dc_offset_ch1_odd']), self.max_samples)
			self.dc_offset_ch1_odd[:n] = payload['dc_offset_ch1_odd'][:n]
			saved_time = float(payload.get('timestamp', 0.0) or 0.0)
			age_minutes = (time.time() - saved_time) / 60
			
			# Вычисляем средние значения для логирования
			mean_ch0_even = np.mean(self.dc_offset_ch0_even[:200]) if len(self.dc_offset_ch0_even) >= 200 else 0
			mean_ch0_odd = np.mean(self.dc_offset_ch0_odd[:200]) if len(self.dc_offset_ch0_odd) >= 200 else 0
			mean_ch1_even = np.mean(self.dc_offset_ch1_even[:200]) if len(self.dc_offset_ch1_even) >= 200 else 0
			mean_ch1_odd = np.mean(self.dc_offset_ch1_odd[:200]) if len(self.dc_offset_ch1_odd) >= 200 else 0
			
			print(f"[DC_REMOVAL] DC offset массивы загружены из {loaded_from} (возраст: {age_minutes:.1f} мин)")
			print(f"[DC_REMOVAL] Средние значения (первые 200 семплов): ch0_even={mean_ch0_even:.1f}, ch0_odd={mean_ch0_odd:.1f}, ch1_even={mean_ch1_even:.1f}, ch1_odd={mean_ch1_odd:.1f}")
		except Exception as e:
			print(f"[DC_REMOVAL] Ошибка загрузки DC offset: {e}")

	# --- numeric buttons persistence ---
	def _num_clicked(self, idx: int):
		# Сброс счетчиков статистики и разморозка при любом переключении режима
		# ВАЖНО: адаптивные пороги НЕ сбрасываем - они продолжают работать
		try:
			self._beep_fire_count = 0
			self._freeze_fire_count = 0
			self._prev_beep_state = False
			self._prev_freeze_state = False
			self._beep_consecutive0 = 0
			self._beep_consecutive1 = 0
			# Проверяем переход между режимами
			last_idx = getattr(self, '_det_last_mode_idx', None)
			going_to_detect = (idx >= 6)  # Переходим на кнопки 6+
			coming_from_detect = (last_idx is not None and last_idx >= 6)  # Были на кнопках 6+
			# Сохраняем текущий режим
			self._det_last_mode_idx = idx
			# Если уходим с кнопок 6+ - сохраняем пороги
			if coming_from_detect and not going_to_detect:
				self._det_saved_thr0 = self._det_thr0
				self._det_saved_thr1 = self._det_thr1
			# Если приходим на кнопки 6+ - восстанавливаем пороги и запускаем warmup
			if going_to_detect:
				# Восстанавливаем сохраненные пороги (если есть)
				if hasattr(self, '_det_saved_thr0') and self._det_saved_thr0 > 0:
					self._det_thr0 = self._det_saved_thr0
					self._det_thr1 = self._det_saved_thr1
				# Запускаем warmup для блокировки до подстройки уровней
				self._det_reset_and_arm_warmup(f'mode_{idx}')
				# Примечание: _det_reset_and_arm_warmup разморозит и сбросит счетчики
			else:
				# На кнопках <6: просто разморозка без warmup
				self._det_dc_frozen = False
				self._det_hold0 = False
				self._det_hold1 = False
				self._det_exceed0 = 0
				self._det_exceed1 = 0
				self._det_start_consec0 = 0
				self._det_start_consec1 = 0
				self._det_hits0 = deque(maxlen=12)
				self._det_hits1 = deque(maxlen=12)
				self._det_last_pair_key0 = None
				self._det_last_pair_key1 = None
				self._det_exceed_peak0 = None
				self._det_exceed_peak1 = None
				# Включаем адаптацию DC на устройстве
				try:
					self._device_set_dc_adapt(True)
				except Exception:
					pass
		except Exception:
			pass
		# Enable heavy phase-shift search only in modes 6+ ("6 и более").
		# This flag is consumed by the USB reader thread.
		try:
			self._phase_search_enabled = bool(int(idx) >= 6)
		except Exception:
			self._phase_search_enabled = False
		# Если поток не запущен — перезапускаем на любой кнопке кроме 0
		try:
			if int(idx) != 0 and self.stream is None and not self._connecting:
				self._activate_stream()
		except Exception:
			pass
		if idx in (1, 2, 3):
			mode_map = {1: 1, 2: 2, 3: 0}  # 1: канал 1, 2: канал 2, 3: оба
			# Переключить в режим LATEST (600 семплов, STREAM_MODE=0)
			if self.stream is not None:
				self._switch_to_latest_mode()
			# Выключить режим DC removal / AVG
			self.dc_removal_enabled = False
			self.avg20_enabled = False
			self._set_view_mode(mode_map[idx])
		elif idx == 4:
			# Кнопка 4: переключение в LOSSLESS_ROI режим (STREAM_MODE=1), показ 2 каналов × 2 осциллограммы × 200 семплов
			self.dc_removal_enabled = False  # Выключить DC removal
			self.avg20_enabled = False
			# If already in STREAM_MODE=1, avoid full restart
			restart = not (getattr(self, 'stream_mode', 0) == 1 and self.stream is not None)
			self._switch_to_lossless_roi(restart=restart)
		elif idx == 5:
			# Кнопка 5: усреднение на УСТРОЙСТВЕ (AVG_ROI, stream_mode=2, avg_n=20) + вычитание DC на хосте
			# Switch to device-side averaging (AVG_ROI); do NOT enable host DC removal
			self.avg20_enabled = False
			# If already in STREAM_MODE=2, avoid full restart and update avg_n in-place
			restart = not (getattr(self, 'stream_mode', 0) == 2 and self.stream is not None)
			avg_n = int(getattr(self, 'avg_n', 20) or 20)
			self._switch_to_avg_roi(avg_n=avg_n, restart=restart)
			self._set_status(f"AVG_ROI({avg_n}): усреднение на устройстве (DC handled by device)", hold_sec=3.0)
		elif idx == 6:
			# Кнопка 6: не переключаем STREAM_MODE — включаем/выключаем корреляцию (overlay).
			# Реальная корреляция управляется в `_on_num_clicked_extra` (подключена к клику кнопки).
			self.avg20_enabled = False
			# Разморозка уже выполнена выше в начале _num_clicked
			# Адаптивные пороги продолжают работать, не сбрасываются
			self._set_status("XCorr: toggle (no stream mode change)", hold_sec=1.5)
		elif self.stream is not None and idx not in (1, 2, 3, 4, 5):
			try:
				self.stream.close()
			except Exception:
				pass
			self.stream = None
			self.base_buf_len = None
			self.base_buf_len_bytes = None
			self.freq_hz = None
			self.data0 = np.zeros(0, dtype=np.int16)
			self.data1 = np.zeros(0, dtype=np.int16)
			self.data0_even = self.data0
			self.data1_even = self.data1
			self.data0_odd = np.zeros(0, dtype=np.int16)
			self.data1_odd = np.zeros(0, dtype=np.int16)
			self.timestamps = np.zeros(0, dtype=np.float64)
			self._last_sample_ts = None
			self.view_len = 0
			self.slider_start.setEnabled(False)
			self.slider_len.setEnabled(False)
			self._set_status("Поток остановлен", hold_sec=2.0)
		if idx == 0:
			try:
				if os.path.exists(self.state_file):
					os.remove(self.state_file)
			except Exception:
				pass
			print('[sel] 0 (не сохраняется)')
			return
		try:
			with open(self.state_file, 'w', encoding='utf-8') as f:
				json.dump({'sel': idx, 'ts': int(time.time())}, f)
			print(f'[sel] saved {idx}')
		except Exception as e:
			print('[sel] save err', e)

	def _load_saved_sel(self) -> int | None:
		try:
			with open(os.path.join(os.path.dirname(__file__), 'bmi30_sel.json'), 'r', encoding='utf-8') as f:
				obj = json.load(f)
			return int(obj.get('sel'))
		except Exception:
			return None

	def _reader_thread_func(self):
		"""Поток чтения USB: получает пакеты и заполняет data0/data1"""
		def _update_chan_seq(kind: str, seq_val: int):
			"""Обновить шаг/пропуски для одного канала (A/B) по seq."""
			try:
				seq_val = int(seq_val) & 0xFFFFFFFF
			except Exception:
				return
			if kind == 'A':
				last = self.last_seq_a
				hist = self._step_hist_a
				hist_n = '_step_hist_a_n'
				step_attr = 'step_a'
				gap_attr = 'gap_a'
				reord_attr = 'reord_a'
				last_attr = 'last_seq_a'
			else:
				last = self.last_seq_b
				hist = self._step_hist_b
				hist_n = '_step_hist_b_n'
				step_attr = 'step_b'
				gap_attr = 'gap_b'
				reord_attr = 'reord_b'
				last_attr = 'last_seq_b'
			if last is None:
				setattr(self, last_attr, seq_val)
				return
			delta = (seq_val - int(last)) & 0xFFFFFFFF
			# Учим шаг на небольших delta.
			if 0 < delta <= 16:
				try:
					hist[int(delta)] = int(hist.get(int(delta), 0)) + 1
					setattr(self, hist_n, int(getattr(self, hist_n, 0)) + 1)
				except Exception:
					pass
			if int(getattr(self, hist_n, 0)) >= 50:
				try:
					best_step = max(hist.items(), key=lambda kv: kv[1])[0]
					if 1 <= int(best_step) <= 16:
						setattr(self, step_attr, int(best_step))
				except Exception:
					pass
			step = int(getattr(self, step_attr, 1) or 1)
			# Пропуски считаем только для монотонного вперёд (delta small/normal). Остальное -> reord.
			if delta != step:
				if delta > step and delta < 0x80000000:
					if step > 0 and (delta % step) == 0:
						missed = max(1, int(delta // step) - 1)
					else:
						missed = 1
					setattr(self, gap_attr, int(getattr(self, gap_attr, 0)) + int(missed))
				else:
					setattr(self, reord_attr, int(getattr(self, reord_attr, 0)) + 1)
			setattr(self, last_attr, seq_val)
		def _phase_candidates(frame):
			"""Return candidate phase bits from frame fields."""
			out = {}
			try:
				seqv = int(getattr(frame, 'seq', 0))
				# seq may increment by 1, 2, or other step depending on firmware/mode.
				# Keep a few low bits as candidates.
				try:
					adc_id = int(getattr(frame, 'adc_id', 0))
					step = int(self.step_a if adc_id == 0 else self.step_b)
					if step < 1:
						step = 1
					# If step>1 (often step=2 with interleaved windows), seq LSB becomes constant;
					# using (seq//step)&1 restores a 50/50 alternating phase.
					out['seq_div_step_lsb'] = (seqv // step) & 1
				except Exception:
					pass
				out['seq'] = seqv & 1
				out['seq1'] = (seqv >> 1) & 1
				out['seq2'] = (seqv >> 2) & 1
				out['seq3'] = (seqv >> 3) & 1
			except Exception:
				pass
			try:
				tsv = int(getattr(frame, 'timestamp', 0))
				# Timestamp can be a stable cadence marker in AVG_ROI; try a few LSBs.
				out['ts'] = tsv & 1
				out['ts1'] = (tsv >> 1) & 1
				out['ts2'] = (tsv >> 2) & 1
				out['ts3'] = (tsv >> 3) & 1
			except Exception:
				pass
			try:
				rv = int(getattr(frame, 'reserved', 0))
				out['reserved'] = rv & 1
				out['reserved1'] = (rv >> 1) & 1
				out['reserved2'] = (rv >> 2) & 1
				out['reserved3'] = (rv >> 3) & 1
				out['reserved4'] = (rv >> 4) & 1
				out['reserved5'] = (rv >> 5) & 1
				out['reserved6'] = (rv >> 6) & 1
				out['reserved7'] = (rv >> 7) & 1
			except Exception:
				pass
			try:
				r2 = int(getattr(frame, 'reserved2', 0))
				out['reserved2_lsb'] = r2 & 1
				out['reserved2_1'] = (r2 >> 1) & 1
				out['reserved2_2'] = (r2 >> 2) & 1
				out['reserved2_3'] = (r2 >> 3) & 1
				out['reserved2_4'] = (r2 >> 4) & 1
				out['reserved2_5'] = (r2 >> 5) & 1
				out['reserved2_6'] = (r2 >> 6) & 1
				out['reserved2_7'] = (r2 >> 7) & 1
			except Exception:
				pass
			return out

		def _update_phase_key_stats(frame):
			"""Track which bit toggles like a true phase marker (alternating ~50/50)."""
			cands = _phase_candidates(frame)
			for name, bit in cands.items():
				st = self._phase_key_stats.get(name)
				if st is None:
					st = {'n': 0, 'ones': 0, 'toggles': 0, 'last': None, 'mismatch': 0}
					self._phase_key_stats[name] = st
				st['n'] += 1
				st['ones'] += 1 if int(bit) else 0
				if st['last'] is not None and int(bit) != int(st['last']):
					st['toggles'] += 1
				st['last'] = int(bit)

		def _update_phase_key_pair_consistency(a_frame, b_frame):
			"""In paired mode, phase marker should be identical for A and B of the same seq."""
			try:
				ca = _phase_candidates(a_frame)
				cb = _phase_candidates(b_frame)
				for name in set(ca.keys()).intersection(cb.keys()):
					if int(ca[name]) != int(cb[name]):
						st = self._phase_key_stats.get(name)
						if st is None:
							st = {'n': 0, 'ones': 0, 'toggles': 0, 'last': None, 'mismatch': 0}
							self._phase_key_stats[name] = st
						st['mismatch'] = int(st.get('mismatch', 0)) + 1
			except Exception:
				pass

		def _maybe_choose_phase_key():
			if self._phase_key_chosen is not None:
				return
			forced = getattr(self, 'phase_key', 'auto')
			if forced and forced != 'auto':
				self._phase_key_chosen = forced
				if bool(getattr(self, 'debug', False)) or bool(getattr(self, 'phase_trace', False)):
					print(f"[PHASE_KEY] forced={self._phase_key_chosen}", flush=True)
				return
			# wait for enough samples
			min_n = 60
			bias = {
				# Best default when seq increments by step>1 (e.g. step=2): keeps even/odd balanced.
				'seq_div_step_lsb': 6.0,
				'seq': 5.0,
				'seq1': 3.0,
				'ts1': 1.5,
				'ts2': 1.0,
				'ts3': 0.5,
				'reserved2_lsb': 1.0,
				'reserved2_1': 1.0,
				'reserved': 0.0,
				'reserved1': 0.0,
			}
			best = None
			best_score = None
			for name, st in self._phase_key_stats.items():
				n = int(st.get('n', 0))
				if n < min_n:
					continue
				# phase marker must be consistent between channels in the same stereo pair
				if int(st.get('mismatch', 0)) > 0:
					continue
				ones = int(st.get('ones', 0))
				tog = int(st.get('toggles', 0))
				# prefer frequent toggling and ~50/50 distribution
				balance_penalty = abs(ones - (n / 2.0))
				score = float(tog) - float(balance_penalty) + float(bias.get(name, 0.0))
				# reject degenerate constant bits
				if ones == 0 or ones == n:
					continue
				if best_score is None or score > best_score:
					best_score = score
					best = name
			if best is not None:
				self._phase_key_chosen = best
				try:
					st = self._phase_key_stats.get(best, {})
					if bool(getattr(self, 'debug', False)) or bool(getattr(self, 'phase_trace', False)):
						print(f"[PHASE_KEY] auto={best} n={st.get('n')} ones={st.get('ones')} toggles={st.get('toggles')}", flush=True)
				except Exception:
					if bool(getattr(self, 'debug', False)) or bool(getattr(self, 'phase_trace', False)):
						print(f"[PHASE_KEY] auto={best}", flush=True)

		def _phase_toggle_bit(kind: str, frame):
			"""Stable even/odd splitter per channel.
			Default strategy: alternate by arrival order (per channel).
			Why: firmware may reuse the same seq for both phases; relying on seq/timestamp LSB can flip.
			We only suppress toggling on *true duplicates* (same seq AND same timestamp).
			On backward jumps/resets: re-sync.
			"""
			try:
				seqv = int(getattr(frame, 'seq', 0)) & 0xFFFFFFFF
			except Exception:
				seqv = 0
			try:
				tsv = int(getattr(frame, 'timestamp', 0)) & 0xFFFFFFFFFFFFFFFF
			except Exception:
				tsv = 0
			if kind == 'A':
				last_seq_attr = '_phase_last_seq_a'
				last_ts_attr = '_phase_last_ts_a'
				tog_attr = '_phase_toggle_a'
				last_par_attr = '_phase_last_par_a'
				rep_attr = '_phase_repeat_a'
			else:
				last_seq_attr = '_phase_last_seq_b'
				last_ts_attr = '_phase_last_ts_b'
				tog_attr = '_phase_toggle_b'
				last_par_attr = '_phase_last_par_b'
				rep_attr = '_phase_repeat_b'
			last_seq = getattr(self, last_seq_attr, None)
			last_ts = getattr(self, last_ts_attr, None)
			tog = int(getattr(self, tog_attr, 0) or 0)
			# Detect backward jump/resets using seq monotonicity when available
			if last_seq is not None:
				delta = (seqv - int(last_seq)) & 0xFFFFFFFF
				if delta >= 0x80000000:
					# backward jump: reorder/reset
					tog = 0
					setattr(self, tog_attr, tog)
					setattr(self, last_seq_attr, seqv)
					setattr(self, last_ts_attr, tsv)
					setattr(self, last_par_attr, None)
					setattr(self, rep_attr, 0)
					return tog
			# Suppress toggling only on true duplicates
			if last_seq is not None and last_ts is not None and int(last_seq) == int(seqv) and int(last_ts) == int(tsv):
				par = int(tog)
			else:
				tog ^= 1
				par = int(tog)
				setattr(self, tog_attr, tog)
			setattr(self, last_seq_attr, seqv)
			setattr(self, last_ts_attr, tsv)
			# Track repeats (should normally alternate)
			lp = getattr(self, last_par_attr, None)
			if lp is not None and int(lp) == int(par):
				setattr(self, rep_attr, int(getattr(self, rep_attr, 0)) + 1)
			else:
				setattr(self, rep_attr, 0)
			setattr(self, last_par_attr, int(par))
			# Optional tracing
			try:
				if getattr(self, 'phase_trace', False) and int(getattr(self, '_phase_trace_n', 0)) < int(getattr(self, 'phase_trace_limit', 0)):
					self._phase_trace_n = int(getattr(self, '_phase_trace_n', 0)) + 1
					rep = int(getattr(self, rep_attr, 0))
					if rep >= 1:
						print(f"[PHASE_ANOM] {kind} rep={rep} par={par} seq={seqv} ts={tsv} last_seq={last_seq} last_ts={last_ts}", flush=True)
					elif (self._phase_trace_n % 50) == 0:
						print(f"[PHASE] {kind} par={par} seq={seqv} ts={tsv}", flush=True)
			except Exception:
				pass
			return par

		def _phase_bit(kind: str, frame):
			"""Compute phase bit (0/1) using the configured splitter."""
			# In LOSSLESS_ROI (STREAM_MODE=1) use seq parity to avoid missing reserved2.
			try:
				if int(getattr(self, 'stream_mode', 0)) == 1:
					return int(getattr(frame, 'seq', 0)) & 1
			except Exception:
				pass
			key = (self._phase_key_chosen or getattr(self, 'phase_key', 'reserved2') or 'reserved2').strip().lower()
			# Preferred/required path: phase = reserved2 & 1
			if key in ('reserved2', 'reserved2_lsb', 'r2', 'reserved2&1'):
				try:
					return int(getattr(frame, 'reserved2', 0)) & 1
				except Exception:
					# If the field is missing for some reason, fall back to 0 (EVEN)
					return 0
			# Legacy/debug paths are only allowed if explicitly enabled
			allow_legacy = str(os.getenv('BMI30_PHASE_ALLOW_LEGACY', '0')).lower() not in ('0','false','no')
			if not allow_legacy:
				try:
					return int(getattr(frame, 'reserved2', 0)) & 1
				except Exception:
					return 0
			if key == 'toggle':
				return int(_phase_toggle_bit(kind, frame))
			# legacy/diagnostic path: auto-select a toggling bit from frame fields
			try:
				_update_phase_key_stats(frame)
			except Exception:
				pass
			try:
				_maybe_choose_phase_key()
			except Exception:
				pass
			key = (self._phase_key_chosen or getattr(self, 'phase_key', 'auto') or 'auto').strip().lower()
			cands = _phase_candidates(frame)
			if key in cands:
				return int(cands[key])
			if 'seq_div_step_lsb' in cands:
				return int(cands.get('seq_div_step_lsb', 0))
			return int(cands.get('seq', 0))

		def _is_true_duplicate(kind: str, frame) -> bool:
			"""Return True if frame repeats exactly (same seq/timestamp and same payload).
			
			Used to drop duplicate frames before updating even/odd buffers.
			In AVG_ROI mode the device/transport can emit repeats; treating those as new
			frames makes one phase look stale (and previously could trigger PHASE_ANOM).
			"""
			try:
				seqv = int(getattr(frame, 'seq', 0)) & 0xFFFFFFFF
			except Exception:
				seqv = 0
			try:
				tsv = int(getattr(frame, 'timestamp', 0)) & 0xFFFFFFFFFFFFFFFF
			except Exception:
				tsv = 0
			try:
				payload = getattr(frame, 'payload', b'')
				if isinstance(payload, memoryview):
					payload = payload.tobytes()
				if not isinstance(payload, (bytes, bytearray)):
					payload = bytes(payload)
				psig = int(zlib.crc32(payload) & 0xFFFFFFFF)
			except Exception:
				psig = 0
			if kind == 'A':
				last_seq_attr = '_dup_last_seq_a'
				last_ts_attr = '_dup_last_ts_a'
				last_sig_attr = '_dup_last_sig_a'
				cnt_attr = '_dup_drop_a'
			else:
				last_seq_attr = '_dup_last_seq_b'
				last_ts_attr = '_dup_last_ts_b'
				last_sig_attr = '_dup_last_sig_b'
				cnt_attr = '_dup_drop_b'
			last_seq = getattr(self, last_seq_attr, None)
			last_ts = getattr(self, last_ts_attr, None)
			last_sig = getattr(self, last_sig_attr, None)
			is_dup = (
				last_seq is not None
				and last_ts is not None
				and last_sig is not None
				and int(last_seq) == int(seqv)
				and int(last_ts) == int(tsv)
				and int(last_sig) == int(psig)
			)
			setattr(self, last_seq_attr, seqv)
			setattr(self, last_ts_attr, tsv)
			setattr(self, last_sig_attr, psig)
			if is_dup:
				setattr(self, cnt_attr, int(getattr(self, cnt_attr, 0)) + 1)
			return bool(is_dup)

		if bool(getattr(self, 'reader_debug', False)):
			print("[READER] Thread started", flush=True)
		while self.reader_running:
			if self.stream is None:
				time.sleep(0.1)
				continue
			try:
				# Reader must not be throttled by GUI/one-channel waits.
				# In independent mode, fetch A/B directly from per-channel queues.
				a = None
				b = None
				independent_mode = False
				try:
					asm = getattr(self.stream, 'asm', None)
					independent_mode = bool(asm is not None and getattr(asm, 'independent', False))
				except Exception:
					independent_mode = False

				if independent_mode:
					try:
						a = self.stream.get_frame(0, timeout=0.0)
					except Exception:
						a = None
					try:
						b = self.stream.get_frame(1, timeout=0.0)
					except Exception:
						b = None
					# If both queues are empty, wait briefly for at least one frame.
					if a is None and b is None:
						pair = self.stream.get_stereo(timeout=0.02)
						if not pair:
							continue
						if isinstance(pair, tuple) and isinstance(pair[0], str) and pair[0] in ('A', 'B'):
							chan, frame = pair
							if chan == 'A':
								a = frame; b = None
							else:
								a = None; b = frame
						else:
							a, b = pair
				else:
					pair = self.stream.get_stereo(timeout=0.1)
					if not pair:
						continue
					# paired mode
					a, b = pair

				# Reset USB error streak on successful read
				try:
					self._usb_err_count = 0
				except Exception:
					pass

				# Help auto-detect phase key: in paired mode, enforce A/B consistency for candidates.
				# (Only relevant when phase_key=='auto'; default is stable 'toggle'.)
				if (getattr(self, 'phase_key', 'toggle') == 'auto') and a is not None and b is not None:
					_update_phase_key_pair_consistency(a, b)

				# Пер-канальные seq/gap: обновляем всегда (даже если пары склеены relaxed-режимом).
				try:
					if a is not None and getattr(a, 'seq', None) is not None:
						_update_chan_seq('A', int(a.seq))
					if b is not None and getattr(b, 'seq', None) is not None:
						_update_chan_seq('B', int(b.seq))
				except Exception:
					pass

				# При необходимости можно явно сбросить накопленную очередь ассемблера (независимый режим),
				# чтобы не было задержки из старых кадров. Выключено по умолчанию, включается env BMI30_FLUSH_ASM_QUEUE=1.
				if getattr(self, 'flush_asm_queue', False) and getattr(self, 'independent_channels', False) and int(getattr(self, 'stream_mode', 0)) == 0:
					try:
						asm = getattr(self.stream, 'asm', None)
						# independent: trim qA/qB; paired: trim q
						if asm is not None and getattr(asm, 'independent', False):
							for tag in ('qA', 'qB'):
								q = getattr(asm, tag, None)
								if q is None or not hasattr(q, 'qsize'):
									continue
								qs = q.qsize()
								if qs <= 1:
									continue
								last_item = None
								while True:
									try:
										item = q.get_nowait()
										last_item = item
									except Exception:
										break
								if last_item is not None:
									try:
										q.put_nowait(last_item)
									except Exception:
										pass
								print(f"[ASM_FLUSH] {tag} trimmed (was {qs}), kept latest. new={q.qsize() if hasattr(q,'qsize') else '?'}", flush=True)
						else:
							q = getattr(asm, 'q', None)
							if q is not None and hasattr(q, 'qsize'):
								qs = q.qsize()
								if qs > 0:
									last_item = None
									while True:
										try:
											item = q.get_nowait()
											last_item = item
										except Exception:
											break
									if last_item is not None:
										try:
											q.put_nowait(last_item)
										except Exception:
											pass
									print(f"[ASM_FLUSH] queue trimmed (was {qs}), kept latest. new_q={q.qsize() if hasattr(q,'qsize') else '?'}", flush=True)
					except Exception:
						pass

				ch0 = np.frombuffer(a.payload, dtype='<u2').astype(np.int32) if a is not None else None
				ch1 = np.frombuffer(b.payload, dtype='<u2').astype(np.int32) if b is not None else None
				
				# --- diagnostics: compute sequence/timestamps early to detect pairing issues ---
				if a is not None and b is not None:
					try:
						seq_a = int(a.seq)
						seq_b = int(b.seq)
					except Exception:
						seq_a = getattr(a, 'seq', None)
						seq_b = getattr(b, 'seq', None)
					try:
						ts_a = a.timestamp / 1_000_000.0
						ts_b = b.timestamp / 1_000_000.0
					except Exception:
						ts_a = ts_b = None

					# If mismatch, record diagnostics and optionally capture to file
					if seq_a != seq_b:
						self._pair_mismatch_count = int(getattr(self, '_pair_mismatch_count', 0)) + 1
						nowp = time.time()
						last_pair_t = float(getattr(self, '_last_pair_mismatch_t', 0.0))
						if (self._pair_mismatch_count % 200) == 0 or (nowp - last_pair_t) > 4.0:
							asm_info = ''
							try:
								asm = getattr(self.stream, 'asm', None)
								if asm is not None:
									asm_info = f" ts_pairs={getattr(asm, '_ts_pair_count', 0)} seq_neigh_pairs={getattr(asm, '_seq_neighbor_pairs', 0)} q={asm.q.qsize()}"
							except Exception:
								asm_info = ''
							if bool(getattr(self, 'reader_debug', False)):
								print(
								f"[PAIR_MISMATCH] count={self._pair_mismatch_count} last seqA={seq_a} seqB={seq_b} "
								f"lenA={len(ch0)} lenB={len(ch1)} flagsA={getattr(a,'flags',None)} flagsB={getattr(b,'flags',None)}{asm_info}",
								flush=True,
							)
							self._last_pair_mismatch_t = nowp
						# capture to file if configured
						try:
							if getattr(self, 'capture_diag_path', None):
								if self._capture_diag_fp is None:
									self._capture_diag_fp = open(self.capture_diag_path, 'a', encoding='utf-8', errors='replace')
									self._capture_diag_started = time.time()
									self._capture_diag_lines = 0
									self._capture_diag_fp.write('#ts_unix,seqA,seqB,lenA,lenB,flagsA,flagsB,tsA,tsB,asm_ts_pairs,asm_seq_neigh_pairs,last_stat_hex\n')
									self._capture_diag_fp.flush()
								# write one line per mismatch while capture window open
								if self._capture_diag_fp is not None and (time.time() - self._capture_diag_started) <= float(self.capture_diag_seconds) and self._capture_diag_lines < int(self.capture_diag_limit):
									try:
										last_stat = getattr(self.stream, 'last_stat', None)
										stat_hex = last_stat.hex() if isinstance(last_stat, (bytes, bytearray)) else ''
										asm = getattr(self.stream, 'asm', None)
										ts_pairs = getattr(asm, '_ts_pair_count', 0) if asm else 0
										neigh = getattr(asm, '_seq_neighbor_pairs', 0) if asm else 0
										line = f"{time.time():.6f},{seq_a},{seq_b},{len(ch0)},{len(ch1)},{getattr(a,'flags',None)},{getattr(b,'flags',None)},{ts_a if ts_a is not None else ''},{ts_b if ts_b is not None else ''},{ts_pairs},{neigh},\"{stat_hex}\"\n"
										self._capture_diag_fp.write(line)
										self._capture_diag_fp.flush()
										self._capture_diag_lines += 1
									except Exception:
										pass
								# close if time or limit exceeded
								try:
									if self._capture_diag_fp is not None and ((time.time() - self._capture_diag_started) > float(self.capture_diag_seconds) or self._capture_diag_lines >= int(self.capture_diag_limit)):
										try:
											self._capture_diag_fp.close()
										except Exception:
											pass
										self._capture_diag_fp = None
								except Exception:
									pass
						except Exception:
							pass

				# Лог размеров кадров (опционально)
				if getattr(self, 'log_frame_len', False) and getattr(self, '_log_frame_len_count', 0) < getattr(self, 'log_frame_len_limit', 0):
					try:
						seq_a = getattr(a, 'seq', None) if a is not None else None
						seq_b = getattr(b, 'seq', None) if b is not None else None
						len_a = len(ch0) if ch0 is not None else 0
						len_b = len(ch1) if ch1 is not None else 0
						print(f"[FRAME_LEN] seqA={seq_a} seqB={seq_b} lenA={len_a} lenB={len_b} flagsA={getattr(a,'flags',None) if a is not None else None} flagsB={getattr(b,'flags',None) if b is not None else None}", flush=True)
						self._log_frame_len_count += 1
					except Exception:
						pass

				# Трассировка содержимого по блокам (каждые 100 семплов) для диагностики мигания хвоста
				if getattr(self, 'chunk_trace', False) and getattr(self, '_chunk_trace_count', 0) < getattr(self, 'chunk_trace_limit', 0):
					try:
						def _chunk_stats(arr, tag):
							if arr is None or len(arr) == 0:
								return f"{tag}:None"
							# группируем по 100 семплов (12 блоков для 1200)
							chunks = arr.reshape(-1, 100) if len(arr) % 100 == 0 else np.array_split(arr, max(1, len(arr)//100))
							parts = []
							for idx, c in enumerate(chunks):
								try:
									parts.append(f"{idx*100}:{int(np.min(c))}-{int(np.max(c))}")
								except Exception:
									parts.append(f"{idx*100}:err")
							return f"{tag}=[" + ' '.join(parts) + "]"
						msg_a = _chunk_stats(ch0, "A") if ch0 is not None else "A:None"
						msg_b = _chunk_stats(ch1, "B") if ch1 is not None else "B:None"
						print(f"[CHUNK] {msg_a} {msg_b}", flush=True)
						self._chunk_trace_count += 1
					except Exception:
						pass

				# Мониторинг редких сбоев по конкретному семплу (по умолчанию индекс 300)
				if getattr(self, 'monitor_sample', False):
					idx = max(0, int(getattr(self, 'monitor_index', 300)))
					try:
						if ch0 is not None and len(ch0) > idx:
							val = int(ch0[idx])
							if self._last_mon_a is None:
								self._last_mon_a = val
							elif val != self._last_mon_a:
								print(f"[MON] A idx={idx} changed {self._last_mon_a}->{val} seqA={getattr(a,'seq',None)} lenA={len(ch0)}", flush=True)
								self._last_mon_a = val
						if ch1 is not None and len(ch1) > idx:
							valb = int(ch1[idx])
							if self._last_mon_b is None:
								self._last_mon_b = valb
							elif valb != self._last_mon_b:
								print(f"[MON] B idx={idx} changed {self._last_mon_b}->{valb} seqB={getattr(b,'seq',None)} lenB={len(ch1)}", flush=True)
								self._last_mon_b = valb
					except Exception:
						pass

				# Инициализация/обновление base_buf_len при первом кадре или смене длины
				first_len = len(ch0) if ch0 is not None else (len(ch1) if ch1 is not None else None)
				if first_len is not None:
					with self.data_lock:
						if (self.base_buf_len is None) or (self.base_buf_len != first_len):
							old_len = self.base_buf_len
							self.base_buf_len = first_len
							self.base_buf_len_bytes = self.base_buf_len * 2
							self._sliders_initialized = False
							# Используем выбранную частоту
							self.freq_hz = getattr(self, 'desired_freq', 200)
							if bool(getattr(self, 'reader_debug', False)):
								print(f"[READER] Buffer size changed: {old_len} -> {self.base_buf_len} семплов, freq={self.freq_hz}Hz", flush=True)
				
				# Копируем данные в shared buffers (поддержка независимых каналов)
				with self.data_lock:
					current_time = time.time()
					if ch0 is not None:
						# Drop exact duplicate frames (same seq+ts) to avoid stale even/odd artifacts
						try:
							if a is not None and _is_true_duplicate('A', a):
								ch0 = None
						except Exception:
							pass
					if ch0 is not None:
						# even/odd selection by detected phase bit
						try:
							par = _phase_bit('A', a) if a is not None else 0
							seqv = int(getattr(a, 'seq', 0)) if a is not None else 0
						except Exception:
							par = 0
							seqv = 0
						tgt = self.data0_odd if par else self.data0_even
						tgt[:len(ch0)] = ch0
						# mark that new data arrived and we should recompute xcorr (schedule outside lock)
						self._need_xcorr = True
						# Also trigger phase shift search in background worker (latest-only)
						try:
							self._request_phase_shift_search()
						except Exception:
							pass
						if len(ch0) < self.max_samples:
							tgt[len(ch0):] = 0
						if par:
							self.seq0_odd = seqv
							self._last_a_odd_t = current_time
						else:
							self.seq0_even = seqv
							self._last_a_even_t = current_time
						# Per-parity rhythm counters + timestamp cadence
						try:
							ts = int(getattr(a, 'timestamp', 0)) if a is not None else None
						except Exception:
							ts = None
						if par:
							self.frames_a_odd += 1
							if ts is not None and self._ts_a_odd is not None:
								self._dt_a_odd = float((ts - int(self._ts_a_odd)) / 1_000_000.0)
							if ts is not None:
								self._ts_a_odd = ts
						else:
							self.frames_a_even += 1
							if ts is not None and self._ts_a_even is not None:
								self._dt_a_even = float((ts - int(self._ts_a_even)) / 1_000_000.0)
							if ts is not None:
								self._ts_a_even = ts
						
					# Флаг для немедленного детектирования
					self._need_detect = True
					
					if ch1 is not None:
						try:
							if b is not None and _is_true_duplicate('B', b):
								ch1 = None
						except Exception:
							pass
					if ch1 is not None:
						try:
							par = _phase_bit('B', b) if b is not None else 0
							seqv = int(getattr(b, 'seq', 0)) if b is not None else 0
						except Exception:
							par = 0
							seqv = 0
						tgt = self.data1_odd if par else self.data1_even
						tgt[:len(ch1)] = ch1
						# mark that new data arrived and we should recompute xcorr (schedule outside lock)
						self._need_xcorr = True
						# Also trigger phase shift search in background worker (latest-only)
						try:
							self._request_phase_shift_search()
						except Exception:
							pass
						if len(ch1) < self.max_samples:
							tgt[len(ch1):] = 0
						if par:
							self.seq1_odd = seqv
							self._last_b_odd_t = current_time
						else:
							self.seq1_even = seqv
							self._last_b_even_t = current_time
						# Per-parity rhythm counters + timestamp cadence
						try:
							ts = int(getattr(b, 'timestamp', 0)) if b is not None else None
						except Exception:
							ts = None
						if par:
							self.frames_b_odd += 1
							if ts is not None and self._ts_b_odd is not None:
								self._dt_b_odd = float((ts - int(self._ts_b_odd)) / 1_000_000.0)
							if ts is not None:
								self._ts_b_odd = ts
						else:
							self.frames_b_even += 1
							if ts is not None and self._ts_b_even is not None:
								self._dt_b_even = float((ts - int(self._ts_b_even)) / 1_000_000.0)
							if ts is not None:
								self._ts_b_even = ts
						
					# Флаг для немедленного детектирования
					self._need_detect = True
					
					# Сохранять DC offset в файл каждые 10 минут (при STREAM_MODE=1)
					if getattr(self, 'stream_mode', 0) == 1 and (current_time - self.dc_last_save >= self.dc_save_interval):
						self._save_dc_offset()
						self.dc_last_save = current_time

					# Phase sync diagnostics: expected even ~= -odd (after DC removal) at lag=0
					if getattr(self, 'phase_diag', False) and self.base_buf_len is not None:
						self._phase_diag_frames += 1
						if self._phase_diag_frames % max(1, int(getattr(self, 'phase_diag_every', 50))) == 0:
							try:
								maxlag = max(0, int(getattr(self, 'phase_diag_maxlag', 20)))
							except Exception:
								maxlag = 20
							def _best_lag(even_arr: np.ndarray, odd_arr: np.ndarray):
								# compare even to inverted odd; return (corr0, best_lag, best_corr)
								if even_arr.size == 0 or odd_arr.size == 0:
									return (None, None, None)
								a0 = even_arr.astype(np.float64)
								b0 = odd_arr.astype(np.float64)
								# DC removal
								a0 = a0 - float(np.mean(a0))
								b0 = b0 - float(np.mean(b0))
								na = float(np.linalg.norm(a0)) + 1e-12
								nb = float(np.linalg.norm(b0)) + 1e-12
								corr0 = float(np.dot(a0, b0) / (na * nb))
								# best lag for a0 ~ -b0 (maximize corr with inverted b)
								best_lag = 0
								best_corr = float(np.dot(a0, -b0) / (na * nb))
								if maxlag > 0 and a0.size > (2 * maxlag + 4):
									for lag in range(-maxlag, maxlag + 1):
										if lag == 0:
											continue
										if lag > 0:
											a = a0[lag:]
											b = -b0[:-lag]
										else:
											a = a0[:lag]
											b = -b0[-lag:]
										nna = float(np.linalg.norm(a)) + 1e-12
										nnb = float(np.linalg.norm(b)) + 1e-12
										c = float(np.dot(a, b) / (nna * nnb))
										if c > best_corr:
											best_corr = c
											best_lag = lag
								return (corr0, best_lag, best_corr)
							try:
								n = int(self.base_buf_len)
								if n > 0:
									ch0e = self.data0_even[:n]
									ch0o = self.data0_odd[:n]
									ch1e = self.data1_even[:n]
									ch1o = self.data1_odd[:n]
									c0, lag0, bc0 = _best_lag(ch0e, ch0o)
									c1, lag1, bc1 = _best_lag(ch1e, ch1o)
									if bool(getattr(self, 'reader_debug', False)):
										print(
										"[PHASE] "
										f"CH0 se={self.seq0_even} so={self.seq0_odd} corr0={c0:.3f} best_lag={lag0} best_corr={bc0:.3f} | "
										f"CH1 se={self.seq1_even} so={self.seq1_odd} corr0={c1:.3f} best_lag={lag1} best_corr={bc1:.3f}",
										flush=True,
									)
							except Exception:
								pass
					# Отладочные маркеры: линейный рамп по всему буферу [0..65535]
					if getattr(self, 'debug_markers', False):
						try:
							buf_len = len(ch0) if ch0 is not None else (len(ch1) if ch1 is not None else 0)
							buf_len = min(buf_len, self.max_samples)
							if buf_len > 0:
								vals = np.linspace(0, 65535, num=buf_len, dtype=np.int32)
								self.data0_even[:buf_len] = vals
								self.data0_odd[:buf_len] = vals
								self.data1_even[:buf_len] = vals
								self.data1_odd[:buf_len] = vals
								# mark new data for xcorr
								self._need_xcorr = True
								# Also trigger phase shift search in background worker (latest-only)
								try:
									self._request_phase_shift_search()
								except Exception:
									pass
								if buf_len < self.max_samples:
									self.data0_even[buf_len:] = 0
									self.data0_odd[buf_len:] = 0
									self.data1_even[buf_len:] = 0
									self.data1_odd[buf_len:] = 0
								try:
									idx_min = int(np.argmin(self.data0[:buf_len]))
									idx_max = int(np.argmax(self.data0[:buf_len]))
									print(f"[MARK] buf_len={buf_len} min_idx={idx_min} max_idx={idx_max}")
								except Exception:
									pass
						except Exception:
							pass
					if self.freq_hz:
						dt = 1.0 / self.freq_hz
						# choose available frame to compute timestamps
						src = a if a is not None else b
						how_many = len(ch0) if ch0 is not None else (len(ch1) if ch1 is not None else 0)
						if how_many > 0 and getattr(src, 'timestamp', None) is not None:
							ts_start = src.timestamp / 1_000_000.0
							ts = ts_start + np.arange(how_many) * dt
							self.timestamps[:len(ts)] = ts
							if len(ts) < self.max_samples:
								self.timestamps[len(ts):] = 0.0
					self.last_frame_t = time.time()
					# Обновим счетчики и проверим разрывы в режиме пар (если оба канала пришли одновременно)
					if a is not None and b is not None:
						if not getattr(self.stream, 'asm', None) or not getattr(self.stream.asm, 'independent', False):
							# ВАЖНО: если seqA!=seqB, это не «пропуск пар», а рассинхрон/независимый счётчик.
							try:
								pair_match = int(a.seq) == int(b.seq)
							except Exception:
								pair_match = False
							if pair_match:
								# Если seq не меняется длительное время — считаем зависанием.
								try:
									now_seq = time.time()
									prev_seq = getattr(self, '_last_seq_value', None)
									if prev_seq is None:
										self._last_seq_value = a.seq
										self._last_seq_advance_t = now_seq
									elif int(a.seq) == int(prev_seq):
										stall_s = float(now_seq - float(getattr(self, '_last_seq_advance_t', now_seq)))
										thr_s = float(getattr(self, 'seq_stall_after', 3.0) or 3.0)
										if stall_s >= thr_s:
											self._maybe_auto_reset_on_stall("seq не меняется", stall_s)
									else:
										self._last_seq_value = a.seq
										self._last_seq_advance_t = now_seq
								except Exception:
									pass
								# Доп. защита: короткий цикл из 1–2 seq значений на протяжении окна
								try:
									self._seq_recent.append((time.time(), int(a.seq)))
									if len(self._seq_recent) >= 6:
										seq_vals = [v for (_t, v) in self._seq_recent]
										unique = set(seq_vals)
										window_s = float(self._seq_recent[-1][0] - self._seq_recent[0][0])
										thr_s = float(getattr(self, 'seq_stall_after', 3.0) or 3.0)
										max_cycle = int(getattr(self, 'seq_cycle_max', 12) or 12)
										# Короткий цикл (1–2 значения)
										if window_s >= thr_s and len(unique) <= 2:
											self._maybe_auto_reset_on_stall("seq зациклен", window_s)
										# Длинный цикл (<= max_cycle значений)
										elif window_s >= thr_s and len(self._seq_recent) >= max(12, 2 * max_cycle) and len(unique) <= max_cycle:
											self._maybe_auto_reset_on_stall("seq цикл", window_s)
								except Exception:
									pass
								# Считаем gap только для "настоящих" стерео-пар (seqA==seqB).
								if self.last_seq is None:
									self.last_seq = a.seq
								else:
									delta = (int(a.seq) - int(self.last_seq)) & 0xFFFFFFFF
									if 0 < delta <= 16:
										try:
											self._seq_step_hist[int(delta)] = int(self._seq_step_hist.get(int(delta), 0)) + 1
											self._seq_step_hist_n = int(self._seq_step_hist_n) + 1
										except Exception:
											pass
									if int(getattr(self, '_seq_step_hist_n', 0)) >= 50:
										try:
											best_step = max(self._seq_step_hist.items(), key=lambda kv: kv[1])[0]
											if 1 <= int(best_step) <= 16:
												self.seq_step = int(best_step)
										except Exception:
											pass
									step = int(getattr(self, 'seq_step', 1) or 1)
									if delta != step:
										missed = 0
										if delta > step and delta < 0x80000000:
											if step > 0 and (delta % step) == 0:
												missed = max(1, int(delta // step) - 1)
											else:
												missed = 1
											self.gap_count += int(missed)
											self._gap_log_pending += int(missed)
										else:
											self.seq_reorder_count = int(getattr(self, 'seq_reorder_count', 0)) + 1
										# GAP-capture (опционально) только при реальном missed>0
										if missed > 0 and getattr(self, 'gap_capture_path', None):
											try:
												if self._gap_capture_fp is None:
													self._gap_capture_fp = open(self.gap_capture_path, 'a', encoding='utf-8', errors='replace')
													self._gap_capture_started = time.time()
													self._gap_capture_lines = 0
													self._gap_capture_fp.write('#ts_unix,last_seq,seq,delta,step,missed,pm,stereo_q,bufA,bufB,usb_magic_bad,usb_crc_bad,usb_bytes_per_s\n')
													self._gap_capture_fp.flush()
												# write line if within capture window
												if (time.time() - float(self._gap_capture_started)) <= float(self.gap_capture_seconds) and int(self._gap_capture_lines) < int(self.gap_capture_limit):
													asm = getattr(self.stream, 'asm', None)
													stereo_q = asm.q.qsize() if asm is not None and hasattr(asm, 'q') else 0
													bufA = len(getattr(asm, 'bufA', {}) or {}) if asm is not None else 0
													bufB = len(getattr(asm, 'bufB', {}) or {}) if asm is not None else 0
													pm = int(getattr(self, '_pair_mismatch_count', 0))
													usb_magic_bad = int(getattr(self.stream, 'magic_bad', 0))
													usb_crc_bad = int(getattr(self.stream, 'crc_bad', 0))
													usb_bps = int(getattr(self.stream, 'bytes', 0))
													line = f"{time.time():.6f},{int(self.last_seq)},{int(a.seq)},{int(delta)},{int(step)},{int(missed)},{pm},{stereo_q},{bufA},{bufB},{usb_magic_bad},{usb_crc_bad},{usb_bps}\n"
													self._gap_capture_fp.write(line)
													self._gap_capture_lines = int(self._gap_capture_lines) + 1
													if (int(self._gap_capture_lines) % 10) == 0:
														self._gap_capture_fp.flush()
												# close if time or limit exceeded
												if (time.time() - float(self._gap_capture_started)) > float(self.gap_capture_seconds) or int(self._gap_capture_lines) >= int(self.gap_capture_limit):
													try:
														self._gap_capture_fp.close()
													except Exception:
														pass
													self._gap_capture_fp = None
											except Exception:
												pass
										# throttled GAP log
										exp = (int(self.last_seq) + step) & 0xFFFFFFFF
										self._gap_log_last_exp = exp
										self._gap_log_last_got = int(a.seq)
										if self.gap_log_enabled:
											now_gap = time.time()
											if self.gap_log_every <= 0 or (now_gap - self._gap_log_last_t) >= self.gap_log_every:
												pending = int(self._gap_log_pending)
												self._gap_log_pending = 0
												self._gap_log_last_t = now_gap
												if bool(getattr(self, 'reader_debug', False)):
													print(f"[GAP] +{pending} step={step} ожидаю {exp}, получил {int(a.seq)} (delta={delta}) total={self.gap_count} reord={int(getattr(self,'seq_reorder_count',0))}", flush=True)
									self.last_seq = a.seq
						self.frames_sec += 2
						self.frames_a += 1
						self.frames_b += 1
					else:
						# independent mode: increment only the channel(s) that arrived
						if a is not None:
							self.frames_sec += 1
							self.frames_a += 1
						if b is not None:
							self.frames_sec += 1
							self.frames_b += 1
					
					# Диагностика каждые 100 кадров
					if not hasattr(self, '_reader_count'):
						self._reader_count = 0
					self._reader_count += 1
					if self._reader_count % 100 == 0:
						extra = ''
						try:
							s0 = ch0[:5] if ch0 is not None else 'None'
						except Exception:
							s0 = 'ERR'
						try:
							s1 = ch1[:5] if ch1 is not None else 'None'
						except Exception:
							s1 = 'ERR'
						if bool(getattr(self, 'reader_debug', False)):
							print(f"[READER] Received {self._reader_count} frames, ch0[0:5]={s0}, ch1[0:5]={s1}", flush=True)
				
			except Exception as e:
				msg = str(e)
				if any(x in msg for x in ("Resource busy", "[Errno 16]", "[Errno 19]", "[Errno 32]", "[Errno 110]")):
					print(f"[READER] USB error: {e}", flush=True)
					now_err = time.time()
					try:
						last_t = float(getattr(self, '_usb_err_last_t', 0.0) or 0.0)
					except Exception:
						last_t = 0.0
					try:
						if (now_err - last_t) > 2.0:
							self._usb_err_count = 0
						self._usb_err_last_t = now_err
						self._usb_err_count = int(getattr(self, '_usb_err_count', 0)) + 1
						err_cnt = int(getattr(self, '_usb_err_count', 0))
						if err_cnt >= 3:
							try:
								if self.stream is not None:
									self.stream.disconnected = True
							except Exception:
								pass
							# После нескольких подряд ошибок сразу просим аппаратный сброс.
							self._usb_err_need_hw_reset = True
							# При более длинной серии дополнительно просим power-cycle USB порта.
							if err_cnt >= 6:
								self._usb_err_need_power_cycle = True
					except Exception:
						pass
					time.sleep(0.5)
					continue
				print(f"[READER] Exception: {e}", flush=True)
				time.sleep(0.1)
		if bool(getattr(self, 'reader_debug', False)):
			print("[READER] Thread stopped", flush=True)
	
	def _tick(self):
		"""GUI thread: читает из shared buffers и отображает данные ВСЕГДА"""
		# Обновляем внешний гейт детекции по GPIO23 и применяем блокировку при 0.
		try:
			self._poll_det_gate_gpio23()
			self._apply_det_gate_state()
		except Exception:
			pass
		# Обработка статуса подключения
		if self.stream is None:
			self._last_sample_ts = None
			if self.num_group.checkedId() != 0:
				if not self._connecting:
					self._set_status("Подключение…", hold_sec=1.5)
					self._activate_stream()
			else:
				self._set_status("Поток остановлен")
		
		# Проверка disconnected (но продолжаем отображать данные)
		if self.stream is not None and getattr(self.stream, 'disconnected', False):
			try:
				self.stream.close()
			except Exception:
				pass
			self.stream = None
			self._last_sample_ts = None
			# Агрессивное восстановление: reset устройства, при повторах — power-cycle USB.
			try:
				need_hw = bool(getattr(self, '_usb_err_need_hw_reset', False))
			except Exception:
				need_hw = False
			try:
				need_power = bool(getattr(self, '_usb_err_need_power_cycle', False))
			except Exception:
				need_power = False
			now_rec = time.time()
			try:
				last_hw = float(getattr(self, '_usb_disc_last_hw_reset_t', 0.0) or 0.0)
			except Exception:
				last_hw = 0.0
			try:
				last_pw = float(getattr(self, '_usb_disc_last_power_t', 0.0) or 0.0)
			except Exception:
				last_pw = 0.0
			# Всегда пытаемся аппаратный сброс при disconnect (с троттлингом)
			if need_hw or (now_rec - last_hw) >= 5.0:
				try:
					self._usb_err_need_hw_reset = False
				except Exception:
					pass
				try:
					self._set_status("USB занят/отключён, аппаратный сброс…", hold_sec=2.0)
				except Exception:
					pass
				try:
					self._hardware_reset_device()
					self._usb_disc_last_hw_reset_t = now_rec
				except Exception:
					pass
			# Если reset не помогает/серия ошибок длинная — power-cycle порта
			if need_power and (now_rec - last_pw) >= 15.0:
				try:
					self._usb_err_need_power_cycle = False
				except Exception:
					pass
				try:
					self._set_status("USB занят/отключён, перезапитка порта…", hold_sec=2.0)
					self._power_cycle_usb_port()
					self._usb_disc_last_power_t = now_rec
				except Exception:
					pass
			self.usb_retry_timer.start()
			self._activate_stream()
			return
		
		# Читаем данные из shared buffers с блокировкой (ВСЕГДА, даже если stream=None)
		with self.data_lock:
			# Всегда держим окно на весь кадр
			if self.base_buf_len is not None:
				try:
					self.slider_start.blockSignals(True)
					self.slider_len.blockSignals(True)
				except Exception:
					pass
				# Инициализируем слайдеры только при первой инициализации
				# или если длина буфера изменилась (чтобы не сбрасывать позицию
				# при каждом тике GUI, когда мы только перемещаем ползунки).
				if (not getattr(self, '_sliders_initialized', False)) or getattr(self, '_last_buf_len', None) != self.base_buf_len:
					self._init_sliders(self.base_buf_len)
					self._last_buf_len = self.base_buf_len
			
			# Используем base_buf_len если установлен, иначе max_samples
			buf_len = self.base_buf_len if self.base_buf_len is not None else self.max_samples
			
			# Вычисляем окно отображения
			slider_val = int(self.slider_len.value())
			vlen_calc = buf_len if not hasattr(self, '_sliders_initialized') else slider_val
			vlen = max(1, min(vlen_calc, buf_len))
			if hasattr(self, '_sliders_initialized'):
				self.slider_start.setMaximum(max(0, buf_len - vlen))
			vstart = min(int(self.slider_start.value()) if hasattr(self, '_sliders_initialized') else 0, max(0, buf_len - vlen))
			vlen = min(vlen, self.max_samples - vstart)
			if vlen <= 0:
				vlen = buf_len  # Fallback
			self.view_start = vstart
			self.view_len = vlen
			# NB: реальные сегменты берутся внутри _update_view(); здесь важно лишь вычислить окно.
		now = time.time()
		if now - self.last_fps_t >= 1.0:
			dt_fps = max(1e-6, (now - self.last_fps_t))
			# processing FPS (fallback/compat)
			proc_fps = self.frames_sec / dt_fps
			proc_afps = self.frames_a / dt_fps
			proc_bfps = self.frames_b / dt_fps
			# per-parity processing cadence (diagnostics)
			self.afps_even = self.frames_a_even / dt_fps
			self.afps_odd = self.frames_a_odd / dt_fps
			self.bfps_even = self.frames_b_even / dt_fps
			self.bfps_odd = self.frames_b_odd / dt_fps
			# Prefer real transport receive rates from USBStream counters.
			# This is independent from GUI redraw rate and reader-side processing jitter.
			rx_afps = None
			rx_bfps = None
			try:
				st = getattr(self, 'stream', None)
				if st is not None:
					rxa = int(getattr(st, 'rx_cnt_ch0', 0))
					rxb = int(getattr(st, 'rx_cnt_ch1', 0))
					pa = getattr(self, '_rx_cnt_a_prev', None)
					pb = getattr(self, '_rx_cnt_b_prev', None)
					if pa is not None and pb is not None:
						da = int(rxa) - int(pa)
						db = int(rxb) - int(pb)
						if da >= 0 and db >= 0:
							rx_afps = float(da) / dt_fps
							rx_bfps = float(db) / dt_fps
					self._rx_cnt_a_prev = int(rxa)
					self._rx_cnt_b_prev = int(rxb)
			except Exception:
				rx_afps = None
				rx_bfps = None

			self.afps = float(rx_afps) if rx_afps is not None else float(proc_afps)
			self.bfps = float(rx_bfps) if rx_bfps is not None else float(proc_bfps)
			self.fps = float(proc_fps)  # общая FPS оставляем как processing/compat
			self.frames_sec = 0
			self.frames_a = 0
			self.frames_b = 0
			self.frames_a_even = 0
			self.frames_a_odd = 0
			self.frames_b_even = 0
			self.frames_b_odd = 0
			self.last_fps_t = now
		# auto symmetric y-range update (0.5s throttle) — ТОЛЬКО если включено BMI30_Y_AUTO=1
		if self.y_auto and (now - self.last_range_t > 0.5) and (len(self.data0) or len(self.data1)):
			try:
				maxv = 1
				if len(self.data0):
					maxv = max(maxv, int(np.max(self.data0)))
					maxv = max(maxv, abs(int(np.min(self.data0))))
				if len(self.data1):
					maxv = max(maxv, int(np.max(self.data1)))
					maxv = max(maxv, abs(int(np.min(self.data1))))
				# небольшая защита от нуля
				span = max(64, maxv * 1.05)
				# экспоненциальное сглаживание перепадов амплитуды
				alpha = 0.25
				if self._y_span_smooth is None:
					self._y_span_smooth = span
				else:
					self._y_span_smooth = alpha * span + (1 - alpha) * self._y_span_smooth
				self.p0.setYRange(-self._y_span_smooth, self._y_span_smooth, padding=0.02)
				self.p1.setYRange(-self._y_span_smooth, self._y_span_smooth, padding=0.02)
			except Exception:
				pass
			self.last_range_t = now
		buf_info = ""
		if self.base_buf_len is not None:
			freq_part = f" FREQ:{self.freq_hz}Hz" if self.freq_hz else ""
			buf_info = f" BUF:{self.base_buf_len}({self.base_buf_len_bytes}B){freq_part}"
		# legend_lbl: wordWrap включен (иначе окно может раздуваться по ширине)
		_zero_part = f" ZERO:{self.zero_blocks}" if getattr(self, 'zero_blocks', 0) else ""
		asm_stat = ''
		try:
			asm = getattr(self.stream, 'asm', None)
			if asm is not None:
				bufA = len(getattr(asm, 'bufA', {}) or {})
				bufB = len(getattr(asm, 'bufB', {}) or {})
				qsz = asm.q.qsize() if hasattr(asm, 'q') else 0
				pm = int(getattr(self, '_pair_mismatch_count', 0))
				dp = int(getattr(asm, 'drop_pairs', 0))
				da = int(getattr(asm, 'drop_a', 0))
				db = int(getattr(asm, 'drop_b', 0))
				asm_stat = f" ASM(ts_pairs={getattr(asm, '_ts_pair_count', 0)} neigh={getattr(asm, '_seq_neighbor_pairs', 0)} q={qsz} bufA={bufA} bufB={bufB} PM={pm} dropP={dp} dropA={da} dropB={db})"
		except Exception:
			asm_stat = ''
		_dt_a = ''
		_dt_b = ''
		try:
			if self._dt_a_even is not None or self._dt_a_odd is not None:
				_dt_a = f" dte/dto:{(self._dt_a_even if self._dt_a_even is not None else -1):.3f}/{(self._dt_a_odd if self._dt_a_odd is not None else -1):.3f}s"
		except Exception:
			_dt_a = ''
		try:
			if self._dt_b_even is not None or self._dt_b_odd is not None:
				_dt_b = f" dte/dto:{(self._dt_b_even if self._dt_b_even is not None else -1):.3f}/{(self._dt_b_odd if self._dt_b_odd is not None else -1):.3f}s"
		except Exception:
			_dt_b = ''
		_phase = ''
		try:
			_phase = f" PH:{(getattr(self,'_phase_key_chosen',None) or getattr(self,'phase_key','auto'))}"
		except Exception:
			_phase = ''
		# Счетчики срабатываний для отображения
		_counters = ''
		try:
			_counters = f" | 🔊:{self._beep_fire_count} ❄️:{self._freeze_fire_count}"
		except Exception:
			_counters = ''
		# Полный статус сохраняем для копирования (правый клик по ⚡)
		_default_status_full = f"Afps:{self.afps:.1f} Bfps:{self.bfps:.1f} Aeo:{self.afps_even:.1f}/{self.afps_odd:.1f}{_dt_a} Beo:{self.bfps_even:.1f}/{self.bfps_odd:.1f}{_dt_b}{_phase} CH0:{len(self.data0)} GAP:{self.gap_count} SEQ:{self.last_seq} STEP:{getattr(self,'seq_step',1)} R:{getattr(self,'seq_reorder_count',0)} GA:{getattr(self,'gap_a',0)} GB:{getattr(self,'gap_b',0)} SA:{getattr(self,'step_a',1)} SB:{getattr(self,'step_b',1)} VIEW[{self.view_start}:{self.view_start+self.view_len}]{buf_info}{_zero_part}{asm_stat}"
		self._last_full_status = _default_status_full
		# Компактный статус для отображения (убираем PH/SEG/VIEW/BUF/FREQ, добавляем счетчики)
		_default_status = f"Afps:{self.afps:.1f} Bfps:{self.bfps:.1f} GAP:{self.gap_count}{_counters}"
		# Forced PWM from GUI: highest priority, independent from detection.
		try:
			mode = int(getattr(self, '_beep_force_mode', 0))
		except Exception:
			mode = 0
		try:
			force_on = (mode == 1)
			force_off = (mode == -1)
			sweep_on = bool(getattr(self, '_beep_sweep_enabled', False))
		except Exception:
			force_on = False
			force_off = False
			sweep_on = False
		if force_off:
			try:
				self._beeper.stop_now()
			except Exception:
				pass
		elif force_on:
			try:
				freq = float(getattr(self, '_beep_force_freq', 2000.0) or 2000.0)
				if (not np.isfinite(freq)) or freq <= 0.0:
					freq = 2000.0
				self._beeper.set_continuous(freq)
			except Exception:
				pass
		else:
			# PWM sweep mode: force variable signal on GPIO12 for scope/debug.
			# Enabled by BMI30_BEEP_MODE=sweep or BMI30_BEEP_SWEEP=1.
			try:
				if sweep_on:
					fmin = float(getattr(self, '_beep_sweep_min', 1000.0))
					fmax = float(getattr(self, '_beep_sweep_max', 4000.0))
					period = float(getattr(self, '_beep_sweep_period_s', 2.0))
					t0 = float(getattr(self, '_beep_sweep_t0', now))
					if period <= 0.1:
						period = 2.0
					# triangle wave 0..1..0 over one period
					t = (now - t0) % period
					frac = float(t) / float(period)
					tri = 1.0 - abs(2.0 * frac - 1.0)
					freq = float(fmin + tri * (fmax - fmin))
					self._beeper.set_continuous(freq)
			except Exception:
				pass
			# PWM while HOLD: after detection keep PWM running until signal is lost.
			try:
				if bool(getattr(self, '_beep_hold_active', False)) and (not sweep_on):
					bm = str(getattr(self, '_beep_mode', 'pattern') or 'pattern')
					if bm == 'pattern':
						after_t = float(getattr(self, '_beep_hold_after_t', 0.0) or 0.0)
						freq = float(getattr(self, '_beep_hold_freq', 0.0) or 0.0)
						if (after_t > 0.0) and (now >= after_t) and (freq > 0.0):
							self._beeper.set_continuous(freq)
			except Exception:
				pass
			# Sync rule: if GUI has no detector color mark, sound must be OFF.
			try:
				adc1_en, adc2_en = self._adc_enable_flags()
			except Exception:
				adc1_en, adc2_en = True, True
			try:
				frozen = bool(getattr(self, '_det_dc_frozen', False))
				h0 = bool(getattr(self, '_det_hold0', False)) and bool(adc1_en)
				h1 = bool(getattr(self, '_det_hold1', False)) and bool(adc2_en)
				gui_color_active = bool(frozen and (h0 or h1))
			except Exception:
				gui_color_active = False
			if not gui_color_active:
				try:
					self._beep_hold_active = False
					self._beep_hold_after_t = 0.0
				except Exception:
					pass
				try:
					self._beeper.stop_now()
				except Exception:
					pass
		# Runtime-легенда (стабильная): обновляем чаще, но с троттлингом и без прыжков высоты
		try:
			self._set_runtime_legend(_default_status)
		except Exception:
			pass

		# Быстрое детектирование: выполняется сразу при получении новых пакетов (независимо от кнопки 6)
		try:
			if getattr(self, '_need_detect', False):
				self._need_detect = False
				try:
					self._quick_detect()
				except Exception:
					pass
		except Exception:
			pass

		# Пер-пакетный триггер корреляции: если reader пометил новые данные и кнопка 6 активна,
		# выполним вычисление в GUI-потоке (здесь мы в GUI-потоке, т.к. _tick вызывается qtimer).
		try:
			if getattr(self, '_need_xcorr', False):
				if hasattr(self, 'num_buttons') and len(self.num_buttons) > 6 and self.num_buttons[6].isChecked():
					# Если включён отдельный таймер XCorr (режим 6), не дёргаем пер-пакетно,
					# иначе получается «двойная перерисовка» и визуальное моргание.
					try:
						if hasattr(self, '_corr_timer') and self._corr_timer is not None and self._corr_timer.isActive():
							self._need_xcorr = False
						else:
							# сбрасываем флаг и вызываем немедленно
							self._need_xcorr = False
							self._compute_and_plot_xcorr()
					except Exception:
						self._need_xcorr = False
				else:
					# очистим флаг если кнопка не активна
					self._need_xcorr = False
		except Exception:
			pass
		# предупреждение если нет данных
		now2 = time.time()
		if self.stream and self.base_buf_len is None and self.connect_t and (now2-self.connect_t)>2.0 and not self.no_data_warned:
			# Не дёргаем устройство бесконечно; просто покажем диагностику и предложим ↻
			try:
				if hasattr(self.stream, 'test_seen') and getattr(self.stream, 'test_seen', 0) > 0:
					# Попробуем вытащить last_stat для отображения ключевых полей
					st = getattr(self.stream, 'last_stat', None)
					if isinstance(st, (bytes, bytearray)) and len(st) >= 16:
						# STAT v1 layout: 0:4='STAT', 4=ver(u8), 5=reserved0, 6:8=cur_samples(u16), 8:10=frame_bytes(u16)
						ver = st[4]
						cur_samples = int.from_bytes(st[6:8],'little')
						frame_bytes = int.from_bytes(st[8:10],'little')
						self._set_status(f"Есть TEST, но нет A/B. STAT v{ver} cur_samples={cur_samples} frame_bytes={frame_bytes}. Нажмите ↻ для ручного пинка.", hold_sec=2.0)
					else:
						self._set_status("Есть TEST, но нет рабочих кадров A/B. Проверьте прошивку: фиксация размера и отправка ADC1/ADC2 после TEST. Нажмите ↻ для ручного пинка.", hold_sec=2.0)
				else:
					self._set_status("Нет данных (нет первых кадров). Нажмите ↻ для повторной попытки. " + self._instr, hold_sec=2.0)
			except Exception:
				self._set_status("Нет данных (нет первых кадров). Нажмите ↻ для повторной попытки. " + self._instr, hold_sec=2.0)
			self.no_data_warned = True
		elif self.stream and (now2 - float(getattr(self.stream, 'last_rx_t', 0.0))) > self.stop_warn_after and (now2 - self.last_diag_t) > self.diag_interval:
			# Совсем нет приёма данных (ни STAT, ни кадров)
			if self.diag_to_console:
				print(f"[diag] Нет приёма данных >{int(self.stop_warn_after)}с. Возможно устройство перестало слать.")
			else:
				self._set_status(f"Нет приёма данных >{int(self.stop_warn_after)}с. Возможно устройство перестало слать. " + self._instr, hold_sec=4.0)
			self.last_diag_t = now2
			# Авто-сброс STM32 при полном отсутствии трафика
			try:
				rx_t = float(getattr(self.stream, 'last_rx_t', 0.0) or 0.0)
				if rx_t > 0:
					self._maybe_auto_reset_on_stall("нет приёма", now2 - rx_t)
			except Exception:
				pass
		elif self.stream and self.base_buf_len is not None and (now2 - self.last_frame_t) > self.stop_warn_after and (now2 - self.last_diag_t) > self.diag_interval:
			# Приём идёт, но нет новых стереопар (например, рассинхрон A/B)
			if self.diag_to_console:
				print(f"[diag] Нет новых стереопар >{int(self.stop_warn_after)}с (приём идёт). Проверьте A/B и seq. Нажмите ↻ для переподключения.")
			else:
				self._set_status(f"Нет новых стереопар >{int(self.stop_warn_after)}с (приём идёт). Проверьте A/B и seq. Нажмите ↻ для переподключения.", hold_sec=3.0)
			self.last_diag_t = now2
			# Авто-сброс STM32 при зависшем потоке (нет новых кадров)
			try:
				self._maybe_auto_reset_on_stall("нет новых кадров", now2 - float(self.last_frame_t))
			except Exception:
				pass
			# Попробуем мягко пнуть поток (без STOP), но не чаще чем раз в diag_interval
			if (not bool(getattr(self, '_stream_user_stopped', False))) and self.auto_soft_kick and (now2 - self.last_soft_kick_t) > max(2.0, self.diag_interval):
				try:
					self._set_status("Мягкий рестарт потока…", hold_sec=1.0)
					self._soft_kick_stream()
					self.last_soft_kick_t = time.time()
				except Exception as e:
					print("[kick] soft restart failed:", e)

		# обновить статус: если hold истёк, очистить его, чтобы отобразить дефолтный FPS-статус
		if self._status_hold_text is not None and time.time() >= self._status_hold_until:
			self._status_hold_text = None
			# немедленно обновим runtime-легенду дефолтным
			buf_info = ""
			if self.base_buf_len is not None:
				freq_part = f" FREQ:{self.freq_hz}Hz" if self.freq_hz else ""
				buf_info = f" BUF:{self.base_buf_len}({self.base_buf_len_bytes}B){freq_part}"
			_zero_part = f" ZERO:{self.zero_blocks}" if getattr(self, 'zero_blocks', 0) else ""
			_counters = ''
			try:
				_counters = f" | 🔊:{self._beep_fire_count} ❄️:{self._freeze_fire_count}"
			except Exception:
				_counters = ''
			_default_status_full = f"Afps:{self.afps:.1f} Bfps:{self.bfps:.1f} CH0:{len(self.data0)} GAP:{self.gap_count} SEQ:{self.last_seq} STEP:{getattr(self,'seq_step',1)} R:{getattr(self,'seq_reorder_count',0)} GA:{getattr(self,'gap_a',0)} GB:{getattr(self,'gap_b',0)} SA:{getattr(self,'step_a',1)} SB:{getattr(self,'step_b',1)} VIEW[{self.view_start}:{self.view_start+self.view_len}]{buf_info}{_zero_part}"
			self._last_full_status = _default_status_full
			_default_status = f"Afps:{self.afps:.1f} Bfps:{self.bfps:.1f} GAP:{self.gap_count}{_counters}"
			self._set_runtime_legend(_default_status, force=True)
		
		# --- Auto-capture: push frame to circular buffer and handle POST phase ---
		try:
			if self.base_buf_len is not None and self.base_buf_len > 0:
				self._capture_push_frame()
			# Handle POST phase countdown
			if getattr(self, '_capture_state', 'idle') == 'finalizing':
				if int(getattr(self, '_capture_post_countdown', 0)) > 0:
					recorded = self._capture_record_frame()
					if recorded:
						self._capture_post_countdown -= 1
					else:
						# если новых кадров нет слишком долго — завершаем
						try:
							t0 = float(getattr(self, '_capture_post_started', 0.0) or 0.0)
							if t0 > 0.0 and (time.time() - t0) >= float(getattr(self, '_capture_post_timeout_s', 2.0)):
								self._capture_finalize()
						except Exception:
							pass
				else:
					# Finalize and save
					self._capture_finalize()
		except Exception as e:
			if bool(getattr(self, 'debug', False)):
				print(f"[CAPTURE] Error in _tick: {e}", flush=True)
		
		# Обновить view после всех изменений данных
		self._update_view()

	def _update_view(self):
		"""Перерисовать окно по текущим параметрам (без чтения новых данных)."""
		if self.base_buf_len is None or self.max_samples == 0:
			return
		vlen = max(1, min(self.view_len, self.base_buf_len))
		max_start = max(0, len(self.data0) - vlen)
		self.slider_start.setMaximum(max(0, self.base_buf_len - vlen))
		self.view_start = min(self.view_start, max_start)
		vlen = min(vlen, len(self.data0) - self.view_start)  # не больше доступных данных
		self.view_len = vlen
		# Snapshot buffers under lock to avoid tearing/races (can look like swaps/in-phase).
		with self.data_lock:
			# copy and cast to float64 immediately to avoid unsigned-int wrap/overflow
			seg0 = (self.data0_even if hasattr(self, 'data0_even') else self.data0)[self.view_start:self.view_start+vlen].copy().astype(np.float64)
			seg1 = (self.data1_even if hasattr(self, 'data1_even') else self.data1)[self.view_start:self.view_start+vlen].copy().astype(np.float64)
			seg0b = (self.data0_odd if hasattr(self, 'data0_odd') else np.zeros_like(seg0))[self.view_start:self.view_start+vlen].copy().astype(np.float64)
			seg1b = (self.data1_odd if hasattr(self, 'data1_odd') else np.zeros_like(seg1))[self.view_start:self.view_start+vlen].copy().astype(np.float64)
			# Если чет/нечет давно не обновлялись — не показываем старые данные
			try:
				# Stale zeroing only in LATEST mode to avoid odd/even disappearing in LOSSLESS/AVG
				if int(getattr(self, 'stream_mode', 0)) == 0:
					st = float(getattr(self, 'parity_stale_s', 0.2) or 0.2)
					if st > 0:
						nowv = time.time()
						if (nowv - float(getattr(self, '_last_a_even_t', 0.0))) > st:
							seg0[:] = 0
						if (nowv - float(getattr(self, '_last_a_odd_t', 0.0))) > st:
							seg0b[:] = 0
						if (nowv - float(getattr(self, '_last_b_even_t', 0.0))) > st:
							seg1[:] = 0
						if (nowv - float(getattr(self, '_last_b_odd_t', 0.0))) > st:
							seg1b[:] = 0
			except Exception:
				pass
			# Validity markers: if we haven't received a phase yet, avoid hiding freshly-filled buffers.
			v0e = (getattr(self, 'seq0_even', None) is not None)
			v0o = (getattr(self, 'seq0_odd', None) is not None)
			v1e = (getattr(self, 'seq1_even', None) is not None)
			v1o = (getattr(self, 'seq1_odd', None) is not None)
			# If seq flags are not yet set but data contain non-zero samples, treat them as valid to display
			try:
				if not v0e and np.any(seg0 != 0):
					v0e = True
				if not v0o and np.any(seg0b != 0):
					v0o = True
				if not v1e and np.any(seg1 != 0):
					v1e = True
				if not v1o and np.any(seg1b != 0):
					v1o = True
			except Exception:
				pass
		
		# Host-side DC removal disabled: device provides DC compensation.
		# (No host-side per-sample DC subtraction.)
		
		# AVG20: вместо текущего кадра показываем среднее по последним N кадрам (уже DC-скорректированные значения)
		if getattr(self, 'avg20_enabled', False):
			try:
				# Берём только реально накопленные кадры, чтобы первые секунды не усреднялись с нулями
				cnt0e = int(getattr(self, '_avg0_even_cnt', 0))
				cnt0o = int(getattr(self, '_avg0_odd_cnt', 0))
				cnt1e = int(getattr(self, '_avg1_even_cnt', 0))
				cnt1o = int(getattr(self, '_avg1_odd_cnt', 0))
				seg0 = (np.mean(self._avg0_even[:cnt0e, self.view_start:self.view_start+vlen], axis=0) if cnt0e > 0 else np.zeros(vlen, dtype=np.float32))
				seg0b = (np.mean(self._avg0_odd[:cnt0o, self.view_start:self.view_start+vlen], axis=0) if cnt0o > 0 else np.zeros(vlen, dtype=np.float32))
				seg1 = (np.mean(self._avg1_even[:cnt1e, self.view_start:self.view_start+vlen], axis=0) if cnt1e > 0 else np.zeros(vlen, dtype=np.float32))
				seg1b = (np.mean(self._avg1_odd[:cnt1o, self.view_start:self.view_start+vlen], axis=0) if cnt1o > 0 else np.zeros(vlen, dtype=np.float32))
			except Exception as e:
				print(f"[AVG20] Ошибка вычисления среднего: {e}")
				# fallback на текущие данные
				pass
		# Инверсию можно включить через BMI30_INVERT=1; для маркеров инверсия не нужна
		if not getattr(self, 'avg20_enabled', False) and not getattr(self, 'debug_markers', False) and not getattr(self, 'no_invert', False):
			# Для беззнаковых данных разворачиваем вокруг середины 32767.5
			seg0 = 32767.5 - (seg0 - 32767.5)
			seg1 = 32767.5 - (seg1 - 32767.5)
			try:
				seg0b = 32767.5 - (seg0b - 32767.5)
				seg1b = 32767.5 - (seg1b - 32767.5)
			except Exception:
				pass
		x = np.arange(vlen)

		# display arrays (use raw seg* values so per-button behavior is preserved)
		disp0 = seg0
		disp0b = seg0b
		disp1 = seg1
		disp1b = seg1b
		# --- режимы отображения ---
		if self.view_mode == 0:
			# оба канала
			if v0e and len(seg0) > 0 and (self.show_zero or not np.all(seg0 == 0)):
				self.curve0_a.setData(x, seg0)
			else:
				self.curve0_a.setData([], [])
			if v0o and len(seg0b) > 0 and (self.show_zero or not np.all(seg0b == 0)):
				self.curve0_b.setData(x, seg0b)
			else:
				self.curve0_b.setData([], [])
			if v1e and len(seg1) > 0 and (self.show_zero or not np.all(seg1 == 0)):
				self.curve1_a.setData(x, seg1)
			else:
				self.curve1_a.setData([], [])
			if v1o and len(seg1b) > 0 and (self.show_zero or not np.all(seg1b == 0)):
				self.curve1_b.setData(x, seg1b)
			else:
				self.curve1_b.setData([], [])
			self.p0.show()
			self.p1.show()
		elif self.view_mode == 1:
			# только канал 1
			if v0e and len(seg0) > 0 and (self.show_zero or not np.all(seg0 == 0)):
				self.curve0_a.setData(x, seg0)
			else:
				self.curve0_a.setData([], [])
			if v0o and len(seg0b) > 0 and (self.show_zero or not np.all(seg0b == 0)):
				self.curve0_b.setData(x, seg0b)
			else:
				self.curve0_b.setData([], [])
			self.curve1_a.setData([], [])
			self.curve1_b.setData([], [])
			self.p0.show()
			self.p1.hide()
		elif self.view_mode == 2:
			# только канал 2
			self.curve0_a.setData([], [])
			self.curve0_b.setData([], [])
			if v1e and len(seg1) > 0 and (self.show_zero or not np.all(seg1 == 0)):
				self.curve1_a.setData(x, seg1)
			else:
				self.curve1_a.setData([], [])
			if v1o and len(seg1b) > 0 and (self.show_zero or not np.all(seg1b == 0)):
				self.curve1_b.setData(x, seg1b)
			else:
				self.curve1_b.setData([], [])
			self.p0.hide()
			self.p1.show()
		self.lbl_start_value.setText(str(self.view_start))
		self.lbl_len_value.setText(str(vlen))
		self._apply_x_range(0, self.view_len or self.initial_expected)
	def _set_view_mode(self, mode:int):
		"""Установить режим отображения: 0=оба, 1=только канал 1, 2=только канал 2"""
		self.view_mode = mode
		self._update_view()

	def _apply_x_range(self, start: float, end: float):
		"""Принудительно зафиксировать диапазон X, чтобы график не 'улетал'."""
		try:
			if end <= start:
				return
			# меняем X-диапазон только если он реально отличается, чтобы избежать мерцания
			vr0 = self.p0.viewRange()[0]
			if abs(vr0[0] - start) > 1e-6 or abs(vr0[1] - end) > 1e-6:
				self.p0.setXRange(start, end, padding=0.0)
				self.p1.setXRange(start, end, padding=0.0)
		except Exception:
			pass

	def _apply_x_axis_mode(self):
		"""Форматирование оси X: только номера семплов (целые)."""
		try:
			ax0 = self.p0.getAxis('bottom')
			ax1 = self.p1.getAxis('bottom')
			# Никаких SI-префиксов и целочисленные метки
			try:
				ax0.enableAutoSIPrefix(False)
				ax1.enableAutoSIPrefix(False)
			except Exception:
				pass
			ax0.setLabel("samples")
			ax1.setLabel("samples")
			def _int_ticks(values, scale, spacing):
				labels = []
				for v in values:
					try:
						labels.append(str(int(round(v))))
					except Exception:
						labels.append(str(v))
				return labels
			ax0.tickStrings = _int_ticks
			ax1.tickStrings = _int_ticks
		except Exception:
			pass

	def _run_init_sequence(self):
		"""Выполнить согласованную с разработчиком последовательность команд USB."""
		if self.stream is None:
			raise RuntimeError("нет активного stream")
		try:
			import time as _t
		except Exception:
			pass
		# STOP
		try:
			self._send_stop_stream()
		except Exception as e:
			print("[initseq] STOP err", e)
		try:
			_t.sleep(0.01)
		except Exception:
			pass
		# SET_WINDOWS: (0,0,0,0) - полный буфер для режима LATEST
		try:
			windows_data = struct.pack('<HHHH', 0, 0, 0, 0)
			self.stream.send_cmd(CMD_SET_WINDOWS, windows_data)
			if bool(getattr(self, 'debug', False)):
				print("[initseq] SET_WINDOWS(0,0,0,0) - полный буфер")
		except Exception as e:
			print("[initseq] SET_WINDOWS err", e)
		# SET_STREAM_MODE: 0 (LATEST) - по умолчанию запускаем в режиме LATEST
		try:
			self.stream.send_cmd(CMD_SET_STREAM_MODE, b"\x00")
			if bool(getattr(self, 'debug', False)):
				print("[initseq] SET_STREAM_MODE=0 (LATEST)")
		except Exception as e:
			print("[initseq] SET_STREAM_MODE err", e)
		# FULL mode
		try:
			self.stream.send_cmd(0x13 if 'CMD_FULL_MODE' not in globals() else CMD_FULL_MODE, b"\x01")
		except Exception as e:
			print("[initseq] FULL err", e)
		# PROFILE
		try:
			prof = self.desired_profile if self.desired_profile in (1,2) else 1
			self.stream.send_cmd(CMD_SET_PROFILE, bytes([prof]))
		except Exception as e:
			print("[initseq] PROFILE err", e)
		# CHMODE both channels
		try:
			self.stream.send_cmd(0x19 if 'CMD_CHMODE' not in globals() else CMD_CHMODE, b"\x02")
		except Exception as e:
			print("[initseq] CHMODE err", e)
		# ASYNC (независимые A/B)
		try:
			self.stream.send_cmd(0x18 if 'CMD_ASYNC' not in globals() else CMD_ASYNC, b"\x01")
		except Exception as e:
			print("[initseq] ASYNC err", e)
		# BLOCK_HZ (опционально)
		try:
			bhz = int(self.block_hz) if getattr(self, 'block_hz', None) else None
			if bhz and 1 <= bhz <= 1000:
				self.stream.send_cmd(0x11 if 'CMD_BLOCK_HZ' not in globals() else CMD_BLOCK_HZ, int(bhz).to_bytes(2,'little'))
		except Exception as e:
			print("[initseq] BLOCK_HZ err", e)
		# START
		try:
			self._send_start_stream()
		except Exception as e:
			print("[initseq] START err", e)

 

	def _set_status(self, text: str, hold_sec: float | None = None):
		"""Установить текст статуса с возможностью удержания, чтобы текст не мигал.

		Если hold_sec задано, текст закрепляется на указанное время и не будет перезаписан
		дефолтным FPS-статусом, пока таймер не истечёт. Идентичные тексты не переустанавливаются,
		чтобы не вызывать лишних перерисовок.
		"""
		try:
			def _fmt3(s: str) -> str:
				# Always keep exactly 3 lines to avoid QLabel height/layout flicker.
				try:
					parts = str(s).splitlines()
				except Exception:
					parts = [str(s)]
				parts = parts[:3]
				while len(parts) < 3:
					parts.append("")
				return "\n".join(parts)

			# если сейчас активен hold и он ещё не истёк, не перетирать другим текстом без hold
			now = time.time()
			if self._status_hold_text is not None and now < self._status_hold_until:
				# если новый текст также с hold и отличается — обновим
				if hold_sec and text != self._status_hold_text:
					self._status_hold_text = text
					self._status_hold_until = now + max(0.5, hold_sec)
					_fmt = _fmt3(text)
					if _fmt != self._last_status_text:
						self.legend_lbl.setText(_fmt)
						self._last_status_text = _fmt
				return
			# сюда попадаем если hold нет или истёк — применим новый текст
			if hold_sec:
				self._status_hold_text = text
				self._status_hold_until = now + max(0.5, hold_sec)
			_fmt = _fmt3(text)
			if _fmt != self._last_status_text:
				self.legend_lbl.setText(_fmt)
				self._last_status_text = _fmt
		except Exception:
			pass

	def _set_runtime_legend(self, line1: str, force: bool = False):
		"""Update main legend without flicker.

		- Respects active hold text.
		- Throttles updates.
		"""
		try:
			now = time.time()
			if (self._status_hold_text is not None) and (now < self._status_hold_until):
				return
			# throttle
			if (not force) and (now - float(getattr(self, '_legend_last_runtime_t', 0.0)) < 0.20):
				return
			self._legend_last_runtime_t = now
			# Default: show compact detector status (user needs it), but keep other diagnostics hidden.
			try:
				verbose = bool(getattr(self, 'legend_verbose', False))
			except Exception:
				verbose = False
			# Always compute minimal detector fields
			thr0 = int(getattr(self, '_det_thr0', 0) or 0)
			thr1 = int(getattr(self, '_det_thr1', 0) or 0)
			lvl0 = int(getattr(self, '_det_last_lvl0', 0) or 0)
			lvl1 = int(getattr(self, '_det_last_lvl1', 0) or 0)
			src = str(getattr(self, '_det_last_source', getattr(self, '_det_source', 'norm')) or 'norm').strip().lower()
			if src in ('raw', 'product'):
				src = 'prod'
			h0_on = bool(getattr(self, '_det_hold0', False))
			h1_on = bool(getattr(self, '_det_hold1', False))
			h0 = 'H' if h0_on else '-'
			h1 = 'H' if h1_on else '-'
			frozen = bool(getattr(self, '_det_dc_frozen', False))
			arrow_up = '↑' if (frozen and h0_on) else ''
			arrow_dn = '↓' if (frozen and h1_on) else ''
			dcf = f"FROZEN{arrow_up}{arrow_dn}" if frozen else 'RUN'
			try:
				adc1_en, adc2_en = self._adc_enable_flags()
			except Exception:
				adc1_en, adc2_en = True, True
			try:
				self._set_det_gpio(frozen and h0_on and adc1_en, frozen and h1_on and adc2_en)
			except Exception:
				pass
			det_on = 'ON' if bool(getattr(self, '_det_enabled', False)) else 'OFF'
			sh0 = int(getattr(self, '_det_last_shift0', 0) or 0)
			sh1 = int(getattr(self, '_det_last_shift1', 0) or 0)
			# Compact (default) lines: ADC1/ADC2 aligned
			try:
				adc1_en, adc2_en = self._adc_enable_flags()
			except Exception:
				adc1_en, adc2_en = True, True
			adc1_state = "ON" if adc1_en else "OFF"
			adc2_state = "ON" if adc2_en else "OFF"
			prefix = f"DET[{det_on}] src={src:<4} DC:{dcf:<8}"
			line_adc1 = f"{prefix} | ADC1[{adc1_state}] xpk/thr={lvl0:5d}/{thr0:5d} {h0} sh={sh0:4d}"
			line_adc2 = f"{prefix} | ADC2[{adc2_state}] xpk/thr={lvl1:5d}/{thr1:5d} {h1} sh={sh1:4d}"
			max_len = max(len(line_adc1), len(line_adc2))
			line_adc1 = line_adc1.ljust(max_len)
			line_adc2 = line_adc2.ljust(max_len)
			# background colors per ADC line
			bg_adc1 = "#ff4d4d" if not adc1_en else ("#4da3ff" if (frozen and h0_on) else "#ffffff")
			bg_adc2 = "#ff4d4d" if not adc2_en else ("#ffd84d" if (frozen and h1_on) else "#ffffff")
			fg_adc1 = "#000000" if bg_adc1 == "#ffffff" else "#ffffff"
			fg_adc2 = "#000000" if bg_adc2 == "#ffffff" else ("#000000" if bg_adc2 == "#ffd84d" else "#ffffff")
			status_html = f"<div style='font-family:monospace; white-space:pre;'>{line1}</div>"
			line1_html = f"<div style='font-family:monospace; white-space:pre; background-color:{bg_adc1}; color:{fg_adc1};'>{line_adc1}</div>"
			line2_html = f"<div style='font-family:monospace; white-space:pre; background-color:{bg_adc2}; color:{fg_adc2};'>{line_adc2}</div>"
			if not verbose:
				self._set_status(f"{line1_html}\n{line2_html}\n{status_html}")
				return
			# Verbose mode: add PWM backend + extra metrics + XCorr summary
			amp0 = int(getattr(self, '_det_last_amp0', 0) or 0)
			amp1 = int(getattr(self, '_det_last_amp1', 0) or 0)
			pm0 = float(getattr(self, '_det_last_prodmax0', 0.0) or 0.0)
			pm1 = float(getattr(self, '_det_last_prodmax1', 0.0) or 0.0)
			sc = float(getattr(self, '_det_last_level_scale', 0.0) or 0.0)
			try:
				beep_st = str(self._beeper.status())
			except Exception:
				beep_st = 'unknown'
			bm = str(getattr(self, '_beep_mode', 'pattern') or 'pattern')
			try:
				_mode = int(getattr(self, '_beep_force_mode', 0))
			except Exception:
				_mode = 0
			try:
				if _mode == 1:
					bm = f"{bm}+FORCE"
				elif _mode == -1:
					bm = f"{bm}+OFF"
			except Exception:
				pass
			_sc_txt = (f"sc={sc:.0f}" if sc > 0 else "sc=?") if src == 'prod' else "sc=norm"
			# XCorr summary for status line
			try:
				_tick_hz = 1000.0 / max(1.0, float(self.qtimer.interval()))
			except Exception:
				_tick_hz = 0.0
			xc_on = False
			try:
				xc_on = bool(hasattr(self, 'num_buttons') and len(self.num_buttons) > 6 and self.num_buttons[6].isChecked())
			except Exception:
				xc_on = False
			xc_sum = str(getattr(self, '_xcorr_last_summary', 'XCORR: off'))
			status_line = f"{line1} | BEEP:{beep_st}/{bm} {_sc_txt} | XCorrFPS:{float(getattr(self,'_xcorr_fps',0.0)):.1f} tick:{_tick_hz:.1f} | {xc_sum if xc_on else 'XCORR: off'}"
			line_adc1_v = f"{prefix} | ADC1[{adc1_state}] amp={amp0:5d} pm={pm0:6.0f} xpk/thr={lvl0:5d}/{thr0:5d} {h0} sh={sh0:4d}"
			line_adc2_v = f"{prefix} | ADC2[{adc2_state}] amp={amp1:5d} pm={pm1:6.0f} xpk/thr={lvl1:5d}/{thr1:5d} {h1} sh={sh1:4d}"
			max_len_v = max(len(line_adc1_v), len(line_adc2_v))
			line_adc1_v = line_adc1_v.ljust(max_len_v)
			line_adc2_v = line_adc2_v.ljust(max_len_v)
			line1_html = f"<div style='font-family:monospace; white-space:pre; background-color:{bg_adc1}; color:{fg_adc1};'>{line_adc1_v}</div>"
			line2_html = f"<div style='font-family:monospace; white-space:pre; background-color:{bg_adc2}; color:{fg_adc2};'>{line_adc2_v}</div>"
			status_html = f"<div style='font-family:monospace; white-space:pre;'>{status_line}</div>"
			self._set_status(f"{line1_html}\n{line2_html}\n{status_html}")
		except Exception:
			pass

	def _on_slider_start(self, val:int):
		if self.base_buf_len and val > self.base_buf_len - self.view_len:
			val = max(0, self.base_buf_len - self.view_len)
			self.slider_start.setValue(val)
		self.view_start = val
		self._update_view()

	def _on_slider_len(self, val:int):
		self.view_len = val
		# обновить максимум стартового смещения
		if self.base_buf_len:
			self.slider_start.setMaximum(max(0, self.base_buf_len - self.view_len))
		self._update_view()

	def _on_toggle_xcorr_norm(self, enabled: bool):
		"""Переключатель нормализации/масштабирования отображения XCorr."""
		try:
			self.xcorr_norm_enabled = bool(enabled)
		except Exception:
			self.xcorr_norm_enabled = True
		try:
			save_ui_state(xcorr_norm_enabled=bool(self.xcorr_norm_enabled))
		except Exception:
			pass
		# Update visual hint (color/tooltip) and status indicator
		try:
			if self.xcorr_norm_enabled:
				style = "QPushButton { background:#b6f0b6; color:#000; border:1px solid #6fb36f; }"
				tt = "XCorr norm: ON (auto)"
				self.btn_diag.setToolTip("XCorr: нормализация/автомасштаб ВКЛ")
			else:
				style = "QPushButton { background:#f0b6b6; color:#000; border:1px solid #b36f6f; }"
				tt = "XCorr norm: OFF (0..65535)"
				self.btn_diag.setToolTip("XCorr: нормализация/автомасштаб ВЫКЛ (шкала 0..65535)")
			try:
				self.btn_diag.setStyleSheet(style)
			except Exception:
				pass
			# краткий статус
			self._set_status(tt, hold_sec=2.0)
			# если XCorr включён (кнопка 6), обновим график сразу
			try:
				if hasattr(self, 'num_buttons') and len(self.num_buttons) > 6 and self.num_buttons[6].isChecked():
					self._compute_and_plot_xcorr()
			except Exception:
				pass
		except Exception:
			pass

	def _update_pwm_btn_style(self):
		"""Обновить стиль кнопки PWM по текущему режиму."""
		try:
			mode = int(getattr(self, '_beep_force_mode', 0))
		except Exception:
			mode = 0
		try:
			try:
				self.btn_pwm.setText("♪")
			except Exception:
				pass
			if mode == 1:
				# принудительно ВКЛ — жёлтый
				self.btn_pwm.setStyleSheet("background-color: #ffe08a; color: #4a3700; border:1px solid #d1b15a;")
				self.btn_pwm.setToolTip("PWM: принудительно ВКЛ")
			elif mode == -1:
				# принудительно ВЫКЛ — красный
				self.btn_pwm.setStyleSheet("background-color: #ff6b6b; color: #3b0000; border:1px solid #c94c4c;")
				self.btn_pwm.setToolTip("PWM: принудительно ВЫКЛ")
			else:
				# работа — зелёный
				self.btn_pwm.setStyleSheet("background-color: #5fd35f; color: #0f2d0f; border:1px solid #3aa93a;")
				self.btn_pwm.setToolTip("PWM: работа")
		except Exception:
			pass

	def _on_toggle_force_pwm(self, enabled: bool = False):
		"""Цикл режимов PWM: работа -> принудительно ВКЛ -> принудительно ВЫКЛ -> работа."""
		try:
			cur = int(getattr(self, '_beep_force_mode', 0))
		except Exception:
			cur = 0
		if cur == 0:
			next_mode = 1
		elif cur == 1:
			next_mode = -1
		else:
			next_mode = 0
		self._beep_force_mode = next_mode
		self._update_pwm_btn_style()
		try:
			self._beep_force_enabled = (next_mode == 1)
		except Exception:
			pass
		try:
			if next_mode == 1:
				# Cancel any pending HOLD schedule to avoid confusing transitions.
				try:
					self._beep_hold_active = False
					self._beep_hold_after_t = 0.0
				except Exception:
					pass
				try:
					freq = float(getattr(self, '_beep_force_freq', 2000.0) or 2000.0)
					if (not np.isfinite(freq)) or freq <= 0.0:
						freq = 2000.0
					self._beeper.set_continuous(freq)
				except Exception:
					pass
				# Show backend status and fail-fast if backend is unavailable
				try:
					st = str(self._beeper.status())
				except Exception:
					st = 'unknown'
				try:
					freq0 = float(getattr(self, '_beep_force_freq', 2000.0) or 2000.0)
				except Exception:
					freq0 = 2000.0
				try:
					self._set_status(f"PWM FORCE: ON @ {freq0:.0f} Hz | BEEP:{st}", hold_sec=3.0)
				except Exception:
					pass
				# If beeper is effectively disabled/unavailable, revert the button so user sees it immediately.
				if st in ('none', 'OFF', 'unknown'):
					try:
						self._beep_force_enabled = False
						self._beep_force_mode = 0
					except Exception:
						pass
					try:
						if hasattr(self, 'btn_pwm'):
							self._update_pwm_btn_style()
					except Exception:
						pass
					try:
						msg = "PWM недоступен: "
						if st == 'OFF':
							msg += "BMI30_BEEP_ENABLE=0 (выключено)"
						elif st == 'none':
							msg += "нет pigpio/RPi.GPIO (или pigpiod не запущен)"
						else:
							msg += "неизвестный статус"
						self._set_status(msg, hold_sec=4.0)
					except Exception:
						pass
			elif next_mode == -1:
				# принудительно ВЫКЛ — остановить PWM независимо от детектора
				try:
					self._beep_hold_active = False
					self._beep_hold_after_t = 0.0
				except Exception:
					pass
				try:
					self._beeper.set_continuous(None)
				except Exception:
					pass
				try:
					st = str(self._beeper.status())
				except Exception:
					st = 'unknown'
				try:
					self._set_status(f"PWM FORCE: OFF (forced) | BEEP:{st}", hold_sec=2.0)
				except Exception:
					pass
			else:
				# работа — снять принудительный режим, разрешить sweep/HOLD
				try:
					if (not bool(getattr(self, '_beep_sweep_enabled', False))) and (not bool(getattr(self, '_beep_hold_active', False))):
						self._beeper.set_continuous(None)
				except Exception:
					pass
				try:
					st = str(self._beeper.status())
				except Exception:
					st = 'unknown'
				try:
					self._set_status(f"PWM: WORK | BEEP:{st}", hold_sec=2.0)
				except Exception:
					pass
		except Exception:
			pass

	def _copy_legend_from_btn(self, pos):
		"""Handle right-click on `btn_power`: copy `legend_lbl` text to clipboard."""
		try:
			text = str(getattr(self, '_last_full_status', '') or '')
			if not text:
				text = self.legend_lbl.text() if hasattr(self, 'legend_lbl') else ''
			cb = QtWidgets.QApplication.clipboard()
			cb.setText(text)
			self._set_status("Заголовок скопирован в буфер обмена", hold_sec=2.0)
		except Exception:
			pass

	def _reset_det_adapt(self):
		"""Сбросить пороги детектора и ускорить адаптацию на короткое время."""
		try:
			fast_sec = float(os.getenv('BMI30_DETECT_FAST_SEC', '3.0'))
			if (not np.isfinite(fast_sec)) or fast_sec <= 0.0:
				fast_sec = 3.0
		except Exception:
			fast_sec = 3.0
		try:
			fast_frames = int(os.getenv('BMI30_DC_FAST_FRAMES', '100'))
		except Exception:
			fast_frames = 100
		if fast_frames < 0:
			fast_frames = 0
		try:
			self._det_fast_adapt_until = float(time.time() + fast_sec)
		except Exception:
			pass
		# Сбросить пороги, чтобы быстро пересчитались из текущего уровня
		try:
			self._det_thr0 = int(getattr(self, '_det_thr_init', 0) or 0)
			self._det_thr1 = int(getattr(self, '_det_thr_init', 0) or 0)
			self._det_exceed0 = 0
			self._det_exceed1 = 0
			self._det_start_consec0 = 0
			self._det_start_consec1 = 0
			self._det_hits0 = deque(maxlen=12)
			self._det_hits1 = deque(maxlen=12)
			self._det_last_pair_key0 = None
			self._det_last_pair_key1 = None
			self._det_exceed_peak0 = None
			self._det_exceed_peak1 = None
			self._det_hold0 = False
			self._det_hold1 = False
			dc_fast_sent = False
			try:
				if int(self.num_group.checkedId()) == 5 and fast_frames > 0:
					self._device_calib_dc_fast(fast_frames)
					dc_fast_sent = True
			except Exception:
				dc_fast_sent = False
			txt = f"Сброс порога: быстрая адаптация ~{fast_sec:.1f}с"
			if dc_fast_sent:
				txt += f" | DC fast {int(fast_frames)}f"
			self._set_status(txt, hold_sec=2.0)
		except Exception:
			pass

	def _manual_reconnect(self):
		# Принудительно закрыть и заново начать поиск
		try:
			if self.stream:
				self.stream.close()
		except Exception:
			pass
		# Аппаратный сброс через GPIO (best-effort)
		try:
			self._hardware_reset_device()
		except Exception:
			pass
		self.stream = None
		self.base_buf_len = None
		self.base_buf_len_bytes = None
		self.freq_hz = None
		self.data0 = np.zeros(0, dtype=np.int16)
		self.data1 = np.zeros(0, dtype=np.int16)
		self.timestamps = np.zeros(0, dtype=np.float64)
		self._last_sample_ts = None
		self.view_start = 0
		self.view_len = 0
		self._reset_sliders()
		if self.num_group.checkedId() != 0:
			self._set_status("Переподключение…", hold_sec=1.5)
			self._activate_stream()
		else:
			self._set_status("Поток остановлен", hold_sec=1.5)

	def _toggle_capture(self):
		"""Переключение автозахвата осциллограмм."""
		self._auto_capture_enabled = self.btn_capture.isChecked()
		print(f"\n{'='*60}\n[CAPTURE] Toggle: auto_capture_enabled={self._auto_capture_enabled}\n{'='*60}\n", flush=True)
		# Создать папку captures при включении
		if self._auto_capture_enabled:
			try:
				os.makedirs(self._capture_dir, exist_ok=True)
			except Exception as e:
				print(f"[CAPTURE] Ошибка создания папки {self._capture_dir}: {e}", flush=True)
				self._auto_capture_enabled = False
				self.btn_capture.setChecked(False)
		self._update_capture_btn_style()
		try:
			save_ui_state(auto_capture_enabled=bool(self._auto_capture_enabled))
		except Exception:
			pass
		status = "включён" if self._auto_capture_enabled else "выключен"
		self._set_status(f"Автозахват {status}", hold_sec=2.0)
	
	def _update_capture_btn_style(self):
		"""Обновление цвета кнопки capture: зелёная=включено, красная=выключено."""
		try:
			if self._auto_capture_enabled:
				self.btn_capture.setStyleSheet("background-color: #00cc00; color: white;")
			else:
				self.btn_capture.setStyleSheet("background-color: #cc0000; color: white;")
		except Exception:
			pass
	
	def _cycle_label_state(self):
		"""Переключение состояния метки: 0→1→2→0 (неизвестно→с меткой→без метки→неизвестно)."""
		self._capture_label_state = (self._capture_label_state + 1) % 3
		self._update_label_btn_style()
		try:
			save_ui_state(capture_label_state=int(self._capture_label_state))
		except Exception:
			pass
		labels = ["неизвестно", "с меткой", "без метки"]
		self._set_status(f"Метка: {labels[self._capture_label_state]}", hold_sec=1.5)
	
	def _cycle_mark_type(self):
		"""Тип метки: 3 позиции Б/М/С (временная заглушка)."""
		try:
			self._mark_type_mode = (int(getattr(self, '_mark_type_mode', 0)) + 1) % 3
		except Exception:
			self._mark_type_mode = 0
		modes = ["Б", "М", "С"]
		try:
			self.btn_mark_type.setText(modes[int(self._mark_type_mode)])
		except Exception:
			pass
		try:
			save_ui_state(mark_type_mode=int(self._mark_type_mode))
		except Exception:
			pass
		# Обновим список коэффициентов детектора при смене типа метки
		try:
			self._refresh_det_ratio_options()
		except Exception:
			pass
		# Покажем вычисленный ROI старт в статусе, чтобы сразу видеть что хост пытается сделать
		try:
			roi_start, roi_len = self._get_mark_type_roi_window()
			sm = int(getattr(self, 'stream_mode', 0) or 0)
			self._set_status(f"Тип метки: {modes[int(self._mark_type_mode)]} | ROI start={int(roi_start)} len={int(roi_len)} | mode={sm}", hold_sec=2.0)
		except Exception:
			try:
				self._set_status(f"Тип метки: {modes[int(self._mark_type_mode)]}", hold_sec=1.5)
			except Exception:
				pass
		# По ТЗ: устройство всегда формирует рабочую зону 200 семплов само,
		# а хост указывает только старт этой зоны. Поэтому при смене Б/М/С
		# отправляем новый старт на устройство (без STOP/START).
		try:
			self._send_mark_type_roi_start_to_device()
		except Exception:
			pass

	def _refresh_det_ratio_options(self):
		"""Обновить список коэффициентов детектора в GUI под текущий тип метки."""
		try:
			mark_type_b = int(getattr(self, '_mark_type_mode', 2)) == 0
		except Exception:
			mark_type_b = False
		# Список значений и диапазоны
		if mark_type_b:
			vals = [str(i) for i in range(1, 21)]
			min_v, max_v = 1, 20
			fmt = "{:.0f}"
			tooltip = "коэффициент срабатывания (1–20, целые)"
		else:
			vals = [f"{v:.1f}" for v in [round(1.0 + 0.1 * i, 1) for i in range(21)]]
			min_v, max_v = 1.0, 3.0
			fmt = "{:.1f}"
			tooltip = "коэффициент срабатывания (1.0–3.0)"
		# Текущее значение
		try:
			cur0 = float(getattr(self, '_det_ratio0', 2.0))
		except Exception:
			cur0 = 2.0
		try:
			cur1 = float(getattr(self, '_det_ratio1', 2.0))
		except Exception:
			cur1 = 2.0
		# Клэмп и округление
		if mark_type_b:
			cur0 = int(max(min_v, min(max_v, round(cur0))))
			cur1 = int(max(min_v, min(max_v, round(cur1))))
		else:
			cur0 = float(max(min_v, min(max_v, round(cur0, 1))))
			cur1 = float(max(min_v, min(max_v, round(cur1, 1))))
		try:
			self._det_ratio0 = cur0
			self._det_ratio1 = cur1
		except Exception:
			pass
		# Применим к комбобоксам
		for _box in (getattr(self, 'det_ratio_box0', None), getattr(self, 'det_ratio_box1', None)):
			if _box is None:
				continue
			try:
				_box.blockSignals(True)
			except Exception:
				pass
			try:
				_box.clear()
				_box.addItems(vals)
			except Exception:
				pass
			try:
				_box.blockSignals(False)
			except Exception:
				pass
		# Установим текущие значения
		try:
			if getattr(self, 'det_ratio_box0', None) is not None:
				self.det_ratio_box0.blockSignals(True)
				self.det_ratio_box0.setCurrentText(fmt.format(cur0))
				self.det_ratio_box0.blockSignals(False)
			if getattr(self, 'det_ratio_box1', None) is not None:
				self.det_ratio_box1.blockSignals(True)
				self.det_ratio_box1.setCurrentText(fmt.format(cur1))
				self.det_ratio_box1.blockSignals(False)
		except Exception:
			pass
		# Обновим подсказки
		try:
			if getattr(self, 'det_ratio_box0', None) is not None:
				self.det_ratio_box0.setToolTip(f"ADC1: {tooltip}")
			if getattr(self, 'det_ratio_box1', None) is not None:
				self.det_ratio_box1.setToolTip(f"ADC2: {tooltip}")
		except Exception:
			pass

	def _get_mark_type_roi_window(self) -> tuple[int, int]:
		"""Вернуть (start, len) ROI на устройстве по текущему типу метки.

		Требование: длина ROI всегда фиксирована (200) и формируется устройством, меняется только старт.
		Б: сдвиг вправо на +70, М: влево на -50, С: без сдвига.
		"""
		# Базовые значения "как сейчас" (можно менять через env без правки кода)
		try:
			base_start = int(os.getenv('BMI30_ROI_BASE_START', '280'))
		except Exception:
			base_start = 280
		try:
			roi_len = int(os.getenv('BMI30_ROI_LEN', '200'))
		except Exception:
			roi_len = 200
		# Полная длина буфера для расчёта границ (по ТЗ сейчас 600)
		try:
			full_len = int(os.getenv('BMI30_FULL_LEN', '600'))
		except Exception:
			full_len = 600
		try:
			mt = int(getattr(self, '_mark_type_mode', 2))
		except Exception:
			mt = 2
		# 0=Б, 1=М, 2=С
		if mt == 0:
			offset = 80
		elif mt == 1:
			offset = -50
		else:
			offset = 0
		start = int(base_start + offset)
		# Безопасное ограничение старта, чтобы окно не вылезало за пределы
		try:
			max_start = max(0, int(full_len) - int(roi_len))
		except Exception:
			max_start = 0
		start = max(0, min(start, max_start))
		return start, int(roi_len)

	def _send_mark_type_roi_start_to_device(self):
		"""Отправить на устройство параметры рабочей зоны (ROI) под текущий тип метки.

		Дефолт: отправляем (start,len) из _get_mark_type_roi_window() (обычно len=200).
		Если нужно переопределить len (в т.ч. поставить 0), задай env `BMI30_SET_WINDOWS_LEN`.
		"""
		if self.stream is None:
			return
		roi_start, roi_len = self._get_mark_type_roi_window()
		start = int(roi_start) & 0xFFFF
		windows_data, sent_len = self._pack_set_windows_start(start, default_len=int(roi_len))
		self.stream.send_cmd(CMD_SET_WINDOWS, windows_data)
		if bool(getattr(self, 'debug', False)):
			print(f"[MARK_TYPE] SET_WINDOWS(start={int(roi_start)}, len={int(sent_len)}) отправлен")

	def _get_set_windows_len(self, default_len: int) -> int:
		"""Какую len отправлять в CMD_SET_WINDOWS.

		По умолчанию используется `default_len` (обычно 200 из ROI-логики).
		Можно переопределить через env `BMI30_SET_WINDOWS_LEN` (например 200 или 0).
		"""
		default_len = int(default_len)
		if default_len < 0:
			default_len = 0
		if default_len > 0xFFFF:
			default_len = 0xFFFF
		raw = str(os.getenv('BMI30_SET_WINDOWS_LEN', '')).strip()
		if raw == "":
			return int(default_len)
		try:
			val = int(raw)
		except Exception:
			return int(default_len)
		if val < 0:
			val = 0
		if val > 0xFFFF:
			val = 0xFFFF
		return int(val)

	def _pack_set_windows_start(self, start_u16: int, default_len: int) -> tuple[bytes, int]:
		"""Упаковать SET_WINDOWS(start,len,start,len) с длиной по умолчанию + override через env."""
		start_u16 = int(start_u16) & 0xFFFF
		ln = int(self._get_set_windows_len(default_len=default_len)) & 0xFFFF
		return struct.pack('<HHHH', start_u16, ln, start_u16, ln), ln
	
	def _cycle_det_count(self):
		"""Количество детектирования подряд: 6 позиций 1..6."""
		try:
			cur = int(getattr(self, '_det_count', 1))
		except Exception:
			cur = 1
		next_val = 1 if cur >= 6 else (cur + 1)
		self._det_count = int(next_val)
		try:
			self.btn_det_count.setText(str(self._det_count))
		except Exception:
			pass
		try:
			save_ui_state(det_count=int(self._det_count))
		except Exception:
			pass
		try:
			self._set_status(f"Детектирование: {int(self._det_count)}", hold_sec=1.5)
		except Exception:
			pass
	
	def _update_label_btn_style(self):
		"""Обновление текста и цвета кнопки label."""
		try:
			if self._capture_label_state == 0:
				# Неизвестно
				self.btn_label.setText("?")
				self.btn_label.setStyleSheet("background-color: #888888; color: white;")
			elif self._capture_label_state == 1:
				# С меткой
				self.btn_label.setText("✓")
				self.btn_label.setStyleSheet("background-color: #0080ff; color: white;")
			else:
				# Без метки
				self.btn_label.setText("✗")
				self.btn_label.setStyleSheet("background-color: #ff8000; color: white;")
		except Exception:
			pass

	def _enqueue_mode_action(self, action: str, *args, **kwargs):
		"""Place a mode-switch action to background worker (non-blocking)."""
		if getattr(self, '_mode_worker', None) is None:
			# no worker: run synchronously as fallback
			try:
				if action == 'latest':
					self._switch_to_latest_mode()
				elif action == 'lossless':
					self._switch_to_lossless_roi(*args, **kwargs)
				elif action == 'avg':
					self._switch_to_avg_roi(*args, **kwargs)
			except Exception:
				pass
			return
		# enqueue for background execution
		try:
			self._mode_worker.enqueue(action, *args, **kwargs)
		except Exception:
			pass

	def _on_mode_action_done(self, action: str, *args, **kwargs):
		"""Called in GUI thread when worker finished an action; update buffers/UI."""
		try:
			if action == 'latest':
				with self.data_lock:
					self._reset_phase_splitter('switch_to_latest')
					self.base_buf_len = None
					self.base_buf_len_bytes = None
					self.freq_hz = None
					self._sliders_initialized = False
				self.stream_mode = 0
				# restore GUI FPS
				try:
					gui_fps = int(os.getenv("BMI30_GUI_FPS", "16"))
				except Exception:
					gui_fps = 16
				self.qtimer.setInterval(max(10, int(1000 / gui_fps)))
				self._set_status("LATEST activated", hold_sec=2.0)
			elif action == 'lossless':
				with self.data_lock:
					self._reset_phase_splitter('switch_to_lossless')
					self.base_buf_len = None
					self.base_buf_len_bytes = None
					self.freq_hz = None
					self._sliders_initialized = False
				self.stream_mode = 1
				self.qtimer.setInterval(200)
				self._set_status("LOSSLESS_ROI activated", hold_sec=2.0)
			elif action == 'avg':
				avg_n = int(args[0]) if args else int(kwargs.get('avg_n', getattr(self,'avg_n',20)))
				with self.data_lock:
					self._reset_phase_splitter(f'switch_to_avg_roi avg_n={avg_n}')
					self.base_buf_len = None
					self.base_buf_len_bytes = None
					self.freq_hz = None
					self._sliders_initialized = False
				self.stream_mode = 2
				self.qtimer.setInterval(200)
				self._set_status(f"AVG_ROI activated (avg_n={avg_n})", hold_sec=2.0)
			# refresh view immediately
			try:
				self._update_view()
			except Exception:
				pass
		except Exception as e:
			print(f"[ModeCallback] error on done({action}): {e}")

	def _reset_sliders(self):
		"""Вернуть слайдеры в исходное состояние и разрешить повторную инициализацию."""
		try:
			self.slider_start.blockSignals(True)
			self.slider_len.blockSignals(True)
		except Exception:
			pass
		self.slider_start.setEnabled(False)
		self.slider_len.setEnabled(False)
		self.slider_start.setMaximum(0)
		self.slider_len.setMaximum(0)
		self.slider_start.setValue(0)
		self.slider_len.setValue(0)
		self.lbl_start_value.setText("0")
		self.lbl_len_value.setText("0")
		self._sliders_initialized = False
		# forget last buffer length so init will run on next valid buf_len
		self._last_buf_len = None
		try:
			self.slider_start.blockSignals(False)
			self.slider_len.blockSignals(False)
		except Exception:
			pass

	def _init_sliders(self, buf_len: int):
		"""Настроить слайдеры под актуальную длину буфера."""
		if buf_len <= 0:
			return
		try:
			self.slider_start.blockSignals(True)
			self.slider_len.blockSignals(True)
		except Exception:
			pass
		self.view_start = 0
		self.view_len = buf_len
		self.slider_start.setEnabled(True)
		self.slider_len.setEnabled(True)
		self.slider_len.setMinimum(1)
		self.slider_len.setMaximum(buf_len)
		self.slider_len.setValue(buf_len)
		self.slider_start.setMaximum(max(0, buf_len - self.view_len))
		self.slider_start.setValue(0)
		self.lbl_start_value.setText(str(self.view_start))
		self.lbl_len_value.setText(str(self.view_len))
		self._sliders_initialized = True
		try:
			self.slider_start.blockSignals(False)
			self.slider_len.blockSignals(False)
		except Exception:
			pass
		try:
			self.slider_start.blockSignals(False)
			self.slider_len.blockSignals(False)
		except Exception:
			pass

	def _soft_kick_stream(self):
		"""Мягко переинициализировать параметры и запустить START без STOP, чтобы не ронять интерфейс."""
		if self.stream is None:
			raise RuntimeError("нет активного потока")
		if bool(getattr(self, '_stream_user_stopped', False)):
			return
		# Повторим текущий профиль и Ns и отправим START
		try:
			# Попробуем новый SOFT_RESET, если прошивка его поддерживает
			try:
				if hasattr(self.stream, 'soft_reset'):
					self.stream.soft_reset()
					try:
						import time as _t
						_t.sleep(0.05)
					except Exception:
						pass
			except Exception:
				pass
			# профиль
			self.stream.send_cmd(CMD_SET_PROFILE, bytes([self.desired_profile]))
			try:
				import time as _t
				_t.sleep(0.02)
			except Exception:
				pass
			# размер кадра (SET_FRAME_SAMPLES) — ТОЛЬКО для профиля 2 и только если явно включено
			if getattr(self, 'send_ns', False) and int(getattr(self, 'desired_profile', 2) or 2) == 2:
				try:
					from usb_vendor.usb_stream import CMD_SET_FRAME_SAMPLES  # type: ignore
				except Exception:
					CMD_SET_FRAME_SAMPLES = 0x17
				ns = self.ns_map.get(self.desired_profile, self.initial_expected)
				try:
					self.stream.send_cmd(CMD_SET_FRAME_SAMPLES, int(ns).to_bytes(2,'little'))
					import time as _t
					_t.sleep(0.02)
				except Exception:
					pass
			# Устанавливаем выбранную частоту
			try:
				freq_to_set = getattr(self, 'desired_freq', 200)
				if hasattr(self.stream, 'set_block_rate'):
					self.stream.set_block_rate(freq_to_set)
					try:
						import time as _t
						_t.sleep(0.1)
					except Exception:
						pass
				else:
					# Fallback: отправляем команду напрямую
					import struct
					self.stream.send_cmd(0x11, struct.pack('<H', freq_to_set))
					try:
						import time as _t
						_t.sleep(0.1)
					except Exception:
						pass
			except Exception as e:
				try:
					print(f'[start] Failed to set frequency: {e}')
				except:
					pass
			# старт
			self._send_start_stream()
			# После soft/deep reset прошивка может потерять runtime-настройки.
			# Повторно применяем текущие GUI-параметры на устройство.
			try:
				self._apply_saved_device_settings()
			except Exception:
				pass
		except Exception as e:
			raise

	def _maybe_auto_reset_on_stall(self, reason: str, idle_s: float):
		"""Авто-сброс STM32 при зависании потока (best-effort, с троттлингом)."""
		try:
			if bool(getattr(self, '_stream_user_stopped', False)):
				return
			if not bool(getattr(self, 'auto_reset_on_stall', False)):
				return
			try:
				thr = float(getattr(self, 'stall_reset_after', 0.0) or 0.0)
			except Exception:
				thr = 0.0
			if thr <= 0 or float(idle_s) < thr:
				return
			if bool(getattr(self, '_stall_reset_inflight', False)):
				return
			now = time.time()
			try:
				cooldown = float(getattr(self, 'stall_reset_cooldown', 0.0) or 0.0)
			except Exception:
				cooldown = 0.0
			last_t = float(getattr(self, '_stall_reset_last_t', 0.0) or 0.0)
			if cooldown > 0 and (now - last_t) < cooldown:
				return
			self._stall_reset_inflight = True
			self._stall_reset_last_t = now
			try:
				self._set_status(f"Поток пропал ({reason}) — сброс STM32…", hold_sec=2.0)
			except Exception:
				pass

			def _worker():
				try:
					# Попробуем SOFT_RESET через CDC (если доступен)
					try:
						self._send_soft_reset_via_cdc()
					except Exception:
						pass
					# Попробуем DEEP_RESET по bulk (если доступен)
					try:
						if self.stream is not None and hasattr(self.stream, 'deep_reset'):
							self.stream.deep_reset()
							time.sleep(0.1)
					except Exception:
						pass
					# Аппаратный reset (GPIO) или power-cycle USB
					try:
						ok = bool(self._hardware_reset_device())
					except Exception:
						ok = False
					if not ok:
						try:
							self._power_cycle_usb_port()
						except Exception:
							pass
					# Отметим как disconnected и запросим аппаратный reset по существующему пути
					try:
						self._usb_err_need_hw_reset = True
					except Exception:
						pass
					try:
						if self.stream is not None:
							self.stream.disconnected = True
					except Exception:
						pass
				finally:
					try:
						self._stall_reset_inflight = False
					except Exception:
						pass

			threading.Thread(target=_worker, daemon=True).start()
		except Exception:
			try:
				self._stall_reset_inflight = False
			except Exception:
				pass

	def _diagnose_and_kick(self):
		"""Проверить EP0, выполнить DEEP_RESET, установить alt=1, проверить готовность и запустить поток.

		Алгоритм восстановления без перезапитки.
		"""
		if self.stream is None:
			self._set_status("Нет активного потока. Нажмите 1 для подключения.", hold_sec=2.0)
			return
		# Шаг 1: Проверить EP0
		try:
			# Получим STAT через EP0 (recipient: interface)
			if hasattr(self.stream, '_get_status_ep0'):
				self.stream._get_status_ep0()
			self._set_status("EP0 проверен, STAT получен…", hold_sec=0.5)
		except Exception as e:
			self._set_status(f"EP0 не отвечает: {e}. Перезапуск интерфейса в ОС или power cycle.", hold_sec=2.0)
			# Сразу попробуем power cycle
			try:
				self._power_cycle_usb_port()
				return
			except Exception as pc_e:
				self._set_status(f"Power cycle не удался: {pc_e}. Требуется аппаратный сброс.", hold_sec=5.0)
			return
		# Шаг 2: DEEP_RESET
		try:
			if hasattr(self.stream, 'deep_reset'):
				self._set_status("DEEP_RESET…", hold_sec=0.8)
				self.stream.deep_reset()
				time.sleep(0.1)  # Пауза после DEEP_RESET
			else:
				self._set_status("DEEP_RESET не поддерживается, пропускаю…", hold_sec=0.5)
		except Exception as e:
			self._set_status(f"DEEP_RESET failed: {e}", hold_sec=1.0)
		# Шаг 3: Установить alt=1
		try:
			if hasattr(self.stream, 'set_alt'):
				self._set_status("Установка alt=1…", hold_sec=0.5)
				self.stream.set_alt(1)
				time.sleep(0.05)
			else:
				self._set_status("set_alt не поддерживается, пропускаю…", hold_sec=0.5)
		except Exception as e:
			self._set_status(f"set_alt failed: {e}", hold_sec=1.0)
		# Шаг 4: Проверить готовность через GET_STATUS
		try:
			if hasattr(self.stream, '_get_status_ep0'):
				self.stream._get_status_ep0()
			time.sleep(0.05)  # Дать время на обновление STAT
			st = getattr(self.stream, 'last_stat', None)
			if isinstance(st, (bytes, bytearray)) and len(st) >= 64 and st[:4] == b'STAT':
				# STAT v1: flags_runtime 48:50 (u16), flags2 50:52 (u16), sending_ch @52 (u8), reserved2 @53 (u8)
				flags_runtime = int.from_bytes(st[48:50], 'little')
				hang_latched = (flags_runtime & 0x0004) != 0
				flags2 = int.from_bytes(st[50:52], 'little')
				alt1 = (flags2 >> 15) & 1
				sending_ch = st[52]
				reserved2 = st[53]
				out_armed = (reserved2 >> 7) & 1
				deep_reset_count_mod4 = reserved2 & 3
				print(f"[diag] STAT parsed: alt1={alt1}, out_armed={out_armed}, hang_latched={hang_latched}, sending_ch={sending_ch}, deep_reset_count_mod4={deep_reset_count_mod4}")
				if alt1 == 1 and out_armed == 1:
					status_msg = f"Готовность подтверждена (alt1=1, out_armed=1"
					if hang_latched:
						status_msg += ", hang_latched=1"
					if deep_reset_count_mod4:
						status_msg += f", deep_resets={deep_reset_count_mod4}"
					status_msg += "). Запуск потока…"
					self._set_status(status_msg, hold_sec=1.0)
					# Шаг 5: Запустить поток
					try:
						self._soft_kick_stream()
						self.last_soft_kick_t = time.time()
						self._set_status("Команды прошли. Ожидание данных…", hold_sec=1.5)
						return
					except Exception as e:
						self._set_status(f"START failed: {e}", hold_sec=1.0)
				else:
					self._set_status(f"Не готово: alt1={alt1}, out_armed={out_armed}. Повторная попытка alt toggle…", hold_sec=1.0)
			else:
				self._set_status("STAT не получен после alt=1. Повторная попытка…", hold_sec=1.0)
		except Exception as e:
			self._set_status(f"Проверка готовности failed: {e}", hold_sec=1.0)
		# Fallback: Alt toggle
		try:
			if hasattr(self.stream, 'set_alt'):
				self._set_status("Alt toggle 0→1…", hold_sec=0.8)
				self.stream.set_alt(0)
				time.sleep(0.03)
				self.stream.set_alt(1)
				time.sleep(0.05)
				self._soft_kick_stream()
				self._set_status("Alt toggle + kick отправлены. Ожидаю данные…", hold_sec=1.2)
				return
		except Exception as e:
			pass
		# Последний шанс: Power cycle
		try:
			self._power_cycle_usb_port()
			return
		except Exception as pc_e:
			self._set_status(f"Все методы восстановления не удались: {pc_e}. Требуется аппаратный сброс.", hold_sec=5.0)

	def _power_cycle_usb_port(self):
		"""Попытаться перезапитать конкретный USB-порт через uhubctl.

		Алгоритм:
		- узнаём топологию у текущего stream (bus, hub_loc, hub_port)
		- пытаемся `uhubctl -l <hub_loc> -p <port> -a off/on` (если установлен)
		- если uhubctl недоступен/не поддерживает PPS – fallback через sysfs:
		  /sys/bus/usb/devices/<port_path>/authorized 0/1, затем unbind/bind
		- после включения запускаем обычное переподключение
		"""
		if self.stream is None and self.last_port_info is None:
			self._set_status("Нет активного потока и сохранённой информации о порте. Нажмите 1 для подключения и повторите.", hold_sec=2.0)
			return
		try:
			info = {}
			try:
				if self.stream is not None:
					info = self.stream.get_port_path_info()
				else:
					info = self.last_port_info
			except Exception:
				info = self.last_port_info if self.last_port_info else {}
			hub_loc = info.get('hub_loc')
			hub_port = info.get('hub_port')
			port_path = info.get('port_path')  # например, "1-1.3.2"
			if not hub_loc or not hub_port:
				self._set_status("Не удалось определить порт хаба. Откройте консоль и выполните: sudo uhubctl", hold_sec=3.0)
				return
			if self.stream is not None:
				# Закрыть текущий поток прежде чем дёргать питание
				try:
					self.stream.close()
				except Exception:
					pass
				self.stream = None
			import subprocess, shlex, shutil, time as _t, os as _os
			# Попытка через uhubctl (если установлен)
			uh_path = shutil.which("uhubctl")
			uh_ok = False
			uh_err = ""
			if uh_path:
				self._set_status(f"Отключаю питание USB {hub_loc} порт {hub_port} через uhubctl…", hold_sec=2.0)
				cmd_off = f"sudo {uh_path} -l {hub_loc} -p {hub_port} -a off"
				cmd_on  = f"sudo {uh_path} -l {hub_loc} -p {hub_port} -a on"
				try:
					res_off = subprocess.run(shlex.split(cmd_off), capture_output=True, text=True, timeout=6)
					_off_rc = res_off.returncode
					_off_out = (res_off.stdout or "") + ("\n" + (res_off.stderr or ""))
					_t.sleep(1.0)
					res_on = subprocess.run(shlex.split(cmd_on), capture_output=True, text=True, timeout=6)
					_on_rc = res_on.returncode
					_on_out = (res_on.stdout or "") + ("\n" + (res_on.stderr or ""))
					uh_ok = (_off_rc == 0 and _on_rc == 0)
					# Типичные признаки отсутствия поддержки: "No compatible devices", "not found", "Permission denied"
					if ("No compatible" in _off_out) or ("No compatible" in _on_out) or ("not found" in _off_out) or ("not found" in _on_out) or ("Permission denied" in _off_out) or ("Permission denied" in _on_out):
						uh_ok = False
					if not uh_ok:
						uh_err = f"uhubctl rc off:{_off_rc} on:{_on_rc}. off_out: {_off_out.strip()} | on_out: {_on_out.strip()}"
				except Exception as e:
					uh_err = f"uhubctl exec error: {e}"
			# Если uhubctl не сработал — fallback через sysfs
			if not uh_ok:
				if not uh_path:
					print("[power] uhubctl не найден в системе. apt install uhubctl для перезапитки PPS-хабов.")
				else:
					print("[power] uhubctl failed:", uh_err)
				# Нужен port_path вида "1-1.3.2" для sysfs
				if not port_path:
					self._set_status("Нет port_path для sysfs fallback. Установите uhubctl или подключите PPS-хаб.", hold_sec=3.0)
					return
				dev_dir = f"/sys/bus/usb/devices/{port_path}"
				auth_file = f"{dev_dir}/authorized"
				self._set_status("Пробую отключить устройство через sysfs authorized…", hold_sec=2.0)
				# authorized 0/1 через tee (чтобы не требовать /bin/sh в sudoers)
				try:
					is_root = False
					try:
						is_root = (os.geteuid() == 0)
					except Exception:
						pass
					if is_root:
						res0 = subprocess.run(["tee", auth_file], input="0\n", text=True, capture_output=True, timeout=6)
					else:
						res0 = subprocess.run(["sudo", "tee", auth_file], input="0\n", text=True, capture_output=True, timeout=6)
					_t.sleep(0.8)
					if is_root:
						res1 = subprocess.run(["tee", auth_file], input="1\n", text=True, capture_output=True, timeout=6)
					else:
						res1 = subprocess.run(["sudo", "tee", auth_file], input="1\n", text=True, capture_output=True, timeout=6)
					if res0.returncode != 0 or res1.returncode != 0:
						raise RuntimeError(f"authorized rc0={res0.returncode} rc1={res1.returncode} out0={res0.stderr or res0.stdout} out1={res1.stderr or res1.stdout}")
					auth_ok = True
				except Exception as e_auth:
					print("[power] sysfs authorized failed:", e_auth)
					# Попробуем unbind/bind через tee
					self._set_status("authorized не сработал, пробую unbind/bind…", hold_sec=2.0)
					try:
						ub = "/sys/bus/usb/drivers/usb/unbind"
						bb = "/sys/bus/usb/drivers/usb/bind"
						is_root = False
						try:
							is_root = (os.geteuid() == 0)
						except Exception:
							pass
						if is_root:
							res_u = subprocess.run(["tee", ub], input=f"{port_path}\n", text=True, capture_output=True, timeout=6)
						else:
							res_u = subprocess.run(["sudo", "tee", ub], input=f"{port_path}\n", text=True, capture_output=True, timeout=6)
						_t.sleep(0.8)
						if is_root:
							res_b = subprocess.run(["tee", bb], input=f"{port_path}\n", text=True, capture_output=True, timeout=6)
						else:
							res_b = subprocess.run(["sudo", "tee", bb], input=f"{port_path}\n", text=True, capture_output=True, timeout=6)
						if res_u.returncode != 0 or res_b.returncode != 0:
							raise RuntimeError(f"unbind/bind rcU={res_u.returncode} rcB={res_b.returncode} outU={res_u.stderr or res_u.stdout} outB={res_b.stderr or res_b.stdout}")
						if bool(getattr(self, 'debug', False)):
							print("[power] unbind/bind OK")
					except Exception as e_ub:
						self._set_status(f"Не удалось перезапустить порт: {e_ub}", hold_sec=3.0)
						return
			else:
				self._set_status("Питание через uhubctl включено. Жду переэнумерации…", hold_sec=2.0)
			# Небольшая пауза и обычное переподключение
			_t.sleep(1.0)
			self._activate_stream()
		except Exception as e:
			self._set_status(f"Power-cycle ошибка: {e}", hold_sec=3.0)

	def _try_connect(self, first=False):
		if self.num_group.checkedId() == 0:
			return
		if self._connecting or self.stream is not None:
			return
		self._connecting = True
		msg_prefix = "Подключение" if not first else "Инициализация"
		try:
			self._set_status(f"{msg_prefix} к устройству…", hold_sec=1.5)
			# восстановим глобальный флаг running в модуле usb_stream (после close() он мог стать False)
			try:
				import usb_vendor.usb_stream as _usm  # type: ignore
				if getattr(_usm, 'running', True) is False:
					_usm.running = True
			except Exception:
				pass
			# frame_samples (SET_FRAME_SAMPLES) безопасен только для профиля 2; профиль 1 не трогаем
			fs = self.expected_len_map.get(self.desired_profile, self.initial_expected) if (self.send_ns and int(self.desired_profile or 2) == 2) else None
			# Для 200 Гц некоторые прошивки ожидают явной установки block rate — включим отправку частоты на старте
			try:
				os.environ['BMI30_SEND_BLOCK_RATE'] = '1'
			except Exception:
				pass
			if bool(getattr(self, 'debug', False)):
				print(f"[CONNECT] Creating USBStream, profile={self.desired_profile}, fs={fs}", flush=True)
			self.stream = USBStream(profile=self.desired_profile, full=True, test_as_data=self.test_as_data, frame_samples=fs, fast_mode=True, assembler_independent=self.independent_channels)
			# успешное подключение — сбросим счётчики ошибок переподключения
			try:
				self._usb_connect_err_count = 0
			except Exception:
				pass
			# On every fresh connect: immediately force RUN state and start warmup from *now*.
			# This prevents "FROZEN right after startup" and ignores early unstable thresholds.
			try:
				self._det_reset_and_arm_warmup('connect')
			except Exception:
				pass
			# Сохраним порт info для power cycle без stream
			self.last_port_info = self.stream.port_info
			# Явная конфигурация устройства по согласованной последовательности
			if self.apply_init_sequence:
				try:
					self._run_init_sequence()
				except Exception as e_init:
					print(f"[initseq] failed: {e_init}")
			# Применим сохранённые параметры после подключения
			try:
				self._apply_saved_device_settings()
			except Exception:
				pass
			self._set_status("Устройство подключено, ожидание данных…", hold_sec=1.5)
			self.connect_t = time.time()
			self.last_frame_t = 0
			self.no_data_warned = False
			# Запускаем reader thread
			if bool(getattr(self, 'debug', False)):
				print(f"[CONNECT] reader_running={self.reader_running}, starting thread...", flush=True)
			if not self.reader_running:
				self.reader_running = True
				self.reader_thread = threading.Thread(target=self._reader_thread_func, daemon=True)
				self.reader_thread.start()
				if bool(getattr(self, 'debug', False)):
					print("[GUI] Reader thread started", flush=True)
			else:
				if bool(getattr(self, 'debug', False)):
					print("[GUI] Reader thread already running", flush=True)
		except SystemExit as se:
			self.stream = None
			print(f"[ERROR] SystemExit: {se}", flush=True)
			self._set_status(str(se), hold_sec=2.0)
		except Exception as e:
			self.stream = None
			print(f"[ERROR] Exception during connect: {e}", flush=True)
			import traceback
			traceback.print_exc()
			msg = str(e)
			# При любой ошибке подключения выполняем аппаратный сброс (с троттлингом)
			try:
				now = time.time()
				min_reset_s = float(os.getenv("BMI30_USB_RESET_MIN_S", "8.0"))
				min_power_s = float(os.getenv("BMI30_USB_POWERCYCLE_MIN_S", "30.0"))
				last_reset = float(getattr(self, "_usb_connect_last_reset_t", 0.0) or 0.0)
				last_power = float(getattr(self, "_usb_connect_last_power_t", 0.0) or 0.0)
				self._usb_connect_err_count = int(getattr(self, "_usb_connect_err_count", 0)) + 1
				if (now - last_reset) >= max(2.0, min_reset_s):
					self._set_status("Ошибка подключения, аппаратный сброс…", hold_sec=2.0)
					self._hardware_reset_device()
					self._usb_connect_last_reset_t = now
				# при серии ошибок попробуем power-cycle порта
				if int(getattr(self, "_usb_connect_err_count", 0)) >= 3 and (now - last_power) >= max(5.0, min_power_s):
					self._set_status("Ошибка подключения, перезапитка порта…", hold_sec=2.0)
					try:
						self._power_cycle_usb_port()
					except Exception:
						pass
					self._usb_connect_last_power_t = now
					self._usb_connect_err_count = 0
			except Exception:
				pass
			self._set_status(f"Нет устройства ({e})", hold_sec=2.0)
		finally:
			self._connecting = False
			if self.stream is None:
				if not self.usb_retry_timer.isActive():
					self.usb_retry_timer.start()
			else:
				self.usb_retry_timer.stop()

	def _activate_stream(self):
		if not self.usb_retry_timer.isActive():
			self.usb_retry_timer.start()
		# Optional: auto hardware reset on first activation
		try:
			if not bool(getattr(self, '_hw_reset_on_start_done', False)):
				auto_hw = str(os.getenv("BMI30_HW_RESET_ON_START", "1")).lower() not in ("0", "false", "no")
				if auto_hw:
					self._hardware_reset_device()
				self._hw_reset_on_start_done = True
		except Exception:
			pass
		self._send_soft_reset_via_cdc()
		self._try_connect(first=True)
		# Транспорт при подключении посылает минимальный START сам.
		# Не дублируем SET_PROFILE/START здесь, чтобы не подавить первые A/B кадры.
		if self.stream is not None:
			# Arm warmup from actual stream start and force RUN state.
			# (User may wait before pressing "1", so GUI-start warmup is not reliable.)
			try:
				self._det_reset_and_arm_warmup('activate')
			except Exception:
				pass
			# Показать ожидаемое число семплов одного буфера по профилю
			expected = self.expected_len_map.get(self.desired_profile, self.initial_expected)
			freq = 200 if self.desired_profile == 1 else 300 if self.desired_profile == 2 else None
			msg = f"Старт потока… ожидание данных… BUF≈{expected} семплов"
			if freq:
				msg += f" (профиль {freq} Гц)"
			self._set_status(msg, hold_sec=1.5)
			try:
				print(f"[start] Профиль={self.desired_profile} ожидаемый BUF={expected} семплов")
			except Exception:
				pass
			# Ensure device streaming is started (best-effort). Some devices require explicit START.
			try:
				self._send_start_stream()
				print("[activate] Sent CMD_START_STREAM (ensure streaming)")
			except Exception:
				pass

	def _apply_saved_device_settings(self):
		"""Применить текущие/сохранённые параметры к устройству после подключения/сброса."""
		if self.stream is None:
			return
		# Применим сохранённую частоту
		try:
			freq = int(getattr(self, 'desired_freq', 0) or 0)
		except Exception:
			freq = 0
		if freq:
			try:
				if hasattr(self.stream, 'set_buf_rate_fine'):
					self.stream.set_buf_rate_fine(freq)
				elif hasattr(self.stream, 'set_block_rate'):
					self.stream.set_block_rate(freq)
				else:
					import struct
					self.stream.send_cmd(0x11, struct.pack('<H', freq))
			except Exception:
				pass
		# Применим сохранённый режим (кнопки 1..6)
		try:
			idx = int(self.num_group.checkedId())
		except Exception:
			try:
				idx = int(self.sel_saved or 0)
			except Exception:
				idx = 0
		if int(idx) != 0:
			try:
				self._num_clicked(int(idx))
				try:
					self._on_num_clicked_extra(int(idx))
				except Exception:
					pass
			except Exception:
				pass
		# Восстановим старт рабочей зоны ROI для выбранного типа метки.
		# (актуально после reset, когда прошивка теряет windows/start)
		try:
			self._send_mark_type_roi_start_to_device()
		except Exception:
			pass
		# Быстрая компенсация DC после reset (восстановление постоянной составляющей)
		try:
			self._device_calib_dc_fast(frames=30)
		except Exception:
			pass
		# Восстановим параметры коммутации/передачи, которые может сбросить прошивка.
		try:
			self._send_sync_mode(int(getattr(self, 'adc_comm_mode', 0) or 0))
		except Exception:
			pass
		try:
			tx_on = bool(getattr(self, 'tim2_enabled', False))
			self._send_tim2_enable(tx_on)
			self._send_tx_enable(tx_on)
		except Exception:
			pass
		# Для режима AVG_ROI дополнительно повторно зададим avg_n.
		try:
			if int(getattr(self, 'stream_mode', 0) or 0) == 2:
				avg_n = int(getattr(self, 'avg_n', 20) or 20)
				avg_n = max(2, min(32, avg_n))
				self.stream.send_cmd(CMD_SET_STREAM_MODE, bytes([0x02, avg_n & 0xFF]))
		except Exception:
			pass
		# START ещё раз (idempotent) — фиксирует состояние после последовательности команд.
		try:
			self._send_start_stream()
		except Exception:
			pass
		# Небольшая диагностическая отметка в лог (не в UI).
		try:
			if bool(getattr(self, 'debug', False)):
				print(f"[restore] device settings reapplied (mode={int(idx)}, freq={int(freq) if freq else 0})")
		except Exception:
			pass
			try:
				if hasattr(self.stream, 'set_buf_rate_fine'):
					self.stream.set_buf_rate_fine(freq)
				elif hasattr(self.stream, 'set_block_rate'):
					self.stream.set_block_rate(freq)
				else:
					import struct
					self.stream.send_cmd(0x11, struct.pack('<H', freq))
			except Exception:
				pass

	def _on_freq_change(self, text:str):
		# Парсим частоту из текста "XXX Hz"
		try:
			freq = int(text.split()[0])
		except:
			freq = 200
		self.desired_freq = freq
		# Для совместимости с существующим кодом сохраняем profile (используем 1 для всех частот)
		self.desired_profile = 1
		save_config(self.desired_profile, freq)  # сохраняем выбор
		if self.stream is None:
			self._set_status(f"Выбрана частота {freq} Гц (нажмите 1 для запуска)")
			return
		# Переключение на лету: не роняем поток, только отправляем частоту
		try:
			if hasattr(self.stream, 'set_buf_rate_fine'):
				self.stream.set_buf_rate_fine(self.desired_freq)
				print(f"[freq_change] Set rate to {self.desired_freq} Hz via set_buf_rate_fine()")
			elif hasattr(self.stream, 'set_block_rate'):
				self.stream.set_block_rate(self.desired_freq)
				print(f"[freq_change] Set block rate to {self.desired_freq} Hz via set_block_rate()")
			else:
				import struct
				self.stream.send_cmd(0x11, struct.pack('<H', self.desired_freq))
				print(f"[freq_change] Set block rate to {self.desired_freq} Hz via CMD_BLOCK_HZ")
			self._set_status(f"Частота установлена: {self.desired_freq} Гц", hold_sec=1.5)
		except Exception as e:
			self._set_status(f"Ошибка смены частоты: {e}", hold_sec=2.0)

	def _on_avg_change(self, idx: int):
		"""Handler for avg_n combo box: send AVG_ROI change to device and save setting."""
		try:
			text = self.avg_box.currentText()
			new_n = int(text)
		except Exception:
			new_n = 20
		# save selection
		save_avg_n(new_n)
		self.avg_n = new_n
		# Если поток не подключен или режим не AVG_ROI — только сохраняем значение
		if self.stream is None or getattr(self, 'stream_mode', 0) != 2:
			self._set_status(f"Сохранено avg_n={new_n} (применится в режиме AVG_ROI)", hold_sec=1.5)
			return
		# Если уже в AVG_ROI, отправим новое значение avg_n
		try:
			self.stream.send_cmd(CMD_SET_STREAM_MODE, bytes([0x02, new_n & 0xFF]))
			self._set_status(f"Отправлен AVG_ROI avg_n={new_n}", hold_sec=2.0)
			if bool(getattr(self, 'debug', False)):
				print(f"[AVG_ROI] SET_STREAM_MODE=2 (avg_n={new_n}) отправлен по изменению меню")
		except Exception as e:
			if bool(getattr(self, 'debug', False)):
				print(f"[AVG_ROI] Ошибка обработки avg_n={new_n}: {e}")

	def _on_det_ratio_change(self, text: str, ch: int = 0):
		"""Handler for detector ratio combo box (per ADC)."""
		try:
			mark_type_b = int(getattr(self, '_mark_type_mode', 2)) == 0
		except Exception:
			mark_type_b = False
		if mark_type_b:
			try:
				val = int(round(float(str(text).strip())))
			except Exception:
				val = 2
			val = max(1, min(20, int(val)))
		else:
			try:
				val = float(str(text).strip())
			except Exception:
				val = 2.0
			# clamp to allowed range and step
			val = max(1.0, min(3.0, round(val, 1)))
		if int(ch) == 0:
			self._det_ratio0 = val
		else:
			self._det_ratio1 = val
		try:
			save_det_params(
				float(getattr(self, '_det_ratio0', 2.0)),
				float(getattr(self, '_det_ratio1', 2.0)),
				int(getattr(self, '_det_add0', 100)),
				int(getattr(self, '_det_add1', 100)),
			)
		except Exception:
			pass
		try:
			adc_name = "ADC1" if int(ch) == 0 else "ADC2"
			if mark_type_b:
				self._set_status(f"{adc_name} det ratio (Б): {int(val)}", hold_sec=1.0)
			else:
				self._set_status(f"{adc_name} det ratio: {float(val):.1f}", hold_sec=1.0)
		except Exception:
			pass

	def _on_det_add_change(self, text: str, ch: int = 0):
		"""Handler for detector additive threshold combo box (per ADC)."""
		try:
			val = int(float(str(text).strip()))
		except Exception:
			val = 100
		val = max(0, min(700, int(round(val / 100.0) * 100)))
		if int(ch) == 0:
			self._det_add0 = val
		else:
			self._det_add1 = val
		try:
			save_det_params(
				float(getattr(self, '_det_ratio0', 2.0)),
				float(getattr(self, '_det_ratio1', 2.0)),
				int(getattr(self, '_det_add0', 100)),
				int(getattr(self, '_det_add1', 100)),
			)
		except Exception:
			pass
		try:
			adc_name = "ADC1" if int(ch) == 0 else "ADC2"
			self._set_status(f"{adc_name} det add: {val}", hold_sec=1.0)
		except Exception:
			pass

	# duplicate _on_freq_change removed

	def _on_close(self, ev):
		try:
			# Перед выходом сохраним DC offset (best-effort)
			try:
				self._save_dc_offset(force=True)
			except Exception:
				pass
			# stop background worker
			try:
				if getattr(self, '_mode_worker', None) is not None:
					self._mode_worker.stop()
			except Exception:
				pass
			try:
				self.stream.close()
			except Exception:
				pass
			try:
				self._cleanup_det_gpio()
			except Exception:
				pass
			try:
				self._cleanup_det_gate_gpio23_input()
			except Exception:
				pass
		except Exception:
			pass

	def _send_sync_mode(self, mode: int):
		"""Отправить режим синхронизации: 0=master, 1=slave, 2=off."""
		try:
			if self.stream is None:
				return
			payload = bytes([int(mode) & 0xFF])
			self.stream.send_cmd(CMD_SET_SYNC_MODE, payload)
		except Exception as e:
			try:
				self._set_status(f"SYNC: ошибка отправки ({e})", hold_sec=2.0)
			except Exception:
				pass

	def _adc_enable_flags(self):
		"""Return (adc1_enabled, adc2_enabled) based on adc_comm_mode."""
		try:
			mode = int(getattr(self, 'adc_comm_mode', 0))
		except Exception:
			mode = 0
		if mode == 1:
			return True, False
		if mode == 2:
			return False, True
		return True, True

	def _cycle_sync_mode(self):
		"""Переключить коммутацию ADC: оба -> ADC1 -> ADC2 -> оба."""
		try:
			cur = int(getattr(self, 'adc_comm_mode', 0))
		except Exception:
			cur = 0
		if cur == 0:
			next_mode = 1
		elif cur == 1:
			next_mode = 2
		else:
			next_mode = 0
		self.adc_comm_mode = next_mode
		try:
			save_ui_state(adc_comm_mode=int(self.adc_comm_mode))
		except Exception:
			pass
		self._update_sync_btn_style()
		try:
			label = {0: "ADC1+ADC2", 1: "ADC1", 2: "ADC2"}.get(next_mode, "ADC1+ADC2")
			self._set_status(f"ADC COMM: {label}", hold_sec=2.0)
		except Exception:
			pass

	def _update_sync_btn_style(self):
		"""Обновить вид кнопки коммутации ADC."""
		try:
			mode = int(getattr(self, 'adc_comm_mode', 0))
		except Exception:
			mode = 0
		try:
			if mode == 0:
				# оба канала: светло‑зелёный фон
				self.btn_sync.setStyleSheet("background-color: #5fd35f; color: #0f2d0f; border:1px solid #3aa93a;")
				if getattr(self, '_btn_sync_m', None) is not None:
					self._btn_sync_m.setStyleSheet("color:#0b2d66; font-size:13pt; font-weight:700;")
					self._btn_sync_slash.setStyleSheet("color:#e0e0e0; font-size:9pt; font-weight:300;")
					self._btn_sync_s.setStyleSheet("color:#7a5a00; font-size:13pt; font-weight:700;")
				self.btn_sync.setToolTip("ADC: 1+2 (оба включены)")
			elif mode == 1:
				# только ADC1: светло‑синий фон
				self.btn_sync.setStyleSheet("background-color: #7fb2ff; color: #0b1f3d; border:1px solid #5b8fd9;")
				if getattr(self, '_btn_sync_m', None) is not None:
					self._btn_sync_m.setStyleSheet("color:#0b2d66; font-size:13pt; font-weight:700;")
					self._btn_sync_slash.setStyleSheet("color:#2b3f66; font-size:9pt; font-weight:300;")
					self._btn_sync_s.setStyleSheet("color:#5a5a5a; font-size:9pt; font-weight:300;")
				self.btn_sync.setToolTip("ADC: 1 (включён только ADC1)")
			else:
				# только ADC2: светло‑жёлтый фон
				self.btn_sync.setStyleSheet("background-color: #ffe08a; color: #4a3700; border:1px solid #d1b15a;")
				if getattr(self, '_btn_sync_m', None) is not None:
					self._btn_sync_m.setStyleSheet("color:#5a5a5a; font-size:9pt; font-weight:300;")
					self._btn_sync_slash.setStyleSheet("color:#6b5a2a; font-size:9pt; font-weight:300;")
					self._btn_sync_s.setStyleSheet("color:#7a5a00; font-size:13pt; font-weight:700;")
				self.btn_sync.setToolTip("ADC: 2 (включён только ADC2)")
		except Exception:
			pass

	def _update_tim2_btn_style(self):
		"""Обновить стиль кнопки передачи TIM2."""
		try:
			en = bool(getattr(self, 'tim2_enabled', False))
		except Exception:
			en = False
		try:
			if en:
				self.btn_tim2.setStyleSheet("background-color: #008800; color: white; font-weight: bold; border:1px solid #005500;")
				self.btn_tim2.setToolTip("Передача TIM2: ВКЛ")
			else:
				self.btn_tim2.setStyleSheet("background-color: #880000; color: white; font-weight: bold; border:1px solid #550000;")
				self.btn_tim2.setToolTip("Передача TIM2: ВЫКЛ")
		except Exception:
			pass

	def _send_tim2_enable(self, enabled: bool):
		"""Отправить CMD_SET_TIM2_ENABLE (0x1E)."""
		try:
			if self.stream is None:
				return
			if hasattr(self.stream, 'set_tim2_enable'):
				self.stream.set_tim2_enable(bool(enabled))
			else:
				payload = b"\x01" if bool(enabled) else b"\x00"
				self.stream.send_cmd(CMD_SET_TIM2_ENABLE, payload)
		except Exception as e:
			try:
				self._set_status(f"TIM2: ошибка ({e})", hold_sec=2.0)
			except Exception:
				pass

	def _send_tx_enable(self, enabled: bool):
		"""Отправить CMD_SET_TX_ENABLE (0x33)."""
		try:
			if self.stream is None:
				return
			payload = b"\x01" if bool(enabled) else b"\x00"
			# через USBStream, если реализовано
			if hasattr(self.stream, 'set_tx_enable'):
				self.stream.set_tx_enable(bool(enabled))
			else:
				self.stream.send_cmd(CMD_SET_TX_ENABLE, payload)
		except Exception as e:
			try:
				self._set_status(f"TX: ошибка ({e})", hold_sec=2.0)
			except Exception:
				pass

	def _send_start_stream(self):
		"""START потока с учётом TIM2 enable (если разрешено)."""
		try:
			if self.stream is None:
				return
			# пользовательский стоп снят
			self._stream_user_stopped = False
			if bool(getattr(self, 'tim2_enabled', False)):
				self._send_tim2_enable(True)
			self.stream.send_cmd(CMD_START_STREAM, b"")
		except Exception:
			pass

	def _send_stop_stream(self):
		"""STOP потока (предпочтительно через EP0 control)."""
		try:
			if self.stream is None:
				return
			# помечаем, что остановлено пользователем
			self._stream_user_stopped = True
			# Используем EP0 stop, если доступно
			if hasattr(self.stream, 'stop_stream'):
				try:
					use_ctrl = str(os.getenv("BMI30_STOP_CTRL", "1")).lower() not in ("0", "false", "no")
				except Exception:
					use_ctrl = True
				self.stream.stop_stream(use_ctrl=use_ctrl)
				return
			# Fallback: прямой EP0
			try:
				self.stream.dev.ctrl_transfer(0x40, CMD_STOP_STREAM, 0, 0, None, timeout=300)
				return
			except Exception:
				pass
			# Final fallback: bulk
			self.stream.send_cmd(CMD_STOP_STREAM, b"")
		except Exception:
			pass

	def _on_toggle_tim2(self, enabled: bool):
		"""GUI: включить/выключить передачу TIM2."""
		try:
			self.tim2_enabled = bool(enabled)
		except Exception:
			self.tim2_enabled = False
		try:
			save_ui_state(tim2_enabled=bool(self.tim2_enabled))
		except Exception:
			pass
		self._update_tim2_btn_style()
		try:
			if self.stream is None:
				return
			if self.tim2_enabled:
				self._stream_user_stopped = False
				# Включаем внешний передатчик, поток не трогаем
				self._send_tx_enable(True)
				self._set_status("TX: передача ВКЛ", hold_sec=1.5)
			else:
				# Не останавливаем поток: выключаем только внешний передатчик
				self._send_tx_enable(False)
				self._stream_user_stopped = False
				self._set_status("TX: передача ВЫКЛ (стрим продолжается)", hold_sec=1.5)
		except Exception:
			pass

	def run(self):
		self.win.resize(900, 600)
		self.win.show()
		# Запускаем цикл событий Qt корректно как для PyQt5 (exec_()), так и для PyQt6 (exec())
		_app = QtWidgets.QApplication.instance()
		if hasattr(_app, 'exec_'):
			_app.exec_()
		else:
			_app.exec()


def main():
	if PG_IMPORT_ERR:
		print('[fatal] pyqtgraph/Qt не установлены. pip install pyqtgraph PyQt5')
		return 2
	ScopeWindow().run()
	return 0


if __name__ == '__main__':
	sys.exit(main())
