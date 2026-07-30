#!/usr/bin/env python3

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import hmac
import ipaddress
import io
import json
import mimetypes
import os
import pathlib
import re
import shlex
import ssl
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener, urlopen


def _initial_page_revision() -> str:
    override = os.getenv("BMI30_PAGE_REV", "").strip()
    if override:
        return override
    for manifest in (
        "/home/techaid/Documents/host/bmi30_firmware_release.env",
        os.path.join(os.path.dirname(__file__), "host", "bmi30_firmware_release.env"),
    ):
        try:
            with open(manifest, "r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    if raw_line.startswith("BMI30_FIRMWARE_VERSION="):
                        value = raw_line.split("=", 1)[1].strip().strip("'\"")
                        if value:
                            return value
        except OSError:
            pass
    return str(int(os.path.getmtime(__file__)))


def _sha256_file(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


PORT         = int(os.getenv("BMI30_HOTSPOT_INFO_PORT",      "80"))
HTTPS_PORT   = int(os.getenv("BMI30_HOTSPOT_INFO_HTTPS_PORT", "443"))
CORE_SERVICE_URL = os.getenv("BMI30_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")
REFRESH_S    = max(10, int(os.getenv("BMI30_HOTSPOT_INFO_REFRESH_S", "30")))
SENSOR_REFRESH_S = max(0.25, float(os.getenv("BMI30_SENSOR_REFRESH_S", "0.5")))
STM32_TEMP_CACHE_S = max(SENSOR_REFRESH_S, float(os.getenv("BMI30_STM32_TEMP_CACHE_S", str(SENSOR_REFRESH_S))))
STM32_TEMP_QUERY_TIMEOUT_S = max(0.2, float(os.getenv("BMI30_STM32_TEMP_QUERY_TIMEOUT_S", "0.8")))
LAN_DEVICE_DISCOVERY_S = max(2.0, float(os.getenv("BMI30_LAN_DEVICE_DISCOVERY_S", "5")))
LAN_SENSOR_REFRESH_S = max(0.25, float(os.getenv("BMI30_LAN_SENSOR_REFRESH_S", "0.5")))
LAN_SENSOR_REQUEST_TIMEOUT_S = max(0.5, float(os.getenv("BMI30_LAN_SENSOR_REQUEST_TIMEOUT_S", "1.5")))
HOTSPOT_IP   = os.getenv("BMI30_HOTSPOT_IP",   "10.42.0.1")
HOTSPOT_CONN = os.getenv("BMI30_HOTSPOT_CONN",  "BMI30-Hotspot")
WIFI_STA_IFACE = os.getenv("BMI30_WIFI_STA_IFACE", "wlan0")
SSH_USER     = os.getenv("BMI30_SSH_USER",      "techaid")
SSH_PORT     = int(os.getenv("BMI30_SSH_PORT",  "22"))
RDP_PORT     = int(os.getenv("BMI30_RDP_PORT",  "3389"))
TLS_CERT_PATH = os.getenv("BMI30_TLS_CERT_PATH", "/etc/ssl/bmi30/portal.crt")
TLS_KEY_PATH  = os.getenv("BMI30_TLS_KEY_PATH",  "/etc/ssl/bmi30/portal.key")
ENABLE_HTTPS = os.getenv("BMI30_ENABLE_HTTPS", "0").strip().lower() in {"1", "true", "yes", "on"}
FORCE_HTTPS = os.getenv("BMI30_FORCE_HTTPS", "0").strip().lower() in {"1", "true", "yes", "on"}
PORTAL_USERNAME = os.getenv("BMI30_PORTAL_USERNAME", "admin")
PORTAL_PASSWORD = os.getenv("BMI30_PORTAL_PASSWORD", "admin")
PORTAL_ENGINEER_USERNAME = os.getenv("BMI30_PORTAL_ENGINEER_USERNAME", "").strip()
PORTAL_ENGINEER_PASSWORD = os.getenv("BMI30_PORTAL_ENGINEER_PASSWORD", "")
PORTAL_ENGINEER_PASSWORD_HASH = os.getenv("BMI30_PORTAL_ENGINEER_PASSWORD_HASH", "").strip()
DEFAULT_ENGINEER_USERNAME = os.getenv("BMI30_DEFAULT_ENGINEER_USERNAME", "TechAid")
DEFAULT_ENGINEER_PASSWORD_HASH = os.getenv(
    "BMI30_DEFAULT_ENGINEER_PASSWORD_HASH",
    "pbkdf2_sha256$390000$Ym1pMzAtZW5naW5lZXItdjE$f8kv-1dqQTiWk756wJgI-4KID-gHYR5Meji3kYpgIV4",
)
PORTAL_SESSION_COOKIE = "bmi30_portal_session"
PORTAL_SESSION_TTL_S = max(60, int(os.getenv("BMI30_PORTAL_SESSION_TTL_S", str(7 * 24 * 60 * 60))))
PORTAL_PASSWORD_HASH_ITERATIONS = max(100_000, int(os.getenv("BMI30_PORTAL_PASSWORD_HASH_ITERATIONS", "390000")))
_CONFIG_JSON_ENV = os.getenv("BMI30_CONFIG_JSON", "").strip()
HOST_CONFIG_JSON = os.path.join(os.path.dirname(__file__), "host", "bmi30_config.json")
if _CONFIG_JSON_ENV:
    CONFIG_JSON = _CONFIG_JSON_ENV
else:
    _CONFIG_JSON_CANDIDATES = [
        "/etc/bmi30/portal_config.json",
        "/usr/local/bin/host/bmi30_config.json",
        HOST_CONFIG_JSON,
    ]
    _CONFIG_JSON_FALLBACK = _CONFIG_JSON_CANDIDATES[0] if getattr(os, "geteuid", lambda: 0)() == 0 else _CONFIG_JSON_CANDIDATES[-1]
    CONFIG_JSON = next((path for path in _CONFIG_JSON_CANDIDATES if os.path.isfile(path)), _CONFIG_JSON_FALLBACK)
DEVICE_SYNC_CACHE_S = max(1, int(os.getenv("BMI30_DEVICE_SYNC_CACHE_S", "3")))
SYNC_STATUS_OFFSET_S = os.getenv("BMI30_SYNC_STATUS_OFFSET", "").strip()
DEVICE_STATE_JSON = os.getenv("BMI30_DEVICE_STATE_JSON", "/tmp/bmi30_device_state.json")
DEVICE_STATE_MAX_AGE_S = max(1, int(os.getenv("BMI30_DEVICE_STATE_MAX_AGE_S", "300")))
PORTAL_USB_STATUS_POLL = os.getenv("BMI30_PORTAL_USB_STATUS_POLL", "0").strip().lower() in {"1", "true", "yes", "on"}
PAGE_REV = _initial_page_revision()
PORTAL_RUNTIME_SHA256 = _sha256_file(__file__)
TAGIT_LOGO_CANDIDATES = [
    os.getenv("BMI30_PORTAL_TAGIT_LOGO_PATH", "").strip(),
    os.path.join(os.path.dirname(__file__), "docs", "Tagit_Logo.png"),
    "/home/techaid/Documents/docs/Tagit_Logo.png",
]

AM_LOGO_CANDIDATES = [
    os.getenv("BMI30_PORTAL_AM_LOGO_PATH", "").strip(),
    os.path.join(os.path.dirname(__file__), "docs", "AM-Secure-Logo@4x-100.jpg"),
    os.path.join(os.path.dirname(__file__), "logo.png"),
    os.path.join(os.path.dirname(__file__), "assets", "logo.png"),
    "/usr/local/share/bmi30/logo.jpg",
    "/usr/local/share/bmi30/logo.png",
]

FAVICON_ICO_CANDIDATES = [
    os.getenv("BMI30_PORTAL_FAVICON_ICO_PATH", "").strip(),
    os.path.join(os.path.dirname(__file__), "docs", "favicon.ico"),
    "/home/techaid/Documents/docs/favicon.ico",
    "/usr/local/share/bmi30/favicon.ico",
]

FAVICON_PNG_CANDIDATES = [
    os.getenv("BMI30_PORTAL_FAVICON_PNG_PATH", "").strip(),
    os.path.join(os.path.dirname(__file__), "docs", "favicon.png"),
    "/home/techaid/Documents/docs/favicon.png",
    "/usr/local/share/bmi30/favicon.png",
]

ANDROID_PROBE_PATHS: frozenset[str] = frozenset({
    "/generate_204",              # Android, Chrome, Chrome OS
    "/gen_204",                   # Android alt
})

# Connectivity-probe пути каждой ОС.
# Android надёжнее распознаёт captive portal через 302 redirect на /login,
# а Apple/Windows/Linux корректно работают, если отдать HTML прямо на probe URL.
PROBE_PATHS: frozenset[str] = ANDROID_PROBE_PATHS | frozenset({
    "/hotspot-detect.html",       # iOS / macOS (Apple CNA)
    "/library/test/success.html", # iOS alt
    "/canonical.html",            # iOS alt
    "/ncsi.txt",                  # Windows NCSI
    "/connecttest.txt",           # Windows alt
    "/redirect",                  # Windows redirect probe
    "/success.txt",               # Firefox
    "/nm",                        # NetworkManager (Linux)
    "/check_inet_status",         # GNOME / Debian
})

# Пути, на которых показывается информационная страница с деталями подключения.
INFO_PATHS: frozenset[str] = frozenset({"/", "/index.html", "/login", "/status"})

_SYNC_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "responded": False,
    "value": "---",
    "code": "",
    "source": "device",
}
_LCD_SYNC_CODE_RE = re.compile(r"^[MS][0-9]{2}$")
_STM32_TEMP_CACHE: dict[str, Any] = {"ts": 0.0, "value": None}
_STM32_TEMP_LOCK = threading.Lock()
_LAN_DEVICE_CACHE: dict[str, Any] = {"updated_at": 0.0, "sensor_updated_at": 0.0, "devices": []}
_LAN_DEVICE_LOCK = threading.Lock()
_LAN_SENSOR_OPENERS: dict[str, Any] = {}
_LAN_SENSOR_OPENERS_LOCK = threading.Lock()

_PORTAL_CLIENTS: dict[str, float] = {}
PORTAL_CLIENT_TTL_S = 15.0

HTTPS_RUNTIME_ENABLED = False


def _ready_sync_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    return code if _LCD_SYNC_CODE_RE.fullmatch(code) else ""


AVG_N_VALUES: tuple[int, ...] = (8, 16, 24, 32, 40, 48, 56, 64)
DEFAULT_AVG_N = 24
DC_SETTLE_MIN_S = 0.0
DC_SETTLE_MAX_S = 86400.0
DC_LIGHTNING_TIMEOUT_MIN_S = 0.1

DEFAULT_DC_CONFIG: dict[str, Any] = {
    "work_settle_s": 5.0,
    "acquisition_settle_s": 500.0,
    "detection_settle_s": 10000.0,
    "startup_settle_s": 1.0,
    "lightning_timeout_s": 1.0,
}

DEFAULT_SOUND_CONFIG: dict[str, Any] = {
    "enabled": False,
    "volume_percent": 100.0,
    "upper_frequency_hz": 4000.0,
    "lower_frequency_hz": 1000.0,
    "phase_upper_min_hz": 1000.0,
    "phase_upper_max_hz": 3000.0,
    "phase_lower_min_hz": 2000.0,
    "phase_lower_max_hz": 4000.0,
    "minimum_duration_ms": 150,
    "minimum_tone_cycles": 1,
    "test_enabled": False,
    "test_upper_enabled": False,
    "test_lower_enabled": False,
    "volume_scale": "ui_0_100_pwm_0_50",
}
DEFAULT_LCD_ROLE_OVERLAY: dict[str, Any] = {
    "enabled": False,
    "period_s": 4,
    "duration_s": 4,
}

try:
    _LED_PATTERN_MAX_RAW = int(os.getenv("BMI30_LED_PATTERN_MAX", "15"))
except Exception:
    _LED_PATTERN_MAX_RAW = 15
LED_PATTERN_MAX = max(0, min(255, _LED_PATTERN_MAX_RAW))
LED_PATTERN_VALUES: tuple[int, ...] = tuple(range(LED_PATTERN_MAX + 1))
GROUP_LED_PATTERN_EVENTS: tuple[tuple[str, str], ...] = (
    ("upper_detection", "Upper antenna detection"),
    ("lower_detection", "Lower antenna detection"),
    ("both_detection", "Both antennas detection"),
    ("neighbor_upper_detection", "Neighbor upper antenna detection"),
    ("neighbor_lower_detection", "Neighbor lower antenna detection"),
    ("neighbor_both_detection", "Neighbor both antennas detection"),
    ("fault", "Fault"),
)
DEFAULT_GROUP_LED_PATTERNS: dict[str, int] = {
    event_key: 0 for event_key, _event_label in GROUP_LED_PATTERN_EVENTS
}

DEFAULT_TAG_DETECTION_CONFIG: dict[str, Any] = {
    "enabled0": True,
    "enabled1": True,
    "confirm0": 2,
    "confirm1": 2,
    "confirm_phase_gate": 3,
    "threshold0": 2.0,
    "threshold1": 2.0,
    "threshold_high0": 5.0,
    "threshold_high1": 5.0,
    "ratio_noise_max_u16": 10.0,
    "auto_floor_u16": 10.0,
    "auto_slope": 5.0,
    "auto0": False,
    "auto1": False,
    "filter_amplitude0": True,
    "filter_amplitude1": True,
    "filter_shape0": True,
    "filter_shape1": True,
    "filter_phase0": True,
    "filter_phase1": True,
    "filter_noise_adapt0": True,
    "filter_noise_adapt1": True,
    "noise_window_s": 1.0,
    "noise_up0": 24,
    "noise_up1": 24,
    "noise_down0": 3,
    "noise_down1": 3,
    "noise_unit0": "adc",
    "noise_unit1": "adc",
    "burst_gate0": True,
    "burst_gate1": True,
    "burst_blank_s0": 0.08,
    "burst_blank_s1": 0.08,
    "burst_max_ratio0": 8.0,
    "burst_max_ratio1": 8.0,
    "smooth_mode": 0,
    "filter_casino": True,
    "filter_barkhausen": False,
    "filter_microwire": False,
    "filter_paper": False,
    "peak_index_min": 0,
    "peak_index_max": 199,
    "barkhausen_radius": 24,
    "barkhausen_frac": 0.22,
    "barkhausen_min_width": 4,
    "barkhausen_max_span": 140,
    "barkhausen_min_product_level": 800000,
    "barkhausen_max_product_level": 20000000,
    "barkhausen_max_total_fraction": 0.82,
    "barkhausen_all_quarter_frac": 0.45,
    "phase_max_shift": 12,
    "phase_shift_penalty": 0.02,
    "mark_window_start_frac": 0.05,
    "mark_window_end_frac": 0.45,
    "mark_gap": 21,
    "mark_gap_tol": 7,
    "mark_second_frac": 0.18,
    "mark_valley_frac": 0.70,
    "mark_multi_max_humps": 3,
    "locality_max_outside_peaks": 1,
    "locality_outside_peak_frac": 0.35,
}

BARKHAUSEN_TAG_KEYS: tuple[str, ...] = (
    "barkhausen_radius",
    "barkhausen_frac",
    "barkhausen_min_width",
    "barkhausen_max_span",
    "barkhausen_min_product_level",
    "barkhausen_max_product_level",
    "barkhausen_max_total_fraction",
    "barkhausen_all_quarter_frac",
)

CORE_TAG_DETECTION_KEYS: tuple[str, ...] = (
    "threshold_high0", "threshold_high1", "ratio_noise_max_u16", "auto_floor_u16", "auto_slope",
    "noise_window_s", "noise_up0", "noise_up1", "noise_down0", "noise_down1", "noise_unit0", "noise_unit1",
    "burst_gate0", "burst_gate1", "burst_blank_s0", "burst_blank_s1", "burst_max_ratio0", "burst_max_ratio1",
    "smooth_mode",
    "confirm_phase_gate",
    "filter_casino", "filter_barkhausen", "filter_microwire", "filter_paper",
    "peak_index_min", "peak_index_max",
    *BARKHAUSEN_TAG_KEYS,
    "phase_max_shift", "phase_shift_penalty",
    "mark_window_start_frac", "mark_window_end_frac",
    "mark_gap", "mark_gap_tol", "mark_second_frac", "mark_valley_frac", "mark_multi_max_humps",
    "locality_max_outside_peaks", "locality_outside_peak_frac",
)

# PDF документация
PDF_CACHE_DIR = pathlib.Path(os.getenv("BMI30_PDF_CACHE_DIR", "/var/cache/bmi30")).expanduser()
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
try:
    os.chmod(PDF_CACHE_DIR, 0o777)
except Exception:
    pass
PDF_UPDATE_INTERVAL_S = max(3600, int(os.getenv("BMI30_PDF_UPDATE_INTERVAL_S", str(24 * 3600))))  # 24 часа по умолчанию

PORTAL_DOCUMENTS: dict[str, dict[str, str]] = {
  "operation": {
    "title": "Operation Guide",
    "summary": "Daily startup, checks, and shutdown sequence for BMI30.",
    "filename": "BMI30_Operation_Guide.pdf",
    "google_doc_id": "171lmgMctV8HfeChDzagbyibgGt0PfuEm3h6Lj2V1djo",
  },
  "safety": {
    "title": "Safety and Service Notes",
    "summary": "Safety checklist and service handling recommendations.",
    "filename": "BMI30_Safety_and_Service_Notes.pdf",
    "google_doc_id": "1ifvh_uU8Vc-1ntcj0QViccQ5mQg9ujBqG8F5Ir_tw_E",
  },
  "network": {
    "title": "Network and Remote Access",
    "summary": "Hotspot, portal access, and remote support checklist.",
    "filename": "BMI30_Network_and_Remote_Access.pdf",
    "google_doc_id": "171lmgMctV8HfeChDzagbyibgGt0PfuEm3h6Lj2V1djo",
  },
}


def is_https_enabled() -> bool:
    return HTTPS_RUNTIME_ENABLED


def format_web_url(ip: str, scheme: str) -> str:
    port = HTTPS_PORT if scheme == "https" else PORT
    needs_port = (scheme == "https" and port != 443) or (scheme == "http" and port != 80)
    suffix = f":{port}" if needs_port else ""
    return f"{scheme}://{ip}{suffix}/"


def with_rev(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}v={PAGE_REV}"


def _fetch_google_doc_pdf_bytes(google_doc_id: str, timeout: int = 30) -> bytes | None:
    if not google_doc_id or not google_doc_id.strip():
        return None
    try:
        export_url = f"https://docs.google.com/document/d/{google_doc_id}/export?format=pdf"
        with urlopen(export_url, timeout=timeout) as response:
            pdf_data = response.read()
        if not pdf_data.startswith(b"%PDF"):
            return None
        return pdf_data
    except Exception:
        return None


def _read_cached_pdf(cache_path: pathlib.Path) -> bytes | None:
    try:
        if cache_path.exists():
            return cache_path.read_bytes()
    except Exception:
        return None
    return None


def download_google_doc_pdf(google_doc_id: str, cache_path: pathlib.Path) -> bool:
    """Скачивает PDF с Google Docs и сохраняет в кэш. Возвращает True если успешно."""
    pdf_data = _fetch_google_doc_pdf_bytes(google_doc_id, timeout=30)
    if pdf_data is None:
        return False
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(pdf_data)
        return True
    except Exception:
        return False


def get_pdf_data(doc_id: str, prefer_cache: bool = True) -> bytes | None:
    """Получает PDF данные. По умолчанию сразу отдает кэш, а сеть используется только при отсутствии кэша."""
    if not doc_id:
        return None

    cache_path = PDF_CACHE_DIR / f"{doc_id}.pdf"

    if prefer_cache:
        cached = _read_cached_pdf(cache_path)
        if cached is not None:
            return cached

    if download_google_doc_pdf(doc_id, cache_path):
        downloaded = _read_cached_pdf(cache_path)
        if downloaded is not None:
            return downloaded

    if not prefer_cache:
        return None

    fallback = _read_cached_pdf(cache_path)
    if fallback is not None:
        return fallback

    return None


def _load_machine_id() -> bytes:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "rb") as f:
                machine_id = f.read().strip()
            if machine_id:
                return machine_id
        except OSError:
            continue
    return b""


def _load_config_json_direct() -> dict[str, Any]:
    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def load_portal_auth_config() -> dict[str, str]:
    raw = _load_config_json_direct().get("portal_auth")
    source = raw if isinstance(raw, dict) else {}
    username = str(source.get("username") or PORTAL_USERNAME).strip() or PORTAL_USERNAME
    password_hash = str(source.get("password_hash") or "").strip()
    return {
        "username": username,
        "password_hash": password_hash,
    }


def load_engineer_auth_config() -> dict[str, Any]:
    raw = _load_config_json_direct().get("engineer_auth")
    source = raw if isinstance(raw, dict) else {}
    env_enabled = bool(PORTAL_ENGINEER_USERNAME and (PORTAL_ENGINEER_PASSWORD_HASH or PORTAL_ENGINEER_PASSWORD))
    username = str(source.get("username") or PORTAL_ENGINEER_USERNAME or DEFAULT_ENGINEER_USERNAME).strip() or DEFAULT_ENGINEER_USERNAME
    password_hash = str(source.get("password_hash") or PORTAL_ENGINEER_PASSWORD_HASH or "").strip()
    enabled = bool(source.get("enabled", env_enabled))
    return {
        "enabled": enabled,
        "username": username,
        "password_hash": password_hash,
        "env_password": PORTAL_ENGINEER_PASSWORD if PORTAL_ENGINEER_USERNAME and username == PORTAL_ENGINEER_USERNAME else "",
    }


def get_portal_username() -> str:
    return load_portal_auth_config()["username"]


def portal_auth_revision(role: str = "user") -> str:
    digest = hashlib.sha256()
    digest.update(b"bmi30-portal-auth-revision")
    if role == "engineer":
        auth = load_engineer_auth_config()
        digest.update(str(auth["enabled"]).encode("utf-8", errors="ignore"))
        digest.update(str(auth["username"]).encode("utf-8", errors="ignore"))
        digest.update(str(auth["password_hash"] or auth["env_password"]).encode("utf-8", errors="ignore"))
    else:
        auth = load_portal_auth_config()
        digest.update(auth["username"].encode("utf-8", errors="ignore"))
        digest.update((auth["password_hash"] or f"plain:{PORTAL_PASSWORD}").encode("utf-8", errors="ignore"))
    return digest.hexdigest()[:24]


def _build_portal_session_secret() -> bytes:
    configured_secret = os.getenv("BMI30_PORTAL_SESSION_SECRET", "").strip()
    if configured_secret:
        return configured_secret.encode("utf-8")

    digest = hashlib.sha256()
    digest.update(b"bmi30-portal-session")
    digest.update(_load_machine_id() or os.urandom(32))
    auth = load_portal_auth_config()
    digest.update(auth["username"].encode("utf-8", errors="ignore"))
    digest.update((auth["password_hash"] or PORTAL_PASSWORD).encode("utf-8", errors="ignore"))
    engineer_auth = load_engineer_auth_config()
    digest.update(str(engineer_auth["enabled"]).encode("utf-8", errors="ignore"))
    digest.update(str(engineer_auth["username"]).encode("utf-8", errors="ignore"))
    digest.update(str(engineer_auth["password_hash"] or engineer_auth["env_password"]).encode("utf-8", errors="ignore"))
    return digest.digest()


PORTAL_SESSION_SECRET = _build_portal_session_secret()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _format_cookie_expires(expires_at: int) -> str:
    return dt.datetime.fromtimestamp(expires_at, tz=dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_portal_password(password: str, *, salt: bytes | None = None, iterations: int = PORTAL_PASSWORD_HASH_ITERATIONS) -> str:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_portal_password_hash(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_s, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iteration_s)
        if iterations < 100_000:
            return False
        salt = _b64url_decode(salt_b64)
        expected_digest = _b64url_decode(digest_b64)
    except Exception:
        return False

    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(candidate_digest, expected_digest)


def verify_portal_user_password(username: str, password: str) -> bool:
    auth = load_portal_auth_config()
    if not constant_time_equals(username, auth["username"]):
        return False
    if auth["password_hash"]:
        return verify_portal_password_hash(password, auth["password_hash"])
    return constant_time_equals(password, PORTAL_PASSWORD)


def verify_engineer_password(username: str, password: str) -> bool:
    auth = load_engineer_auth_config()
    if not auth["enabled"] or not constant_time_equals(username, str(auth["username"])):
        return False
    if auth["password_hash"]:
        return verify_portal_password_hash(password, str(auth["password_hash"]))
    if auth["env_password"]:
        return constant_time_equals(password, str(auth["env_password"]))
    return False


def is_engineer_account_enabled() -> bool:
    auth = load_engineer_auth_config()
    return bool(auth["enabled"] and (auth["password_hash"] or auth["env_password"]))


def authenticate_portal_credentials(username: str, password: str) -> dict[str, str] | None:
    if verify_portal_user_password(username, password):
        return {"username": get_portal_username(), "role": "user"}

    if verify_engineer_password(username, password):
        return {"username": str(load_engineer_auth_config()["username"]), "role": "engineer"}

    return None


def create_portal_session_token(username: str, expires_at: int, role: str = "user") -> str:
    payload = json.dumps(
        {"u": username, "exp": expires_at, "r": role, "v": portal_auth_revision(role)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload)
    signature = hmac.new(PORTAL_SESSION_SECRET, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def parse_portal_session_token(token: str) -> dict[str, Any] | None:
    if not token or len(token) > 1024 or "." not in token:
        return None

    payload_b64, signature = token.rsplit(".", 1)
    expected_signature = hmac.new(PORTAL_SESSION_SECRET, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        username = str(payload.get("u", ""))
        expires_at = int(payload.get("exp", 0))
        role = str(payload.get("r", "user"))
        revision = str(payload.get("v", ""))
    except (TypeError, ValueError):
        return None

    if role == "user":
        expected_username = get_portal_username()
    elif role == "engineer" and is_engineer_account_enabled():
        expected_username = str(load_engineer_auth_config()["username"])
    else:
        return None

    if username != expected_username or expires_at <= 0:
        return None
    if revision != portal_auth_revision(role):
        return None

    return {"u": username, "exp": expires_at, "r": role}


def build_portal_session_cookie(token: str, *, remember: bool, secure: bool) -> str:
    jar = SimpleCookie()
    jar[PORTAL_SESSION_COOKIE] = token
    morsel = jar[PORTAL_SESSION_COOKIE]
    morsel["path"] = "/"
    morsel["httponly"] = True
    morsel["samesite"] = "Lax"
    if secure:
        morsel["secure"] = True
    if remember:
        expires_at = int(time.time()) + PORTAL_SESSION_TTL_S
        morsel["max-age"] = str(PORTAL_SESSION_TTL_S)
        morsel["expires"] = _format_cookie_expires(expires_at)
    return morsel.OutputString()


def build_expired_portal_session_cookie(*, secure: bool) -> str:
    jar = SimpleCookie()
    jar[PORTAL_SESSION_COOKIE] = ""
    morsel = jar[PORTAL_SESSION_COOKIE]
    morsel["path"] = "/"
    morsel["httponly"] = True
    morsel["samesite"] = "Lax"
    if secure:
        morsel["secure"] = True
    morsel["max-age"] = "0"
    morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    return morsel.OutputString()


def run_command(*args: str) -> str:
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _read_first_text(paths: tuple[str, ...]) -> str:
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                value = f.read().replace("\x00", "").strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def detect_rpi_identity() -> dict[str, str]:
    info = {"serial": "", "model": "", "revision": "", "software_version": ""}
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                if ":" not in raw_line:
                    continue
                key, value = raw_line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "serial" and value:
                    info["serial"] = value
                elif key == "model" and value:
                    info["model"] = value
                elif key == "revision" and value:
                    info["revision"] = value
    except Exception:
        pass
    if not info["model"]:
        info["model"] = _read_first_text((
            "/sys/firmware/devicetree/base/model",
            "/proc/device-tree/model",
        ))
    info["software_version"] = detect_rpi_software_version()
    return info


def _read_key_value_file(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                try:
                    parsed = shlex.split(value, comments=False, posix=True)
                    value = parsed[0] if len(parsed) == 1 else value.strip("'\"")
                except ValueError:
                    value = value.strip("'\"")
                data[key.strip()] = value
    except Exception:
        pass
    return data


def detect_bmi30_firmware_release() -> dict[str, Any]:
    manifest_path = ""
    data: dict[str, str] = {}
    for candidate in (
        os.getenv("BMI30_FIRMWARE_MANIFEST", "").strip(),
        "/home/techaid/Documents/host/bmi30_firmware_release.env",
        os.path.join(os.path.dirname(__file__), "host", "bmi30_firmware_release.env"),
        "/usr/local/bin/host/bmi30_firmware_release.env",
    ):
        if not candidate:
            continue
        candidate_data = _read_key_value_file(candidate)
        if candidate_data.get("BMI30_FIRMWARE_VERSION"):
            manifest_path = candidate
            data = candidate_data
            break

    version = data.get("BMI30_FIRMWARE_VERSION", "").strip()
    label = data.get("BMI30_FIRMWARE_LABEL", "").strip() or version
    expected_portal_hash = data.get("BMI30_FIRMWARE_PORTAL_SHA256", "").strip().lower()
    runtime_portal_hash = PORTAL_RUNTIME_SHA256.lower()
    portal_matches = bool(expected_portal_hash and runtime_portal_hash == expected_portal_hash)

    return {
        "version": version,
        "label": label,
        "created_at": data.get("BMI30_FIRMWARE_CREATED_AT", "").strip(),
        "content_signature": data.get("BMI30_FIRMWARE_CONTENT_SIGNATURE", "").strip(),
        "signature_version": data.get("BMI30_FIRMWARE_SIGNATURE_VERSION", "").strip(),
        "core_path": data.get("BMI30_FIRMWARE_CORE_PATH", "").strip(),
        "engine_path": data.get("BMI30_FIRMWARE_ENGINE_PATH", "").strip(),
        "gui_path": data.get("BMI30_FIRMWARE_GUI_PATH", "").strip(),
        "portal_path": data.get("BMI30_FIRMWARE_PORTAL_PATH", "").strip(),
        "portal_sha256": expected_portal_hash,
        "runtime_portal_sha256": runtime_portal_hash,
        "portal_matches_release": portal_matches,
        "manifest_path": manifest_path,
    }


def format_firmware_version_with_date(release: dict[str, Any]) -> str:
    """Return the dated release ID for compact FW displays, not its prose label."""
    version = str(release.get("version") or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2}-\d{4})(?:[-_.]|$)", version)
    if match:
        return match.group(1)
    return version or str(release.get("label") or "").strip()


def _format_active_app_version(path: str) -> str:
    name = os.path.basename(str(path or "").strip())
    if not name:
        return ""
    match = re.match(r"^(BMI30\.\d+)\.py\.(\d{4}-\d{2}-\d{2})(?:-(.+))?$", name)
    if match:
        suffix = (match.group(3) or "").strip()
        return " ".join(part for part in (match.group(1), match.group(2), suffix) if part)
    if name.startswith("BMI30."):
        name = name[:-3] if name.endswith(".py") else name
        name = name.replace(".py.", " ")
        name = name.replace(".py", "")
    return " ".join(name.split())


def _natural_version_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _unique_existing_text_paths(paths: tuple[str, ...]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = str(raw_path or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _bmi30_project_roots() -> tuple[str, ...]:
    script_dir = os.path.abspath(os.path.dirname(__file__))
    return (
        "/home/techaid/Documents",
        script_dir,
        os.path.dirname(script_dir),
    )


def _resolve_project_path(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    for root in _bmi30_project_roots():
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_bmi30_project_roots()[0], path)


def _split_active_env_candidates() -> list[str]:
    return _unique_existing_text_paths((
        os.getenv("BMI30_SPLIT_ACTIVE_ENV", ""),
        "/home/techaid/Documents/host/bmi30_split_active_version.env",
        os.path.join(os.path.dirname(__file__), "host", "bmi30_split_active_version.env"),
        "/usr/local/bin/host/bmi30_split_active_version.env",
    ))


def _find_latest_split_core_path() -> str:
    candidates: list[pathlib.Path] = []
    for root in _bmi30_project_roots():
        host_dir = pathlib.Path(root) / "host"
        if not host_dir.is_dir():
            continue
        candidates.extend(path for path in host_dir.glob("BMI30.001.py.*") if path.is_file())
    if not candidates:
        return ""
    latest = sorted(candidates, key=lambda path: _natural_version_key(path.name))[-1]
    try:
        return str(latest.relative_to(pathlib.Path("/home/techaid/Documents")))
    except ValueError:
        return str(latest)


def _split_version_from_core_path(path: str) -> str:
    name = os.path.basename(str(path or "").strip())
    resolved_path = _resolve_project_path(path)
    date_part = ""
    time_part = ""

    match = re.search(r"(\d{4}-\d{2}-\d{2})-([0-9]{2})([0-9]{2})", name)
    if match:
        date_part = match.group(1)
        time_part = f"{match.group(2)}{match.group(3)}"
    else:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        if match:
            date_part = match.group(1)

    if not time_part and os.path.exists(resolved_path):
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(resolved_path))
            if not date_part:
                date_part = mtime.strftime("%Y-%m-%d")
            time_part = mtime.strftime("%H%M")
        except Exception:
            pass

    if date_part and time_part:
        return f"{date_part}-{time_part}"
    if date_part:
        return date_part
    return name


def _format_split_system_label(version: str, core_path: str = "") -> str:
    version = str(version or "").strip()
    if not version:
        version = _split_version_from_core_path(core_path)
    if not version:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})-([0-9]{2})([0-9]{2})$", version)
    if match:
        return f"{match.group(1)} {match.group(2)}:{match.group(3)}"
    return version


def detect_bmi30_split_system_version() -> dict[str, str]:
    env_path = ""
    data: dict[str, str] = {}
    for candidate in _split_active_env_candidates():
        candidate_data = _read_key_value_file(candidate)
        if candidate_data:
            env_path = candidate
            data = candidate_data
            break

    version = os.getenv("BMI30_SPLIT_VERSION", "").strip() or data.get("BMI30_SPLIT_VERSION", "").strip()
    label = os.getenv("BMI30_SPLIT_LABEL", "").strip() or data.get("BMI30_SPLIT_LABEL", "").strip()
    selected_by = os.getenv("BMI30_SPLIT_SELECTED_BY", "").strip() or data.get("BMI30_SPLIT_SELECTED_BY", "").strip()
    selected_at = os.getenv("BMI30_SPLIT_SELECTED_AT", "").strip() or data.get("BMI30_SPLIT_SELECTED_AT", "").strip()
    core_path = os.getenv("BMI30_CORE_PATH", "").strip() or data.get("BMI30_CORE_PATH", "").strip()
    gui_path = os.getenv("BMI30_GUI_PATH", "").strip() or data.get("BMI30_GUI_PATH", "").strip()
    portal_path = os.getenv("BMI30_PORTAL_PATH", "").strip() or data.get("BMI30_PORTAL_PATH", "").strip()
    service_url = os.getenv("BMI30_SERVICE_URL", "").strip() or data.get("BMI30_SERVICE_URL", "").strip() or CORE_SERVICE_URL

    source = selected_by or ("env" if env_path else "")
    if core_path and not os.path.exists(_resolve_project_path(core_path)):
        source = "auto-latest-fallback"
        core_path = ""

    if not core_path:
        latest_core = _find_latest_split_core_path()
        if latest_core:
            core_path = latest_core
            source = source or "auto-latest-fallback"

    if not version:
        version = _split_version_from_core_path(core_path)
    if not label:
        label = _format_split_system_label(version, core_path)
    if not source:
        source = "unknown"

    return {
        "version": version or "",
        "label": label or "",
        "selected_by": selected_by or source,
        "selected_at": selected_at or "",
        "source": source,
        "core_path": core_path or "",
        "gui_path": gui_path or "",
        "portal_path": portal_path or "",
        "service_url": service_url,
        "active_env": env_path,
    }


def detect_rpi_software_version() -> str:
    for env_name in ("BMI30_RPI_FW_VERSION", "BMI30_RPI_SOFTWARE_VERSION", "BMI30_HOST_FW_VERSION"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value

    firmware_release = detect_bmi30_firmware_release()
    release_version = format_firmware_version_with_date(firmware_release)
    if release_version:
        return release_version

    value = _read_first_text((
        "/etc/bmi30/rpi_fw_version",
        "/etc/bmi30/rpi_software_version",
        "/etc/bmi30/version",
        "/usr/local/share/bmi30/version",
        "/home/techaid/Documents/host/VERSION",
        "/home/techaid/Documents/VERSION",
    ))
    if value:
        return value.splitlines()[0].strip()

    split_version = detect_bmi30_split_system_version().get("label", "").strip()
    if split_version:
        return split_version

    app_path = os.getenv("BMI30_APP_PATH", "").strip()
    if not app_path:
        for env_path in (
            "/home/techaid/Documents/host/bmi30_active_version.env",
            "/usr/local/bin/host/bmi30_active_version.env",
            os.path.join(os.path.dirname(__file__), "host", "bmi30_active_version.env"),
        ):
            data = _read_key_value_file(env_path)
            app_path = data.get("BMI30_APP_PATH", "").strip()
            if app_path:
                break
    version = _format_active_app_version(app_path)
    if version:
        return version

    os_release = _read_key_value_file("/etc/os-release")
    return os_release.get("PRETTY_NAME", "").strip()


def format_rpi_identity(info: dict[str, str]) -> str:
    serial = str(info.get("serial") or "").strip() or "---"
    version = str(info.get("software_version") or "").strip() or "---"
    return f"{serial} / FW {version}"



def _now_monotonic() -> float:
    return time.monotonic()


def remember_portal_client(address: str) -> None:
    address = (address or "").strip()
    if not address:
        return
    now = _now_monotonic()
    _PORTAL_CLIENTS[address] = now
    for key, seen_at in list(_PORTAL_CLIENTS.items()):
        if now - seen_at > PORTAL_CLIENT_TTL_S:
            _PORTAL_CLIENTS.pop(key, None)


def count_portal_clients() -> int:
    now = _now_monotonic()
    for key, seen_at in list(_PORTAL_CLIENTS.items()):
        if now - seen_at > PORTAL_CLIENT_TTL_S:
            _PORTAL_CLIENTS.pop(key, None)
    return len(_PORTAL_CLIENTS)


def _load_config_json() -> dict[str, Any]:
    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_config_json(payload: dict[str, Any]) -> None:
    directory = os.path.dirname(CONFIG_JSON) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{CONFIG_JSON}.tmp"
    try:
        previous_stat = os.stat(CONFIG_JSON)
    except Exception:
        previous_stat = None
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    if previous_stat is not None:
        try:
            runtime_gid = os.stat("/home/techaid/Documents").st_gid
            os.chown(tmp_path, previous_stat.st_uid, runtime_gid)
        except Exception:
            pass
    try:
        os.chmod(tmp_path, 0o640)
    except Exception:
        pass
    os.replace(tmp_path, CONFIG_JSON)


def _float_form_value(form: dict[str, str], key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(form.get(key, default)).strip())
    except Exception:
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


def _normalize_avg_n(value: Any, default: int = DEFAULT_AVG_N) -> int:
    try:
        avg_n = int(value)
    except Exception:
        avg_n = int(default)
    if avg_n in AVG_N_VALUES:
        return avg_n
    return int(default) if int(default) in AVG_N_VALUES else DEFAULT_AVG_N


def load_default_avg_n() -> int:
    payload = _load_config_json()
    operation = payload.get("operation")
    operation_avg = operation.get("avg_n") if isinstance(operation, dict) else None
    return _normalize_avg_n(payload.get("avg_n", operation_avg), DEFAULT_AVG_N)


def save_default_avg_n(avg_n: int) -> None:
    avg_n = _normalize_avg_n(avg_n, DEFAULT_AVG_N)
    payload = _load_config_json()
    payload["avg_n"] = avg_n
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        operation = {}
    operation["avg_n"] = avg_n
    operation["updated_at"] = int(time.time())
    payload["operation"] = operation
    _save_config_json(payload)


def avg_n_from_form(form: dict[str, str]) -> int:
    return _normalize_avg_n(form.get("avg_n"), load_default_avg_n())


def _int_form_value(form: dict[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(form.get(key, default)).strip())
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


def _bool_form_value(form: dict[str, str], key: str, default: bool = False) -> bool:
    raw = form.get(key, "1" if default else "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _normalize_sound_config(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_SOUND_CONFIG)
    cfg.update({k: source.get(k, v) for k, v in DEFAULT_SOUND_CONFIG.items()})
    cfg["enabled"] = bool(cfg.get("enabled", False))
    cfg["volume_percent"] = round(_float_form_value(cfg, "volume_percent", 100.0, 0.0, 100.0), 1)
    cfg["upper_frequency_hz"] = round(_float_form_value(cfg, "upper_frequency_hz", 4000.0, 1.0, 20000.0), 1)
    cfg["lower_frequency_hz"] = round(_float_form_value(cfg, "lower_frequency_hz", 1000.0, 1.0, 20000.0), 1)
    cfg["phase_upper_min_hz"] = round(_float_form_value(cfg, "phase_upper_min_hz", 1000.0, 1.0, 20000.0), 1)
    cfg["phase_upper_max_hz"] = round(_float_form_value(cfg, "phase_upper_max_hz", 3000.0, 1.0, 20000.0), 1)
    cfg["phase_lower_min_hz"] = round(_float_form_value(cfg, "phase_lower_min_hz", 2000.0, 1.0, 20000.0), 1)
    cfg["phase_lower_max_hz"] = round(_float_form_value(cfg, "phase_lower_max_hz", 4000.0, 1.0, 20000.0), 1)
    cfg["minimum_duration_ms"] = _int_form_value(cfg, "minimum_duration_ms", 150, 0, 60000)
    cfg["minimum_tone_cycles"] = _int_form_value(cfg, "minimum_tone_cycles", 1, 1, 1000)
    if cfg["phase_upper_max_hz"] < cfg["phase_upper_min_hz"]:
        cfg["phase_upper_min_hz"], cfg["phase_upper_max_hz"] = cfg["phase_upper_max_hz"], cfg["phase_upper_min_hz"]
    if cfg["phase_lower_max_hz"] < cfg["phase_lower_min_hz"]:
        cfg["phase_lower_min_hz"], cfg["phase_lower_max_hz"] = cfg["phase_lower_max_hz"], cfg["phase_lower_min_hz"]
    legacy_test = bool(source.get("test_enabled", cfg.get("test_enabled", False)))
    cfg["test_upper_enabled"] = bool(source.get("test_upper_enabled", legacy_test))
    cfg["test_lower_enabled"] = bool(source.get("test_lower_enabled", legacy_test))
    if cfg["test_upper_enabled"] and cfg["test_lower_enabled"]:
        cfg["test_lower_enabled"] = False
    cfg["test_enabled"] = bool(cfg["test_upper_enabled"] or cfg["test_lower_enabled"])
    cfg["volume_scale"] = "ui_0_100_pwm_0_50"
    return cfg


def _normalize_lcd_role_overlay(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    def seconds(key: str) -> int:
        try:
            value = int(source.get(key, 4))
        except Exception:
            value = 4
        return max(1, min(5, value))
    return {
        "enabled": _bool_form_value({"enabled": str(source.get("enabled", "0"))}, "enabled", False),
        "period_s": seconds("period_s"),
        "duration_s": seconds("duration_s"),
    }


def load_lcd_role_overlay() -> dict[str, Any]:
    payload = _load_config_json()
    return _normalize_lcd_role_overlay(payload.get("lcd_role_overlay"))


def save_lcd_role_overlay(cfg: dict[str, Any]) -> None:
    payload = _load_config_json()
    payload["lcd_role_overlay"] = _normalize_lcd_role_overlay(cfg)
    payload["lcd_role_overlay_updated_at"] = int(time.time())
    _save_config_json(payload)


def lcd_role_overlay_from_form(form: dict[str, str]) -> dict[str, Any]:
    return _normalize_lcd_role_overlay({
        "enabled": _bool_form_value(form, "lcd_role_overlay_enabled", False),
        "period_s": form.get("lcd_role_overlay_period_s", 4),
        "duration_s": form.get("lcd_role_overlay_duration_s", 4),
    })


def apply_lcd_role_overlay_to_core(cfg: dict[str, Any], persist: bool = True) -> tuple[bool, str, dict[str, Any]]:
    cfg = _normalize_lcd_role_overlay(cfg)
    payload = {"action": "lcd_role_overlay", "params": dict(cfg, persist=bool(persist))}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_lcd_role_overlay"},
            method="POST",
        )
        with urlopen(req, timeout=3.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}", dict(cfg, applied=False, pending=True)
    actual = result.get("lcd_role_overlay") if isinstance(result, dict) else None
    if not isinstance(actual, dict):
        actual = dict(cfg, applied=False, pending=True)
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str(result.get("error") or "BMI30 core rejected LCD role overlay"), actual
    return True, "LCD role overlay sent to BMI30 core service", actual


def load_sound_config_from_core() -> dict[str, Any] | None:
    try:
        with urlopen(f"{CORE_SERVICE_URL}/api/status", timeout=0.5) as response:
            status = json.loads(response.read().decode("utf-8") or "{}")
        sound = (status or {}).get("sound")
        if not isinstance(sound, dict):
            return None
        return _normalize_sound_config(sound)
    except Exception:
        return None


def load_sound_config() -> dict[str, Any]:
    payload = _load_config_json()
    raw = payload.get("sound_settings")
    if not isinstance(raw, dict):
        raw = payload.get("sound")
    source = raw if isinstance(raw, dict) else {}
    if "sound_enabled" in payload and "enabled" not in source:
        source = dict(source)
        source["enabled"] = payload.get("sound_enabled")
    if source and source.get("volume_scale") != "ui_0_100_pwm_0_50" and "volume_percent" in source:
        try:
            source = dict(source)
            source["volume_percent"] = min(100.0, max(0.0, float(source.get("volume_percent", 50.0)) * 2.0))
        except Exception:
            pass
    cfg = _normalize_sound_config(source)
    core_cfg = load_sound_config_from_core()
    if core_cfg is not None:
        if not source:
            cfg = core_cfg
        else:
            cfg["test_enabled"] = bool(core_cfg.get("test_enabled", False))
            cfg["test_upper_enabled"] = bool(core_cfg.get("test_upper_enabled", False))
            cfg["test_lower_enabled"] = bool(core_cfg.get("test_lower_enabled", False))
    return _normalize_sound_config(cfg)


def save_sound_config(cfg: dict[str, Any]) -> None:
    payload = _load_config_json()
    saved = _normalize_sound_config(cfg)
    saved["test_enabled"] = False
    saved["test_upper_enabled"] = False
    saved["test_lower_enabled"] = False
    payload["sound_enabled"] = bool(saved["enabled"])
    payload["sound_settings"] = saved
    payload["sound_settings_updated_at"] = int(time.time())
    _save_config_json(payload)


def sound_config_from_form(form: dict[str, str]) -> dict[str, Any]:
    return _normalize_sound_config({
        "enabled": _bool_form_value(form, "sound_enabled", False),
        "volume_percent": _float_form_value(form, "sound_volume_percent", 100.0, 0.0, 100.0),
        "upper_frequency_hz": _float_form_value(form, "sound_upper_frequency_hz", 4000.0, 1.0, 20000.0),
        "lower_frequency_hz": _float_form_value(form, "sound_lower_frequency_hz", 1000.0, 1.0, 20000.0),
        "phase_upper_min_hz": _float_form_value(form, "sound_phase_upper_min_hz", 1000.0, 1.0, 20000.0),
        "phase_upper_max_hz": _float_form_value(form, "sound_phase_upper_max_hz", 3000.0, 1.0, 20000.0),
        "phase_lower_min_hz": _float_form_value(form, "sound_phase_lower_min_hz", 2000.0, 1.0, 20000.0),
        "phase_lower_max_hz": _float_form_value(form, "sound_phase_lower_max_hz", 4000.0, 1.0, 20000.0),
        "minimum_duration_ms": _int_form_value(form, "sound_minimum_duration_ms", 150, 0, 60000),
        "minimum_tone_cycles": _int_form_value(form, "sound_minimum_tone_cycles", 1, 1, 1000),
        "test_upper_enabled": _bool_form_value(form, "sound_test_upper_enabled", False),
        "test_lower_enabled": _bool_form_value(form, "sound_test_lower_enabled", False),
    })


def apply_sound_config_to_core(cfg: dict[str, Any], persist: bool = True) -> tuple[bool, str]:
    cfg = _normalize_sound_config(cfg)
    payload = {
        "action": "sound_settings",
        "params": {
            "enabled": bool(cfg["enabled"]),
            "volume_percent": float(cfg["volume_percent"]),
            "upper_frequency_hz": float(cfg["upper_frequency_hz"]),
            "lower_frequency_hz": float(cfg["lower_frequency_hz"]),
            "phase_upper_min_hz": float(cfg["phase_upper_min_hz"]),
            "phase_upper_max_hz": float(cfg["phase_upper_max_hz"]),
            "phase_lower_min_hz": float(cfg["phase_lower_min_hz"]),
            "phase_lower_max_hz": float(cfg["phase_lower_max_hz"]),
            "minimum_duration_ms": int(cfg["minimum_duration_ms"]),
            "minimum_tone_cycles": int(cfg["minimum_tone_cycles"]),
            "test_enabled": bool(cfg["test_enabled"]),
            "test_upper_enabled": bool(cfg["test_upper_enabled"]),
            "test_lower_enabled": bool(cfg["test_lower_enabled"]),
            "volume_scale": "ui_0_100_pwm_0_50",
            "persist": bool(persist),
        },
    }
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_sound_settings"},
            method="POST",
        )
        with urlopen(req, timeout=3.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str(result.get("error") or "BMI30 core service rejected sound settings")
    return True, "Sound settings sent to BMI30 core service"


def _noise_unit_value(value: Any, default: str = "adc") -> str:
    try:
        unit = str(value or default).strip().lower()
    except Exception:
        unit = str(default or "adc")
    if unit in {"percent", "pct", "%"}:
        return "percent"
    return "adc"


def _normalize_tag_detection_config(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_TAG_DETECTION_CONFIG)
    cfg.update({k: source.get(k, v) for k, v in DEFAULT_TAG_DETECTION_CONFIG.items()})
    cfg["enabled0"] = bool(cfg.get("enabled0", True))
    cfg["enabled1"] = bool(cfg.get("enabled1", True))
    cfg["confirm0"] = _int_form_value(cfg, "confirm0", 2, 1, 6)
    cfg["confirm1"] = _int_form_value(cfg, "confirm1", 2, 1, 6)
    cfg["confirm_phase_gate"] = _int_form_value(cfg, "confirm_phase_gate", 3, 0, 199)
    cfg["threshold0"] = round(_float_form_value(cfg, "threshold0", 2.0, 1.0, 100.0), 1)
    cfg["threshold1"] = round(_float_form_value(cfg, "threshold1", 2.0, 1.0, 100.0), 1)
    cfg["threshold_high0"] = round(_float_form_value(cfg, "threshold_high0", 5.0, 1.0, 100.0), 1)
    cfg["threshold_high1"] = round(_float_form_value(cfg, "threshold_high1", 5.0, 1.0, 100.0), 1)
    cfg["ratio_noise_max_u16"] = round(_float_form_value(cfg, "ratio_noise_max_u16", 10.0, 0.1, 65535.0), 3)
    cfg["auto_floor_u16"] = round(_float_form_value(cfg, "auto_floor_u16", 10.0, 0.0, 65535.0), 3)
    cfg["auto_slope"] = round(_float_form_value(cfg, "auto_slope", 5.0, 0.1, 100.0), 3)
    cfg["auto0"] = bool(cfg.get("auto0", False))
    cfg["auto1"] = bool(cfg.get("auto1", False))
    cfg["filter_amplitude0"] = bool(cfg.get("filter_amplitude0", True))
    cfg["filter_amplitude1"] = bool(cfg.get("filter_amplitude1", True))
    cfg["filter_shape0"] = bool(cfg.get("filter_shape0", True))
    cfg["filter_shape1"] = bool(cfg.get("filter_shape1", True))
    cfg["filter_phase0"] = bool(cfg.get("filter_phase0", True))
    cfg["filter_phase1"] = bool(cfg.get("filter_phase1", True))
    cfg["filter_noise_adapt0"] = bool(cfg.get("filter_noise_adapt0", True))
    cfg["filter_noise_adapt1"] = bool(cfg.get("filter_noise_adapt1", True))
    cfg["noise_window_s"] = round(_float_form_value(cfg, "noise_window_s", 1.0, 0.05, 10.0), 3)
    cfg["noise_up0"] = _int_form_value(cfg, "noise_up0", 24, 1, 65535)
    cfg["noise_up1"] = _int_form_value(cfg, "noise_up1", 24, 1, 65535)
    cfg["noise_down0"] = _int_form_value(cfg, "noise_down0", 3, 1, 65535)
    cfg["noise_down1"] = _int_form_value(cfg, "noise_down1", 3, 1, 65535)
    cfg["noise_unit0"] = _noise_unit_value(cfg.get("noise_unit0", "adc"), "adc")
    cfg["noise_unit1"] = _noise_unit_value(cfg.get("noise_unit1", "adc"), "adc")
    cfg["burst_gate0"] = _bool_form_value(cfg, "burst_gate0", True)
    cfg["burst_gate1"] = _bool_form_value(cfg, "burst_gate1", True)
    cfg["burst_blank_s0"] = round(_float_form_value(cfg, "burst_blank_s0", 0.08, 0.0, 1.0), 3)
    cfg["burst_blank_s1"] = round(_float_form_value(cfg, "burst_blank_s1", 0.08, 0.0, 1.0), 3)
    cfg["burst_max_ratio0"] = round(_float_form_value(cfg, "burst_max_ratio0", 8.0, 0.0, 100.0), 1)
    cfg["burst_max_ratio1"] = round(_float_form_value(cfg, "burst_max_ratio1", 8.0, 0.0, 100.0), 1)
    cfg["smooth_mode"] = _int_form_value(cfg, "smooth_mode", 0, 0, 5)
    cfg["filter_casino"] = bool(cfg.get("filter_casino", True))
    cfg["filter_barkhausen"] = bool(cfg.get("filter_barkhausen", False))
    cfg["filter_microwire"] = bool(cfg.get("filter_microwire", False))
    cfg["filter_paper"] = bool(cfg.get("filter_paper", False))
    if "peak_index_min" not in source and "peak_index_max" not in source:
        legacy_enabled = _bool_form_value(source, "peak_thirds_limit_enabled", False)
        legacy_type = str(source.get("peak_thirds_limit_type", "microwire") or "microwire").strip().lower()
        legacy_barkhausen = legacy_type in {"barkhausen", "bark", "b"}
        cfg["peak_index_min"] = 67 if legacy_enabled and legacy_barkhausen else 0
        cfg["peak_index_max"] = 66 if legacy_enabled and not legacy_barkhausen else 199
    cfg["peak_index_min"] = _int_form_value(cfg, "peak_index_min", 0, 0, 199)
    cfg["peak_index_max"] = _int_form_value(cfg, "peak_index_max", 199, 0, 199)
    if cfg["peak_index_max"] < cfg["peak_index_min"]:
        cfg["peak_index_max"] = cfg["peak_index_min"]
    cfg["barkhausen_radius"] = _int_form_value(cfg, "barkhausen_radius", 24, 1, 120)
    cfg["barkhausen_frac"] = round(_float_form_value(cfg, "barkhausen_frac", 0.22, 0.01, 1.0), 3)
    cfg["barkhausen_min_width"] = _int_form_value(cfg, "barkhausen_min_width", 4, 1, 120)
    cfg["barkhausen_max_span"] = _int_form_value(cfg, "barkhausen_max_span", 140, 1, 200)
    cfg["barkhausen_min_product_level"] = _int_form_value(cfg, "barkhausen_min_product_level", 800000, 0, 2147483647)
    cfg["barkhausen_max_product_level"] = _int_form_value(cfg, "barkhausen_max_product_level", 20000000, 0, 2147483647)
    if cfg["barkhausen_max_product_level"] and cfg["barkhausen_max_product_level"] < cfg["barkhausen_min_product_level"]:
        cfg["barkhausen_max_product_level"] = cfg["barkhausen_min_product_level"]
    cfg["barkhausen_max_total_fraction"] = round(_float_form_value(cfg, "barkhausen_max_total_fraction", 0.82, 0.01, 1.0), 3)
    cfg["barkhausen_all_quarter_frac"] = round(_float_form_value(cfg, "barkhausen_all_quarter_frac", 0.45, 0.01, 1.0), 3)
    cfg["phase_max_shift"] = _int_form_value(cfg, "phase_max_shift", 12, 0, 80)
    cfg["phase_shift_penalty"] = round(_float_form_value(cfg, "phase_shift_penalty", 0.02, 0.0, 1.0), 4)
    cfg["mark_window_start_frac"] = round(_float_form_value(cfg, "mark_window_start_frac", 0.05, 0.0, 0.95), 4)
    mark_window_end_default = 0.95 if cfg["filter_barkhausen"] else 0.45
    cfg["mark_window_end_frac"] = round(_float_form_value(cfg, "mark_window_end_frac", mark_window_end_default, 0.01, 1.0), 4)
    if cfg["filter_barkhausen"] and cfg["mark_window_end_frac"] < 0.90:
        cfg["mark_window_end_frac"] = 0.95
    if cfg["mark_window_end_frac"] <= cfg["mark_window_start_frac"]:
        cfg["mark_window_end_frac"] = min(1.0, round(float(cfg["mark_window_start_frac"]) + 0.01, 4))
    cfg["mark_gap"] = _int_form_value(cfg, "mark_gap", 21, 1, 160)
    cfg["mark_gap_tol"] = _int_form_value(cfg, "mark_gap_tol", 7, 0, 80)
    cfg["mark_second_frac"] = round(_float_form_value(cfg, "mark_second_frac", 0.18, 0.01, 1.0), 3)
    cfg["mark_valley_frac"] = round(_float_form_value(cfg, "mark_valley_frac", 0.70, 0.01, 0.99), 3)
    cfg["mark_multi_max_humps"] = _int_form_value(cfg, "mark_multi_max_humps", 3, 1, 12)
    cfg["locality_max_outside_peaks"] = _int_form_value(cfg, "locality_max_outside_peaks", 1, 0, 20)
    cfg["locality_outside_peak_frac"] = round(_float_form_value(cfg, "locality_outside_peak_frac", 0.35, 0.01, 1.0), 3)
    return cfg


def load_tag_detection_config() -> dict[str, Any]:
    payload = _load_config_json()
    raw = payload.get("tag_detection")
    source = raw if isinstance(raw, dict) else payload
    cfg = _normalize_tag_detection_config(source)
    if "smooth_mode" not in source and "smooth_mode" in payload:
        cfg["smooth_mode"] = _int_form_value(payload, "smooth_mode", 0, 0, 5)
    core_backfill_keys = CORE_TAG_DETECTION_KEYS
    missing_core = any(key not in source for key in core_backfill_keys)
    if missing_core:
        core_cfg = load_tag_detection_config_from_core()
        if core_cfg is not None:
            for key in core_backfill_keys:
                if key not in source and key in core_cfg:
                    cfg[key] = core_cfg[key]
    return _normalize_tag_detection_config(cfg)


def save_tag_detection_config(cfg: dict[str, Any]) -> None:
    payload = _load_config_json()
    payload["tag_detection"] = _normalize_tag_detection_config(cfg)
    payload["smooth_mode"] = int(payload["tag_detection"]["smooth_mode"])
    payload["tag_detection_updated_at"] = int(time.time())
    _save_config_json(payload)


def tag_detection_config_from_form(form: dict[str, str]) -> dict[str, Any]:
    return _normalize_tag_detection_config({
        "enabled0": _bool_form_value(form, "enabled0", True),
        "enabled1": _bool_form_value(form, "enabled1", True),
        "confirm0": _int_form_value(form, "confirm0", 2, 1, 6),
        "confirm1": _int_form_value(form, "confirm1", 2, 1, 6),
        "confirm_phase_gate": _int_form_value(form, "confirm_phase_gate", 3, 0, 199),
        "threshold0": _float_form_value(form, "threshold0", 2.0, 1.0, 100.0),
        "threshold1": _float_form_value(form, "threshold1", 2.0, 1.0, 100.0),
        "threshold_high0": _float_form_value(form, "threshold_high0", 5.0, 1.0, 100.0),
        "threshold_high1": _float_form_value(form, "threshold_high1", 5.0, 1.0, 100.0),
        "ratio_noise_max_u16": _float_form_value(form, "ratio_noise_max_u16", 10.0, 0.1, 65535.0),
        "auto_floor_u16": _float_form_value(form, "auto_floor_u16", 10.0, 0.0, 65535.0),
        "auto_slope": _float_form_value(form, "auto_slope", 5.0, 0.1, 100.0),
        "auto0": _bool_form_value(form, "auto0", False),
        "auto1": _bool_form_value(form, "auto1", False),
        "filter_amplitude0": _bool_form_value(form, "filter_amplitude0", True),
        "filter_amplitude1": _bool_form_value(form, "filter_amplitude1", True),
        "filter_shape0": _bool_form_value(form, "filter_shape0", True),
        "filter_shape1": _bool_form_value(form, "filter_shape1", True),
        "filter_phase0": _bool_form_value(form, "filter_phase0", True),
        "filter_phase1": _bool_form_value(form, "filter_phase1", True),
        "filter_noise_adapt0": True,
        "filter_noise_adapt1": True,
        "noise_window_s": _float_form_value(form, "noise_window_s", 1.0, 0.05, 10.0),
        "noise_up0": _int_form_value(form, "noise_up0", 24, 1, 65535),
        "noise_up1": _int_form_value(form, "noise_up1", 24, 1, 65535),
        "noise_down0": _int_form_value(form, "noise_down0", 3, 1, 65535),
        "noise_down1": _int_form_value(form, "noise_down1", 3, 1, 65535),
        "noise_unit0": _noise_unit_value(form.get("noise_unit0", "adc"), "adc"),
        "noise_unit1": _noise_unit_value(form.get("noise_unit1", "adc"), "adc"),
        "burst_gate0": _bool_form_value(form, "burst_gate0", True),
        "burst_gate1": _bool_form_value(form, "burst_gate1", True),
        "burst_blank_s0": _float_form_value(form, "burst_blank_s0", 0.08, 0.0, 1.0),
        "burst_blank_s1": _float_form_value(form, "burst_blank_s1", 0.08, 0.0, 1.0),
        "burst_max_ratio0": _float_form_value(form, "burst_max_ratio0", 8.0, 0.0, 100.0),
        "burst_max_ratio1": _float_form_value(form, "burst_max_ratio1", 8.0, 0.0, 100.0),
        "smooth_mode": _int_form_value(form, "smooth_mode", 0, 0, 5),
        "filter_casino": _bool_form_value(form, "filter_casino", True),
        "filter_barkhausen": _bool_form_value(form, "filter_barkhausen", False),
        "filter_microwire": _bool_form_value(form, "filter_microwire", False),
        "filter_paper": _bool_form_value(form, "filter_paper", False),
        "peak_index_min": _int_form_value(form, "peak_index_min", 0, 0, 199),
        "peak_index_max": _int_form_value(form, "peak_index_max", 199, 0, 199),
        "barkhausen_radius": _int_form_value(form, "barkhausen_radius", 24, 1, 120),
        "barkhausen_frac": _float_form_value(form, "barkhausen_frac", 0.22, 0.01, 1.0),
        "barkhausen_min_width": _int_form_value(form, "barkhausen_min_width", 4, 1, 120),
        "barkhausen_max_span": _int_form_value(form, "barkhausen_max_span", 140, 1, 200),
        "barkhausen_min_product_level": _int_form_value(form, "barkhausen_min_product_level", 800000, 0, 2147483647),
        "barkhausen_max_product_level": _int_form_value(form, "barkhausen_max_product_level", 20000000, 0, 2147483647),
        "barkhausen_max_total_fraction": _float_form_value(form, "barkhausen_max_total_fraction", 0.82, 0.01, 1.0),
        "barkhausen_all_quarter_frac": _float_form_value(form, "barkhausen_all_quarter_frac", 0.45, 0.01, 1.0),
        "phase_max_shift": _int_form_value(form, "phase_max_shift", 12, 0, 80),
        "phase_shift_penalty": _float_form_value(form, "phase_shift_penalty", 0.02, 0.0, 1.0),
        "mark_window_start_frac": _float_form_value(form, "mark_window_start_frac", 0.05, 0.0, 0.95),
        "mark_window_end_frac": _float_form_value(form, "mark_window_end_frac", 0.45, 0.01, 1.0),
        "mark_gap": _int_form_value(form, "mark_gap", 21, 1, 160),
        "mark_gap_tol": _int_form_value(form, "mark_gap_tol", 7, 0, 80),
        "mark_second_frac": _float_form_value(form, "mark_second_frac", 0.18, 0.01, 1.0),
        "mark_valley_frac": _float_form_value(form, "mark_valley_frac", 0.70, 0.01, 0.99),
        "mark_multi_max_humps": _int_form_value(form, "mark_multi_max_humps", 3, 1, 12),
        "locality_max_outside_peaks": _int_form_value(form, "locality_max_outside_peaks", 1, 0, 20),
        "locality_outside_peak_frac": _float_form_value(form, "locality_outside_peak_frac", 0.35, 0.01, 1.0),
    })


def load_tag_detection_config_from_core() -> dict[str, Any] | None:
    try:
        with urlopen(f"{CORE_SERVICE_URL}/api/status", timeout=0.5) as response:
            status = json.loads(response.read().decode("utf-8") or "{}")
        detector = (status or {}).get("detector") or {}
        smoothing = (status or {}).get("smoothing") or {}
        channels = detector.get("channels") or {}
        detector_settings = detector.get("settings") if isinstance(detector.get("settings"), dict) else {}
        upper = channels.get("upper") or {}
        lower = channels.get("lower") or {}
        if not isinstance(upper, dict) or not isinstance(lower, dict):
            return None
        cfg = {
            "enabled0": bool(upper.get("enabled", True)),
            "enabled1": bool(lower.get("enabled", True)),
            "confirm0": upper.get("confirm_count", 2),
            "confirm1": lower.get("confirm_count", 2),
            "threshold0": upper.get("threshold", 2.0),
            "threshold1": lower.get("threshold", 2.0),
            "threshold_high0": upper.get("threshold_high", 5.0),
            "threshold_high1": lower.get("threshold_high", 5.0),
            "ratio_noise_max_u16": detector_settings.get("ratio_noise_max_u16", 10.0),
            "auto_floor_u16": detector_settings.get("auto_floor_u16", 10.0),
            "auto_slope": detector_settings.get("auto_slope", 5.0),
            "auto0": bool(upper.get("auto_threshold", False)),
            "auto1": bool(lower.get("auto_threshold", False)),
            "noise_window_s": detector_settings.get("noise_window_s", 1.0),
            "noise_up0": upper.get("noise_up", 24),
            "noise_up1": lower.get("noise_up", 24),
            "noise_down0": upper.get("noise_down", 3),
            "noise_down1": lower.get("noise_down", 3),
            "noise_unit0": upper.get("noise_unit", "adc"),
            "noise_unit1": lower.get("noise_unit", "adc"),
            "burst_gate0": bool(upper.get("burst_gate", True)),
            "burst_gate1": bool(lower.get("burst_gate", True)),
            "burst_blank_s0": upper.get("burst_blank_s", 0.08),
            "burst_blank_s1": lower.get("burst_blank_s", 0.08),
            "burst_max_ratio0": upper.get("burst_max_ratio", 8.0),
            "burst_max_ratio1": lower.get("burst_max_ratio", 8.0),
            "smooth_mode": smoothing.get("mode", detector_settings.get("smooth_mode", 0)),
            "confirm_phase_gate": detector_settings.get("confirm_phase_gate", 3),
        }
        for key in (
            "filter_casino", "filter_barkhausen", "filter_microwire", "filter_paper",
            "peak_index_min", "peak_index_max",
            *BARKHAUSEN_TAG_KEYS,
            "phase_max_shift", "phase_shift_penalty",
            "mark_window_start_frac", "mark_window_end_frac",
            "mark_gap", "mark_gap_tol", "mark_second_frac", "mark_valley_frac", "mark_multi_max_humps",
            "locality_max_outside_peaks", "locality_outside_peak_frac",
        ):
            if key in detector_settings:
                cfg[key] = detector_settings.get(key)
        return _normalize_tag_detection_config(cfg)
    except Exception:
        return None


def apply_tag_detection_config_to_core(cfg: dict[str, Any]) -> tuple[bool, str]:
    cfg = _normalize_tag_detection_config(cfg)
    payload = {
        "action": "tag_detection",
        "params": {
            "enabled0": bool(cfg["enabled0"]),
            "enabled1": bool(cfg["enabled1"]),
            "confirm0": int(cfg["confirm0"]),
            "confirm1": int(cfg["confirm1"]),
            "threshold0": float(cfg["threshold0"]),
            "threshold1": float(cfg["threshold1"]),
            "threshold_high0": float(cfg["threshold_high0"]),
            "threshold_high1": float(cfg["threshold_high1"]),
            "ratio_noise_max_u16": float(cfg["ratio_noise_max_u16"]),
            "auto_floor_u16": float(cfg["auto_floor_u16"]),
            "auto_slope": float(cfg["auto_slope"]),
            "auto0": bool(cfg["auto0"]),
            "auto1": bool(cfg["auto1"]),
            "noise_window_s": float(cfg["noise_window_s"]),
            "noise_up0": int(cfg["noise_up0"]),
            "noise_up1": int(cfg["noise_up1"]),
            "noise_down0": int(cfg["noise_down0"]),
            "noise_down1": int(cfg["noise_down1"]),
            "noise_unit0": str(cfg["noise_unit0"]),
            "noise_unit1": str(cfg["noise_unit1"]),
            "burst_gate0": bool(cfg["burst_gate0"]),
            "burst_gate1": bool(cfg["burst_gate1"]),
            "burst_blank_s0": float(cfg["burst_blank_s0"]),
			"burst_blank_s1": float(cfg["burst_blank_s1"]),
			"burst_max_ratio0": float(cfg["burst_max_ratio0"]),
			"burst_max_ratio1": float(cfg["burst_max_ratio1"]),
			"smooth_mode": int(cfg["smooth_mode"]),
			"confirm_phase_gate": int(cfg["confirm_phase_gate"]),
			"filter_casino": bool(cfg["filter_casino"]),
			"filter_barkhausen": bool(cfg["filter_barkhausen"]),
			"filter_microwire": bool(cfg["filter_microwire"]),
			"filter_paper": bool(cfg["filter_paper"]),
			"peak_index_min": int(cfg["peak_index_min"]),
			"peak_index_max": int(cfg["peak_index_max"]),
			"barkhausen_radius": int(cfg["barkhausen_radius"]),
			"barkhausen_frac": float(cfg["barkhausen_frac"]),
			"barkhausen_min_width": int(cfg["barkhausen_min_width"]),
			"barkhausen_max_span": int(cfg["barkhausen_max_span"]),
			"barkhausen_min_product_level": int(cfg["barkhausen_min_product_level"]),
			"barkhausen_max_product_level": int(cfg["barkhausen_max_product_level"]),
			"barkhausen_max_total_fraction": float(cfg["barkhausen_max_total_fraction"]),
			"barkhausen_all_quarter_frac": float(cfg["barkhausen_all_quarter_frac"]),
			"phase_max_shift": int(cfg["phase_max_shift"]),
			"phase_shift_penalty": float(cfg["phase_shift_penalty"]),
			"mark_window_start_frac": float(cfg["mark_window_start_frac"]),
			"mark_window_end_frac": float(cfg["mark_window_end_frac"]),
			"mark_gap": int(cfg["mark_gap"]),
			"mark_gap_tol": int(cfg["mark_gap_tol"]),
			"mark_second_frac": float(cfg["mark_second_frac"]),
			"mark_valley_frac": float(cfg["mark_valley_frac"]),
			"mark_multi_max_humps": int(cfg["mark_multi_max_humps"]),
			"locality_max_outside_peaks": int(cfg["locality_max_outside_peaks"]),
			"locality_outside_peak_frac": float(cfg["locality_outside_peak_frac"]),
		},
	}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_detector_settings"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"
    if not bool(result.get("ok", False)):
        return False, str(result.get("error") or "BMI30 core service rejected detector settings")
    return True, "Tag Detection settings sent to BMI30 core service"


def apply_group_optic_to_core(
    reaction_enabled: bool,
    neighbor_reaction_enabled: bool,
    neighbor_device_id: int | None,
    hold_seconds: int,
) -> tuple[bool, str]:
    """Send hold duration and independent local/RS485 optic gates to the core."""
    hold_seconds = max(0, min(10, int(hold_seconds)))
    hold_ds = hold_seconds * 10
    messages: list[str] = []
    ok_all = True
    for action, params, src in (
        ("optic_hold", {"hold_ds": hold_ds}, "portal_optic_hold"),
        (
            "optic_reaction",
            {
                "enabled": bool(reaction_enabled),
                "neighbor_enabled": bool(neighbor_reaction_enabled),
                "neighbor_device_id": neighbor_device_id,
            },
            "portal_optic_reaction",
        ),
    ):
        payload = {"action": action, "params": params}
        try:
            req = Request(
                f"{CORE_SERVICE_URL}/api/command",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-BMI30-Source": src},
                method="POST",
            )
            with urlopen(req, timeout=2.5) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
        except Exception as exc:
            return False, f"Unable to contact BMI30 core service: {exc}"
        if not bool(result.get("ok", False)):
            ok_all = False
            messages.append(str(result.get("error") or f"{action} rejected"))
    if not ok_all:
        return False, "; ".join(messages) or "BMI30 core rejected optic settings"
    try:
        cached = _CORE_OPTIC_CACHE.get("data")
        data = dict(cached) if isinstance(cached, dict) else {}
        data["reaction_enabled"] = bool(reaction_enabled)
        data["neighbor_reaction_enabled"] = bool(neighbor_reaction_enabled)
        data["neighbor_device_id"] = neighbor_device_id
        data["indication_control_enabled"] = bool(reaction_enabled or neighbor_reaction_enabled)
        data["indication_optic_hold_ds"] = hold_ds
        data.setdefault("led_patterns", load_group_led_patterns())
        _CORE_OPTIC_CACHE["t"] = time.time()
        _CORE_OPTIC_CACHE["data"] = data
        _CORE_STATUS_CACHE["t"] = 0.0
    except Exception:
        pass
    return True, "Optic settings sent to BMI30 core service"


def _parse_group_sync_assignment(role: Any, node_id: Any = None) -> tuple[str, int | None]:
    """Return an explicit persisted role; automatic/off assignments are forbidden."""
    role_s = str(role or "").strip().lower()
    if len(role_s) >= 2 and role_s[0] == "s" and role_s[1:].isdigit():
        # Slave numbers are assigned by the master after a timestamped role
        # assignment; they are status values, not a host-selectable role.
        role_s = "slave"
    if role_s in {"0", "master", "m"}:
        return "master", None
    if role_s in {"1", "slave", "s"}:
        return "slave", None
    raise ValueError("Role assignment is required and must be Master or Slave")


def apply_group_sync_mode_to_core(role: str, node_id: Any = None) -> tuple[bool, str, dict[str, Any]]:
    """Force the local STM32 synchronization role via the BMI30 core service."""
    try:
        role_s, node = _parse_group_sync_assignment(role, node_id)
    except ValueError as exc:
        return False, str(exc), {}
    params: dict[str, Any] = {"role": role_s}
    payload = {"action": "sync_mode", "params": params}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_sync_role"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}", params
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core rejected sync role"), params
    return True, f"Role assigned: {role_s.capitalize()}", params


def apply_group_rs485_id_to_core(device_id: Any) -> tuple[bool, str, dict[str, Any]]:
    """Persist the local STM32 RS485 device ID independently from its role."""
    try:
        device_id_i = int(device_id)
    except Exception:
        return False, "RS485 ID must be an integer from 00 to 31", {}
    if not 0 <= device_id_i <= 31:
        return False, "RS485 ID must be from 00 to 31", {}
    params = {"device_id": device_id_i}
    payload = {"action": "rs485_id", "params": params}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_rs485_id"},
            method="POST",
        )
        with urlopen(req, timeout=3.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}", params
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core rejected RS485 ID"), params
    return True, f"RS485 ID assigned: {device_id_i:02d}", params


def refresh_group_rs485_ident_from_core(
    request_scan: bool = True,
    local_ip: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Request and read the replicated RS485 device identity map."""
    params: dict[str, Any] = {"request_scan": bool(request_scan)}
    # Firmware 1.2.13 makes EVT1 SENSOR_MAP the authoritative presence table.
    # Restrict EP0 identity reads to those exact IDs; walking all 32 selectors
    # can occupy the device long enough to delay normal RS485 status handling.
    params["device_ids"] = []
    cache = _read_device_state_cache()
    events = cache.get("events") if isinstance(cache.get("events"), dict) else {}
    sensor_map = events.get("sensor_map") if isinstance(events.get("sensor_map"), dict) else {}
    sensors = cache.get("sensors") if isinstance(cache.get("sensors"), dict) else {}
    if sensor_map.get("valid") is True:
        try:
            seen_mask = int(sensor_map.get("sync_seen_mask", 0) or 0) & 0xFFFFFFFF
            params["device_ids"] = [
                device_id
                for device_id in range(32)
                if bool(seen_mask & (1 << device_id))
            ]
        except Exception:
            pass
    elif sensors.get("remote_valid") is True:
        try:
            seen_mask = int(sensors.get("remote_seen_mask", 0) or 0) & 0xFFFFFFFF
            params["device_ids"] = [
                device_id
                for device_id in range(32)
                if bool(seen_mask & (1 << device_id))
            ]
        except Exception:
            pass
    params["local_ip"] = str(local_ip or "0.0.0.0")
    rpi_id = group_local_rpi_id()
    if rpi_id:
        params["rpi_id"] = rpi_id
    payload = {"action": "rs485_ident", "params": params}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_rs485_ident"},
            method="POST",
        )
        with urlopen(req, timeout=25.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to read RS485 device list: {exc}", {}
    ident = result.get("rs485_ident") if isinstance(result, dict) else {}
    if not isinstance(ident, dict):
        ident = {}
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core rejected RS485 identity scan"), ident
    return True, "RS485 device list refresh started", ident


def publish_group_rpi_identity_to_core(local_ip: str | None = None) -> tuple[bool, str]:
    """Publish the immutable hostname RPI ID and current preferred IPv4 over RS485."""
    rpi_id = group_local_rpi_id()
    if not rpi_id:
        return False, "Hostname must have the form BMI30-XXXXXXXXX"
    params = {
        "rpi_id": rpi_id,
        "local_ip": str(local_ip or _group_publication_ip(None) or "0.0.0.0"),
    }
    payload = {"action": "rpi_info", "params": params}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_rpi_identity"},
            method="POST",
        )
        with urlopen(req, timeout=3.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to publish RPI ID over RS485: {exc}"
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core rejected RPI ID publication")
    if not bool(result.get("published", False)):
        wire_format = str(result.get("wire_format") or "unknown")
        return False, f"STM32 did not confirm RPI ID (identity format {wire_format})"
    return True, f"Published {rpi_id} at {params['local_ip']} over RS485"


def publish_group_rpi_identity_background() -> None:
    """Republish on startup and IP changes; periodically refresh the STM32 copy."""
    last_attempt_identity: tuple[str, str] | None = None
    next_attempt_at = 0.0
    while True:
        rpi_id = group_local_rpi_id()
        local_ip = str(_group_publication_ip(None) or "0.0.0.0")
        identity = (rpi_id, local_ip)
        now = time.monotonic()
        if rpi_id and (identity != last_attempt_identity or now >= next_attempt_at):
            last_attempt_identity = identity
            ok, message = publish_group_rpi_identity_to_core(local_ip)
            if ok:
                next_attempt_at = now + 300.0
            else:
                retry_s = 300.0 if "did not confirm" in message else 30.0
                next_attempt_at = now + retry_s
                print(f"[RS485-RPI-ID] {message}", flush=True)
        time.sleep(10.0)


def _led_pattern_value(value: Any, default: int = 0) -> int:
    try:
        pattern = int(str(value).strip())
    except Exception:
        pattern = int(default)
    return max(0, min(255, pattern))


def _normalize_group_led_patterns(raw: Any = None) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_GROUP_LED_PATTERNS)
    for event_key, _event_label in GROUP_LED_PATTERN_EVENTS:
        event_source = source.get(event_key)
        if isinstance(event_source, dict):
            legacy_value = None
            for key in ("pattern", "value", "current", "upper", "lower"):
                if key in event_source:
                    legacy_value = event_source.get(key)
                    break
            event_source = legacy_value
        cfg[event_key] = _led_pattern_value(event_source, cfg[event_key])
    return cfg


def load_group_led_patterns() -> dict[str, int]:
    payload = _load_config_json()
    return _normalize_group_led_patterns(payload.get("group_led_patterns"))


def load_led_pattern_options() -> tuple[tuple[int, str], ...]:
    payload = _load_config_json()
    raw = payload.get("stm32_led_patterns")
    if raw is None:
        raw = payload.get("led_patterns")
    options: list[tuple[int, str]] = []
    seen: set[int] = set()

    def add_option(pattern_id: Any, label: Any = None) -> None:
        pid = _led_pattern_value(pattern_id)
        if pid in seen:
            return
        text = str(label if label is not None else f"Pattern {pid}").strip()
        options.append((pid, text or f"Pattern {pid}"))
        seen.add(pid)

    if isinstance(raw, dict):
        for key in sorted(raw.keys(), key=lambda item: _led_pattern_value(item)):
            add_option(key, raw.get(key))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                add_option(
                    item.get("id", item.get("value", item.get("pattern", 0))),
                    item.get("label", item.get("name", item.get("title", None))),
                )
            else:
                add_option(item)
    if not options:
        for pattern_id in LED_PATTERN_VALUES:
            add_option(pattern_id)
    return tuple(options)


def save_group_led_patterns(cfg: dict[str, Any]) -> None:
    normalized = _normalize_group_led_patterns(cfg)
    payload = _load_config_json()
    payload["group_led_patterns"] = normalized
    payload["group_led_patterns_updated_at"] = int(time.time())
    _save_config_json(payload)
    if os.path.abspath(CONFIG_JSON) != os.path.abspath(HOST_CONFIG_JSON):
        try:
            host_payload: dict[str, Any] = {}
            if os.path.isfile(HOST_CONFIG_JSON):
                with open(HOST_CONFIG_JSON, "r", encoding="utf-8") as f:
                    host_raw = json.load(f) or {}
                if isinstance(host_raw, dict):
                    host_payload = host_raw
            host_payload["group_led_patterns"] = normalized
            host_payload["group_led_patterns_updated_at"] = payload["group_led_patterns_updated_at"]
            directory = os.path.dirname(HOST_CONFIG_JSON) or "."
            os.makedirs(directory, exist_ok=True)
            tmp_path = f"{HOST_CONFIG_JSON}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(host_payload, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            try:
                owner_source = HOST_CONFIG_JSON if os.path.exists(HOST_CONFIG_JSON) else directory
                st = os.stat(owner_source)
                os.chown(tmp_path, st.st_uid, st.st_gid)
            except Exception:
                pass
            try:
                os.chmod(tmp_path, 0o644)
            except Exception:
                pass
            os.replace(tmp_path, HOST_CONFIG_JSON)
        except Exception:
            pass


def group_led_patterns_from_form(form: dict[str, str]) -> dict[str, int]:
    cfg = load_group_led_patterns()
    for event_key, _event_label in GROUP_LED_PATTERN_EVENTS:
        cfg[event_key] = _int_form_value(form, f"led_{event_key}", cfg[event_key], 0, 255)
    return _normalize_group_led_patterns(cfg)


def apply_group_led_patterns_to_core(cfg: dict[str, Any]) -> tuple[bool, str]:
    payload = {
        "action": "group_led_patterns",
        "params": {
            "patterns": _normalize_group_led_patterns(cfg),
            "persist": False,
        },
    }
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_group_led_patterns"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core service rejected LED pattern settings")
    return True, "LED pattern settings sent to BMI30 core service"


def apply_led_pattern_to_core(pattern_id: int) -> tuple[bool, str]:
    pattern_id = _led_pattern_value(pattern_id)
    payload = {"action": "led_pattern", "params": {"pattern": pattern_id, "manual_test": True}}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_group_led_live_test"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core service rejected LED pattern")
    return True, f"LED pattern set to {pattern_id}"


def apply_non_addressable_led_to_core(
    enabled: bool | None = None,
    test_enabled: bool | None = None,
    persist: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    params: dict[str, Any] = {"persist": bool(persist)}
    if enabled is not None:
        params["enabled"] = bool(enabled)
    if test_enabled is not None:
        params["test_enabled"] = bool(test_enabled)
    command = {"action": "non_addressable_led", "params": params}
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(command).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_non_addressable_led"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}", {}
    actual = result.get("non_addressable_led") if isinstance(result, dict) else None
    if not isinstance(actual, dict):
        actual = {}
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core rejected detection LED strip settings"), actual
    return True, "Detection LED strip updated", actual


_CORE_OPTIC_CACHE: dict[str, Any] = {"t": 0.0, "data": {}}
_CORE_STATUS_CACHE: dict[str, Any] = {"t": 0.0, "data": {}}


def _read_core_status_snapshot(max_age_s: float = 0.20) -> dict[str, Any]:
    now = time.time()
    try:
        if (now - float(_CORE_STATUS_CACHE.get("t", 0.0))) < float(max_age_s):
            data = _CORE_STATUS_CACHE.get("data")
            return dict(data) if isinstance(data, dict) else {}
    except Exception:
        pass
    try:
        with urlopen(f"{CORE_SERVICE_URL}/api/status", timeout=0.6) as response:
            status = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(status, dict):
            status = {}
        _CORE_STATUS_CACHE.update({"t": now, "data": status})
        return dict(status)
    except Exception:
        return {}


def _portal_host_config_candidates() -> list[str]:
    active_config = ""
    for env_path in _split_active_env_candidates():
        data = _read_key_value_file(env_path)
        configured = str(data.get("BMI30_PROJECT_CONFIG_PATH") or "").strip()
        if configured:
            active_config = _resolve_project_path(configured)
            break
    return _unique_existing_text_paths((
        os.getenv("BMI30_HOST_CONFIG_JSON", ""),
        active_config,
        "/home/techaid/Documents/host/bmi30_config.json",
        os.path.join(_bmi30_project_roots()[0], "host", "bmi30_config.json"),
        HOST_CONFIG_JSON,
        "/usr/local/bin/host/bmi30_config.json",
        CONFIG_JSON,
        os.getenv("BMI30_CONFIG_JSON", ""),
    ))


def _read_saved_optic_settings() -> dict[str, Any]:
    for path in _portal_host_config_candidates():
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
            if not isinstance(payload, dict):
                continue
            source = payload.get("optic") if isinstance(payload.get("optic"), dict) else payload
            out: dict[str, Any] = {}
            if "optic_reaction_enabled" in payload:
                out["reaction_enabled"] = bool(payload.get("optic_reaction_enabled"))
            elif "reaction_enabled" in source:
                out["reaction_enabled"] = bool(source.get("reaction_enabled"))
            if "optic_neighbor_reaction_enabled" in payload:
                out["neighbor_reaction_enabled"] = bool(payload.get("optic_neighbor_reaction_enabled"))
            elif "neighbor_reaction_enabled" in source:
                out["neighbor_reaction_enabled"] = bool(source.get("neighbor_reaction_enabled"))
            raw_neighbor_device_id = payload.get(
                "optic_neighbor_device_id",
                source.get("neighbor_device_id"),
            )
            if raw_neighbor_device_id not in (None, "", -1, "-1", "any", "all"):
                try:
                    node_id = int(raw_neighbor_device_id)
                    if 0 <= node_id <= 31:
                        out["neighbor_device_id"] = node_id
                except Exception:
                    pass
            else:
                out["neighbor_device_id"] = None
            if "indication_control_enabled" in source:
                out["indication_control_enabled"] = bool(source.get("indication_control_enabled"))
            if "optic_hold_ds" in source:
                out["indication_optic_hold_ds"] = source.get("optic_hold_ds")
            if out:
                return out
        except Exception:
            continue
    return {}


def _read_core_optic_settings() -> dict[str, Any]:
    """Best-effort read of optic settings without erasing saved values on short core timeouts."""
    now = time.time()
    if (now - float(_CORE_OPTIC_CACHE.get("t", 0.0))) < 0.25:
        cached = _CORE_OPTIC_CACHE.get("data")
        if isinstance(cached, dict) and cached:
            return dict(cached)
    cached = _CORE_OPTIC_CACHE.get("data")
    out: dict[str, Any] = dict(cached) if isinstance(cached, dict) else {}
    saved = _read_saved_optic_settings()
    for key, value in saved.items():
        out.setdefault(key, value)
    out.setdefault("reaction_enabled", False)
    out.setdefault("neighbor_reaction_enabled", False)
    out.setdefault("neighbor_device_id", None)
    out["led_patterns"] = load_group_led_patterns()
    try:
        status = _read_core_status_snapshot()
        optic = status.get("optic") if isinstance(status.get("optic"), dict) else {}
        if optic:
            if "reaction_enabled" in optic:
                out["reaction_enabled"] = bool(optic.get("reaction_enabled"))
            if "neighbor_reaction_enabled" in optic:
                out["neighbor_reaction_enabled"] = bool(optic.get("neighbor_reaction_enabled"))
            if "neighbor_device_id" in optic:
                raw_neighbor_device_id = optic.get("neighbor_device_id")
                try:
                    node_id = int(raw_neighbor_device_id)
                    out["neighbor_device_id"] = node_id if 0 <= node_id <= 31 else None
                except Exception:
                    out["neighbor_device_id"] = None
            if isinstance(optic.get("led_patterns"), dict):
                out["led_patterns"] = _normalize_group_led_patterns(optic.get("led_patterns"))
            for key in (
                "indication_control_enabled",
                "indication_allowed",
                "indication_optic_active",
                "indication_source",
                "indication_sync_role",
                "indication_local_node_id",
                "indication_master_node_id",
                "indication_optic_hold_ds",
                "indication_host_hold_remaining_s",
                "led_pattern_actual",
                "led_pattern_actual_source",
                "led_pattern_actual_age_s",
                "led_pattern_commanded",
                "led_manual_test_pattern",
                "led_detection_allowed",
                "led_event",
                "led_desired_event",
                "led_state",
                "non_addressable_led",
            ):
                if key in optic:
                    out[key] = optic.get(key)
    except Exception:
        pass
    _CORE_OPTIC_CACHE["t"] = now
    _CORE_OPTIC_CACHE["data"] = dict(out)
    return out


def apply_avg_n_to_core(avg_n: int) -> tuple[bool, str]:
    avg_n = _normalize_avg_n(avg_n, DEFAULT_AVG_N)
    payload = {
        "action": "avg",
        "params": {"avg_n": avg_n},
    }
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_avg"},
            method="POST",
        )
        with urlopen(req, timeout=2.5) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"
    if not bool(result.get("ok", False)):
        return False, str(result.get("error") or "BMI30 core service rejected averaging settings")
    return True, f"Averaging set to {avg_n}"


def _normalize_dc_config(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_DC_CONFIG)
    cfg.update({k: source.get(k, v) for k, v in DEFAULT_DC_CONFIG.items()})
    cfg["work_settle_s"] = _float_form_value(cfg, "work_settle_s", 5.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S)
    # Migration from the old mislabeled form: detect_settle_s was shown as
    # Acquisition, while fast_settle_s was shown as Detection.
    legacy_schema = "acquisition_settle_s" not in source and "detection_settle_s" not in source
    legacy_forbidden = (
        legacy_schema
        and cfg["work_settle_s"] == 900.0
        and _float_form_value(source, "detect_settle_s", 500.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S) == 60.0
        and _float_form_value(source, "fast_settle_s", 10000.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S) == 5.0
    )
    if legacy_forbidden:
        cfg["work_settle_s"] = 5.0
    acquisition_value = 500.0 if legacy_forbidden else source.get("acquisition_settle_s", source.get("detect_settle_s", 500.0))
    detection_value = 10000.0 if legacy_forbidden else source.get("detection_settle_s", source.get("fast_settle_s", 10000.0))
    cfg["acquisition_settle_s"] = _float_form_value(
        {"value": acquisition_value}, "value", 500.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S
    )
    cfg["detection_settle_s"] = _float_form_value(
        {"value": detection_value}, "value", 10000.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S
    )
    cfg["startup_settle_s"] = 1.0
    cfg["lightning_timeout_s"] = _float_form_value(
        cfg, "lightning_timeout_s", 1.0, DC_LIGHTNING_TIMEOUT_MIN_S, DC_SETTLE_MAX_S
    )
    return cfg


def load_dc_config() -> dict[str, Any]:
    return _normalize_dc_config(_load_config_json().get("dc_config"))


def load_dc_config_from_core() -> dict[str, Any] | None:
    try:
        with urlopen(f"{CORE_SERVICE_URL}/api/dc-config", timeout=1.2) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception:
        return None
    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return None
    cfg = result.get("dc_config")
    if not isinstance(cfg, dict):
        return None
    return _normalize_dc_config(cfg)


def save_dc_config(cfg: dict[str, Any]) -> None:
    normalized = _normalize_dc_config(cfg)
    payload = _load_config_json()
    payload["dc_config"] = normalized
    payload["dc_config_updated_at"] = int(time.time())
    _save_config_json(payload)
    # Core and Portal must see the same three host profiles. Keep the active
    # project and installed fallback synchronized with the authoritative
    # /etc config so a restart cannot resurrect stale 100/1000/10000 values.
    for path in _portal_host_config_candidates():
        if os.path.abspath(path) == os.path.abspath(CONFIG_JSON):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                host_payload = json.load(f) or {}
            if not isinstance(host_payload, dict):
                host_payload = {}
            host_payload["dc_config"] = normalized
            host_payload["dc_config_updated_at"] = payload["dc_config_updated_at"]
            previous_stat = os.stat(path)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(host_payload, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.chown(tmp_path, previous_stat.st_uid, previous_stat.st_gid)
            os.chmod(tmp_path, previous_stat.st_mode & 0o777)
            os.replace(tmp_path, path)
        except Exception as exc:
            print(f"[DC] unable to synchronize config copy {path}: {exc}", flush=True)


def save_portal_credentials(username: str, password: str) -> None:
    username = username.strip()
    if not username or len(username) > 64:
        raise ValueError("Username must be 1-64 characters long.")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    payload = _load_config_json()
    payload["portal_auth"] = {
        "username": username,
        "password_hash": hash_portal_password(password),
        "updated_at": int(time.time()),
    }
    _save_config_json(payload)


def save_engineer_credentials(enabled: bool, username: str, password: str = "") -> None:
    username = username.strip() or DEFAULT_ENGINEER_USERNAME
    if len(username) > 64:
        raise ValueError("Engineer login must be 1-64 characters long.")
    payload = _load_config_json()
    existing_raw = payload.get("engineer_auth")
    existing = existing_raw if isinstance(existing_raw, dict) else {}
    password_hash = str(existing.get("password_hash") or "").strip()
    if enabled:
        if password:
            if len(password) < 8:
                raise ValueError("Engineer password must contain at least 8 characters.")
            password_hash = hash_portal_password(password)
        elif not password_hash:
            password_hash = DEFAULT_ENGINEER_PASSWORD_HASH
    payload["engineer_auth"] = {
        "enabled": bool(enabled),
        "username": username,
        "password_hash": password_hash,
        "updated_at": int(time.time()),
    }
    _save_config_json(payload)


def load_remote_desktop_config() -> dict[str, Any]:
    raw = _load_config_json_direct().get("remote_desktop")
    source = raw if isinstance(raw, dict) else {}
    username = str(source.get("username") or SSH_USER).strip() or SSH_USER
    return {
        "username": username,
        "password_saved": bool(source.get("password_saved")),
        "updated_at": int(source.get("updated_at") or 0),
    }


def save_remote_desktop_metadata(username: str, password_changed: bool) -> None:
    payload = _load_config_json()
    previous_raw = payload.get("remote_desktop")
    previous = previous_raw if isinstance(previous_raw, dict) else {}
    payload["remote_desktop"] = {
        "username": username,
        "password_saved": bool(password_changed or previous.get("password_saved")),
        "secret_store": "system user password and x11vnc rfbauth",
        "updated_at": int(time.time()),
    }
    _save_config_json(payload)


CHANNEL_KEYS = {"hotspot", "wifi", "ethernet", "remote"}


def load_channel_permissions() -> dict[str, bool]:
    raw = _load_config_json_direct().get("channel_permissions")
    source = raw if isinstance(raw, dict) else {}
    return {key: bool(source.get(key, True)) for key in CHANNEL_KEYS}


def save_channel_permission(channel: str, enabled: bool) -> None:
    if channel not in CHANNEL_KEYS:
        raise ValueError("Unknown communication channel.")
    payload = _load_config_json()
    raw = payload.get("channel_permissions")
    permissions = raw if isinstance(raw, dict) else {}
    permissions[channel] = bool(enabled)
    permissions["updated_at"] = int(time.time())
    payload["channel_permissions"] = permissions
    _save_config_json(payload)


def save_hotspot_access_metadata(ssid: str, password_changed: bool) -> None:
    payload = _load_config_json()
    previous = payload.get("hotspot_access")
    previous_saved = bool(previous.get("password_saved")) if isinstance(previous, dict) else False
    payload["hotspot_access"] = {
        "ssid": ssid,
        "password_saved": bool(password_changed or previous_saved),
        "secret_store": "NetworkManager",
        "updated_at": int(time.time()),
    }
    _save_config_json(payload)


def save_wifi_internet_metadata(ssid: str, connected: bool, message: str = "") -> None:
    payload = _load_config_json()
    payload["wifi_internet"] = {
        "ssid": ssid,
        "password_saved": True,
        "secret_store": "NetworkManager",
        "last_apply_ok": bool(connected),
        "last_message": message[:240],
        "updated_at": int(time.time()),
    }
    _save_config_json(payload)


def dc_config_from_form(form: dict[str, str]) -> dict[str, Any]:
    return _normalize_dc_config({
        "work_settle_s": _float_form_value(form, "work_settle_s", 5.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "acquisition_settle_s": _float_form_value(form, "acquisition_settle_s", 500.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "detection_settle_s": _float_form_value(form, "detection_settle_s", 10000.0, DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "startup_settle_s": 1.0,
        "lightning_timeout_s": _float_form_value(
            form, "lightning_timeout_s", 1.0, DC_LIGHTNING_TIMEOUT_MIN_S, DC_SETTLE_MAX_S
        ),
    })


def dc_timing_config_from_form(form: dict[str, str], base: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _normalize_dc_config(base)
    cfg.update({
        "work_settle_s": _float_form_value(form, "work_settle_s", cfg["work_settle_s"], DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "acquisition_settle_s": _float_form_value(form, "acquisition_settle_s", cfg["acquisition_settle_s"], DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "detection_settle_s": _float_form_value(form, "detection_settle_s", cfg["detection_settle_s"], DC_SETTLE_MIN_S, DC_SETTLE_MAX_S),
        "lightning_timeout_s": _float_form_value(
            form,
            "lightning_timeout_s",
            cfg["lightning_timeout_s"],
            DC_LIGHTNING_TIMEOUT_MIN_S,
            DC_SETTLE_MAX_S,
        ),
    })
    return _normalize_dc_config(cfg)


def apply_dc_config_to_device(cfg: dict[str, Any]) -> tuple[bool, str]:
    cfg = _normalize_dc_config(cfg)
    payload = {
        "action": "dc_config",
        "params": {
            "work_settle_s": float(cfg["work_settle_s"]),
            "acquisition_settle_s": float(cfg["acquisition_settle_s"]),
            "detection_settle_s": float(cfg["detection_settle_s"]),
            "startup_settle_s": float(cfg["startup_settle_s"]),
            "lightning_timeout_s": float(cfg["lightning_timeout_s"]),
        },
    }
    try:
        req = Request(
            f"{CORE_SERVICE_URL}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-BMI30-Source": "portal_dc_config"},
            method="POST",
        )
        with urlopen(req, timeout=4.0) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return False, f"Unable to contact BMI30 core service: {exc}"

    if not isinstance(result, dict) or not bool(result.get("ok", False)):
        return False, str((result or {}).get("error") or "BMI30 core service rejected DC configuration")
    return True, "DC configuration sent to BMI30 core service"


def _load_ui_sync_mode_from_config() -> str:
    """Best-effort: read last known UI sync mode (0/1/2) from config."""
    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        if isinstance(payload, dict):
            mode_int = int(payload.get("adc_comm_mode", 2))
            return {0: "master", 1: "slave", 2: "off"}.get(mode_int, "---")
    except Exception:
        pass
    return "---"


def _read_device_ep0_packet(request: int, length: int, magic: bytes) -> bytes | None:
    """Query device via USB EP0 and return a packet with the expected magic."""
    request_i = int(request) & 0xFF
    length_i = max(1, int(length))
    magic_b = bytes(magic)
    script = f"""
import os
import sys
import usb.core

request = {request_i}
length = {length_i}
magic = {magic_b!r}
ok = b''
vid = int(os.getenv('BMI30_USB_VID', '0xCAFE'), 0)
pid = int(os.getenv('BMI30_USB_PID', '0x4001'), 0)
try:
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is not None:
        data = bytes(dev.ctrl_transfer(0xC0, request, 0, 0, length, timeout=500))
        if data[:len(magic)] == magic:
            ok = data
except Exception:
    ok = b''
sys.stdout.buffer.write(ok)
"""
    try:
        proc = subprocess.run(
            ["python3", "-c", script],
            check=False,
            capture_output=True,
            timeout=1.2,
        )
        if proc.returncode != 0:
            return None
        out = bytes(proc.stdout or b"")
        return out if out else None
    except Exception:
        return None


def _read_device_status_packet() -> bytes | None:
    """Query device via USB GET_STATUS and return raw STAT packet if available."""
    return _read_device_ep0_packet(0x30, 136, b"STAT")


def _read_device_state_cache(max_age_s: int | None = None) -> dict[str, Any]:
    """Read last device state published by the main Bulk IN reader."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with open(DEVICE_STATE_JSON, "r", encoding="utf-8") as f:
                payload = json.load(f)
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.01)
            else:
                payload = None
    try:
        if not isinstance(payload, dict):
            return {}
        ts = float(payload.get("updated_at", 0.0) or 0.0)
        age = max(0.0, time.time() - ts) if ts > 0 else None
        limit = DEVICE_STATE_MAX_AGE_S if max_age_s is None else int(max_age_s)
        if age is None or age > limit:
            payload = dict(payload)
            payload["_stale"] = True
            payload["_age_s"] = age
            return payload
        payload["_stale"] = False
        payload["_age_s"] = age
        return payload
    except Exception:
        _ = last_error
        return {}


def _device_cache_temperature(cache: dict[str, Any]) -> float | None:
    for path in (
        ("temperature", "temp_c"),
        ("events", "mcu_adc", "temp_c"),
        ("events", "temp_c", "temp_c"),
    ):
        cur: Any = cache
        for key in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(key)
        if isinstance(cur, (int, float)):
            return float(cur)
    return None


def _cache_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _sanitize_group_sync_snapshot(
    sync_snapshot: dict[str, Any],
    stat: dict[str, Any],
    local: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    """Normalize the fixed-role/fixed-ID protocol without inventing missing IDs."""
    sync = dict(sync_snapshot) if isinstance(sync_snapshot, dict) else {}
    raw_mask = _cache_int(sync.get("sync_seen_mask", stat.get("sync_seen_mask", 0)), 0) & 0xFFFFFFFF
    local_id_raw = _cache_int(
        sync.get("device_id", sync.get("local_node_id", local.get("node_id", local.get("status_node_id", 0)))),
        0,
    )
    id_assigned_raw = sync.get("device_id_assigned")
    if id_assigned_raw is None:
        assignment_status = _cache_int(sync.get("assignment_status", sync.get("local_status_raw")), 0)
        id_assigned = bool(assignment_status & 0x04)
        if not id_assigned:
            code = str(sync.get("code") or sync.get("lcd_code") or "").strip().upper()
            id_assigned = bool(re.fullmatch(r"[MS][0-9]{2}", code))
    else:
        id_assigned = bool(id_assigned_raw)
    local_id = local_id_raw if id_assigned and 0 <= local_id_raw <= 31 else -1

    role = str(sync.get("role") or "").strip().lower()
    raw_mode = _cache_int(sync.get("raw_mode"), -1)
    if role not in {"master", "slave", "off"}:
        role = {0: "master", 1: "slave", 2: "off"}.get(raw_mode, role)
    assigned_role = str(sync.get("assigned_role") or "").strip().lower()
    if assigned_role not in {"master", "slave"}:
        assigned_role = {1: "master", 2: "slave"}.get(_cache_int(sync.get("saved_role_code"), 0), "")
    if assigned_role not in {"master", "slave"} and bool(sync.get("role_persisted")) and role in {"master", "slave"}:
        assigned_role = role

    clean_mask = raw_mask
    if local_id >= 0:
        clean_mask |= 1 << local_id
    clean_count = clean_mask.bit_count()

    if sync:
        sync["sync_seen_mask"] = clean_mask
        sync["active_status_count"] = clean_count
        sync["total_devices"] = max(clean_count, 1 if id_assigned else 0)
        sync["device_id"] = local_id_raw
        sync["local_node_id"] = local_id_raw
        sync["device_id_assigned"] = id_assigned
        if role:
            sync["role"] = role
        if assigned_role:
            sync["assigned_role"] = assigned_role
    return sync, clean_mask, local_id


def _device_cache_sensors(cache: dict[str, Any]) -> dict[str, Any]:
    sensors = cache.get("sensors") if isinstance(cache.get("sensors"), dict) else {}
    local = sensors.get("local") if isinstance(sensors.get("local"), dict) else {}
    remote_raw = sensors.get("remote") if isinstance(sensors.get("remote"), list) else []
    stat = cache.get("stat") if isinstance(cache.get("stat"), dict) else {}
    events_raw = cache.get("events") if isinstance(cache.get("events"), dict) else {}
    events = dict(events_raw)
    sync_snapshot = cache.get("sync") if isinstance(cache.get("sync"), dict) else {}
    if isinstance(events_raw.get("sync_state"), dict):
        sync_snapshot = events_raw["sync_state"]
    sensor_map = events_raw.get("sensor_map") if isinstance(events_raw.get("sensor_map"), dict) else {}
    if sensor_map.get("valid") is True:
        sync_snapshot = {
            **sync_snapshot,
            "sync_seen_mask": sensor_map.get("sync_seen_mask", 0),
            "active_status_count": sensor_map.get("node_count", 0),
            "total_devices": sensor_map.get("node_count", 0),
            "device_id": sensor_map.get("local_node_id"),
            "local_node_id": sensor_map.get("local_node_id"),
            "device_id_assigned": sensor_map.get("device_id_assigned", False),
        }
    sync_mask_known = isinstance(sync_snapshot, dict) and "sync_seen_mask" in sync_snapshot
    sync_snapshot, current_seen_mask, current_local_id = _sanitize_group_sync_snapshot(sync_snapshot, stat, local)
    sync_out = cache.get("sync") if isinstance(cache.get("sync"), dict) else {}
    sync_out = {**sync_out, **sync_snapshot} if sync_snapshot else dict(sync_out)
    if sync_snapshot:
        events["sync_state"] = sync_snapshot
    remote: list[dict[str, Any]] = []
    for item in remote_raw:
        if not isinstance(item, dict):
            continue
        try:
            node_id_for_mask = int(item.get("node_id", item.get("status_node_id", 0)) or 0)
        except Exception:
            node_id_for_mask = 0
        if node_id_for_mask < 0 or node_id_for_mask > 31 or node_id_for_mask == current_local_id:
            continue
        if sync_mask_known:
            try:
                if not (current_seen_mask & (1 << node_id_for_mask)):
                    continue
            except Exception:
                continue
        elif item.get("seen") is not True:
            continue
        remote.append(item)
    rs485_ident = cache.get("rs485_ident") if isinstance(cache.get("rs485_ident"), dict) else {}
    ident_nodes: dict[int, dict[str, Any]] = {}
    try:
        nodes = rs485_ident.get("nodes") if isinstance(rs485_ident.get("nodes"), dict) else {}
        for key, entry in nodes.items():
            if not isinstance(entry, dict):
                continue
            node_id = int(entry.get("node_id", key) or 0)
            if 0 <= node_id <= 31:
                ident_nodes[node_id] = entry
    except Exception:
        ident_nodes = {}

    def _identity_patch(entry: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        entry_ip = str(entry.get("ip") or "").strip()
        for key in (
            "short_id",
            "host_id",
            "rpi_id",
            "rpi_id_valid",
            "wire_format",
            "ip",
            "ip_last",
            "group_label",
            "complete",
            "recent",
            "scan_active",
            "flags_hex",
            "host_updated_at",
            "host_updated_iso",
            "node_id",
            "device_id_assigned",
            "master",
            "role",
            "node_conflict",
        ):
            value = entry.get(key)
            if key in {"ip", "ip_last"} and entry_ip in {"", "0.0.0.0"}:
                continue
            if value is not None and value != "":
                out[key] = value
        return out

    local_id = current_local_id
    if 0 <= local_id <= 31 and local_id in ident_nodes:
        local = {**_identity_patch(ident_nodes[local_id]), **local}
    elif isinstance(rs485_ident.get("local"), dict):
        local = {**_identity_patch(rs485_ident["local"]), **local}
    if 0 <= local_id <= 31:
        local["node_id"] = local_id
        local["device_id_assigned"] = True

    optic_event = events.get("optic_state") if isinstance(events.get("optic_state"), dict) else {}
    if "optic_active" in optic_event:
        local["optic_active_event"] = bool(optic_event.get("optic_active"))
        runtime_gate = any(
            bool(local.get(key))
            for key in (
                "optic_active_flags_runtime",
                "optic_master_flags_runtime",
                "optic_any_flags_runtime",
                "optic_indication_allow",
            )
        )
        local["optic_active"] = bool(local.get("optic_active_flags_runtime", optic_event.get("optic_active")))
        local["optic_indication_allow"] = bool(
            runtime_gate
            or optic_event.get("optic_indication_allow", optic_event.get("optic_active"))
        )
    elif isinstance(stat, dict) and "optic_active" in stat:
        local["optic_active"] = bool(stat.get("optic_active"))
        local["optic_indication_allow"] = bool(
            stat.get("optic_active")
            or stat.get("master_optic_active")
            or stat.get("any_optic_active")
        )

    merged_remote: list[dict[str, Any]] = []
    seen_remote_ids: set[int] = set()
    for item in remote:
        try:
            node_id = int(item.get("node_id", item.get("status_node_id", 0)) or 0)
        except Exception:
            node_id = 0
        if 0 <= node_id <= 31:
            seen_remote_ids.add(node_id)
            if node_id in ident_nodes:
                item = {**_identity_patch(ident_nodes[node_id]), **item}
        merged_remote.append(item)
    for node_id, entry in sorted(ident_nodes.items()):
        if node_id == local_id or node_id in seen_remote_ids:
            continue
        seen_now = bool(current_seen_mask & (1 << node_id))
        if sync_mask_known and not seen_now:
            continue
        if not sync_mask_known and entry.get("recent") is not True:
            continue
        identity_item = _identity_patch(entry)
        if not identity_item:
            continue
        identity_item["node_id"] = node_id
        identity_item["seen"] = seen_now
        identity_item["online"] = bool(seen_now if sync_mask_known else entry.get("recent"))
        merged_remote.append(identity_item)
    remote = merged_remote
    return {
        "available": bool(cache) and not bool(cache.get("_stale")),
        "stale": bool(cache.get("_stale")) if cache else True,
        "age_s": cache.get("_age_s"),
        "source": str(cache.get("source", "")) if cache else "",
        "updated_at": cache.get("updated_at"),
        "updated_iso": cache.get("updated_iso"),
        "cache_written_at": cache.get("cache_written_at"),
        "cache_written_iso": cache.get("cache_written_iso"),
        "evt1": cache.get("evt1") if isinstance(cache.get("evt1"), dict) else {},
        "event_updates": cache.get("event_updates") if isinstance(cache.get("event_updates"), dict) else {},
        "service": cache.get("service") if isinstance(cache.get("service"), dict) else {},
        "identity": cache.get("identity") if isinstance(cache.get("identity"), dict) else {},
        "rs485_ident": rs485_ident,
        "local": local,
        "remote": remote,
        "remote_count": len(remote),
        "stat": stat,
        "events": events,
        "mode": cache.get("mode") if isinstance(cache.get("mode"), dict) else {},
        "sync": sync_out,
    }


def _current_group_lan_devices(
    devices: Any,
    device_sensors: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep LAN metadata only for IDs present in the current STM32 group mask."""
    lan_devices = [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else []
    sync = device_sensors.get("sync") if isinstance(device_sensors.get("sync"), dict) else {}
    events = device_sensors.get("events") if isinstance(device_sensors.get("events"), dict) else {}
    sync_event = events.get("sync_state") if isinstance(events.get("sync_state"), dict) else {}
    sensor_map = events.get("sensor_map") if isinstance(events.get("sensor_map"), dict) else {}
    mask_raw = (
        sensor_map.get("sync_seen_mask")
        if sensor_map.get("valid") is True
        else sync_event.get("sync_seen_mask", sync.get("sync_seen_mask"))
    )
    if mask_raw is None:
        return lan_devices
    try:
        seen_mask = int(mask_raw) & 0xFFFFFFFF
    except Exception:
        return []
    current: list[dict[str, Any]] = []
    for item in lan_devices:
        if item.get("device_id_assigned") is not True:
            continue
        try:
            node_id = int(item.get("node_id"))
        except Exception:
            continue
        if 0 <= node_id <= 31 and (seen_mask & (1 << node_id)):
            current.append(item)
    return current


def _stm32_identity_from_cache(cache: dict[str, Any]) -> dict[str, Any]:
    identity = cache.get("identity") if isinstance(cache.get("identity"), dict) else {}
    stm32 = identity.get("stm32") if isinstance(identity.get("stm32"), dict) else {}
    if stm32:
        return stm32
    events = cache.get("events") if isinstance(cache.get("events"), dict) else {}
    fw_info = events.get("fw_info") if isinstance(events.get("fw_info"), dict) else {}
    return fw_info


def format_stm32_identity(info: dict[str, Any]) -> str:
    if not info:
        return "---"
    uid = str(info.get("uid96_words") or info.get("uid96") or "").strip()
    build_date = str(info.get("build_date") or "").strip()
    build_time = str(info.get("build_time") or "").strip()
    firmware = " ".join(part for part in (build_date, build_time) if part).strip()
    if not firmware:
        firmware = str(info.get("fw_version") or "").strip()
    parts = []
    if uid:
        parts.append(uid)
    if firmware:
        parts.append("FW " + firmware)
    return " / ".join(parts) if parts else "---"


def _sync_mode_from_device_cache(cache: dict[str, Any]) -> dict[str, Any] | None:
    if not cache or bool(cache.get("_stale")):
        return None
    sync = cache.get("sync") if isinstance(cache.get("sync"), dict) else {}
    events = cache.get("events") if isinstance(cache.get("events"), dict) else {}
    if not sync and isinstance(events.get("sync_state"), dict):
        sync = events["sync_state"]
    value = str(sync.get("role") or "").strip().lower()
    raw_mode = sync.get("raw_mode")
    if not value or value == "---":
        try:
            value = {0: "master", 1: "slave", 2: "off"}.get(int(raw_mode), "---")
        except Exception:
            value = "---"
    display_char = str(sync.get("display_char") or "").strip().upper()
    display_value = sync.get("display_value")
    code = ""
    stored_code = str(sync.get("code") or sync.get("lcd_code") or "").strip().upper()
    if _LCD_SYNC_CODE_RE.fullmatch(stored_code):
        code = stored_code
    try:
        if not code and display_char:
            code = f"{display_char}{int(display_value):02d}"
    except Exception:
        code = display_char
    role_from_code = _sync_role_from_lcd_code(code)
    if role_from_code:
        value = role_from_code
    return {
        "value": value or "---",
        "code": code,
        "source": "event-cache",
        "device_responded": True,
    }


def _read_device_lcd_status_packet() -> bytes | None:
    """Query device via USB GET_LCD_STATUS and return raw LCDS packet if available."""
    return _read_device_ep0_packet(0x38, 24, b"LCDS")


def _lcd_sync_code(lcd: bytes | None) -> str:
    """Extract a compact LCD role code such as M00/S00/S01."""
    if not isinstance(lcd, (bytes, bytearray)) or len(lcd) < 8 or bytes(lcd[:4]) != b"LCDS":
        return ""

    candidates: list[bytes] = []
    if len(lcd) >= 23:
        candidates.append(bytes(lcd[20:23]))
    for off in range(4, max(4, len(lcd) - 2)):
        chunk = bytes(lcd[off:off + 3])
        if all(32 <= b < 127 for b in chunk):
            candidates.append(chunk)

    for chunk in candidates:
        try:
            code = chunk.decode("ascii", errors="strict").upper()
        except Exception:
            continue
        if _LCD_SYNC_CODE_RE.fullmatch(code):
            return code
    return ""


def _sync_role_from_lcd_status(lcd: bytes | None) -> str:
    code = _lcd_sync_code(lcd)
    return _sync_role_from_lcd_code(code)


def _sync_role_from_lcd_code(code: str) -> str:
    code = str(code or "").strip().upper()
    if code.startswith("M"):
        return "master"
    if code.startswith("S"):
        return "slave"
    return ""


def detect_sync_mode() -> dict[str, Any]:
    """
    Source is the device.
    - Normal path: use event cache written by the Bulk IN reader (EVT1/STAT).
    - Optional fallback: USB control polling only when BMI30_PORTAL_USB_STATUS_POLL=1.
    """
    now = time.time()
    if (now - float(_SYNC_CACHE.get("ts", 0.0))) < DEVICE_SYNC_CACHE_S:
        return {
            "value": str(_SYNC_CACHE.get("value", "---")),
            "code": str(_SYNC_CACHE.get("code", "")),
            "source": str(_SYNC_CACHE.get("source", "device")),
            "device_responded": bool(_SYNC_CACHE.get("responded", False)),
        }

    core_status = _read_core_status_snapshot()
    core_sync = core_status.get("sync") if isinstance(core_status.get("sync"), dict) else {}
    core_code = _ready_sync_code(core_sync.get("code") or core_sync.get("lcd_code"))
    core_value = str(core_sync.get("value") or core_sync.get("role") or "").strip().lower()
    if core_sync and (core_code or core_value in {"master", "slave", "off"}):
        if core_code:
            role_from_code = _sync_role_from_lcd_code(core_code)
            if role_from_code:
                core_value = role_from_code
        if core_value not in {"master", "slave", "auto"}:
            core_value = "---"
        _SYNC_CACHE.update({
            "ts": now,
            "responded": bool(core_sync.get("device_responded", True)),
            "value": core_value or "---",
            "code": core_code,
            "source": str(core_sync.get("source") or "core"),
        })
        return {
            "value": core_value or "---",
            "code": core_code,
            "source": str(core_sync.get("source") or "core"),
            "device_responded": bool(core_sync.get("device_responded", True)),
        }

    cached = _sync_mode_from_device_cache(_read_device_state_cache())
    if cached is not None:
        _SYNC_CACHE.update({
            "ts": now,
            "responded": True,
            "value": cached["value"],
            "code": cached.get("code", ""),
            "source": cached.get("source", "event-cache"),
        })
        return cached

    if not PORTAL_USB_STATUS_POLL:
        _SYNC_CACHE.update({"ts": now, "responded": False, "value": "---", "code": "", "source": "event-cache"})
        return {"value": "---", "code": "", "source": "event-cache", "device_responded": False}

    lcd = _read_device_lcd_status_packet()
    code = _lcd_sync_code(lcd)
    mode = _sync_role_from_lcd_code(code)
    if mode:
        _SYNC_CACHE.update({"ts": now, "responded": True, "value": mode, "code": code, "source": "device"})
        return {"value": mode, "code": code, "source": "device", "device_responded": True}

    st = _read_device_status_packet()
    if not st:
        responded = lcd is not None
        _SYNC_CACHE.update({"ts": now, "responded": responded, "value": "---", "code": "", "source": "device"})
        return {"value": "---", "code": "", "source": "device", "device_responded": responded}

    mode = "---"
    source = "device"

    # Optional strict parser: byte offset in STAT packet can be configured.
    # Example: BMI30_SYNC_STATUS_OFFSET=52
    if SYNC_STATUS_OFFSET_S:
        try:
            off = int(SYNC_STATUS_OFFSET_S, 0)
            if 0 <= off < len(st):
                b = int(st[off]) & 0xFF
                mode = {0: "master", 1: "slave", 2: "off"}.get(b, "---")
        except Exception:
            pass

    _SYNC_CACHE.update({"ts": now, "responded": True, "value": mode, "code": "", "source": source})
    return {"value": mode, "code": "", "source": source, "device_responded": True}


def detect_logo_path(candidates: list[str]) -> str:
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if os.path.isfile(candidate):
                return candidate
        except Exception:
            continue
    return ""


def load_logo_bytes(path: str) -> tuple[bytes, str] | None:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        ctype, _ = mimetypes.guess_type(path)
        return data, (ctype or "application/octet-stream")
    except Exception:
        return None


def render_style_bootstrap() -> str:
    return """  <script>
    (function () {
      try {
        var theme = localStorage.getItem('bmi30.portal.theme') || 'auto';
        if (theme !== 'auto' && theme !== 'light' && theme !== 'dark') {
          theme = 'auto';
        }
        var style = localStorage.getItem('bmi30.portal.style') || 'crystal';
        if (style !== 'glass' && style !== 'crystal' && style !== 'warm' && style !== 'neumorph') {
          style = 'crystal';
        }
        var effectiveTheme = theme;
        if (theme === 'auto') {
          effectiveTheme = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
        }
        document.documentElement.dataset.themePref = theme;
        document.documentElement.dataset.themeMode = effectiveTheme;
        document.documentElement.dataset.uiStyle = style;
      } catch (error) {
        document.documentElement.dataset.themePref = 'auto';
        var effectiveTheme = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
        document.documentElement.dataset.themeMode = effectiveTheme;
        document.documentElement.dataset.uiStyle = 'crystal';
      }
    }());
  </script>"""


def render_debug_style_css() -> str:
    return """  <style>
    html[data-theme-mode="light"]{
      color-scheme:light;
      --bg:#eef4f1;--bg-2:#d7e3de;--glass:rgba(255,255,255,.60);--glass-strong:rgba(255,255,255,.74);
      --glass-fallback:#f8fbf9;--panel:rgba(255,255,255,.62);--panel-fallback:#f8fbf9;--text:#17252a;
      --muted:#5d6e74;--line:rgba(255,255,255,.68);--line-soft:rgba(23,37,42,.12);--accent:#0f8a70;
      --accent-2:#f28f3b;--accent-soft:rgba(15,138,112,.16);--warm:rgba(242,143,59,.14);--grid-line:rgba(15,138,112,.075);
      --panel-shadow:0 2px 1px rgba(255,255,255,.36),0 14px 28px rgba(29,42,46,.16),0 34px 72px rgba(29,42,46,.20),inset 1px 1px 0 rgba(255,255,255,.86),inset -1px -1px 0 rgba(60,82,86,.16),inset 0 18px 32px rgba(255,255,255,.22);
      --panel-hover-shadow:0 2px 1px rgba(255,255,255,.40),0 18px 34px rgba(29,42,46,.18),0 42px 84px rgba(29,42,46,.24),inset 1px 1px 0 rgba(255,255,255,.92),inset -1px -1px 0 rgba(60,82,86,.18),inset 0 20px 36px rgba(255,255,255,.25);
      --edge-shadow:rgba(31,48,52,.18);--input-bg:rgba(255,255,255,.58);--portal-border:rgba(242,143,59,.46);
      --form-error-border:#f1beb5;--form-error-bg:rgba(255,242,239,.78);--form-error-text:#a33b2d;
      --footer:#718287;--note-bg:rgba(255,255,255,.44);--note-border:rgba(15,138,112,.25);--note-text:#4c605a;--shine:.72;
    }
    html[data-theme-mode="dark"]{
      color-scheme:dark;
      --bg:#0b1210;--bg-2:#14201c;--glass:rgba(23,34,31,.66);--glass-strong:rgba(31,45,41,.76);
      --glass-fallback:#18211d;--panel:rgba(23,34,31,.68);--panel-fallback:#18211d;--text:#ecf2ee;
      --muted:#a7b5ae;--line:rgba(220,255,244,.18);--line-soft:rgba(220,255,244,.10);--accent:#47c7a7;
      --accent-2:#f0a75e;--accent-soft:rgba(71,199,167,.13);--warm:rgba(240,167,94,.13);--grid-line:rgba(71,199,167,.105);
      --panel-shadow:0 2px 1px rgba(255,255,255,.06),0 16px 34px rgba(0,0,0,.42),0 42px 88px rgba(0,0,0,.52),inset 1px 1px 0 rgba(255,255,255,.18),inset -1px -1px 0 rgba(0,0,0,.50),inset 0 18px 34px rgba(255,255,255,.045);
      --panel-hover-shadow:0 2px 1px rgba(255,255,255,.08),0 20px 40px rgba(0,0,0,.48),0 52px 96px rgba(0,0,0,.58),inset 1px 1px 0 rgba(255,255,255,.22),inset -1px -1px 0 rgba(0,0,0,.54),inset 0 20px 38px rgba(255,255,255,.06);
      --edge-shadow:rgba(0,0,0,.46);--input-bg:rgba(9,15,13,.52);--portal-border:rgba(240,167,94,.42);
      --form-error-border:#8c463a;--form-error-bg:rgba(53,27,23,.78);--form-error-text:#f6b4a9;
      --footer:#87958e;--note-bg:rgba(20,32,28,.58);--note-border:rgba(71,199,167,.24);--note-text:#bfd5cc;--shine:.24;
    }
    html[data-ui-style="crystal"]{
      color-scheme:light;
      --bg:#eef3f8;--bg-2:#e4ebf4;--glass:rgba(255,255,255,.74);--glass-strong:rgba(255,255,255,.86);
      --glass-fallback:#f8fbff;--panel:rgba(255,255,255,.78);--panel-fallback:#f8fbff;--text:#111827;
      --muted:#4b5563;--line:rgba(100,116,139,.26);--line-soft:rgba(30,41,59,.13);--accent:#0d6f69;
      --accent-2:#1d4ed8;--accent-soft:rgba(15,118,110,.16);--warm:rgba(59,130,246,.13);--grid-line:rgba(30,41,59,.055);
      --edge-shadow:rgba(15,23,42,.18);--input-bg:rgba(255,255,255,.82);--portal-border:rgba(59,130,246,.40);
      --form-error-border:#fed7d7;--form-error-bg:rgba(254,242,242,.90);--form-error-text:#c53030;
      --footer:#596273;--note-bg:rgba(255,255,255,.72);--note-border:rgba(59,130,246,.30);--note-text:#303846;--shine:.94;
      --panel-shadow:0 0 0 1px rgba(255,255,255,.92),0 3px 8px rgba(15,23,42,.08),0 16px 34px rgba(59,130,246,.16),0 30px 68px rgba(15,23,42,.14),inset 0 1px 1px rgba(255,255,255,1),inset 0 -14px 28px rgba(59,130,246,.08);
      --panel-hover-shadow:0 0 0 1px rgba(255,255,255,.98),0 4px 10px rgba(15,23,42,.10),0 20px 42px rgba(59,130,246,.20),0 38px 82px rgba(15,23,42,.18),inset 0 1px 1px rgba(255,255,255,1),inset 0 -16px 30px rgba(59,130,246,.11);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"]{
      color-scheme:dark;
      --bg:#0f172a;--bg-2:#1e293b;--glass:rgba(30,41,59,.55);--glass-strong:rgba(51,65,85,.68);
      --glass-fallback:#1e293b;--panel:rgba(30,41,59,.62);--panel-fallback:#1e293b;--text:#f1f5f9;
      --muted:#cbd5e1;--line:rgba(226,232,240,.20);--line-soft:rgba(226,232,240,.10);--accent:#14b8a6;
      --accent-2:#60a5fa;--accent-soft:rgba(20,184,166,.15);--warm:rgba(96,165,250,.12);--grid-line:rgba(226,232,240,.05);
      --edge-shadow:rgba(0,0,0,.40);--input-bg:rgba(15,23,42,.50);--portal-border:rgba(96,165,250,.28);
      --form-error-border:#7f1d1d;--form-error-bg:rgba(127,29,29,.40);--form-error-text:#fecaca;
      --footer:#94a3b8;--note-bg:rgba(30,41,59,.50);--note-border:rgba(96,165,250,.22);--note-text:#cbd5e1;--shine:.35;
      --panel-shadow:0 0 0 1px rgba(226,232,240,.12),0 2px 4px rgba(0,0,0,.20),0 12px 24px rgba(0,0,0,.25),0 20px 48px rgba(0,0,0,.30),inset 0 1px 1px rgba(226,232,240,.10),inset 0 -12px 24px rgba(0,0,0,.20);
      --panel-hover-shadow:0 0 0 1px rgba(226,232,240,.16),0 3px 6px rgba(0,0,0,.25),0 16px 32px rgba(0,0,0,.30),0 28px 64px rgba(0,0,0,.35),inset 0 1px 1px rgba(226,232,240,.14),inset 0 -14px 28px rgba(0,0,0,.24);
    }
    html[data-ui-style="crystal"] body{
      background:
        radial-gradient(800px 400px at 20% 10%,rgba(59,130,246,.11),rgba(59,130,246,0) 60%),
        radial-gradient(600px 300px at 80% 90%,rgba(20,184,166,.08),rgba(20,184,166,0) 55%),
        linear-gradient(180deg,#eef3f8 0%,#e4ebf4 100%);
    }
    html[data-ui-style="crystal"] body::before{
      background:linear-gradient(135deg,rgba(59,130,246,.03),rgba(255,255,255,0) 40%);
      opacity:.80;
    }
    html[data-ui-style="crystal"] .hero,
    html[data-ui-style="crystal"] .card,
    html[data-ui-style="crystal"] .security-note,
    html[data-ui-style="crystal"] .panel{
      border-radius:24px;
      background:linear-gradient(135deg,rgba(255,255,255,.90),rgba(255,255,255,.62) 60%,rgba(255,255,255,.82));
      border:1px solid rgba(100,116,139,.30);
      box-shadow:var(--panel-shadow);
      backdrop-filter:blur(20px) saturate(1.20) brightness(1.05);
      -webkit-backdrop-filter:blur(20px) saturate(1.20) brightness(1.05);
    }
    html[data-ui-style="crystal"] .hero::before,
    html[data-ui-style="crystal"] .card::before,
    html[data-ui-style="crystal"] .security-note::before,
    html[data-ui-style="crystal"] .panel::before{
      top:0;left:0;right:0;height:45%;
      background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(255,255,255,.38),rgba(255,255,255,0));
      mix-blend-mode:screen;
      opacity:var(--shine);
    }
    html[data-ui-style="crystal"] .hero::after,
    html[data-ui-style="crystal"] .card::after,
    html[data-ui-style="crystal"] .security-note::after,
    html[data-ui-style="crystal"] .panel::after{
      inset:0;
      border-radius:inherit;
      background:linear-gradient(125deg,rgba(255,255,255,.70),rgba(255,255,255,0) 30%,rgba(255,255,255,0) 70%,rgba(255,255,255,.48));
      mix-blend-mode:normal;
      opacity:.58;
    }
    html[data-ui-style="crystal"] .card:hover{
      box-shadow:var(--panel-hover-shadow);
    }
    html[data-ui-style="crystal"] .hero{
      background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(255,255,255,.66) 60%,rgba(255,255,255,.84));
    }
    html[data-ui-style="crystal"] h1,
    html[data-ui-style="crystal"] h2,
    html[data-ui-style="crystal"] h3,
    html[data-ui-style="crystal"] dd,
    html[data-ui-style="crystal"] strong{
      color:var(--text);
    }
    html[data-ui-style="crystal"] dt,
    html[data-ui-style="crystal"] .subtle,
    html[data-ui-style="crystal"] .access-note,
    html[data-ui-style="crystal"] p,
    html[data-ui-style="crystal"] span{
      color:var(--muted);
    }
    html[data-ui-style="crystal"] .data-table th,
    html[data-ui-style="crystal"] .data-table td{
      border-color:rgba(255,255,255,.50);
    }
    html[data-ui-style="crystal"] .sbtn,
    html[data-ui-style="crystal"] .link,
    html[data-ui-style="crystal"] .menu-btn,
    html[data-ui-style="crystal"] .mode-option,
    html[data-ui-style="crystal"] .debug-option{
      position:relative;
      overflow:hidden;
      border-radius:12px;
      background:linear-gradient(135deg,rgba(255,255,255,.90),rgba(255,255,255,.62) 60%,rgba(255,255,255,.82));
      border:1px solid rgba(100,116,139,.30);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(255,255,255,.86),0 5px 14px rgba(59,130,246,.14),0 14px 32px rgba(15,23,42,.09),inset 0 1px 1px rgba(255,255,255,1),inset 0 -9px 18px rgba(59,130,246,.07);
    }
    html[data-ui-style="crystal"] .sbtn::before,
    html[data-ui-style="crystal"] .link::before,
    html[data-ui-style="crystal"] .menu-btn::before,
    html[data-ui-style="crystal"] .mode-option::before{
      content:"";position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(255,255,255,.78),rgba(255,255,255,.24),rgba(255,255,255,0));
      pointer-events:none;opacity:.68;
    }
    html[data-ui-style="crystal"] .sbtn:hover,
    html[data-ui-style="crystal"] .link:hover,
    html[data-ui-style="crystal"] .menu-btn:hover,
    html[data-ui-style="crystal"] .mode-option:hover{
      background:linear-gradient(135deg,rgba(255,255,255,.96),rgba(255,255,255,.70) 60%,rgba(255,255,255,.90));
      border-color:rgba(100,116,139,.40);
      transform:translateY(-2px);
      box-shadow:0 0 0 1px rgba(255,255,255,.92),0 7px 18px rgba(59,130,246,.18),0 18px 40px rgba(15,23,42,.13),inset 0 1px 1px rgba(255,255,255,1),inset 0 -9px 18px rgba(59,130,246,.09);
    }
    html[data-ui-style="crystal"] .sbtn:active,
    html[data-ui-style="crystal"] .link:active,
    html[data-ui-style="crystal"] .menu-btn:active,
    html[data-ui-style="crystal"] .mode-option:active{
      transform:translateY(0);
      box-shadow:inset 0 2px 6px rgba(59,130,246,.10),0 2px 6px rgba(15,23,42,.08);
    }
    html[data-ui-style="crystal"] .menu-btn[aria-selected="true"],
    html[data-ui-style="crystal"] .mode-option:has(input:checked),
    html[data-ui-style="crystal"] .debug-option[aria-pressed="true"]{
      background:linear-gradient(135deg,rgba(15,118,110,.18),rgba(15,118,110,.10) 60%);
      border-color:rgba(15,118,110,.42);
      color:var(--text);
      transform:translateY(1px);
      box-shadow:0 0 0 1px rgba(15,118,110,.42),inset 0 3px 8px rgba(15,118,110,.18),inset 0 1px 3px rgba(0,0,0,.08);
    }
    html[data-ui-style="crystal"] .sbtn{
      background:linear-gradient(135deg,rgba(255,255,255,.70),rgba(255,255,255,.40) 60%,rgba(255,255,255,.62)),linear-gradient(180deg,#0f766e 0%,#0d6b63 100%);
      border-color:rgba(255,255,255,.40);
      color:#fff;
      box-shadow:0 0 0 1px rgba(255,255,255,.30),0 6px 16px rgba(15,118,110,.20),0 16px 36px rgba(15,118,110,.15),inset 0 1px 1px rgba(255,255,255,.60),inset 0 -10px 18px rgba(0,0,0,.10);
    }
    html[data-ui-style="crystal"] .sbtn:hover{
      background:linear-gradient(135deg,rgba(255,255,255,.80),rgba(255,255,255,.50) 60%,rgba(255,255,255,.72)),linear-gradient(180deg,#107568 0%,#0f766e 100%);
      box-shadow:0 0 0 1px rgba(255,255,255,.40),0 8px 20px rgba(15,118,110,.28),0 20px 44px rgba(15,118,110,.22),inset 0 1px 1px rgba(255,255,255,.70),inset 0 -10px 18px rgba(0,0,0,.14);
    }
    html[data-ui-style="crystal"] .fld input,
    html[data-ui-style="crystal"] .field input,
    html[data-ui-style="crystal"] .cbtn,
    html[data-ui-style="crystal"] .debug-close{
      border-radius:12px;
      min-height:44px;
      background:linear-gradient(135deg,rgba(255,255,255,.90),rgba(255,255,255,.62) 60%,rgba(255,255,255,.82));
      border:1px solid rgba(100,116,139,.30);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(255,255,255,.86),0 5px 14px rgba(59,130,246,.12),inset 0 1px 1px rgba(255,255,255,1),inset 0 -7px 14px rgba(59,130,246,.07);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] body{
      background:
        radial-gradient(800px 400px at 20% 10%,rgba(96,165,250,.06),rgba(96,165,250,0) 60%),
        radial-gradient(600px 300px at 80% 90%,rgba(20,184,166,.05),rgba(20,184,166,0) 55%),
        linear-gradient(180deg,#0f172a 0%,#1e293b 100%);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] body::before{
      background:linear-gradient(135deg,rgba(96,165,250,.02),rgba(255,255,255,0) 40%);
      opacity:.60;
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .hero,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .card,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .security-note,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .panel{
      background:linear-gradient(135deg,rgba(51,65,85,.70),rgba(30,41,59,.50) 60%,rgba(30,41,59,.65));
      border-color:rgba(226,232,240,.15);
      box-shadow:var(--panel-shadow);
      backdrop-filter:blur(18px) saturate(1.15) brightness(.95);
      -webkit-backdrop-filter:blur(18px) saturate(1.15) brightness(.95);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .hero::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .card::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .security-note::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .panel::before{
      background:linear-gradient(180deg,rgba(226,232,240,.15),rgba(226,232,240,.05),rgba(226,232,240,0));
      opacity:var(--shine);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .hero::after,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .card::after,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .security-note::after,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .panel::after{
      background:linear-gradient(125deg,rgba(226,232,240,.10),rgba(226,232,240,0) 30%,rgba(226,232,240,0) 70%,rgba(226,232,240,.08));
      opacity:.35;
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .sbtn,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .link,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .menu-btn,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .mode-option,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .debug-option{
      background:linear-gradient(135deg,rgba(51,65,85,.70),rgba(30,41,59,.50) 60%,rgba(30,41,59,.65));
      border-color:rgba(226,232,240,.13);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(226,232,240,.12),0 4px 12px rgba(0,0,0,.25),0 12px 28px rgba(0,0,0,.30),inset 0 1px 1px rgba(226,232,240,.10),inset 0 -8px 16px rgba(0,0,0,.20);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .sbtn::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .link::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .menu-btn::before,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .mode-option::before{
      background:linear-gradient(180deg,rgba(226,232,240,.12),rgba(226,232,240,.05),rgba(226,232,240,0));
      opacity:.40;
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .sbtn:hover,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .link:hover,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .menu-btn:hover,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .mode-option:hover{
      background:linear-gradient(135deg,rgba(71,85,105,.80),rgba(51,65,85,.60) 60%,rgba(51,65,85,.75));
      border-color:rgba(226,232,240,.18);
      box-shadow:0 0 0 1px rgba(226,232,240,.16),0 6px 16px rgba(0,0,0,.30),0 16px 36px rgba(0,0,0,.35),inset 0 1px 1px rgba(226,232,240,.14),inset 0 -8px 16px rgba(0,0,0,.24);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .menu-btn[aria-selected="true"]{
      color:#38bdf8;
      border-color:rgba(56,189,248,.55);
      background:linear-gradient(135deg,rgba(14,165,233,.20),rgba(56,189,248,.10) 60%,rgba(14,165,233,.16));
      box-shadow:0 0 0 1px rgba(56,189,248,.50),inset 0 3px 8px rgba(14,116,144,.40),inset 0 1px 3px rgba(0,0,0,.30);
      transform:translateY(1px);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .sbtn{
      background:linear-gradient(135deg,rgba(226,232,240,.15),rgba(226,232,240,.05) 60%,rgba(226,232,240,.10)),linear-gradient(180deg,#14b8a6 0%,#0d9488 100%);
      border-color:rgba(226,232,240,.15);
      color:#fff;
      box-shadow:0 0 0 1px rgba(226,232,240,.12),0 6px 16px rgba(20,184,166,.20),0 16px 36px rgba(20,184,166,.15),inset 0 1px 1px rgba(226,232,240,.15),inset 0 -10px 18px rgba(0,0,0,.20);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .sbtn:hover{
      background:linear-gradient(135deg,rgba(226,232,240,.20),rgba(226,232,240,.10) 60%,rgba(226,232,240,.15)),linear-gradient(180deg,#17c9b2 0%,#14b8a6 100%);
      box-shadow:0 0 0 1px rgba(226,232,240,.16),0 8px 20px rgba(20,184,166,.28),0 20px 44px rgba(20,184,166,.22),inset 0 1px 1px rgba(226,232,240,.20),inset 0 -10px 18px rgba(0,0,0,.24);
    }
    html[data-ui-style="crystal"][data-theme-mode="dark"] .fld input,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .field input,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .cbtn,
    html[data-ui-style="crystal"][data-theme-mode="dark"] .debug-close{
      background:linear-gradient(135deg,rgba(51,65,85,.70),rgba(30,41,59,.50) 60%,rgba(30,41,59,.65));
      border-color:rgba(226,232,240,.13);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(226,232,240,.12),0 4px 12px rgba(0,0,0,.25),inset 0 1px 1px rgba(226,232,240,.10),inset 0 -6px 12px rgba(0,0,0,.18);
    }
    html[data-ui-style="neumorph"]{
      color-scheme:light;
      --bg:#d9d9d9;--bg-2:#d9d9d9;--glass:#d9d9d9;--glass-strong:#e1e1e1;
      --glass-fallback:#d9d9d9;--panel:#d9d9d9;--panel-fallback:#d9d9d9;--text:#31343a;
      --muted:#74777d;--line:rgba(120,124,132,.18);--line-soft:rgba(120,124,132,.16);--accent:#596068;
      --accent-2:#f0642f;--accent-soft:rgba(255,255,255,.22);--warm:rgba(255,255,255,0);--grid-line:rgba(0,0,0,0);
      --edge-shadow:rgba(158,158,158,.55);--input-bg:#d9d9d9;--portal-border:rgba(255,255,255,.35);
      --form-error-border:rgba(198,92,76,.28);--form-error-bg:#ded6d4;--form-error-text:#9a3b30;
      --footer:#777a80;--note-bg:#d9d9d9;--note-border:rgba(120,124,132,.18);--note-text:#646970;--shine:.0;
      --neumo-hi:rgba(255,255,255,.82);--neumo-lo:rgba(156,156,156,.52);
      --panel-shadow:12px 12px 24px var(--neumo-lo),-12px -12px 24px var(--neumo-hi);
      --panel-hover-shadow:14px 14px 28px rgba(150,150,150,.56),-14px -14px 28px rgba(255,255,255,.88);
    }
    html[data-ui-style="neumorph"][data-theme-mode="dark"]{
      color-scheme:dark;
      --bg:#2a2e34;--bg-2:#24282e;--glass:#2a2e34;--glass-strong:#333842;
      --glass-fallback:#2b3037;--panel:#2b3037;--panel-fallback:#2b3037;--text:#f2f5f8;
      --muted:#b5bcc6;--line:rgba(255,255,255,.13);--line-soft:rgba(255,255,255,.10);--accent:#d6dbe3;
      --accent-2:#ff9464;--accent-soft:rgba(255,255,255,.075);--warm:rgba(255,255,255,0);--grid-line:rgba(0,0,0,0);
      --edge-shadow:rgba(0,0,0,.62);--input-bg:#2b3037;--portal-border:rgba(255,255,255,.13);
      --form-error-border:rgba(255,148,120,.30);--form-error-bg:#372d2b;--form-error-text:#ffc8bf;
      --footer:#a6adb7;--note-bg:#2b3037;--note-border:rgba(255,255,255,.12);--note-text:#c8ced7;--shine:.0;
      --neumo-hi:rgba(255,255,255,.13);--neumo-lo:rgba(0,0,0,.62);
      --panel-shadow:12px 12px 24px var(--neumo-lo),-12px -12px 24px var(--neumo-hi);
      --panel-hover-shadow:14px 14px 28px rgba(0,0,0,.66),-14px -14px 28px rgba(255,255,255,.15);
    }
    html[data-ui-style="neumorph"] body{
      background:linear-gradient(145deg,var(--bg),var(--bg-2));
      color:var(--text);
    }
    html[data-ui-style="neumorph"] body::before{
      display:none;
    }
    html[data-ui-style="neumorph"] .hero,
    html[data-ui-style="neumorph"] .card,
    html[data-ui-style="neumorph"] .security-note,
    html[data-ui-style="neumorph"] .panel,
    html[data-ui-style="neumorph"] .debug-drawer{
      overflow:hidden;
      background:var(--panel);
      border:0;
      border-radius:28px;
      box-shadow:var(--panel-shadow);
      backdrop-filter:none;
      -webkit-backdrop-filter:none;
    }
    html[data-ui-style="neumorph"] .hero{
      min-height:184px;
      border-radius:0 0 30px 30px;
    }
    html[data-ui-style="neumorph"] .hero::before,
    html[data-ui-style="neumorph"] .hero::after,
    html[data-ui-style="neumorph"] .card::before,
    html[data-ui-style="neumorph"] .card::after,
    html[data-ui-style="neumorph"] .security-note::before,
    html[data-ui-style="neumorph"] .security-note::after,
    html[data-ui-style="neumorph"] .panel::before,
    html[data-ui-style="neumorph"] .panel::after{
      content:none;
    }
    html[data-ui-style="neumorph"] .card:hover{
      transform:translateY(-1px);
      box-shadow:var(--panel-hover-shadow);
    }
    html[data-ui-style="neumorph"] .hero h1,
    html[data-ui-style="neumorph"] .card h2,
    html[data-ui-style="neumorph"] h1,
    html[data-ui-style="neumorph"] h2,
    html[data-ui-style="neumorph"] h3,
    html[data-ui-style="neumorph"] dd,
    html[data-ui-style="neumorph"] .metric strong{
      color:var(--text);
      text-shadow:1px 1px 0 rgba(255,255,255,.35);
    }
    html[data-ui-style="neumorph"][data-theme-mode="dark"] .hero h1,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] .card h2,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] h1,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] h2,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] h3,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] dd,
    html[data-ui-style="neumorph"][data-theme-mode="dark"] .metric strong{
      text-shadow:1px 1px 0 rgba(0,0,0,.35);
    }
    html[data-ui-style="neumorph"] .hero p,
    html[data-ui-style="neumorph"] dt,
    html[data-ui-style="neumorph"] .subtle,
    html[data-ui-style="neumorph"] .access-note,
    html[data-ui-style="neumorph"] p,
    html[data-ui-style="neumorph"] .metric span{
      color:var(--muted);
    }
    html[data-ui-style="neumorph"] .data-table th,
    html[data-ui-style="neumorph"] .data-table td,
    html[data-ui-style="neumorph"] .metric,
    html[data-ui-style="neumorph"] .summary-item,
    html[data-ui-style="neumorph"] .section{
      border-color:var(--line-soft);
    }
    html[data-ui-style="neumorph"] .sbtn,
    html[data-ui-style="neumorph"] .link,
    html[data-ui-style="neumorph"] .menu-btn,
    html[data-ui-style="neumorph"] .mode-option,
    html[data-ui-style="neumorph"] .debug-option,
    html[data-ui-style="neumorph"] .debug-close,
    html[data-ui-style="neumorph"] .cbtn{
      position:relative;
      overflow:hidden;
      background:var(--panel);
      border:0;
      border-radius:999px;
      color:var(--text);
      box-shadow:7px 7px 14px var(--neumo-lo),-7px -7px 14px var(--neumo-hi);
      backdrop-filter:none;
      -webkit-backdrop-filter:none;
    }
    html[data-ui-style="neumorph"] .sbtn::before,
    html[data-ui-style="neumorph"] .link::before,
    html[data-ui-style="neumorph"] .menu-btn::before,
    html[data-ui-style="neumorph"] .mode-option::before{
      content:none;
    }
    html[data-ui-style="neumorph"] .sbtn:hover,
    html[data-ui-style="neumorph"] .link:hover,
    html[data-ui-style="neumorph"] .menu-btn:hover,
    html[data-ui-style="neumorph"] .mode-option:hover{
      background:var(--panel);
      border:0;
      transform:translateY(-1px);
      box-shadow:9px 9px 18px var(--neumo-lo),-9px -9px 18px var(--neumo-hi);
    }
    html[data-ui-style="neumorph"] .sbtn:active,
    html[data-ui-style="neumorph"] .link:active,
    html[data-ui-style="neumorph"] .menu-btn:active,
    html[data-ui-style="neumorph"] .mode-option:active,
    html[data-ui-style="neumorph"] .debug-option:active{
      transform:translateY(0);
      box-shadow:inset 6px 6px 12px var(--neumo-lo),inset -6px -6px 12px var(--neumo-hi);
    }
    html[data-ui-style="neumorph"] .menu-btn[aria-selected="true"],
    html[data-ui-style="neumorph"] .mode-option:has(input:checked),
    html[data-ui-style="neumorph"] .debug-option[aria-pressed="true"]{
      color:var(--accent-2);
      background:var(--panel);
      border:0;
      transform:translateY(1px);
      box-shadow:inset 6px 6px 12px var(--neumo-lo),inset -6px -6px 12px var(--neumo-hi);
    }
    html[data-ui-style="neumorph"] .fld input,
    html[data-ui-style="neumorph"] .field input{
      min-height:44px;
      background:var(--panel);
      border:0;
      border-radius:999px;
      color:var(--text);
      box-shadow:inset 6px 6px 12px var(--neumo-lo),inset -6px -6px 12px var(--neumo-hi);
    }
    html[data-ui-style="neumorph"] .fld input:focus-visible,
    html[data-ui-style="neumorph"] .field input:focus-visible,
    html[data-ui-style="neumorph"] .sbtn:focus-visible,
    html[data-ui-style="neumorph"] .link:focus-visible{
      outline:2px solid color-mix(in srgb,var(--accent-2) 46%,transparent);
      outline-offset:3px;
    }
    html[data-ui-style="neumorph"] .remember input{
      accent-color:var(--accent-2);
    }
    html[data-ui-style="neumorph"] .debug-tab{
      background:var(--panel);
      border:0;
      border-radius:12px 0 0 12px;
      box-shadow:7px 7px 14px var(--neumo-lo),-5px -5px 12px var(--neumo-hi);
    }
    html[data-ui-style="neumorph"] .debug-drawer{
      border-left:0;
      border-radius:28px 0 0 28px;
    }
    html[data-ui-style="warm"]{
      color-scheme:light;
      --bg:#f5f1eb;--bg-2:#ede5db;--glass:rgba(245,241,235,.72);--glass-strong:rgba(245,241,235,.84);
      --glass-fallback:#faf7f2;--panel:rgba(245,241,235,.75);--panel-fallback:#faf7f2;--text:#3d2817;
      --muted:#6b5d52;--line:rgba(245,241,235,.88);--line-soft:rgba(61,40,23,.08);--accent:#b45309;
      --accent-2:#d97706;--accent-soft:rgba(180,83,9,.12);--warm:rgba(217,119,6,.10);--grid-line:rgba(61,40,23,.04);
      --edge-shadow:rgba(61,40,23,.10);--input-bg:rgba(245,241,235,.78);--portal-border:rgba(217,119,6,.28);
      --form-error-border:#fecaca;--form-error-bg:rgba(254,242,242,.92);--form-error-text:#b91c1c;
      --footer:#7a6f68;--note-bg:rgba(245,241,235,.68);--note-border:rgba(217,119,6,.18);--note-text:#5a4f48;--shine:.85;
      --panel-shadow:0 0 0 1px rgba(245,241,235,.84),0 2px 4px rgba(61,40,23,.06),0 12px 24px rgba(217,119,6,.08),0 20px 48px rgba(61,40,23,.06),inset 0 1px 1px rgba(255,250,247,.95),inset 0 -12px 24px rgba(217,119,6,.04);
      --panel-hover-shadow:0 0 0 1px rgba(245,241,235,.90),0 3px 6px rgba(61,40,23,.08),0 16px 32px rgba(217,119,6,.12),0 28px 64px rgba(61,40,23,.10),inset 0 1px 1px rgba(255,250,247,.98),inset 0 -14px 28px rgba(217,119,6,.06);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"]{
      color-scheme:dark;
      --bg:#1a1410;--bg-2:#251910;--glass:rgba(37,25,16,.62);--glass-strong:rgba(54,38,25,.74);
      --glass-fallback:#251910;--panel:rgba(37,25,16,.68);--panel-fallback:#251910;--text:#f3ede4;
      --muted:#d8cfc4;--line:rgba(243,237,228,.18);--line-soft:rgba(243,237,228,.10);--accent:#fbbf24;
      --accent-2:#f59e0b;--accent-soft:rgba(251,191,36,.14);--warm:rgba(245,158,11,.10);--grid-line:rgba(243,237,228,.05);
      --edge-shadow:rgba(0,0,0,.45);--input-bg:rgba(20,14,10,.55);--portal-border:rgba(251,191,36,.26);
      --form-error-border:#7f1d1d;--form-error-bg:rgba(127,29,29,.42);--form-error-text:#fecaca;
      --footer:#b8aea3;--note-bg:rgba(37,25,16,.58);--note-border:rgba(251,191,36,.20);--note-text:#d8cfc4;--shine:.38;
      --panel-shadow:0 0 0 1px rgba(243,237,228,.12),0 2px 4px rgba(0,0,0,.22),0 12px 24px rgba(0,0,0,.26),0 20px 48px rgba(0,0,0,.32),inset 0 1px 1px rgba(243,237,228,.10),inset 0 -12px 24px rgba(0,0,0,.22);
      --panel-hover-shadow:0 0 0 1px rgba(243,237,228,.16),0 3px 6px rgba(0,0,0,.28),0 16px 32px rgba(0,0,0,.32),0 28px 64px rgba(0,0,0,.38),inset 0 1px 1px rgba(243,237,228,.14),inset 0 -14px 28px rgba(0,0,0,.26);
    }
    html[data-ui-style="warm"] body{
      background:
        radial-gradient(800px 400px at 20% 10%,rgba(217,119,6,.06),rgba(217,119,6,0) 60%),
        radial-gradient(600px 300px at 80% 90%,rgba(180,83,9,.05),rgba(180,83,9,0) 55%),
        linear-gradient(180deg,#f5f1eb 0%,#ede5db 100%);
    }
    html[data-ui-style="warm"] body::before{
      background:linear-gradient(135deg,rgba(217,119,6,.03),rgba(255,255,255,0) 40%);
      opacity:.80;
    }
    html[data-ui-style="warm"] .hero,
    html[data-ui-style="warm"] .card,
    html[data-ui-style="warm"] .security-note,
    html[data-ui-style="warm"] .panel{
      border-radius:20px;
      background:linear-gradient(135deg,rgba(255,250,247,.86),rgba(255,250,247,.58) 60%,rgba(255,250,247,.78));
      border:1px solid rgba(245,241,235,.92);
      box-shadow:var(--panel-shadow);
      backdrop-filter:blur(18px) saturate(1.18) brightness(1.04);
      -webkit-backdrop-filter:blur(18px) saturate(1.18) brightness(1.04);
    }
    html[data-ui-style="warm"] .hero::before,
    html[data-ui-style="warm"] .card::before,
    html[data-ui-style="warm"] .security-note::before,
    html[data-ui-style="warm"] .panel::before{
      top:0;left:0;right:0;height:45%;
      background:linear-gradient(180deg,rgba(255,250,247,.82),rgba(255,250,247,.28),rgba(255,250,247,0));
      mix-blend-mode:screen;
      opacity:var(--shine);
    }
    html[data-ui-style="warm"] .hero::after,
    html[data-ui-style="warm"] .card::after,
    html[data-ui-style="warm"] .security-note::after,
    html[data-ui-style="warm"] .panel::after{
      inset:0;
      border-radius:inherit;
      background:linear-gradient(125deg,rgba(255,250,247,.56),rgba(255,250,247,0) 30%,rgba(255,250,247,0) 70%,rgba(255,250,247,.38));
      mix-blend-mode:normal;
      opacity:.48;
    }
    html[data-ui-style="warm"] .card:hover{
      box-shadow:var(--panel-hover-shadow);
    }
    html[data-ui-style="warm"] h1,
    html[data-ui-style="warm"] h2,
    html[data-ui-style="warm"] h3,
    html[data-ui-style="warm"] dd,
    html[data-ui-style="warm"] strong{
      color:var(--text);
    }
    html[data-ui-style="warm"] dt,
    html[data-ui-style="warm"] .subtle,
    html[data-ui-style="warm"] .access-note,
    html[data-ui-style="warm"] p,
    html[data-ui-style="warm"] span{
      color:var(--muted);
    }
    html[data-ui-style="warm"] .data-table th,
    html[data-ui-style="warm"] .data-table td{
      border-color:rgba(245,241,235,.60);
    }
    html[data-ui-style="warm"] .sbtn,
    html[data-ui-style="warm"] .link,
    html[data-ui-style="warm"] .menu-btn,
    html[data-ui-style="warm"] .mode-option,
    html[data-ui-style="warm"] .debug-option{
      position:relative;
      overflow:hidden;
      border-radius:12px;
      background:linear-gradient(135deg,rgba(255,250,247,.86),rgba(255,250,247,.58) 60%,rgba(255,250,247,.78));
      border:1px solid rgba(245,241,235,.90);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(245,241,235,.78),0 4px 12px rgba(217,119,6,.08),0 12px 28px rgba(61,40,23,.05),inset 0 1px 1px rgba(255,250,247,.95),inset 0 -8px 16px rgba(217,119,6,.03);
    }
    html[data-ui-style="warm"] .sbtn::before,
    html[data-ui-style="warm"] .link::before,
    html[data-ui-style="warm"] .menu-btn::before,
    html[data-ui-style="warm"] .mode-option::before{
      content:"";position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(255,250,247,.68),rgba(255,250,247,.18),rgba(255,250,247,0));
      pointer-events:none;opacity:.58;
    }
    html[data-ui-style="warm"] .sbtn:hover,
    html[data-ui-style="warm"] .link:hover,
    html[data-ui-style="warm"] .menu-btn:hover,
    html[data-ui-style="warm"] .mode-option:hover{
      background:linear-gradient(135deg,rgba(255,250,247,.92),rgba(255,250,247,.66) 60%,rgba(255,250,247,.86));
      border-color:rgba(245,241,235,.96);
      transform:translateY(-2px);
      box-shadow:0 0 0 1px rgba(245,241,235,.84),0 6px 16px rgba(217,119,6,.12),0 16px 36px rgba(61,40,23,.08),inset 0 1px 1px rgba(255,250,247,.98),inset 0 -8px 16px rgba(217,119,6,.05);
    }
    html[data-ui-style="warm"] .sbtn:active,
    html[data-ui-style="warm"] .link:active,
    html[data-ui-style="warm"] .menu-btn:active,
    html[data-ui-style="warm"] .mode-option:active{
      transform:translateY(0);
      box-shadow:inset 0 2px 6px rgba(217,119,6,.10),0 2px 6px rgba(61,40,23,.06);
    }
    html[data-ui-style="warm"] .menu-btn[aria-selected="true"],
    html[data-ui-style="warm"] .mode-option:has(input:checked),
    html[data-ui-style="warm"] .debug-option[aria-pressed="true"]{
      background:linear-gradient(135deg,rgba(180,83,9,.18),rgba(180,83,9,.10) 60%);
      border-color:rgba(180,83,9,.40);
      color:var(--text);
      transform:translateY(1px);
      box-shadow:0 0 0 1px rgba(180,83,9,.40),inset 0 3px 8px rgba(180,83,9,.18),inset 0 1px 3px rgba(61,40,23,.10);
    }
    html[data-ui-style="warm"] .sbtn{
      background:linear-gradient(135deg,rgba(255,250,247,.76),rgba(255,250,247,.46) 60%,rgba(255,250,247,.68)),linear-gradient(180deg,#b45309 0%,#a16207 100%);
      border-color:rgba(255,245,230,.44);
      color:#fff;
      box-shadow:0 0 0 1px rgba(255,245,230,.34),0 6px 16px rgba(180,83,9,.18),0 16px 36px rgba(180,83,9,.12),inset 0 1px 1px rgba(255,250,247,.56),inset 0 -10px 18px rgba(0,0,0,.08);
    }
    html[data-ui-style="warm"] .sbtn:hover{
      background:linear-gradient(135deg,rgba(255,250,247,.86),rgba(255,250,247,.56) 60%,rgba(255,250,247,.78)),linear-gradient(180deg,#b8530f 0%,#b45309 100%);
      box-shadow:0 0 0 1px rgba(255,245,230,.40),0 8px 20px rgba(180,83,9,.24),0 20px 44px rgba(180,83,9,.18),inset 0 1px 1px rgba(255,250,247,.66),inset 0 -10px 18px rgba(0,0,0,.12);
    }
    html[data-ui-style="warm"] .fld input,
    html[data-ui-style="warm"] .field input,
    html[data-ui-style="warm"] .cbtn,
    html[data-ui-style="warm"] .debug-close{
      border-radius:12px;
      min-height:44px;
      background:linear-gradient(135deg,rgba(255,250,247,.86),rgba(255,250,247,.58) 60%,rgba(255,250,247,.78));
      border:1px solid rgba(245,241,235,.90);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(245,241,235,.78),0 4px 12px rgba(217,119,6,.06),inset 0 1px 1px rgba(255,250,247,.95),inset 0 -6px 12px rgba(217,119,6,.03);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] body{
      background:
        radial-gradient(800px 400px at 20% 10%,rgba(251,191,36,.05),rgba(251,191,36,0) 60%),
        radial-gradient(600px 300px at 80% 90%,rgba(245,158,11,.04),rgba(245,158,11,0) 55%),
        linear-gradient(180deg,#1a1410 0%,#251910 100%);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] body::before{
      background:linear-gradient(135deg,rgba(251,191,36,.02),rgba(255,255,255,0) 40%);
      opacity:.60;
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .hero,
    html[data-ui-style="warm"][data-theme-mode="dark"] .card,
    html[data-ui-style="warm"][data-theme-mode="dark"] .security-note,
    html[data-ui-style="warm"][data-theme-mode="dark"] .panel{
      background:linear-gradient(135deg,rgba(54,38,25,.78),rgba(37,25,16,.56) 60%,rgba(37,25,16,.70));
      border-color:rgba(243,237,228,.12);
      box-shadow:var(--panel-shadow);
      backdrop-filter:blur(16px) saturate(1.12) brightness(.96);
      -webkit-backdrop-filter:blur(16px) saturate(1.12) brightness(.96);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .hero::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .card::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .security-note::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .panel::before{
      background:linear-gradient(180deg,rgba(243,237,228,.12),rgba(243,237,228,.04),rgba(243,237,228,0));
      opacity:var(--shine);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .hero::after,
    html[data-ui-style="warm"][data-theme-mode="dark"] .card::after,
    html[data-ui-style="warm"][data-theme-mode="dark"] .security-note::after,
    html[data-ui-style="warm"][data-theme-mode="dark"] .panel::after{
      background:linear-gradient(125deg,rgba(243,237,228,.08),rgba(243,237,228,0) 30%,rgba(243,237,228,0) 70%,rgba(243,237,228,.06));
      opacity:.32;
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .sbtn,
    html[data-ui-style="warm"][data-theme-mode="dark"] .link,
    html[data-ui-style="warm"][data-theme-mode="dark"] .menu-btn,
    html[data-ui-style="warm"][data-theme-mode="dark"] .mode-option,
    html[data-ui-style="warm"][data-theme-mode="dark"] .debug-option{
      background:linear-gradient(135deg,rgba(54,38,25,.78),rgba(37,25,16,.56) 60%,rgba(37,25,16,.70));
      border-color:rgba(243,237,228,.10);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(243,237,228,.10),0 4px 12px rgba(0,0,0,.28),0 12px 28px rgba(0,0,0,.32),inset 0 1px 1px rgba(243,237,228,.08),inset 0 -8px 16px rgba(0,0,0,.22);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .sbtn::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .link::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .menu-btn::before,
    html[data-ui-style="warm"][data-theme-mode="dark"] .mode-option::before{
      background:linear-gradient(180deg,rgba(243,237,228,.10),rgba(243,237,228,.04),rgba(243,237,228,0));
      opacity:.36;
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .sbtn:hover,
    html[data-ui-style="warm"][data-theme-mode="dark"] .link:hover,
    html[data-ui-style="warm"][data-theme-mode="dark"] .menu-btn:hover,
    html[data-ui-style="warm"][data-theme-mode="dark"] .mode-option:hover{
      background:linear-gradient(135deg,rgba(74,56,40,.88),rgba(54,38,25,.68) 60%,rgba(54,38,25,.80));
      border-color:rgba(243,237,228,.14);
      box-shadow:0 0 0 1px rgba(243,237,228,.14),0 6px 16px rgba(0,0,0,.34),0 16px 36px rgba(0,0,0,.38),inset 0 1px 1px rgba(243,237,228,.12),inset 0 -8px 16px rgba(0,0,0,.26);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .menu-btn[aria-selected="true"]{
      color:#fbbf24;
      border-color:rgba(251,191,36,.55);
      background:linear-gradient(135deg,rgba(245,158,11,.22),rgba(251,191,36,.10) 60%,rgba(245,158,11,.18));
      box-shadow:0 0 0 1px rgba(251,191,36,.50),inset 0 3px 8px rgba(180,83,9,.38),inset 0 1px 3px rgba(0,0,0,.32);
      transform:translateY(1px);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .sbtn{
      background:linear-gradient(135deg,rgba(243,237,228,.12),rgba(243,237,228,.04) 60%,rgba(243,237,228,.08)),linear-gradient(180deg,#fbbf24 0%,#f59e0b 100%);
      border-color:rgba(243,237,228,.12);
      color:#1a1410;
      box-shadow:0 0 0 1px rgba(243,237,228,.10),0 6px 16px rgba(251,191,36,.18),0 16px 36px rgba(251,191,36,.12),inset 0 1px 1px rgba(243,237,228,.12),inset 0 -10px 18px rgba(0,0,0,.18);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .sbtn:hover{
      background:linear-gradient(135deg,rgba(243,237,228,.18),rgba(243,237,228,.08) 60%,rgba(243,237,228,.14)),linear-gradient(180deg,#fcd34d 0%,#fbbf24 100%);
      box-shadow:0 0 0 1px rgba(243,237,228,.14),0 8px 20px rgba(251,191,36,.26),0 20px 44px rgba(251,191,36,.20),inset 0 1px 1px rgba(243,237,228,.16),inset 0 -10px 18px rgba(0,0,0,.22);
    }
    html[data-ui-style="warm"][data-theme-mode="dark"] .fld input,
    html[data-ui-style="warm"][data-theme-mode="dark"] .field input,
    html[data-ui-style="warm"][data-theme-mode="dark"] .cbtn,
    html[data-ui-style="warm"][data-theme-mode="dark"] .debug-close{
      background:linear-gradient(135deg,rgba(54,38,25,.78),rgba(37,25,16,.56) 60%,rgba(37,25,16,.70));
      border-color:rgba(243,237,228,.10);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(243,237,228,.10),0 4px 12px rgba(0,0,0,.28),inset 0 1px 1px rgba(243,237,228,.08),inset 0 -6px 12px rgba(0,0,0,.20);
    }
    .debug-tab{
      position:fixed;right:0;top:50%;z-index:60;transform:translateY(-50%);
      border:1px solid var(--line);border-right:0;border-radius:8px 0 0 8px;
      background:var(--glass-strong);color:var(--text);padding:10px 8px;font-size:12px;font-weight:700;
      box-shadow:0 10px 24px rgba(29,42,46,.18),inset 1px 1px 0 rgba(255,255,255,.54);
      cursor:pointer;writing-mode:vertical-rl;letter-spacing:.02em;
      backdrop-filter:blur(18px) saturate(1.2);-webkit-backdrop-filter:blur(18px) saturate(1.2);
    }
    .debug-drawer{
      position:fixed;right:0;top:0;bottom:0;z-index:70;width:min(320px,calc(100vw - 24px));
      padding:18px;background:var(--glass-strong);color:var(--text);border-left:1px solid var(--line);
      box-shadow:-24px 0 58px rgba(20,34,38,.22),inset 1px 0 0 rgba(255,255,255,.28);
      transform:translateX(100%);transition:transform .18s ease;
      backdrop-filter:blur(22px) saturate(1.35);-webkit-backdrop-filter:blur(22px) saturate(1.35);
    }
    html[data-debug-open="true"] .debug-drawer{transform:translateX(0)}
    html[data-debug-open="true"] .debug-tab{display:none}
    .debug-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px}
    .debug-title{font-size:15px;font-weight:800}
    .debug-close{inline-size:32px;block-size:32px;border-radius:999px;border:1px solid var(--line);background:var(--input-bg);color:var(--text);cursor:pointer;font-weight:800}
    .debug-group{display:grid;gap:8px;margin-bottom:18px}
    .debug-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:800}
    .debug-seg{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}
    .debug-seg.style{grid-template-columns:repeat(4,1fr)}
    .debug-option{min-height:34px;border:1px solid var(--line);border-radius:8px;background:var(--input-bg);color:var(--text);font-size:12px;font-weight:700;cursor:pointer;transition:background-color .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease}
    .debug-option[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-soft);transform:translateY(-1px);box-shadow:inset 1px 1px 0 rgba(255,255,255,.34),0 8px 18px rgba(15,138,112,.13)}
    html[data-ui-style="crystal"][data-theme-mode="dark"] .debug-option{opacity:.55}
    html[data-ui-style="crystal"][data-theme-mode="dark"] .debug-option[aria-pressed="true"]{opacity:1;color:#38bdf8!important;border-color:#38bdf8!important;background:rgba(56,189,248,.22)!important;transform:translateY(-2px);box-shadow:0 0 0 2px #38bdf8,0 8px 20px rgba(56,189,248,.35)!important}
    html[data-ui-style="warm"][data-theme-mode="dark"] .debug-option{opacity:.55}
    html[data-ui-style="warm"][data-theme-mode="dark"] .debug-option[aria-pressed="true"]{opacity:1;color:#fbbf24!important;border-color:#fbbf24!important;background:rgba(251,191,36,.22)!important;transform:translateY(-2px);box-shadow:0 0 0 2px #fbbf24,0 8px 20px rgba(251,191,36,.35)!important}
    @media (prefers-color-scheme:dark){
      html[data-ui-style="crystal"][data-theme-mode="auto"] .debug-option{opacity:.55}
      html[data-ui-style="crystal"][data-theme-mode="auto"] .debug-option[aria-pressed="true"]{opacity:1;color:#38bdf8!important;border-color:#38bdf8!important;background:rgba(56,189,248,.22)!important;transform:translateY(-2px);box-shadow:0 0 0 2px #38bdf8,0 8px 20px rgba(56,189,248,.35)!important}
      html[data-ui-style="crystal"][data-theme-mode="auto"] .menu-btn[aria-selected="true"]{color:#38bdf8;border-color:rgba(56,189,248,.55);background:linear-gradient(135deg,rgba(14,165,233,.20),rgba(56,189,248,.10) 60%,rgba(14,165,233,.16));box-shadow:0 0 0 1px rgba(56,189,248,.50),inset 0 3px 8px rgba(14,116,144,.40),inset 0 1px 3px rgba(0,0,0,.30);transform:translateY(1px)}
      html[data-ui-style="warm"][data-theme-mode="auto"] .debug-option{opacity:.55}
      html[data-ui-style="warm"][data-theme-mode="auto"] .debug-option[aria-pressed="true"]{opacity:1;color:#fbbf24!important;border-color:#fbbf24!important;background:rgba(251,191,36,.22)!important;transform:translateY(-2px);box-shadow:0 0 0 2px #fbbf24,0 8px 20px rgba(251,191,36,.35)!important}
      html[data-ui-style="warm"][data-theme-mode="auto"] .menu-btn[aria-selected="true"]{color:#fbbf24;border-color:rgba(251,191,36,.55);background:linear-gradient(135deg,rgba(245,158,11,.22),rgba(251,191,36,.10) 60%,rgba(245,158,11,.18));box-shadow:0 0 0 1px rgba(251,191,36,.50),inset 0 3px 8px rgba(180,83,9,.38),inset 0 1px 3px rgba(0,0,0,.32);transform:translateY(1px)}
    }
    html[data-ui-style="crystal"][data-theme-mode="light"] .debug-option{opacity:.95}
    html[data-ui-style="crystal"][data-theme-mode="light"] .debug-option[aria-pressed="true"]{opacity:1;color:#0f766e!important;border-color:#0f766e!important;background:rgba(15,118,110,.16)!important;transform:translateY(-1px);box-shadow:inset 1px 1px 0 rgba(255,255,255,.34),0 4px 12px rgba(15,138,112,.13)!important}
    html[data-ui-style="warm"][data-theme-mode="light"] .debug-option{opacity:.95}
    html[data-ui-style="warm"][data-theme-mode="light"] .debug-option[aria-pressed="true"]{opacity:1;color:#b45309!important;border-color:#b45309!important;background:rgba(180,83,9,.14)!important;transform:translateY(-1px);box-shadow:inset 1px 1px 0 rgba(255,255,255,.34),0 4px 12px rgba(180,83,9,.11)!important}
    .debug-note{font-size:12px;line-height:1.5;color:var(--muted)}
    @media (max-width:640px){
      .debug-tab{top:auto;bottom:18px;writing-mode:horizontal-tb;border-right:1px solid var(--line);border-radius:8px 0 0 8px}
    }
  </style>"""


def render_debug_panel() -> str:
    return """<button class="debug-tab" type="button" data-debug-open>Debug</button>
<aside class="debug-drawer" aria-label="Theme panel">
  <div class="debug-head">
    <div class="debug-title">Theme</div>
    <button class="debug-close" type="button" data-debug-close aria-label="Close debug panel">X</button>
  </div>
  <div class="debug-group">
    <div class="debug-label">Mode</div>
    <div class="debug-seg" style="grid-template-columns:repeat(3,1fr)">
      <button class="debug-option" type="button" data-theme-option="auto">Auto</button>
      <button class="debug-option" type="button" data-theme-option="light">Light</button>
      <button class="debug-option" type="button" data-theme-option="dark">Dark</button>
    </div>
  </div>
  <div class="debug-group">
    <div class="debug-label">Style</div>
    <div class="debug-seg style">
      <button class="debug-option" type="button" data-style-option="glass">Glass</button>
      <button class="debug-option" type="button" data-style-option="crystal">Crystal</button>
      <button class="debug-option" type="button" data-style-option="warm">Warm</button>
      <button class="debug-option" type="button" data-style-option="neumorph">Neumo</button>
    </div>
  </div>
  <p class="debug-note">Theme and style are saved only in this browser.</p>
</aside>"""


def render_debug_panel_script() -> str:
    return """<script>
  (function () {
    var root = document.documentElement;
    var themeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-theme-option]'));
    var styleButtons = Array.prototype.slice.call(document.querySelectorAll('[data-style-option]'));
    var openButton = document.querySelector('[data-debug-open]');
    var closeButton = document.querySelector('[data-debug-close]');
    var mediaQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    var themePref = root.dataset.themePref || localStorage.getItem('bmi30.portal.theme') || 'auto';
    if (themePref !== 'auto' && themePref !== 'light' && themePref !== 'dark') {
      themePref = 'auto';
    }
    var style = root.dataset.uiStyle || 'crystal';
    if (style !== 'glass' && style !== 'crystal' && style !== 'warm' && style !== 'neumorph') {
      style = 'crystal';
    }
    root.dataset.uiStyle = style;

    function store(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch (error) {}
    }

    function resolveTheme(pref) {
      if (pref === 'auto') {
        return (mediaQuery && mediaQuery.matches) ? 'dark' : 'light';
      }
      return pref;
    }

    function paintButtons() {
      themeButtons.forEach(function (button) {
        button.setAttribute('aria-pressed', button.dataset.themeOption === themePref ? 'true' : 'false');
      });
      styleButtons.forEach(function (button) {
        button.setAttribute('aria-pressed', button.dataset.styleOption === style ? 'true' : 'false');
      });
    }

    function applyTheme(pref, persist) {
      themePref = pref || 'auto';
      if (themePref !== 'auto' && themePref !== 'light' && themePref !== 'dark') {
        themePref = 'auto';
      }
      root.dataset.themePref = themePref;
      root.dataset.themeMode = resolveTheme(themePref);
      if (persist !== false) {
        store('bmi30.portal.theme', themePref);
      }
      paintButtons();
    }

    function setStyle(nextStyle) {
      style = nextStyle || 'crystal';
      if (style !== 'glass' && style !== 'crystal' && style !== 'warm' && style !== 'neumorph') {
        style = 'crystal';
      }
      root.dataset.uiStyle = style;
      store('bmi30.portal.style', style);
      paintButtons();
    }

    themeButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        applyTheme(button.dataset.themeOption, true);
      });
    });
    styleButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        setStyle(button.dataset.styleOption);
      });
    });
    if (mediaQuery) {
      var handleSystemThemeChange = function () {
        if (themePref === 'auto') {
          applyTheme('auto', false);
        }
      };
      if (typeof mediaQuery.addEventListener === 'function') {
        mediaQuery.addEventListener('change', handleSystemThemeChange);
      } else if (typeof mediaQuery.addListener === 'function') {
        mediaQuery.addListener(handleSystemThemeChange);
      }
    }
    if (openButton) {
      openButton.addEventListener('click', function () {
        root.dataset.debugOpen = 'true';
      });
    }
    if (closeButton) {
      closeButton.addEventListener('click', function () {
        delete root.dataset.debugOpen;
      });
    }
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        delete root.dataset.debugOpen;
      }
    });
    applyTheme(themePref, false);
  }());
</script>"""


def _nmcli_unescape(value: str) -> str:
    result: list[str] = []
    escaped = False
    for ch in value:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            result.append(ch)
    if escaped:
        result.append("\\")
    return "".join(result)


def _split_nmcli_terse_line(line: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return parts


def _run_nmcli_result(*args: str, timeout: float = 12.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ("nmcli", *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)
    output = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, output


def _is_hotspot_connection(connection_id: str, device: str = "") -> bool:
    lowered_device = device.lower()
    if lowered_device == "wlan0ap":
        return True
    mode = run_command("nmcli", "-g", "802-11-wireless.mode", "connection", "show", connection_id).strip().lower()
    ipv4_method = run_command("nmcli", "-g", "ipv4.method", "connection", "show", connection_id).strip().lower()
    iface = run_command("nmcli", "-g", "connection.interface-name", "connection", "show", connection_id).strip().lower()
    conn_ssid = run_command("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", connection_id).strip()
    lowered_name = connection_id.lower()
    return (
        mode == "ap"
        or ipv4_method == "shared"
        or iface == "wlan0ap"
        or lowered_name.startswith("hotspot")
        or conn_ssid.startswith("BMI30-")
        or conn_ssid.startswith("BMI30.")
    )


def detect_hotspot_connection() -> dict[str, Any]:
    info: dict[str, Any] = {
        "ssid": "",
        "connection_id": "",
        "interface": "wlan0ap",
    }
    output = run_command("nmcli", "-t", "-f", "DEVICE,NAME,UUID,TYPE", "connection", "show", "--active")
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) < 4:
            continue
        device, name, _uuid, conn_type = parts[:4]
        if conn_type in {"wifi", "802-11-wireless"} and _is_hotspot_connection(name, device):
            info["interface"] = device or "wlan0ap"
            info["connection_id"] = name
            info["ssid"] = run_command("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name)
            if not info["ssid"]:
                info["ssid"] = name
            break
    if not info["connection_id"]:
        output = run_command("nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show")
        for line in output.splitlines():
            parts = _split_nmcli_terse_line(line)
            if len(parts) < 3:
                continue
            name, _uuid, conn_type = parts[:3]
            if conn_type in {"wifi", "802-11-wireless"} and _is_hotspot_connection(name):
                info["connection_id"] = name
                info["ssid"] = run_command("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name) or name
                info["interface"] = run_command("nmcli", "-g", "connection.interface-name", "connection", "show", name) or "wlan0ap"
                break
    return info


def scan_visible_wifi_networks() -> list[dict[str, str]]:
    ok, output = _run_nmcli_result(
        "-t",
        "-f",
        "SSID,SECURITY,SIGNAL,IN-USE",
        "dev",
        "wifi",
        "list",
        "--rescan",
        "yes",
        timeout=10.0,
    )
    if not ok:
        return []

    by_ssid: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) < 4:
            continue
        ssid, security, signal, in_use = (_nmcli_unescape(part).strip() for part in parts[:4])
        if not ssid:
            continue
        existing = by_ssid.get(ssid)
        if existing is None or int(signal or "0") > int(existing.get("signal") or "0"):
            by_ssid[ssid] = {
                "ssid": ssid,
                "security": security or "open",
                "signal": signal or "0",
                "in_use": "yes" if in_use == "*" else "",
            }
    return sorted(by_ssid.values(), key=lambda item: (item.get("in_use") != "yes", -int(item.get("signal") or "0"), item["ssid"].lower()))


def _reactivate_hotspot_connection(old_connection_id: str, new_connection_id: str) -> None:
    time.sleep(1.5)
    _run_nmcli_result("connection", "down", old_connection_id, timeout=8.0)
    up_ok, _message = _run_nmcli_result("connection", "up", new_connection_id, timeout=20.0)
    if not up_ok and old_connection_id != new_connection_id:
        _run_nmcli_result("connection", "up", old_connection_id, timeout=20.0)


def apply_hotspot_access_settings(ssid: str, password: str = "") -> tuple[bool, str]:
    ssid = ssid.strip()
    if not ssid or len(ssid.encode("utf-8")) > 32:
        return False, "HotSpot SSID must be 1-32 bytes long."
    if password and not (8 <= len(password) <= 63):
        return False, "HotSpot password must contain 8-63 characters."

    hotspot = detect_hotspot_connection()
    connection_id = hotspot.get("connection_id") or HOTSPOT_CONN
    ok, message = _run_nmcli_result("connection", "show", connection_id, timeout=6.0)
    if not ok:
        return False, message or "HotSpot connection profile was not found."

    args = [
        "connection",
        "modify",
        connection_id,
        "connection.id",
        ssid,
        "802-11-wireless.ssid",
        ssid,
        "802-11-wireless.mode",
        "ap",
        "ipv4.method",
        "shared",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "connection.autoconnect",
        "yes",
    ]
    if password:
        args.extend(["wifi-sec.psk", password])
    ok, message = _run_nmcli_result(*args, timeout=12.0)
    if not ok:
        return False, message or "NetworkManager rejected HotSpot settings."

    run_command("nmcli", "connection", "reload")
    save_hotspot_access_metadata(ssid, bool(password))
    threading.Thread(target=_reactivate_hotspot_connection, args=(connection_id, ssid), daemon=True).start()
    return True, "HotSpot settings saved. The access point will restart in a moment."


def connect_wifi_internet(ssid: str, password: str = "") -> tuple[bool, str]:
    ssid = ssid.strip()
    if not ssid:
        return False, "Select or type a Wi-Fi network name."
    if len(ssid.encode("utf-8")) > 32:
        return False, "Wi-Fi SSID must be 1-32 bytes long."

    args = ["dev", "wifi", "connect", ssid, "ifname", WIFI_STA_IFACE]
    if password:
        args.extend(["password", password])
    ok, message = _run_nmcli_result(*args, timeout=35.0)
    save_wifi_internet_metadata(ssid, ok, message)
    if not ok:
        return False, message or "Unable to connect to Wi-Fi."
    return True, message or "Wi-Fi connection saved."


def _active_connection_for_device(device: str) -> str:
    output = run_command("nmcli", "-t", "-f", "DEVICE,CONNECTION", "dev", "status")
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) >= 2 and parts[0] == device:
            return _nmcli_unescape(parts[1]).strip()
    return ""


def _ethernet_connection_names() -> list[str]:
    output = run_command("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show")
    names: list[str] = []
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) >= 2 and parts[1] in {"802-3-ethernet", "ethernet"}:
            names.append(_nmcli_unescape(parts[0]).strip())
    return [name for name in names if name]


def _systemctl(*args: str, timeout: float = 20.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ("systemctl", *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()


def apply_channel_permission(channel: str, enabled: bool) -> tuple[bool, str]:
    if channel not in CHANNEL_KEYS:
        return False, "Unknown communication channel."

    save_channel_permission(channel, enabled)

    if channel == "hotspot":
        hotspot = detect_hotspot_connection()
        connection_id = hotspot.get("connection_id") or HOTSPOT_CONN
        if enabled:
            _systemctl("enable", "bmi30-hotspot.service", timeout=12.0)
            ok, message = _systemctl("restart", "bmi30-hotspot.service", timeout=25.0)
            if not ok:
                _run_nmcli_result("connection", "up", connection_id, timeout=20.0)
            return True, message or "HotSpot enabled."
        _systemctl("stop", "bmi30-hotspot.service", timeout=15.0)
        _systemctl("disable", "bmi30-hotspot.service", timeout=12.0)
        if connection_id:
            _run_nmcli_result("connection", "down", connection_id, timeout=12.0)
        return True, "HotSpot disabled."

    if channel == "wifi":
        active_connection = _active_connection_for_device(WIFI_STA_IFACE)
        if enabled:
            saved_raw = _load_config_json().get("wifi_internet")
            saved = saved_raw if isinstance(saved_raw, dict) else {}
            saved_ssid = str(saved.get("ssid") or "").strip()
            if saved_ssid:
                _run_nmcli_result("connection", "modify", saved_ssid, "connection.autoconnect", "yes", timeout=8.0)
                _run_nmcli_result("connection", "up", saved_ssid, timeout=25.0)
            else:
                _run_nmcli_result("device", "connect", WIFI_STA_IFACE, timeout=20.0)
            return True, "Internet Wi-Fi enabled."
        if active_connection:
            _run_nmcli_result("connection", "modify", active_connection, "connection.autoconnect", "no", timeout=8.0)
        _run_nmcli_result("device", "disconnect", WIFI_STA_IFACE, timeout=15.0)
        return True, "Internet Wi-Fi disabled."

    if channel == "ethernet":
        ethernet_names = _ethernet_connection_names()
        for name in ethernet_names:
            _run_nmcli_result("connection", "modify", name, "connection.autoconnect", "yes" if enabled else "no", timeout=8.0)
            if enabled:
                _run_nmcli_result("connection", "up", name, timeout=12.0)
            else:
                _run_nmcli_result("connection", "down", name, timeout=8.0)
        return True, "Ethernet enabled." if enabled else "Ethernet disabled."

    if channel == "remote":
        units = ("xrdp-sesman.service", "xrdp.service", "bmi30-x11vnc.service")
        if enabled:
            for unit in units:
                _systemctl("enable", unit, timeout=10.0)
            for unit in units:
                _systemctl("restart", unit, timeout=20.0)
            return True, "RDP/VNC enabled."
        for unit in reversed(units):
            _systemctl("stop", unit, timeout=15.0)
            _systemctl("disable", unit, timeout=10.0)
        return True, "RDP/VNC disabled."

    return False, "Unknown communication channel."


def count_hotspot_clients(interface: str = "wlan0ap") -> int:
    output = run_command("iw", "dev", interface or "wlan0ap", "station", "dump")
    return sum(1 for line in output.splitlines() if line.startswith("Station "))


def is_wifi_internet_connected(interface: str = WIFI_STA_IFACE) -> bool:
    return bool(detect_wifi_internet_connection(interface).get("connected"))


def detect_wifi_internet_connection(interface: str = WIFI_STA_IFACE) -> dict[str, Any]:
    output = run_command("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status")
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) >= 4 and parts[0] == interface and parts[1] == "wifi":
            connected = parts[2].lower() == "connected"
            connection = _nmcli_unescape(parts[3]).strip()
            ssid = run_command("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", connection) if connection else ""
            return {
                "connected": connected,
                "ssid": ssid or connection,
                "connection": connection,
            }
    return {"connected": False, "ssid": "", "connection": ""}


def _ethernet_has_carrier(device: str) -> bool:
    if not device or device == "lo" or device.startswith(("veth", "br-", "docker", "virbr")):
        return False
    carrier_path = f"/sys/class/net/{device}/carrier"
    try:
        with open(carrier_path, "r", encoding="utf-8") as f:
            return f.read().strip() == "1"
    except Exception:
        return False


def count_ethernet_connections() -> int:
    output = run_command("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev", "status")
    count = 0
    for line in output.splitlines():
        parts = _split_nmcli_terse_line(line)
        if len(parts) >= 3 and parts[1] == "ethernet" and parts[2].lower() == "connected" and _ethernet_has_carrier(parts[0]):
            count += 1
    return count


def _host_part(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if endpoint.startswith("[") and "]" in endpoint:
        return endpoint[1:endpoint.index("]")].split("%", 1)[0]
    if ":" in endpoint:
        return endpoint.rsplit(":", 1)[0].split("%", 1)[0]
    return endpoint.split("%", 1)[0]


def _port_part(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if endpoint.startswith("[") and "]:" in endpoint:
        return endpoint.rsplit("]:", 1)[-1]
    if ":" in endpoint:
        return endpoint.rsplit(":", 1)[-1]
    return ""


def _is_loopback_host(host: str) -> bool:
    host = host.strip("[]")
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def count_remote_desktop_connections() -> int:
    ports = {str(RDP_PORT), "5901"}
    output = run_command("ss", "-Htn", "state", "established")
    clients: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[2]
        peer = parts[3]
        local_port = _port_part(local)
        peer_host = _host_part(peer)
        if local_port in ports and peer_host and not _is_loopback_host(peer_host):
            clients.add(peer_host)
    return len(clients)


def _valid_linux_username(username: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username))


def _user_exists(username: str) -> bool:
    return bool(run_command("getent", "passwd", username))


def _groups_for_new_remote_user() -> list[str]:
    groups = run_command("id", "-nG", SSH_USER).split()
    skip = {SSH_USER, "root"}
    return [group for group in groups if group and group not in skip]


def _ensure_remote_user(username: str, password: str) -> tuple[bool, str]:
    if _user_exists(username):
        return True, ""
    if not password:
        return False, "Password is required when creating a new remote desktop login."
    groups = ",".join(_groups_for_new_remote_user())
    args = ["useradd", "-m", "-s", "/bin/bash"]
    if groups:
        args.extend(["-G", groups])
    args.append(username)
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True, timeout=12.0)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "Unable to create remote desktop user.").strip()
    return True, ""


def _set_system_user_password(username: str, password: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["chpasswd"],
            input=f"{username}:{password}\n",
            check=False,
            capture_output=True,
            text=True,
            timeout=12.0,
        )
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "Unable to set system password.").strip()
    return True, ""


def _store_x11vnc_password(password: str) -> tuple[bool, str]:
    secret_path = "/etc/bmi30/x11vnc.pass"
    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    try:
        proc = subprocess.run(
            ["x11vnc", "-storepasswd", password, secret_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=12.0,
        )
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "Unable to store VNC password.").strip()
    try:
        os.chmod(secret_path, 0o600)
    except Exception:
        pass
    return True, ""


def _ensure_x11vnc_rfbauth() -> None:
    service_path = "/etc/systemd/system/bmi30-x11vnc.service"
    secret_path = "/etc/bmi30/x11vnc.pass"
    try:
        with open(service_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return
    if "-rfbauth" in content:
        return
    lines = []
    changed = False
    for line in content.splitlines():
        if line.startswith("ExecStart=") and "x11vnc" in line:
            if " -rfbport " in line:
                line = line.replace(" -rfbport ", f" -rfbauth {secret_path} -rfbport ", 1)
            else:
                line = f"{line} -rfbauth {secret_path}"
            changed = True
        lines.append(line)
    if not changed:
        return
    backup_path = f"{service_path}.bak.{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        with open(service_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        return
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True, text=True, timeout=10.0)


def apply_remote_desktop_credentials(username: str, password: str = "") -> tuple[bool, str]:
    username = username.strip()
    if not _valid_linux_username(username):
        return False, "Remote desktop login must be a valid Linux username: lowercase letters, digits, _ or -."
    if password and len(password) < 8:
        return False, "Remote desktop password must contain at least 8 characters."
    ok, message = _ensure_remote_user(username, password)
    if not ok:
        return False, message
    if password:
        ok, message = _set_system_user_password(username, password)
        if not ok:
            return False, message
        ok, message = _store_x11vnc_password(password)
        if not ok:
            return False, message
        _ensure_x11vnc_rfbauth()
        subprocess.run(["systemctl", "restart", "bmi30-x11vnc.service"], check=False, capture_output=True, text=True, timeout=15.0)
    save_remote_desktop_metadata(username, bool(password))
    return True, "Remote desktop credentials saved."


def collect_ipv4_interfaces() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    output = run_command("ip", "-o", "-4", "addr", "show", "up")
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[1]
        cidr = parts[3]
        ip = cidr.split("/", 1)[0]
        role = classify_interface(iface, ip)
        items.append({"iface": iface, "ip": ip, "cidr": cidr, "role": role})
    return items


def classify_interface(iface: str, ip: str) -> str:
    lowered = iface.lower()
    if lowered == "lo":
        return "loopback"
    if lowered == "wlan0ap" or ip.startswith("10.42."):
        return "hotspot"
    if lowered.startswith("eth"):
        return "ethernet"
    if lowered.startswith("wlan"):
        return "wifi"
    return "other"


def detect_hostname_candidates() -> list[str]:
    names: list[str] = []
    host = socket.gethostname().strip()
    if host:
        names.append(host)
        names.append(f"{host}.local")
    pretty = run_command("hostnamectl", "--pretty")
    if pretty:
        names.append(pretty)
    result: list[str] = []
    for item in names:
        if item and item not in result:
            result.append(item)
    return result


def detect_default_route() -> str:
    output = run_command("ip", "route")
    for line in output.splitlines():
        if not line.startswith("default "):
            continue
        parts = line.split()
        if "dev" in parts:
            idx = parts.index("dev")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return ""


def extract_request_host_ip(host_header: str) -> str | None:
    if not host_header:
        return None

    candidate = host_header.strip()
    if not candidate:
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    elif candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _group_publication_ip(preferred_ip: str | None = None) -> str | None:
    """Choose the most useful local IPv4 address for RS485 identity.

    Priority: router/default-route address, the exact local address used to
    open Portal, then an active Ethernet/Wi-Fi/hotspot address.
    """
    interfaces = collect_ipv4_interfaces()
    usable = [
        item for item in interfaces
        if item.get("role") != "loopback" and item.get("ip")
    ]

    default_iface = detect_default_route()
    if default_iface:
        for item in usable:
            if item.get("iface") == default_iface:
                return str(item["ip"])

    try:
        preferred = str(ipaddress.ip_address(str(preferred_ip or "").strip()))
    except ValueError:
        preferred = ""
    if preferred and any(item.get("ip") == preferred for item in usable):
        return preferred

    role_order = {"ethernet": 0, "wifi": 1, "hotspot": 2, "other": 3}
    usable.sort(key=lambda item: role_order.get(str(item.get("role")), 9))
    if usable:
        return str(usable[0]["ip"])

    try:
        fallback = ipaddress.ip_address(str(HOTSPOT_IP or "").strip())
        if fallback.version == 4 and not fallback.is_loopback and not fallback.is_unspecified:
            return str(fallback)
    except ValueError:
        pass
    return None


def _group_short_host_id(hostname: str | None = None) -> str:
    raw = str(hostname or socket.gethostname() or "").strip().split(".", 1)[0]
    if not raw:
        raw = ""
    match = re.search(r"(?i)bmi30[-_]?([0-9a-f]{6,})$", raw)
    if match:
        return match.group(1).upper()
    match = re.search(r"([0-9A-Fa-f]{8,})$", raw)
    if match:
        return match.group(1).upper()
    try:
        serial = str(detect_rpi_identity().get("serial") or "").strip()
        if serial:
            return serial[-9:].upper()
    except Exception:
        pass
    return (raw or "---").upper()


def group_local_rpi_id(hostname: str | None = None) -> str:
    raw = str(hostname or socket.gethostname() or "").strip().split(".", 1)[0]
    match = re.fullmatch(r"(?i)BMI30-([0-9A-F]{9})", raw)
    return match.group(1).upper() if match else ""


def _ip_last_octet(ip: str | None) -> str:
    try:
        parsed = ipaddress.ip_address(str(ip or "").strip())
        if parsed.version == 4:
            return str(parsed).rsplit(".", 1)[-1]
        return str(parsed).rsplit(":", 1)[-1]
    except Exception:
        return ""


def group_local_host_identity(preferred_ip: str | None = None) -> dict[str, Any]:
    ip = str(_group_publication_ip(preferred_ip) or "").strip()
    host_id = _group_short_host_id()
    ip_last = _ip_last_octet(ip)
    label = f"{host_id}/{ip_last}" if ip_last else host_id
    identity: dict[str, Any] = {
        "host_id": host_id,
        "rpi_id": group_local_rpi_id(),
        "ip": ip,
        "ip_last": ip_last,
        "label": label,
    }
    return identity


def _bmi30_rpi_id_from_name(value: Any) -> str:
    name = str(value or "").strip().split(".", 1)[0]
    match = re.fullmatch(r"(?i)BMI30-([0-9A-F]{9})", name)
    return match.group(1).upper() if match else ""


def _lan_bmi30_candidates() -> list[dict[str, str]]:
    """Return currently advertised/neighbor IPv4 candidates without subnet scanning."""
    candidates: dict[tuple[str, str], dict[str, str]] = {}
    try:
        proc = subprocess.run(
            ["timeout", "4", "avahi-browse", "-rtpk", "_device-info._tcp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=LAN_SENSOR_REQUEST_TIMEOUT_S,
        )
        avahi_output = proc.stdout or ""
    except Exception:
        avahi_output = ""
    for raw_line in avahi_output.splitlines():
        if not raw_line.startswith("=;"):
            continue
        fields = raw_line.split(";")
        if len(fields) < 9 or fields[2] != "IPv4":
            continue
        iface = fields[1].strip()
        service_name = fields[3].strip().replace("\\032", " ")
        rpi_id = _bmi30_rpi_id_from_name(service_name)
        ip = fields[7].strip()
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
            continue
        if not rpi_id:
            continue
        candidates[(ip, iface)] = {
            "ip": ip,
            "iface": iface,
            "rpi_id": rpi_id,
            "hostname": f"BMI30-{rpi_id}",
            "discovery_source": "mdns",
        }

    neighbor_output = run_command("ip", "-4", "neigh", "show")
    for raw_line in neighbor_output.splitlines():
        fields = raw_line.split()
        if not fields:
            continue
        ip = fields[0].strip()
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or parsed.is_unspecified:
            continue
        iface = ""
        if "dev" in fields:
            idx = fields.index("dev")
            if idx + 1 < len(fields):
                iface = fields[idx + 1]
        key = (ip, iface)
        candidates.setdefault(key, {
            "ip": ip,
            "iface": iface,
            "rpi_id": "",
            "hostname": "",
            "discovery_source": "neighbor",
        })
    return list(candidates.values())[:64]


def _probe_remote_group_state(ip: str, expected_rpi_id: str) -> dict[str, Any]:
    def _read_sensors(opener: Any) -> dict[str, Any]:
        with opener.open(
            Request(
                f"http://{ip}/api/sensors",
                headers={"Accept": "application/json", "X-BMI30-Source": "group_sensor_discovery"},
                method="GET",
            ),
            timeout=5.0,
        ) as response:
            payload = json.loads(response.read(524288).decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            return {}
        host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
        remote_rpi_id = str(host.get("rpi_id") or "").strip().upper()
        if remote_rpi_id and remote_rpi_id != expected_rpi_id:
            return {}
        device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
        events = device.get("events") if isinstance(device.get("events"), dict) else {}
        optic = events.get("optic_state") if isinstance(events.get("optic_state"), dict) else {}
        local = device.get("local") if isinstance(device.get("local"), dict) else {}
        state: dict[str, Any] = {}
        for key in ("optic_active", "optic_indication_allow", "tx_enabled", "detadc1", "detadc2"):
            value = optic.get(key) if key in optic else local.get(key)
            if isinstance(value, bool):
                state[key] = value
        return state

    with _LAN_SENSOR_OPENERS_LOCK:
        cached_opener = _LAN_SENSOR_OPENERS.get(ip)
    if cached_opener is not None:
        try:
            state = _read_sensors(cached_opener)
            if state:
                return state
        except Exception:
            with _LAN_SENSOR_OPENERS_LOCK:
                _LAN_SENSOR_OPENERS.pop(ip, None)

    try:
        class _PortalLoginNoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
                return None

        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar), _PortalLoginNoRedirect())
        login_body = urlencode({
            "username": get_portal_username(),
            "password": PORTAL_PASSWORD,
            "remember": "0",
        }).encode("utf-8")
        try:
            with opener.open(
                Request(
                    f"http://{ip}/portal-login",
                    data=login_body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                ),
                timeout=max(2.0, LAN_SENSOR_REQUEST_TIMEOUT_S),
            ) as response:
                response.read(1)
        except HTTPError as exc:
            if exc.code not in (HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FOUND, HTTPStatus.SEE_OTHER, HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT):
                raise
        state = _read_sensors(opener)
        if state:
            with _LAN_SENSOR_OPENERS_LOCK:
                _LAN_SENSOR_OPENERS[ip] = opener
            return state
    except Exception:
        pass
    return {}


def _public_group_state_from_status(status: dict[str, Any]) -> dict[str, Any]:
    group_state = status.get("group_state") if isinstance(status.get("group_state"), dict) else {}
    state: dict[str, Any] = {}
    for key in ("optic_active", "optic_indication_allow", "detadc1", "detadc2", "tx_enabled"):
        value = group_state.get(key)
        if isinstance(value, bool):
            state[key] = value
    return state


def _probe_lan_bmi30(candidate: dict[str, str]) -> dict[str, Any] | None:
    ip = str(candidate.get("ip") or "").strip()
    rpi_id = str(candidate.get("rpi_id") or "").strip().upper()
    hostname = str(candidate.get("hostname") or "").strip()
    status: dict[str, Any] = {}
    api_ok = False
    try:
        req = Request(
            f"http://{ip}/api/status",
            headers={"Accept": "application/json", "X-BMI30-Source": "group_lan_discovery"},
            method="GET",
        )
        with urlopen(req, timeout=1.2) as response:
            parsed = json.loads(response.read(262144).decode("utf-8") or "{}")
        if isinstance(parsed, dict):
            status = parsed
            api_ok = True
    except Exception:
        status = {}

    remote_hostname = str(status.get("hostname") or "").strip()
    remote_rpi_id = _bmi30_rpi_id_from_name(remote_hostname)
    # An mDNS advertisement or neighbor-cache entry is only a candidate.  It
    # must answer now and identify itself as BMI30 before it is shown.
    if not api_ok or not remote_rpi_id:
        return None
    rpi_id = remote_rpi_id
    hostname = f"BMI30-{rpi_id}"

    sync = status.get("sync_mode") if isinstance(status.get("sync_mode"), dict) else {}
    code = str(sync.get("code") or "").strip().upper()
    code_match = re.fullmatch(r"([MS])([0-9]{2})", code)
    role = str(sync.get("value") or "").strip().lower()
    if role not in {"master", "slave"} and code_match:
        role = "master" if code_match.group(1) == "M" else "slave"
    device_id = int(code_match.group(2)) if code_match else None
    access = status.get("access") if isinstance(status.get("access"), dict) else {}
    access_ip = str(access.get("ip") or "").strip()
    if access_ip == ip:
        connect_url = str(access.get("web_url") or "").strip()
    else:
        connect_url = ""
    if not connect_url:
        connect_url = f"http://{ip}/"
    group_state = _public_group_state_from_status(status)
    public_group_state = isinstance(group_state.get("optic_active"), bool)
    if not isinstance(group_state.get("optic_active"), bool):
        group_state = _probe_remote_group_state(ip, rpi_id)

    return {
        "rpi_id": rpi_id,
        "hostname": hostname,
        "ip": ip,
        "ip_last": _ip_last_octet(ip),
        "iface": str(candidate.get("iface") or ""),
        "connect_url": connect_url,
        "role": role if role in {"master", "slave"} else "",
        "code": code if code_match else "",
        "node_id": device_id,
        "device_id_assigned": device_id is not None,
        "role_assigned": role in {"master", "slave"},
        "device_responded": bool(sync.get("device_responded", False)),
        "online": True,
        "api_ok": api_ok,
        "public_group_state": public_group_state,
        "optic_active": group_state.get("optic_active") if isinstance(group_state.get("optic_active"), bool) else None,
        "optic_indication_allow": group_state.get("optic_indication_allow") if isinstance(group_state.get("optic_indication_allow"), bool) else None,
        "detadc1": group_state.get("detadc1") if isinstance(group_state.get("detadc1"), bool) else None,
        "detadc2": group_state.get("detadc2") if isinstance(group_state.get("detadc2"), bool) else None,
        "tx_enabled": group_state.get("tx_enabled") if isinstance(group_state.get("tx_enabled"), bool) else None,
        "discovery_source": str(candidate.get("discovery_source") or "lan"),
        "last_seen_at": time.time(),
    }


def discover_lan_bmi30_devices() -> list[dict[str, Any]]:
    candidates = _lan_bmi30_candidates()
    discovered: list[dict[str, Any]] = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(12, len(candidates))) as pool:
            futures = [pool.submit(_probe_lan_bmi30, candidate) for candidate in candidates]
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception:
                    item = None
                if item:
                    discovered.append(item)

    default_iface = detect_default_route()
    role_order = {"wifi": 0, "ethernet": 1, "hotspot": 2, "other": 3, "loopback": 9}

    def _priority(item: dict[str, Any]) -> tuple[int, int, int, str]:
        iface = str(item.get("iface") or "")
        ip = str(item.get("ip") or "")
        return (
            0 if bool(item.get("api_ok")) else 1,
            0 if default_iface and iface == default_iface else 1,
            role_order.get(classify_interface(iface, ip), 8),
            ip,
        )

    by_rpi: dict[str, dict[str, Any]] = {}
    for item in sorted(discovered, key=_priority):
        rpi_id = str(item.get("rpi_id") or "")
        if rpi_id and rpi_id not in by_rpi:
            by_rpi[rpi_id] = item
    result = sorted(by_rpi.values(), key=lambda item: str(item.get("rpi_id") or ""))
    node_owners: dict[int, set[str]] = {}
    for item in result:
        node_id = item.get("node_id")
        if isinstance(node_id, int) and 0 <= node_id <= 31:
            node_owners.setdefault(node_id, set()).add(str(item.get("rpi_id") or ""))
    for item in result:
        node_id = item.get("node_id")
        item["node_conflict"] = (
            isinstance(node_id, int)
            and len(node_owners.get(node_id, set())) > 1
        )
    return result


def lan_bmi30_discovery_background() -> None:
    while True:
        try:
            devices = discover_lan_bmi30_devices()
            with _LAN_DEVICE_LOCK:
                _LAN_DEVICE_CACHE["updated_at"] = time.time()
                _LAN_DEVICE_CACHE["devices"] = devices
        except Exception as exc:
            print(f"[LAN-BMI30] discovery failed: {exc}", flush=True)
        time.sleep(LAN_DEVICE_DISCOVERY_S)


def _probe_known_lan_sensor_state(device: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    ip = str(device.get("ip") or "").strip()
    rpi_id = str(device.get("rpi_id") or "").strip().upper()
    if not ip or not rpi_id:
        return rpi_id, ip, {}

    if device.get("public_group_state") is True:
        try:
            req = Request(
                f"http://{ip}/api/status",
                headers={"Accept": "application/json", "X-BMI30-Source": "group_sensor_refresh"},
                method="GET",
            )
            with urlopen(req, timeout=LAN_SENSOR_REQUEST_TIMEOUT_S) as response:
                status = json.loads(response.read(262144).decode("utf-8") or "{}")
            if isinstance(status, dict) and _bmi30_rpi_id_from_name(status.get("hostname")) == rpi_id:
                state = _public_group_state_from_status(status)
                if state:
                    return rpi_id, ip, state
        except Exception:
            pass

    return rpi_id, ip, _probe_remote_group_state(ip, rpi_id)


def lan_bmi30_sensor_refresh_background() -> None:
    """Refresh transient sensor bits without repeating full mDNS discovery."""
    local_rpi_id = group_local_rpi_id()
    while True:
        started = time.monotonic()
        with _LAN_DEVICE_LOCK:
            cached = _LAN_DEVICE_CACHE.get("devices")
            devices = [
                dict(item)
                for item in cached
                if isinstance(item, dict)
                and str(item.get("rpi_id") or "").strip().upper() != local_rpi_id
            ] if isinstance(cached, list) else []

        updates: list[tuple[str, str, dict[str, Any]]] = []
        if devices:
            with ThreadPoolExecutor(max_workers=min(8, len(devices))) as pool:
                futures = [pool.submit(_probe_known_lan_sensor_state, item) for item in devices]
                for future in as_completed(futures):
                    try:
                        update = future.result()
                    except Exception:
                        update = ("", "", {})
                    if update[2]:
                        updates.append(update)

        if updates:
            now = time.time()
            update_by_rpi = {rpi_id: (ip, state) for rpi_id, ip, state in updates if rpi_id}
            with _LAN_DEVICE_LOCK:
                current = _LAN_DEVICE_CACHE.get("devices")
                if isinstance(current, list):
                    for item in current:
                        if not isinstance(item, dict):
                            continue
                        rpi_id = str(item.get("rpi_id") or "").strip().upper()
                        update = update_by_rpi.get(rpi_id)
                        if update is None or (update[0] and str(item.get("ip") or "") != update[0]):
                            continue
                        for key, value in update[1].items():
                            if isinstance(value, bool):
                                item[key] = value
                        item["sensor_updated_at"] = now
                        item["last_seen_at"] = now
                _LAN_DEVICE_CACHE["sensor_updated_at"] = now

        elapsed = time.monotonic() - started
        time.sleep(max(0.05, LAN_SENSOR_REFRESH_S - elapsed))


def get_lan_bmi30_devices() -> list[dict[str, Any]]:
    now = time.time()
    max_age_s = max(30.0, LAN_DEVICE_DISCOVERY_S * 2.5)
    local_rpi_id = group_local_rpi_id()
    with _LAN_DEVICE_LOCK:
        devices = _LAN_DEVICE_CACHE.get("devices")
        if not isinstance(devices, list):
            return []
        return [
            dict(item)
            for item in devices
            if item.get("api_ok") is True
            and item.get("online") is True
            and str(item.get("rpi_id") or "").strip().upper() != local_rpi_id
            and now - float(item.get("last_seen_at", 0.0) or 0.0) <= max_age_s
        ]


def collect_public_group_state() -> dict[str, Any]:
    device = _device_cache_sensors(_read_device_state_cache())
    events = device.get("events") if isinstance(device.get("events"), dict) else {}
    optic = events.get("optic_state") if isinstance(events.get("optic_state"), dict) else {}
    local = device.get("local") if isinstance(device.get("local"), dict) else {}
    state: dict[str, Any] = {}
    for key in ("optic_active", "optic_indication_allow", "tx_enabled", "detadc1", "detadc2"):
        value = optic.get(key) if key in optic else local.get(key)
        if isinstance(value, bool):
            state[key] = value
    return state


def collect_remote_access_targets(preferred_ip: str | None = None) -> dict[str, Any]:
    hotspot = detect_hotspot_connection()
    interfaces = collect_ipv4_interfaces()
    default_iface = detect_default_route()
    hostnames = detect_hostname_candidates()

    hotspot_ip = HOTSPOT_IP
    for item in interfaces:
        if item["role"] == "hotspot":
            hotspot_ip = item["ip"]
            break

    access_ip = hotspot_ip
    access_role = "hotspot"
    access_iface = hotspot.get("interface") or "wlan0ap"
    if preferred_ip:
        for item in interfaces:
            if item["ip"] != preferred_ip:
                continue
            access_ip = item["ip"]
            access_role = item["role"]
            access_iface = item["iface"]
            break

    sync_mode = detect_sync_mode()
    split_system = detect_bmi30_split_system_version()
    firmware_release = detect_bmi30_firmware_release()
    tagit_logo_path = detect_logo_path(TAGIT_LOGO_CANDIDATES)
    am_logo_path = detect_logo_path(AM_LOGO_CANDIDATES)
    web_scheme = "https" if is_https_enabled() and FORCE_HTTPS else "http"

    payload = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "hostnames": hostnames,
        "default_iface": default_iface,
        "hotspot": {
            "ssid": hotspot.get("ssid") or hotspot.get("connection_id") or "BMI30-Hotspot",
            "interface": hotspot.get("interface") or "wlan0ap",
            "ip": hotspot_ip,
            "web_url": format_web_url(hotspot_ip, web_scheme),
        },
        "access": {
            "ip": access_ip,
            "role": access_role,
            "interface": access_iface,
            "web_url": format_web_url(access_ip, web_scheme),
        },
        "connections": {
            "portal": count_portal_clients(),
            "hotspot": count_hotspot_clients(hotspot.get("interface") or "wlan0ap"),
            "wifi": 1 if is_wifi_internet_connected(WIFI_STA_IFACE) else 0,
            "ethernet": count_ethernet_connections(),
            "remote": count_remote_desktop_connections(),
        },
        "channels": load_channel_permissions(),
        "sync_mode": sync_mode,
        "group_state": collect_public_group_state(),
        "split_system": split_system,
        "firmware_release": firmware_release,
        "logos": {
            "tagit": {
                "available": bool(tagit_logo_path),
                "url": "/logo-tagit" if tagit_logo_path else "",
            },
            "am": {
                "available": bool(am_logo_path),
                "url": "/logo-am" if am_logo_path else "",
            },
        },
        "interfaces": interfaces,
        "services": {
            "ssh_user": SSH_USER,
            "ssh": SSH_PORT,
            "rdp": RDP_PORT,
            "web": PORT,
            "web_scheme": web_scheme,
            "web_tls": HTTPS_PORT,
        },
    }
    return payload


def render_interface_cards(data: dict[str, Any]) -> str:
    items = []
    for item in data["interfaces"]:
        iface = html.escape(item["iface"])
        ip = html.escape(item["ip"])
        cidr = html.escape(item["cidr"])
        role = html.escape(item["role"])
        ssh_cmd = html.escape(f"ssh {SSH_USER}@{item['ip']}")
        rdp_target = html.escape(f"{item['ip']}:{data['services']['rdp']}")
        items.append(
            "".join(
                [
                    '<section class="card">',
                    f'<div class="label">{role}</div>',
                    f'<h3>{iface}</h3>',
                    f'<div class="ip">{ip}</div>',
                    f'<p class="meta">{cidr}</p>',
                    '<dl>',
                    f'<dt>SSH</dt><dd>{ssh_cmd}</dd>',
                    f'<dt>RDP</dt><dd>{rdp_target}</dd>',
                    f'<dt>Web</dt><dd>http://{ip}/</dd>',
                    '</dl>',
                    '</section>',
                ]
            )
        )
    return "\n".join(items)


def render_html_page(
    data: dict[str, Any],
    auth_error: str = "",
    entered_username: str = "",
    remember_session: bool = True,
) -> bytes:
    hostname   = html.escape(data["hostname"])
    ssid       = html.escape(data["hotspot"]["ssid"])
    hotspot_ip = html.escape(data["hotspot"]["ip"])
    access_ip  = html.escape(data.get("access", {}).get("ip", data["hotspot"]["ip"]))
    access_role = html.escape(data.get("access", {}).get("role", "hotspot"))
    sync_payload = data.get("sync_mode", {})
    sync_value = str(sync_payload.get("value", "off"))
    if sync_value.lower() in {"master", "slave"}:
        sync_value = sync_value.capitalize()
    sync_mode  = html.escape(sync_value)
    sync_code  = html.escape(str(sync_payload.get("code", "")))
    sync_src   = html.escape(str(sync_payload.get("source", "unknown")))
    sync_extra = sync_code or sync_src
    sync_ok    = bool(sync_payload.get("device_responded", False))
    has_tagit_logo = bool(data.get("logos", {}).get("tagit", {}).get("available", False))
    has_am_logo = bool(data.get("logos", {}).get("am", {}).get("available", False))
    ssh_user   = html.escape(data["services"].get("ssh_user", "techaid"))
    rdp_port   = data["services"]["rdp"]
    web_scheme = str(data["services"].get("web_scheme", "http"))
    generated  = html.escape(data["generated_at"])
    entered_username = html.escape(entered_username)
    remember_checked_attr = " checked" if remember_session else ""
    auth_error_html = (
        f'<p class="form-error" role="alert">{html.escape(auth_error)}</p>'
        if auth_error else ""
    )

    # Строки таблицы интерфейсов (loopback не нужен)
    iface_rows: list[str] = []
    for ifc in data["interfaces"]:
        if ifc["role"] == "loopback":
            continue
        role_labels = {"hotspot": "HotSpot", "wifi": "Wi-Fi", "ethernet": "Ethernet"}
        rlabel = html.escape(role_labels.get(ifc["role"], ifc["role"]))
        iname  = html.escape(ifc["iface"])
        ip     = html.escape(ifc["ip"])
        iface_rows.append(
            f'<tr><td class="role" data-label="Type">{rlabel}</td>'
            f'<td class="iname" data-label="Interface">{iname}</td>'
            f'<td class="mono" data-label="IP Address">{ip}</td></tr>'
        )
    iface_table = "\n".join(iface_rows) or '<tr><td colspan="3">no data</td></tr>'
    tagit_logo_html = '<img class="logo logo-left" src="/logo-tagit" alt="TAGIT logo">' if has_tagit_logo else ''
    am_logo_html = '<img class="logo logo-right" src="/logo-am" alt="AM Secure logo">' if has_am_logo else ''
    remote_rows = f"""
      <tr>
        <td data-label="Method">SSH</td>
        <td class="mono" data-label="Address / command">ssh {ssh_user}@{access_ip}</td>
      </tr>
      <tr>
        <td data-label="Method">RDP</td>
        <td class="mono" data-label="Address / command">{access_ip}:{rdp_port}</td>
      </tr>
      <tr>
        <td data-label="Method">Web</td>
                <td data-label="Address / command"><a href="{format_web_url(access_ip, web_scheme)}">{format_web_url(access_ip, web_scheme)}</a></td>
      </tr>
    """

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
{render_style_bootstrap()}
  <link rel="icon" href="{with_rev('/favicon.ico')}" sizes="any">
  <link rel="icon" href="{with_rev('/favicon.png')}" type="image/png">
  <title>BMI30 - Connection Info</title>
  <style>
    :root{{
      color-scheme:light dark;
      --bg:#eef4f1;
      --bg-2:#d7e3de;
      --glass:rgba(255,255,255,.60);
      --glass-strong:rgba(255,255,255,.74);
      --glass-fallback:#f8fbf9;
      --text:#17252a;
      --muted:#5d6e74;
      --line:rgba(255,255,255,.68);
      --line-soft:rgba(23,37,42,.12);
      --accent:#0f8a70;
      --accent-2:#f28f3b;
      --accent-soft:rgba(15,138,112,.16);
      --warm:rgba(242,143,59,.14);
      --grid-line:rgba(15,138,112,.075);
      --panel-shadow:0 2px 1px rgba(255,255,255,.36), 0 14px 28px rgba(29,42,46,.16), 0 34px 72px rgba(29,42,46,.20), inset 1px 1px 0 rgba(255,255,255,.86), inset -1px -1px 0 rgba(60,82,86,.16), inset 0 18px 32px rgba(255,255,255,.22);
      --panel-hover-shadow:0 2px 1px rgba(255,255,255,.40), 0 18px 34px rgba(29,42,46,.18), 0 42px 84px rgba(29,42,46,.24), inset 1px 1px 0 rgba(255,255,255,.92), inset -1px -1px 0 rgba(60,82,86,.18), inset 0 20px 36px rgba(255,255,255,.25);
      --edge-shadow:rgba(31,48,52,.18);
      --input-bg:rgba(255,255,255,.58);
      --portal-border:rgba(242,143,59,.46);
      --form-error-border:#f1beb5;
      --form-error-bg:rgba(255,242,239,.78);
      --form-error-text:#a33b2d;
      --footer:#718287;
      --note-bg:rgba(255,255,255,.44);
      --note-border:rgba(15,138,112,.25);
      --note-text:#4c605a;
      --shine:.72;
    }}
    @media (prefers-color-scheme:dark){{
      :root{{
        --bg:#0b1210;
        --bg-2:#14201c;
        --glass:rgba(23,34,31,.66);
        --glass-strong:rgba(31,45,41,.76);
        --glass-fallback:#18211d;
        --text:#ecf2ee;
        --muted:#a7b5ae;
        --line:rgba(220,255,244,.18);
        --line-soft:rgba(220,255,244,.10);
        --accent:#47c7a7;
        --accent-2:#f0a75e;
        --accent-soft:rgba(71,199,167,.13);
        --warm:rgba(240,167,94,.13);
        --grid-line:rgba(71,199,167,.105);
        --panel-shadow:0 2px 1px rgba(255,255,255,.06), 0 16px 34px rgba(0,0,0,.42), 0 42px 88px rgba(0,0,0,.52), inset 1px 1px 0 rgba(255,255,255,.18), inset -1px -1px 0 rgba(0,0,0,.50), inset 0 18px 34px rgba(255,255,255,.045);
        --panel-hover-shadow:0 2px 1px rgba(255,255,255,.08), 0 20px 40px rgba(0,0,0,.48), 0 52px 96px rgba(0,0,0,.58), inset 1px 1px 0 rgba(255,255,255,.22), inset -1px -1px 0 rgba(0,0,0,.54), inset 0 20px 38px rgba(255,255,255,.06);
        --edge-shadow:rgba(0,0,0,.46);
        --input-bg:rgba(9,15,13,.52);
        --portal-border:rgba(240,167,94,.42);
        --form-error-border:#8c463a;
        --form-error-bg:rgba(53,27,23,.78);
        --form-error-text:#f6b4a9;
        --footer:#87958e;
        --note-bg:rgba(20,32,28,.58);
        --note-border:rgba(71,199,167,.24);
        --note-text:#bfd5cc;
        --shine:.24;
      }}
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
          background:
            linear-gradient(135deg,var(--accent-soft) 0%,transparent 36%),
            linear-gradient(315deg,var(--warm) 0%,transparent 40%),
            linear-gradient(180deg,var(--bg) 0%,var(--bg-2) 100%);
          background-attachment:fixed;color:var(--text);padding:clamp(10px,2.5vw,26px);min-height:100vh;overflow-x:hidden}}
    body::before{{content:"";position:fixed;inset:0;pointer-events:none;
          background-image:linear-gradient(var(--grid-line) 1px,transparent 1px),linear-gradient(90deg,var(--grid-line) 1px,transparent 1px);
          background-size:56px 56px;mask-image:linear-gradient(180deg,rgba(0,0,0,.70),rgba(0,0,0,.18) 78%,transparent);
          -webkit-mask-image:linear-gradient(180deg,rgba(0,0,0,.70),rgba(0,0,0,.18) 78%,transparent)}}
    .page{{position:relative;width:min(100%,1680px);margin:0 auto;display:flex;flex-direction:column;gap:clamp(12px,1.6vw,20px)}}
    .grid{{display:grid;grid-template-columns:1fr;gap:clamp(12px,1.6vw,20px);align-items:start}}
    .logo{{max-height:56px;max-width:min(220px,52vw);object-fit:contain;display:block}}
    .logo-left{{margin-right:auto}}
    .logo-right{{margin-left:auto}}
    .hero,.card,.security-note{{position:relative;overflow:hidden;background:var(--glass);
           border:1px solid var(--line);border-radius:8px;box-shadow:var(--panel-shadow);
           backdrop-filter:blur(18px) saturate(1.24);-webkit-backdrop-filter:blur(18px) saturate(1.24)}}
    .hero::before,.card::before,.security-note::before{{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;
           background:linear-gradient(145deg,rgba(255,255,255,.70),rgba(255,255,255,.16) 36%,rgba(255,255,255,0) 62%);
           opacity:var(--shine)}}
    .hero::after,.card::after,.security-note::after{{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;
           background:linear-gradient(315deg,var(--edge-shadow),rgba(0,0,0,0) 34%),linear-gradient(180deg,rgba(255,255,255,.30),rgba(255,255,255,0) 18%);
           mix-blend-mode:multiply;opacity:.74}}
    .hero>*,
    .card>*,
    .security-note>*{{position:relative}}
    @supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){{
      .hero,.card,.security-note{{background:var(--glass-fallback)}}
    }}
    @media (hover:hover){{
      .card:hover{{transform:translateY(-2px);box-shadow:var(--panel-hover-shadow)}}
    }}
    /* Hero */
    .hero{{background:linear-gradient(145deg,var(--glass-strong),var(--glass));
           padding:clamp(16px,3vw,26px)}}
    .hero-top{{display:flex;align-items:center;justify-content:flex-end;gap:14px;margin-bottom:12px}}
    .hero h1{{font-size:clamp(20px,3.6vw,34px);font-weight:700;line-height:1.15;margin-bottom:4px;text-align:center;overflow-wrap:anywhere}}
    .hero p{{font-size:clamp(13px,1.9vw,15px);color:var(--muted);text-align:center}}
    /* Cards */
    .card{{padding:clamp(14px,2vw,20px);min-width:0;transition:transform .16s ease,box-shadow .16s ease}}
    .card h2{{font-size:15px;font-weight:600;margin-bottom:10px;color:var(--text)}}
    /* Definition list */
    dl{{display:grid;grid-template-columns:minmax(96px,auto) minmax(0,1fr);gap:8px 14px;align-items:start}}
    dt{{font-size:12px;color:var(--muted);white-space:nowrap}}
    dd{{font-size:13px;min-width:0}}
    .mono{{font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;overflow-wrap:anywhere;word-break:break-word}}
    /* Copy row */
    .cr{{display:flex;align-items:center;gap:8px}}
    .cbtn{{background:var(--input-bg);border:1px solid var(--line);border-radius:7px;
           padding:2px 9px;font-size:11px;cursor:pointer;color:var(--accent);white-space:nowrap}}
    .cbtn:active{{background:var(--accent-soft)}}
    /* Tables */
    .table-wrap{{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}}
    .data-table{{width:100%;border-collapse:collapse;font-size:13px}}
    .data-table th{{text-align:left;font-size:11px;font-weight:600;color:var(--muted);
        padding:0 0 7px;border-bottom:1px solid var(--line)}}
    .data-table td{{padding:7px 0;border-bottom:1px solid var(--line-soft);vertical-align:middle}}
    tr:last-child td{{border-bottom:none}}
    .role{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
           color:var(--muted);padding-right:10px;white-space:nowrap}}
    .iname{{padding-right:10px;color:var(--muted)}}
    .access-note{{font-size:12px;color:var(--muted);margin-bottom:8px;overflow-wrap:anywhere}}
    .subtle{{color:var(--muted)}}
    /* Portal card */
    .portal{{border-color:var(--portal-border)}}
    .portal h2 span{{color:var(--accent-2);font-size:11px;font-weight:400;margin-left:6px}}
    .portal-form{{display:flex;flex-direction:column;gap:12px;margin-top:8px}}
    .form-error{{border:1px solid var(--form-error-border);background:var(--form-error-bg);color:var(--form-error-text);
                 padding:10px 12px;border-radius:8px;font-size:12px;line-height:1.45}}
    .fld{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
    .fld label{{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px}}
    .fld input{{border:1px solid var(--line);border-radius:7px;
                padding:7px 10px;font-size:13px;background:var(--input-bg);color:var(--text);width:100%;
                box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .fld input:focus-visible{{outline:2px solid rgba(15,138,112,.24);outline-offset:1px;border-color:var(--accent)}}
    .portal-options{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}}
    .remember{{display:flex;align-items:flex-start;gap:10px;font-size:12px;color:var(--muted);line-height:1.45}}
    .remember input{{margin-top:2px;accent-color:var(--accent);inline-size:16px;block-size:16px;flex:0 0 auto}}
    .portal-help{{font-size:12px;color:var(--muted);line-height:1.55}}
    .sbtn{{background:var(--glass-strong);color:var(--text);border:1px solid var(--line);border-radius:8px;
           padding:11px 16px;font-size:14px;width:100%;cursor:pointer;font-weight:700;
           box-shadow:0 1px 0 rgba(255,255,255,.44),0 10px 20px rgba(29,42,46,.13),0 22px 42px rgba(15,138,112,.14),
                      inset 1px 1px 0 rgba(255,255,255,.72),inset -1px -1px 0 rgba(29,42,46,.14);
           transition:background-color .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease,color .14s ease}}
    .sbtn:hover{{background:var(--accent-soft);border-color:var(--accent);color:var(--text);
           transform:translateY(-1px);
           box-shadow:0 1px 0 rgba(255,255,255,.50),0 14px 24px rgba(29,42,46,.16),0 28px 54px rgba(15,138,112,.20),
                      inset 1px 1px 0 rgba(255,255,255,.78),inset -1px -1px 0 rgba(29,42,46,.16)}}
    .sbtn:active{{transform:translateY(1px);
           box-shadow:inset 0 2px 8px rgba(29,42,46,.18),0 4px 12px rgba(29,42,46,.12)}}
    .sbtn:focus-visible{{outline:2px solid rgba(15,138,112,.34);outline-offset:2px;border-color:var(--accent)}}
    .security-note{{border-color:var(--note-border);background:var(--note-bg);color:var(--note-text);
                    padding:12px 14px;font-size:12px;line-height:1.55}}
    .security-note strong{{color:var(--text)}}
    .security-note[hidden]{{display:none}}
    .footer{{text-align:center;font-size:11px;color:var(--footer);padding:2px 0 6px;line-height:1.5}}
    a{{color:var(--accent);text-decoration:none}}
    @media (min-width:860px){{
      .grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}
      .hero{{grid-column:1 / -1}}
      .remote-card,.network-card{{grid-column:1 / -1}}
    }}
    @media (min-width:1320px){{
      .grid{{grid-template-columns:repeat(12,minmax(0,1fr))}}
      .hero{{grid-column:1 / -1}}
      .wifi-card{{grid-column:span 4}}
      .remote-card{{grid-column:span 8}}
      .network-card{{grid-column:span 8}}
      .portal{{grid-column:span 4}}
    }}
    @media (max-width:640px){{
      body{{padding:10px}}
      .page,.grid{{gap:10px}}
            .hero-top{{
                flex-direction:row;
                align-items:center;
                justify-content:space-between;
                flex-wrap:nowrap;
                gap:8px;
            }}
            .logo{{max-height:38px;max-width:calc(50vw - 24px)}}
            .logo-left{{margin-right:0}}
            .logo-right{{margin-left:0}}
      .fld{{grid-template-columns:1fr}}
            dl{{grid-template-columns:minmax(96px,auto) minmax(0,1fr);gap:6px 10px;align-items:center}}
            dt{{white-space:nowrap}}
            dd{{margin-bottom:0;min-width:0}}
      .data-table thead{{display:none}}
            .data-table,.data-table tbody,.data-table tr{{display:block;width:100%}}
      .data-table tr{{padding:8px 0;border-bottom:1px solid var(--line-soft)}}
            .data-table td{{display:flex;align-items:baseline;gap:6px;padding:3px 0;border-bottom:none;overflow-wrap:anywhere;word-break:break-word}}
            .data-table td::before{{content:attr(data-label) ": ";display:inline-block;font-size:10px;font-weight:700;
                letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin-bottom:0;white-space:nowrap;flex:0 0 auto}}
      .role{{padding-right:0;white-space:normal}}
    }}
  </style>
{render_debug_style_css()}
</head>
<body>
<div class="page">

  <div class="grid">
  <div class="hero">
    <div class="hero-top">
    {tagit_logo_html}
    {am_logo_html}
    </div>
    <h1>{hostname}</h1>
    <p>EM Anti-theft EAS System</p>
  </div>

  <div class="card wifi-card">
        <h2>Wi-Fi Network</h2>
    <dl>
            <dt>SSID</dt>
      <dd class="mono">{ssid}</dd>
            <dt>Hotspot IP</dt>
      <dd class="mono">{hotspot_ip}</dd>
            <dt>Sync Mode</dt>
            <dd class="mono">{sync_mode} <span class="subtle">({sync_extra})</span></dd>
            <dt>Device Link</dt>
            <dd>{'online' if sync_ok else '---'}</dd>
    </dl>
  </div>

  <div class="card remote-card">
        <h2>Remote Access</h2>
        <p class="access-note">Current access path: {access_role} via {access_ip}</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>Method</th><th>Address / command</th></tr>
        </thead>
        <tbody>
          {remote_rows}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card network-card">
        <h2>Device Network Addresses</h2>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>Type</th><th>Interface</th><th>IP Address</th></tr>
        </thead>
        <tbody>
          {iface_table}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card portal">
        <h2>Management Portal <span>(preview)</span></h2>
    <p class="access-note" style="margin-bottom:2px">
            Sign in to open the next management screen.
    </p>
    <form class="portal-form" method="post" action="/portal-login" novalidate>
      {auth_error_html}
      <div class="fld">
                <label>Username<input name="username" type="text" value="{entered_username}" placeholder="admin" autocomplete="username" aria-required="true"></label>
                <label>Password<input name="password" type="password" placeholder="admin" autocomplete="current-password" aria-required="true"></label>
      </div>
      <div class="portal-options">
        <label class="remember"><input name="remember" type="checkbox" value="1"{remember_checked_attr}>Remember this browser for 7 days</label>
      </div>
      <p class="portal-help">The device does not store your password here. When enabled, it keeps a signed login cookie that expires automatically after 7 days.</p>
            <button class="sbtn" type="submit">Sign In</button>
    </form>
  </div>
  </div>

    <div id="security-note" class="security-note" hidden>
      <strong>Local device page.</strong> Your browser may show "Not secure" because this hotspot page is running over HTTP.
      The warning disappears only after HTTPS with a trusted certificate is configured for the device.
    </div>

    <p class="footer">Updated: {generated} · auto-refresh {REFRESH_S}&#x202f;s
        &nbsp;·&nbsp; <a href="/api/status">JSON API</a></p>

</div>
{render_debug_panel()}
{render_debug_panel_script()}
<script>
  var securityNote = document.getElementById('security-note');
  if (securityNote && window.location.protocol !== 'https:') {{
    securityNote.hidden = false;
  }}
  var portalForm = document.querySelector('.portal-form');
  if (portalForm) {{
    var usernameInput = portalForm.querySelector('input[name="username"]');
    var passwordInput = portalForm.querySelector('input[name="password"]');
    var showPortalError = function (message) {{
      var error = portalForm.querySelector('.form-error');
      if (!error) {{
        error = document.createElement('p');
        error.className = 'form-error';
        error.setAttribute('role', 'alert');
        portalForm.insertBefore(error, portalForm.firstElementChild);
      }}
      error.textContent = message;
    }};
    var clearPortalError = function () {{
      var error = portalForm.querySelector('.form-error');
      if (error) {{
        error.remove();
      }}
    }};
    portalForm.addEventListener('submit', function (event) {{
      var usernameMissing = usernameInput && usernameInput.value.trim() === '';
      var passwordMissing = passwordInput && passwordInput.value === '';
      if (!usernameMissing && !passwordMissing) {{
        return;
      }}
      event.preventDefault();
      if (usernameMissing && passwordMissing) {{
        showPortalError('Please enter username and password.');
        usernameInput.focus();
      }} else if (usernameMissing) {{
        showPortalError('Please enter username.');
        usernameInput.focus();
      }} else {{
        showPortalError('Please enter password.');
        passwordInput.focus();
      }}
    }});
    [usernameInput, passwordInput].forEach(function (input) {{
      if (input) {{
        input.addEventListener('input', clearPortalError);
      }}
    }});
  }}
  window.setTimeout(function () {{
    var inputs = Array.prototype.slice.call(document.querySelectorAll('.portal-form input[type="text"], .portal-form input[type="password"]'));
    var hasFocus = inputs.some(function (input) {{ return input === document.activeElement; }});
    var hasValue = inputs.some(function (input) {{ return input.value.trim() !== ''; }});
    var debugOpen = document.documentElement.dataset.debugOpen === 'true';
    if (!debugOpen && !hasFocus && !hasValue) {{
      window.location.reload();
    }}
  }}, {REFRESH_S * 1000});
</script>
</body>
</html>
"""
    return body.encode("utf-8")


def _read_rpi_temperatures() -> list[tuple[str, float]]:
    """Read all available temperature sensors on Raspberry Pi.

    Returns list of (label, celsius) tuples, deduplicated by sensor type.
    """
    results: list[tuple[str, float]] = []
    seen_types: set[str] = set()

    # 1. Thermal zones (/sys/class/thermal/thermal_zone*)
    import glob as _glob
    for zone_path in sorted(_glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            zone_type = open(f"{zone_path}/type").read().strip()
            raw = int(open(f"{zone_path}/temp").read().strip())
        except Exception:
            continue
        if zone_type in seen_types:
            continue
        seen_types.add(zone_type)
        label_map = {
            "cpu-thermal": "CPU",
            "gpu-thermal": "GPU",
            "soc-thermal": "SoC",
        }
        label = label_map.get(zone_type, zone_type)
        results.append((label, raw / 1000.0))

    # 2. hwmon sensors not already covered by thermal zones
    hwmon_label_map = {
        "rp1_adc": "RP1",
        "rp1_temp": "RP1",
        "bcm2835_thermal": "SoC",
        "cpu_thermal": "CPU",
    }
    for hwmon_path in sorted(_glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            hwmon_name = open(f"{hwmon_path}/name").read().strip()
        except Exception:
            continue
        if hwmon_name not in hwmon_label_map:
            continue
        label = hwmon_label_map[hwmon_name]
        # skip if already added (same label)
        if any(l == label for l, _ in results):
            continue
        for temp_file in sorted(_glob.glob(f"{hwmon_path}/temp*_input")):
            try:
                raw = int(open(temp_file).read().strip())
                results.append((label, raw / 1000.0))
                break
            except Exception:
                continue

    # 3. GPU temperature via vcgencmd (if not already present)
    if not any(l == "GPU" for l, _ in results):
        try:
            import subprocess as _subprocess
            out = _subprocess.check_output(
                ["vcgencmd", "measure_temp"],
                timeout=2, stderr=_subprocess.DEVNULL
            ).decode()
            # output: "temp=52.1'C"
            val_str = out.strip().removeprefix("temp=").removesuffix("'C")
            results.append(("GPU", float(val_str)))
        except Exception:
            pass

    return results


def _read_rpi_hwmon_readings() -> list[dict[str, Any]]:
    """Return raw Raspberry Pi hwmon readings with neutral labels."""
    readings: list[dict[str, Any]] = []
    try:
        import glob as _glob
        import re as _re
        paths = sorted(_glob.glob("/sys/class/hwmon/hwmon*"))
    except Exception:
        return readings

    for hwmon_path in paths:
        try:
            hwmon_name = open(f"{hwmon_path}/name").read().strip()
        except Exception:
            hwmon_name = os.path.basename(hwmon_path)
        for pattern in ("in*_input", "curr*_input", "power*_input", "*_raw", "*_alarm"):
            try:
                files = sorted(_glob.glob(f"{hwmon_path}/{pattern}"))
            except Exception:
                files = []
            for file_path in files:
                name = os.path.basename(file_path)
                try:
                    raw_text = open(file_path).read().strip()
                except Exception:
                    continue
                if not raw_text:
                    continue
                item: dict[str, Any] = {
                    "label": f"{hwmon_name} {name}",
                    "raw": raw_text,
                    "unit": "",
                    "path": file_path,
                }
                try:
                    raw_i = int(raw_text, 0)
                except Exception:
                    raw_i = None
                if raw_i is not None and _re.fullmatch(r"temp\d+_input", name):
                    item["value"] = round(raw_i / 1000.0, 2)
                    item["unit"] = "C"
                elif raw_i is not None and _re.fullmatch(r"in\d+_input", name):
                    item["value"] = raw_i
                    item["unit"] = "mV"
                elif raw_i is not None and _re.fullmatch(r"curr\d+_input", name):
                    item["value"] = raw_i
                    item["unit"] = "mA"
                elif raw_i is not None and _re.fullmatch(r"power\d+_input", name):
                    item["value"] = raw_i
                    item["unit"] = "uW"
                elif raw_i is not None:
                    item["value"] = raw_i
                else:
                    item["value"] = raw_text
                readings.append(item)
    return readings


def _decode_stm32_temperature_raw(raw: int) -> float | None:
    """Decode STM32 CDC temperature raw value to Celsius."""
    raw_i = int(raw)
    if abs(raw_i) >= 1000:
        candidates = (raw_i / 100.0, raw_i / 10.0, float(raw_i))
    elif abs(raw_i) >= 200:
        candidates = (raw_i / 10.0, raw_i / 100.0, float(raw_i))
    else:
        candidates = (float(raw_i), raw_i / 10.0, raw_i / 100.0)
    for value in candidates:
        if -55.0 <= value <= 150.0:
            return value
    return None


def _query_stm32_temperature_cdc() -> float | None:
    """Read STM32 temperature via low-priority CDC diagnostic command 0x31."""
    script = f"""
import glob
import struct
import sys
import time

try:
    import serial
except Exception:
    sys.exit(0)

for port in sorted(glob.glob('/dev/ttyACM*')):
    try:
        with serial.Serial(port=port, baudrate=115200, timeout=0.12, write_timeout=0.12) as ser:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            ser.write(bytes([0x31]))
            ser.flush()
            buf = bytearray()
            deadline = time.monotonic() + 0.35
            while len(buf) < 16 and time.monotonic() < deadline:
                chunk = ser.read(16 - len(buf))
                if chunk:
                    buf.extend(chunk)
                else:
                    time.sleep(0.01)
        data = bytes(buf)
        idx = data.find(bytes([0x80, 0x31]))
        if idx >= 0 and idx + 4 <= len(data):
            raw = struct.unpack('<h', data[idx + 2:idx + 4])[0]
            print(raw)
            sys.exit(0)
    except Exception:
        continue
"""
    try:
        proc = subprocess.run(
            ["python3", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=STM32_TEMP_QUERY_TIMEOUT_S,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    raw_s = (proc.stdout or "").strip().splitlines()
    if not raw_s:
        return None
    try:
        raw = int(raw_s[-1].strip(), 0)
    except Exception:
        return None
    return _decode_stm32_temperature_raw(raw)


def read_stm32_temperature() -> float | None:
    """Return cached STM32 temperature; probe CDC at most once per cache interval."""
    now = time.time()
    cached_ts = float(_STM32_TEMP_CACHE.get("ts", 0.0) or 0.0)
    cached_value = _STM32_TEMP_CACHE.get("value")
    if (now - cached_ts) < STM32_TEMP_CACHE_S:
        return cached_value if isinstance(cached_value, (int, float)) else None

    if not _STM32_TEMP_LOCK.acquire(blocking=False):
        return cached_value if isinstance(cached_value, (int, float)) else None
    try:
        now = time.time()
        cached_ts = float(_STM32_TEMP_CACHE.get("ts", 0.0) or 0.0)
        cached_value = _STM32_TEMP_CACHE.get("value")
        if (now - cached_ts) < STM32_TEMP_CACHE_S:
            return cached_value if isinstance(cached_value, (int, float)) else None
        value = _query_stm32_temperature_cdc()
        _STM32_TEMP_CACHE.update({"ts": time.time(), "value": value})
        return value
    finally:
        _STM32_TEMP_LOCK.release()


def render_portal_page(
    hostname: str,
    session_username: str = "",
    session_role: str = "user",
    notice: str = "",
    notice_kind: str = "ok",
    request_host: str = "",
) -> bytes:
    title = html.escape(hostname)
    split_system = detect_bmi30_split_system_version()
    split_system_label = html.escape(split_system.get("label") or split_system.get("version") or "---")
    split_system_source = html.escape(split_system.get("source") or split_system.get("selected_by") or "---")
    split_system_core = html.escape(split_system.get("core_path") or "---")
    split_system_selected_at = html.escape(split_system.get("selected_at") or "---")
    firmware_release = detect_bmi30_firmware_release()
    firmware_version = html.escape(format_firmware_version_with_date(firmware_release) or "---")
    firmware_created_at = html.escape(str(firmware_release.get("created_at") or "---"))
    firmware_portal_hash = str(firmware_release.get("runtime_portal_sha256") or "").strip()
    firmware_portal_status = "OK" if firmware_release.get("portal_matches_release") else "MISMATCH"
    firmware_portal_build = html.escape(
        f"{firmware_portal_hash[:12]} {firmware_portal_status}" if firmware_portal_hash else "---"
    )
    rpi_identity_text = html.escape(format_rpi_identity(detect_rpi_identity()))
    initial_device_cache = _read_device_state_cache(max_age_s=24 * 60 * 60)
    stm32_identity_text = html.escape(format_stm32_identity(_stm32_identity_from_cache(initial_device_cache)))
    signed_in_as = html.escape(session_username)
    access_label = "Engineering access" if session_role == "engineer" else "User access"
    cfg = load_dc_config()
    tag_cfg = load_tag_detection_config()
    tag_enabled0_checked = " checked" if tag_cfg["enabled0"] else ""
    tag_enabled1_checked = " checked" if tag_cfg["enabled1"] else ""
    tag_auto0_checked = " checked" if tag_cfg["auto0"] else ""
    tag_auto1_checked = " checked" if tag_cfg["auto1"] else ""
    tag_confirm_phase_gate_value = int(tag_cfg["confirm_phase_gate"])
    tag_threshold0_readonly = " readonly" if tag_cfg["auto0"] else ""
    tag_threshold1_readonly = " readonly" if tag_cfg["auto1"] else ""
    tag_filter_amplitude0_checked = " checked" if tag_cfg["filter_amplitude0"] else ""
    tag_filter_amplitude1_checked = " checked" if tag_cfg["filter_amplitude1"] else ""
    tag_filter_shape0_checked = " checked" if tag_cfg["filter_shape0"] else ""
    tag_filter_shape1_checked = " checked" if tag_cfg["filter_shape1"] else ""
    tag_filter_phase0_checked = " checked" if tag_cfg["filter_phase0"] else ""
    tag_filter_phase1_checked = " checked" if tag_cfg["filter_phase1"] else ""
    tag_filter_casino_checked = " checked" if tag_cfg["filter_casino"] else ""
    tag_filter_barkhausen_checked = " checked" if tag_cfg["filter_barkhausen"] else ""
    tag_filter_microwire_checked = " checked" if tag_cfg["filter_microwire"] else ""
    tag_filter_paper_checked = " checked" if tag_cfg["filter_paper"] else ""
    tag_peak_index_min_value = int(tag_cfg["peak_index_min"])
    tag_peak_index_max_value = int(tag_cfg["peak_index_max"])
    tag_barkhausen_radius_value = int(tag_cfg["barkhausen_radius"])
    tag_barkhausen_frac_value = f'{float(tag_cfg["barkhausen_frac"]):.3f}'.rstrip("0").rstrip(".")
    tag_barkhausen_min_width_value = int(tag_cfg["barkhausen_min_width"])
    tag_barkhausen_max_span_value = int(tag_cfg["barkhausen_max_span"])
    tag_barkhausen_min_product_level_value = int(tag_cfg["barkhausen_min_product_level"])
    tag_barkhausen_max_product_level_value = int(tag_cfg["barkhausen_max_product_level"])
    tag_barkhausen_max_total_fraction_value = f'{float(tag_cfg["barkhausen_max_total_fraction"]):.3f}'.rstrip("0").rstrip(".")
    tag_barkhausen_all_quarter_frac_value = f'{float(tag_cfg["barkhausen_all_quarter_frac"]):.3f}'.rstrip("0").rstrip(".")
    tag_phase_max_shift_value = int(tag_cfg["phase_max_shift"])
    tag_phase_shift_penalty_value = f'{float(tag_cfg["phase_shift_penalty"]):.4f}'.rstrip("0").rstrip(".")
    tag_mark_window_start_frac_value = f'{float(tag_cfg["mark_window_start_frac"]):.4f}'.rstrip("0").rstrip(".")
    tag_mark_window_end_frac_value = f'{float(tag_cfg["mark_window_end_frac"]):.4f}'.rstrip("0").rstrip(".")
    tag_mark_gap_value = int(tag_cfg["mark_gap"])
    tag_mark_gap_tol_value = int(tag_cfg["mark_gap_tol"])
    tag_mark_second_frac_value = f'{float(tag_cfg["mark_second_frac"]):.3f}'.rstrip("0").rstrip(".")
    tag_mark_valley_frac_value = f'{float(tag_cfg["mark_valley_frac"]):.3f}'.rstrip("0").rstrip(".")
    tag_mark_multi_max_humps_value = int(tag_cfg["mark_multi_max_humps"])
    tag_locality_max_outside_peaks_value = int(tag_cfg["locality_max_outside_peaks"])
    tag_locality_outside_peak_frac_value = f'{float(tag_cfg["locality_outside_peak_frac"]):.3f}'.rstrip("0").rstrip(".")
    tag_noise_up0_value = int(tag_cfg["noise_up0"])
    tag_noise_up1_value = int(tag_cfg["noise_up1"])
    tag_noise_down0_value = int(tag_cfg["noise_down0"])
    tag_noise_down1_value = int(tag_cfg["noise_down1"])
    tag_noise_unit0_adc_selected = " selected" if tag_cfg["noise_unit0"] == "adc" else ""
    tag_noise_unit0_percent_selected = " selected" if tag_cfg["noise_unit0"] == "percent" else ""
    tag_noise_unit1_adc_selected = " selected" if tag_cfg["noise_unit1"] == "adc" else ""
    tag_noise_unit1_percent_selected = " selected" if tag_cfg["noise_unit1"] == "percent" else ""
    tag_burst_gate0_checked = " checked" if tag_cfg["burst_gate0"] else ""
    tag_burst_gate1_checked = " checked" if tag_cfg["burst_gate1"] else ""
    tag_burst_blank_s0_value = f'{float(tag_cfg["burst_blank_s0"]):.3f}'.rstrip("0").rstrip(".")
    tag_burst_blank_s1_value = f'{float(tag_cfg["burst_blank_s1"]):.3f}'.rstrip("0").rstrip(".")
    tag_burst_max_ratio0_value = f'{float(tag_cfg["burst_max_ratio0"]):.1f}'
    tag_burst_max_ratio1_value = f'{float(tag_cfg["burst_max_ratio1"]):.1f}'
    tag_smooth_mode_options = "".join(
        f'<option value="{mode}"{" selected" if int(tag_cfg["smooth_mode"]) == mode else ""}>'
        f'{label}</option>'
        for mode, label in enumerate(("off", "med3", "med5", "avg7", "avg9", "avg11"))
    )
    tag_confirm0_options = "\n".join(
        f'<option value="{i}"{" selected" if int(tag_cfg["confirm0"]) == i else ""}>{i}</option>'
        for i in range(1, 7)
    )
    tag_confirm1_options = "\n".join(
        f'<option value="{i}"{" selected" if int(tag_cfg["confirm1"]) == i else ""}>{i}</option>'
        for i in range(1, 7)
    )
    tag_threshold0_value = f'{float(tag_cfg["threshold0"]):.1f}'
    tag_threshold1_value = f'{float(tag_cfg["threshold1"]):.1f}'
    tag_threshold_high0_value = f'{float(tag_cfg["threshold_high0"]):.1f}'
    tag_threshold_high1_value = f'{float(tag_cfg["threshold_high1"]):.1f}'
    tag_ratio_noise_max_u16_value = f'{float(tag_cfg["ratio_noise_max_u16"]):.3f}'.rstrip("0").rstrip(".")
    tag_auto_floor_u16_value = f'{float(tag_cfg["auto_floor_u16"]):.3f}'.rstrip("0").rstrip(".")
    tag_auto_slope_value = f'{float(tag_cfg["auto_slope"]):.3f}'.rstrip("0").rstrip(".")
    tag_noise_window_s_value = f'{float(tag_cfg["noise_window_s"]):.3f}'.rstrip("0").rstrip(".")
    core_oscilloscope_url = "/portal-oscilloscope"
    portal_auth = load_portal_auth_config()
    portal_username = html.escape(portal_auth["username"])
    hotspot_cfg = detect_hotspot_connection()
    hotspot_ssid = html.escape(hotspot_cfg.get("ssid") or hotspot_cfg.get("connection_id") or "BMI30-Hotspot")
    hotspot_profile = html.escape(hotspot_cfg.get("connection_id") or "NetworkManager")
    config_payload = _load_config_json()
    operation_cfg = config_payload.get("operation")
    operation_avg = operation_cfg.get("avg_n") if isinstance(operation_cfg, dict) else None
    default_avg_n = _normalize_avg_n(config_payload.get("avg_n", operation_avg), DEFAULT_AVG_N)
    avg_n_options = "\n".join(
        f'<option value="{value}"{" selected" if default_avg_n == value else ""}>{value}</option>'
        for value in AVG_N_VALUES
    )
    sound_cfg = load_sound_config()
    lcd_role_cfg = load_lcd_role_overlay()
    lcd_role_enabled_checked = " checked" if lcd_role_cfg["enabled"] else ""
    lcd_role_period_options = "".join(f'<option value="{value}"{" selected" if lcd_role_cfg["period_s"] == value else ""}>{value} s</option>' for value in range(1, 6))
    lcd_role_duration_options = "".join(f'<option value="{value}"{" selected" if lcd_role_cfg["duration_s"] == value else ""}>{value} s</option>' for value in range(1, 6))
    sound_enabled_checked = " checked" if sound_cfg["enabled"] else ""
    sound_test_upper_checked = " checked" if sound_cfg["test_upper_enabled"] else ""
    sound_test_lower_checked = " checked" if sound_cfg["test_lower_enabled"] else ""
    sound_volume_value = f'{float(sound_cfg["volume_percent"]):.1f}'.rstrip("0").rstrip(".")
    sound_upper_frequency_value = f'{float(sound_cfg["upper_frequency_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_lower_frequency_value = f'{float(sound_cfg["lower_frequency_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_phase_upper_min_value = f'{float(sound_cfg["phase_upper_min_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_phase_upper_max_value = f'{float(sound_cfg["phase_upper_max_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_phase_lower_min_value = f'{float(sound_cfg["phase_lower_min_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_phase_lower_max_value = f'{float(sound_cfg["phase_lower_max_hz"]):.1f}'.rstrip("0").rstrip(".")
    sound_minimum_duration_value = int(sound_cfg["minimum_duration_ms"])
    sound_minimum_cycles_value = int(sound_cfg["minimum_tone_cycles"])
    wifi_meta_raw = config_payload.get("wifi_internet")
    wifi_meta = wifi_meta_raw if isinstance(wifi_meta_raw, dict) else {}
    wifi_active = detect_wifi_internet_connection(WIFI_STA_IFACE)
    wifi_saved_ssid = html.escape(str(wifi_active.get("ssid") or wifi_meta.get("ssid") or ""))
    wifi_last_status = "Connected / saved" if wifi_meta.get("last_apply_ok") else ("Saved, last connect failed" if wifi_meta else "Not configured")
    wifi_last_status_html = html.escape(wifi_last_status)
    privacy_counts = {
        "portal": count_portal_clients(),
        "hotspot": count_hotspot_clients(hotspot_cfg.get("interface") or "wlan0ap"),
        "wifi": 1 if wifi_active.get("connected") else 0,
        "ethernet": count_ethernet_connections(),
        "remote": count_remote_desktop_connections(),
    }
    channel_permissions = load_channel_permissions()
    channel_checked = {key: " checked" if channel_permissions.get(key, True) else "" for key in CHANNEL_KEYS}
    engineer_auth = load_engineer_auth_config()
    engineer_enabled = bool(engineer_auth["enabled"] and (engineer_auth["password_hash"] or engineer_auth["env_password"]))
    engineer_username = html.escape(str(engineer_auth["username"]) or DEFAULT_ENGINEER_USERNAME)
    engineer_checked = " checked" if engineer_enabled else ""
    # Temperature sensors
    _temps = _read_rpi_temperatures()
    if _temps:
        temp_metrics = "".join(
            f'<div class="metric"><span>{html.escape(lbl)}</span>'
            f'<strong data-sensor="rpi-{lbl.lower()}">{temp:.1f}\u00b0C</strong></div>'
            for lbl, temp in _temps
        )
        # placeholder for STM32 temperature (populated via JS when available)
        temp_metrics += '<div class="metric"><span>STM32</span><strong data-sensor="stm32-temp">---</strong></div>'
    else:
        temp_metrics = ('<div class="metric"><span>Temperature</span><strong data-sensor="rpi-cpu">N/A</strong></div>'
                        '<div class="metric"><span>STM32</span><strong data-sensor="stm32-temp">---</strong></div>')
    device_sensor_metrics = (
        '<div class="metric"><span>Last device update</span><strong data-sensor-text="device-cache">---</strong></div>'
        '<div class="metric"><span>Local optic</span><strong data-sensor-text="local-optic">---</strong></div>'
        '<div class="sensor-list sensor-list-block" data-sensor-list="stm32-raw-sensors"></div>'
        '<div class="sensor-list sensor-list-block" data-sensor-list="rpi-hwmon"></div>'
    )
    operation_optic_metrics = (
        '<div class="sensor-list" data-sensor-list="optic-sensors"></div>'
    )
    group_rs485_metrics = (
        '<div class="metric"><span>Last status update</span><strong data-sensor-text="group-cache">---</strong></div>'
        '<div class="metric"><span>Local RS485 D1</span><strong data-sensor-text="local-detadc1">---</strong></div>'
        '<div class="metric"><span>Local RS485 D2</span><strong data-sensor-text="local-detadc2">---</strong></div>'
        '<div class="sensor-list" data-sensor-list="remote-sensors"></div>'
    )
    group_optic_cfg = _read_core_optic_settings()
    group_led_cfg = load_group_led_patterns()
    group_led_options = load_led_pattern_options()
    group_led_event_labels = {event_key: event_label for event_key, event_label in GROUP_LED_PATTERN_EVENTS}
    group_led_desired_event = str(
        group_optic_cfg.get("led_desired_event") or group_optic_cfg.get("led_event") or ""
    ).strip()
    group_led_actual_raw = group_optic_cfg.get("led_pattern_actual")
    if group_led_desired_event == "manual_test":
        group_led_target_raw = group_optic_cfg.get(
            "led_manual_test_pattern",
            group_optic_cfg.get("led_pattern_commanded", 0),
        )
    else:
        group_led_target_raw = group_led_cfg.get(group_led_desired_event, 0) if group_led_desired_event else 0

    def _group_led_pattern_text(value: Any) -> str:
        if value is None:
            return "---"
        return f"Pattern {_led_pattern_value(value)}"

    group_led_event_text = group_led_event_labels.get(
        group_led_desired_event,
        "Idle" if not group_led_desired_event else ("Manual test" if group_led_desired_event == "manual_test" else group_led_desired_event.replace("_", " ").title()),
    )
    group_led_feedback_html = (
        '<div class="group-led-feedback" data-group-led-feedback-root>'
        '<span>Current <b data-group-led-feedback="actual">'
        f'{html.escape(_group_led_pattern_text(group_led_actual_raw))}</b></span>'
        '<span>Target <b data-group-led-feedback="target">'
        f'{html.escape(_group_led_pattern_text(group_led_target_raw))}</b></span>'
        '<span>State <b data-group-led-feedback="event">'
        f'{html.escape(group_led_event_text)}</b></span>'
        '</div>'
    )

    def _group_led_select(event_key: str) -> str:
        selected = _led_pattern_value(group_led_cfg[event_key])
        option_values = {pattern_id for pattern_id, _label in group_led_options}
        pattern_options = group_led_options
        if selected not in option_values:
            pattern_options = tuple(sorted((*group_led_options, (selected, f"Pattern {selected}")), key=lambda item: item[0]))
        options = "".join(
            f'<option value="{pattern_id}"{" selected" if selected == pattern_id else ""}>{html.escape(label)}</option>'
            for pattern_id, label in pattern_options
        )
        return (
            f'<select class="group-led-select" name="led_{event_key}" data-group-led-select="{event_key}" '
            f'aria-label="{html.escape(event_key.replace("_", " "))} pattern">'
            f'{options}</select>'
        )

    group_led_pattern_rows = "\n".join(
        '<tr>'
        f'<th>{html.escape(event_label)}</th>'
        f'<td>{_group_led_select(event_key)}</td>'
        f'<td><div class="group-led-test-cell">'
        f'<button class="link link-secondary group-led-test-btn" type="button" data-group-led-test="{event_key}" aria-pressed="false">Test</button>'
        f'</div></td>'
        + '</tr>'
        for event_key, event_label in GROUP_LED_PATTERN_EVENTS
    )
    group_nonaddr_led = group_optic_cfg.get("non_addressable_led")
    if not isinstance(group_nonaddr_led, dict):
        group_nonaddr_led = {}
    group_nonaddr_led_enabled = bool(group_nonaddr_led.get("enabled", True))
    group_nonaddr_led_test = bool(group_nonaddr_led.get("test_enabled", False))
    group_nonaddr_led_level = 1 if bool(group_nonaddr_led.get("level", False)) else 0
    group_nonaddr_led_enabled_checked = " checked" if group_nonaddr_led_enabled else ""
    group_nonaddr_led_test_pressed = "true" if group_nonaddr_led_test else "false"
    group_nonaddr_led_test_active_class = " is-active" if group_nonaddr_led_test else ""
    remote_desktop = load_remote_desktop_config()
    remote_username = html.escape(str(remote_desktop["username"]))
    remote_password_state = "Saved" if remote_desktop.get("password_saved") else "Current system password"
    remote_password_state_html = html.escape(remote_password_state)
    networks = scan_visible_wifi_networks()
    wifi_options_parts = ['<option value="">Choose visible network...</option>']
    for item in networks:
        ssid_value = html.escape(item["ssid"], quote=True)
        marker = " (connected)" if item.get("in_use") == "yes" else ""
        label = html.escape(f'{item["ssid"]} - {item.get("signal", "0")}% - {item.get("security", "open")}{marker}')
        selected = " selected" if item["ssid"] == wifi_meta.get("ssid") else ""
        wifi_options_parts.append(f'<option value="{ssid_value}"{selected}>{label}</option>')
    wifi_options = "\n".join(wifi_options_parts)
    notice_html = ""
    if notice:
        cls = "notice notice-error" if notice_kind == "error" else "notice"
        notice_html = f'<p class="{cls}" role="status">{html.escape(notice)}</p>'
    doc_order = ["operation", "safety", "network"]
    doc_tabs_parts: list[str] = []
    doc_pages_parts: list[str] = []
    for idx, doc_id in enumerate(doc_order):
        doc = PORTAL_DOCUMENTS[doc_id]
        active = idx == 0
        tab_class = "doc-tab is-active" if active else "doc-tab"
        page_class = "doc-page is-active" if active else "doc-page"
        tab_selected = "true" if active else "false"
        doc_tabs_parts.append(
            f'<button class="{tab_class}" type="button" data-doc-tab="{doc_id}" aria-selected="{tab_selected}">{html.escape(doc["title"])}</button>'
        )
        # PDF viewer HTML для каждого документа
        doc_pages_parts.append(
            f'<article class="{page_class}" data-doc-page="{doc_id}">'
            f'  <div class="pdf-viewer" data-pdf-id="{doc_id}">'
            f'    <div class="pdf-controls">'
            f'      <button class="pdf-btn" data-action="prev-page" title="Previous page">← Prev</button>'
            f'      <div class="pdf-page-nav">'
            f'        <input type="number" class="pdf-page-input" min="1" value="1" data-doc="{doc_id}">'
            f'        <span class="pdf-page-total">/—</span>'
            f'      </div>'
            f'      <button class="pdf-btn" data-action="next-page" title="Next page">Next →</button>'
            f'      <div class="pdf-actions">'
            f'        <a class="pdf-btn pdf-dl-btn" href="/portal-doc-download?doc={doc_id}">↓ PDF</a>'
            f'        <button class="pdf-update-btn" data-action="apply-update" data-doc="{doc_id}" hidden>↑ Update</button>'
            f'        <span class="pdf-check-status" data-doc-status="{doc_id}"></span>'
            f'      </div>'
            f'    </div>'
            f'    <div class="pdf-pages">'
            f'      <canvas class="pdf-canvas" data-doc="{doc_id}"></canvas>'
            f'    </div>'
            f'  </div>'
            f'</article>'
        )
    doc_tabs = "\n".join(doc_tabs_parts)
    doc_pages = "\n".join(doc_pages_parts)
    first_doc = doc_order[0]
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
{render_style_bootstrap()}
  <link rel="icon" href="{with_rev('/favicon.ico')}" sizes="any">
  <link rel="icon" href="{with_rev('/favicon.png')}" type="image/png">
  <title>BMI30 - Management Portal</title>
  <style>
    :root{{
      color-scheme:light dark;
      --bg:#eef4f1;
      --bg-2:#d7e3de;
      --panel:rgba(255,255,255,.62);
      --panel-fallback:#f8fbf9;
      --text:#17252a;
      --muted:#5d6e74;
      --accent:#0f8a70;
      --accent-2:#f28f3b;
      --accent-soft:rgba(15,138,112,.16);
      --warm:rgba(242,143,59,.14);
      --grid-line:rgba(15,138,112,.075);
      --line:rgba(255,255,255,.68);
      --panel-shadow:0 2px 1px rgba(255,255,255,.36), 0 16px 34px rgba(29,42,46,.16), 0 40px 84px rgba(29,42,46,.20), inset 1px 1px 0 rgba(255,255,255,.86), inset -1px -1px 0 rgba(60,82,86,.16), inset 0 18px 34px rgba(255,255,255,.22);
      --edge-shadow:rgba(31,48,52,.18);
      --note-bg:rgba(255,255,255,.44);
      --note-border:rgba(15,138,112,.25);
      --note-text:#4c605a;
      --shine:.72;
    }}
    html[data-theme-mode="light"]{{
      color-scheme:light;
      --bg:#eef4f1;
      --bg-2:#d7e3de;
      --panel:rgba(255,255,255,.62);
      --panel-fallback:#f8fbf9;
      --text:#17252a;
      --muted:#5d6e74;
      --accent:#0f8a70;
      --accent-2:#f28f3b;
      --accent-soft:rgba(15,138,112,.16);
      --warm:rgba(242,143,59,.14);
      --grid-line:rgba(15,138,112,.075);
      --line:rgba(255,255,255,.68);
      --panel-shadow:0 2px 1px rgba(255,255,255,.36), 0 16px 34px rgba(29,42,46,.16), 0 40px 84px rgba(29,42,46,.20), inset 1px 1px 0 rgba(255,255,255,.86), inset -1px -1px 0 rgba(60,82,86,.16), inset 0 18px 34px rgba(255,255,255,.22);
      --edge-shadow:rgba(31,48,52,.18);
      --note-bg:rgba(255,255,255,.44);
      --note-border:rgba(15,138,112,.25);
      --note-text:#4c605a;
      --shine:.72;
    }}
    html[data-theme-mode="dark"]{{
      color-scheme:dark;
      --bg:#0b1210;
      --bg-2:#14201c;
      --panel:rgba(23,34,31,.68);
      --panel-fallback:#18211d;
      --text:#ecf2ee;
      --muted:#a7b5ae;
      --accent:#47c7a7;
      --accent-2:#f0a75e;
      --accent-soft:rgba(71,199,167,.13);
      --warm:rgba(240,167,94,.13);
      --grid-line:rgba(71,199,167,.105);
      --line:rgba(220,255,244,.18);
      --panel-shadow:0 2px 1px rgba(255,255,255,.06), 0 18px 38px rgba(0,0,0,.44), 0 48px 96px rgba(0,0,0,.56), inset 1px 1px 0 rgba(255,255,255,.18), inset -1px -1px 0 rgba(0,0,0,.50), inset 0 18px 34px rgba(255,255,255,.045);
      --edge-shadow:rgba(0,0,0,.46);
      --note-bg:rgba(20,32,28,.58);
      --note-border:rgba(71,199,167,.24);
      --note-text:#bfd5cc;
      --shine:.24;
    }}
    @media (prefers-color-scheme:dark){{
      :root{{
        --bg:#0b1210;
        --bg-2:#14201c;
        --panel:rgba(23,34,31,.68);
        --panel-fallback:#18211d;
        --text:#ecf2ee;
        --muted:#a7b5ae;
        --accent:#47c7a7;
        --accent-2:#f0a75e;
        --accent-soft:rgba(71,199,167,.13);
        --warm:rgba(240,167,94,.13);
        --grid-line:rgba(71,199,167,.105);
        --line:rgba(220,255,244,.18);
        --panel-shadow:0 2px 1px rgba(255,255,255,.06), 0 18px 38px rgba(0,0,0,.44), 0 48px 96px rgba(0,0,0,.56), inset 1px 1px 0 rgba(255,255,255,.18), inset -1px -1px 0 rgba(0,0,0,.50), inset 0 18px 34px rgba(255,255,255,.045);
        --edge-shadow:rgba(0,0,0,.46);
        --note-bg:rgba(20,32,28,.58);
        --note-border:rgba(71,199,167,.24);
        --note-text:#bfd5cc;
        --shine:.24;
      }}
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{min-height:100vh;width:100%;padding:clamp(12px,2vw,28px);display:block;
          background:
            linear-gradient(135deg,var(--accent-soft) 0%,transparent 36%),
            linear-gradient(315deg,var(--warm) 0%,transparent 40%),
            linear-gradient(180deg,var(--bg) 0%,var(--bg-2) 100%);
          background-attachment:fixed;
          color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;overflow-x:hidden}}
    body::before{{content:"";position:fixed;inset:0;pointer-events:none;
          background-image:linear-gradient(var(--grid-line) 1px,transparent 1px),linear-gradient(90deg,var(--grid-line) 1px,transparent 1px);
          background-size:56px 56px;mask-image:linear-gradient(180deg,rgba(0,0,0,.70),rgba(0,0,0,.18) 78%,transparent);
          -webkit-mask-image:linear-gradient(180deg,rgba(0,0,0,.70),rgba(0,0,0,.18) 78%,transparent)}}
    .panel{{position:relative;overflow:visible;width:100%;max-width:none;min-width:0;background:var(--panel);
            border:1px solid var(--line);border-radius:8px;padding:clamp(18px,2.4vw,38px);
            box-shadow:var(--panel-shadow);backdrop-filter:blur(18px) saturate(1.24);
            -webkit-backdrop-filter:blur(18px) saturate(1.24)}}
    .panel::before{{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;
            background:linear-gradient(145deg,rgba(255,255,255,.70),rgba(255,255,255,.16) 36%,rgba(255,255,255,0) 62%);
            opacity:var(--shine)}}
    .panel::after{{content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;
            background:linear-gradient(315deg,var(--edge-shadow),rgba(0,0,0,0) 34%),linear-gradient(180deg,rgba(255,255,255,.30),rgba(255,255,255,0) 18%);
            mix-blend-mode:multiply;opacity:.74}}
    .panel>*{{position:relative}}
    @supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){{
      .panel{{background:var(--panel-fallback)}}
    }}
    .eyebrow{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}}
    h1{{font-size:clamp(28px,5vw,44px);line-height:1.08;margin-bottom:14px}}
    h2{{font-size:20px;line-height:1.25;margin-bottom:10px}}
    h3{{font-size:15px;line-height:1.25;margin-bottom:8px}}
    p{{font-size:16px;line-height:1.6;color:var(--muted);max-width:34rem}}
    .session-tag{{display:inline-flex;align-items:center;gap:8px;margin:0 0 14px;padding:8px 12px;border-radius:999px;
                  background:var(--accent-soft);color:var(--text);font-size:12px;font-weight:600}}
    .portal-side{{display:grid;justify-items:end;align-content:start;gap:8px;max-width:min(760px,100%);min-width:min(360px,100%)}}
    .language-switch{{grid-column:1;grid-row:1 / span 2;align-self:center;display:block;width:38px;height:26px;padding:0;
                      border:0;border-radius:2px;background:transparent;color:inherit;cursor:pointer;
                      box-shadow:0 1px 3px rgba(0,0,0,.24);overflow:hidden;
                      transition:box-shadow .14s ease,transform .14s ease}}
    .language-switch:hover{{transform:translateY(-1px);box-shadow:0 3px 7px rgba(0,0,0,.28)}}
    .language-switch:focus-visible{{outline:2px solid var(--accent);outline-offset:3px}}
    .language-switch-flag{{display:block;width:38px;height:26px}}
    .language-switch-flag[hidden]{{display:none}}
    .session-block{{display:grid;justify-items:end;align-content:start;gap:8px;max-width:min(540px,100%)}}
    .session-notice-slot{{width:min(540px,100%);min-height:0}}
    .session-notice-slot .notice{{margin:0}}
    .session-notice-slot .notice-error{{margin:0}}
    .device-identity{{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:5px 14px;margin-top:8px;
                      font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;color:var(--text);
                      font-size:13px;line-height:1.35;max-width:min(520px,100%)}}
    .device-meta{{display:grid;grid-template-columns:max-content max-content minmax(0,max-content);grid-template-rows:repeat(2,13px);
                  justify-content:end;align-items:center;column-gap:10px;row-gap:0;height:26px;margin:0;
                  font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;font-size:11px;line-height:13px;
                  max-width:min(760px,100%);text-align:left}}
    .device-meta .identity-label{{grid-column:2;align-self:center;font-size:11px;line-height:13px}}
    .device-meta .identity-value{{grid-column:3;max-width:min(620px,52vw);line-height:13px;white-space:nowrap;
                                  overflow:hidden;text-overflow:ellipsis;overflow-wrap:normal}}
    .identity-label{{align-self:baseline;color:var(--accent);font-size:16px;font-weight:900;text-transform:uppercase;letter-spacing:0}}
    .identity-value{{min-width:0;color:var(--muted);overflow-wrap:anywhere}}
    .identity-device-value{{color:var(--text);font-size:16px;font-weight:900}}
    .portal-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px;min-width:0}}
    .portal-title{{min-width:min(240px,100%)}}
    @media (max-width:720px){{
      .portal-side,.session-block{{justify-items:start;min-width:0;width:100%}}
      .device-meta{{justify-content:start;max-width:100%}}
      .device-meta .identity-value{{max-width:100%}}
    }}
    .portal-shell{{display:grid;grid-template-columns:minmax(190px,260px) minmax(0,1fr);gap:clamp(14px,1.7vw,28px);align-items:start;min-width:0}}
    .portal-menu{{display:grid;gap:8px;position:sticky;top:18px}}
    .menu-btn{{width:100%;min-height:44px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);
               color:var(--text);font:inherit;font-weight:700;text-align:left;padding:10px 12px;cursor:pointer;
               display:flex;align-items:center;gap:10px;text-decoration:none;
               transition:background-color .14s ease,border-color .14s ease,transform .14s ease}}
    .menu-btn:hover{{background:var(--accent-soft);border-color:var(--accent)}}
    .menu-btn[aria-selected="true"]{{background:var(--accent-soft);border-color:var(--accent);transform:translateY(1px);box-shadow:inset 0 2px 6px rgba(0,0,0,.12),inset 0 0 0 1px var(--accent)}}
    .menu-index{{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;
                 background:var(--panel);border:1px solid var(--line);font-size:12px;color:var(--accent);flex:0 0 auto}}
    .portal-content{{min-width:0;width:100%}}
    .portal-panel{{display:none}}
    .portal-panel.is-active{{display:block}}
    .summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:12px;margin-top:18px}}
    .summary-item{{border-top:1px solid var(--line);padding-top:12px}}
    .metric{{display:flex;align-items:baseline;justify-content:space-between;gap:12px;border-top:1px solid var(--line);
             padding:11px 0;color:var(--text)}}
    .metric span{{font-size:13px;color:var(--muted)}}
    .metric strong{{font-size:14px;text-align:right}}
    #panel-antenna .summary-grid{{gap:18px}}
    #panel-antenna .summary-item{{
      padding:12px 14px;
      position:relative;
      border:1px solid var(--line);
      border-radius:12px;
      background:color-mix(in srgb, var(--panel) 84%, white 16%);
      box-shadow:0 10px 24px rgba(0,0,0,.08), inset 0 1px 0 rgba(255,255,255,.22);
    }}
    html[data-theme-mode="dark"] #panel-antenna .summary-item{{
      background:color-mix(in srgb, var(--panel) 90%, black 10%);
      box-shadow:0 8px 22px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.06);
    }}
    #panel-antenna .summary-item + .summary-item::before{{content:none}}
    #panel-antenna .summary-item h3{{margin-bottom:8px}}
    #panel-antenna .metric{{padding:7px 0;gap:18px}}
    #panel-antenna .metric span{{font-size:12px;line-height:1.2}}
    #panel-antenna .metric strong{{font-size:14px;line-height:1.2;min-width:78px;text-align:right}}
    #panel-antenna .sensor-list,#panel-operation .sensor-list,#panel-group .sensor-list{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
    #panel-antenna .sensor-list-block{{padding-top:8px;border-top:1px solid var(--line)}}
    #panel-antenna .sensor-chip,#panel-operation .sensor-chip,#panel-group .sensor-chip{{display:inline-flex;align-items:center;gap:5px;max-width:100%;
      border:1px solid var(--line);border-radius:6px;background:var(--note-bg);
      color:var(--text);font-size:11px;line-height:1.2;padding:5px 7px;overflow-wrap:anywhere}}
    #panel-antenna .sensor-chip b,#panel-operation .sensor-chip b,#panel-group .sensor-chip b{{font-size:11px;color:var(--accent)}}
    #panel-group .group-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
    #panel-group .group-head-actions{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    #panel-group .group-update{{font-size:12px;color:var(--muted,#888)}}
    #panel-group .group-refresh{{min-height:28px;padding:4px 9px;font-size:11px}}
    #panel-group .group-legend{{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:10px 0 2px;font-size:12px;color:var(--text)}}
    #panel-group .group-legend .group-dot{{margin-right:5px}}
    #panel-group .group-matrix-wrap{{overflow-x:auto;margin-top:12px;border-radius:10px}}
    #panel-group .group-matrix{{border-collapse:collapse;width:auto;min-width:100%;font-size:13px}}
    #panel-group .group-matrix th,#panel-group .group-matrix td{{border:1px solid var(--line);padding:8px 14px;text-align:center;white-space:nowrap}}
    #panel-group .group-matrix .group-param{{text-align:left;font-weight:600;color:var(--text);background:var(--note-bg);position:sticky;left:0;z-index:1}}
    #panel-group .group-matrix .group-dev-head{{font-weight:700;vertical-align:bottom}}
    #panel-group .group-matrix .group-dev-code{{display:block;font-size:15px;color:var(--accent);letter-spacing:.5px}}
    #panel-group .group-matrix .group-dev-badge{{display:block;margin-top:3px;font-size:10px;font-weight:600;color:var(--text);opacity:.7;text-transform:uppercase}}
    #panel-group .group-matrix .group-dev-cell.is-local{{background:color-mix(in srgb, var(--accent) 14%, transparent)}}
    #panel-group .group-matrix .group-dev-head.is-local{{box-shadow:inset 0 3px 0 var(--accent)}}
    #panel-group .group-ip-link{{color:var(--accent);font-weight:700;text-decoration:underline;text-underline-offset:2px}}
    #panel-group .group-dot{{display:inline-block;width:14px;height:14px;border-radius:50%;background:#9aa0a6;vertical-align:middle}}
    #panel-group .group-dot.is-green{{background:#2ecc71;box-shadow:0 0 7px rgba(46,204,113,.7)}}
    #panel-group .group-dot.is-red{{background:#e74c3c;box-shadow:0 0 7px rgba(231,76,60,.7)}}
    #panel-group .group-dot.is-off{{background:#9aa0a6}}
    #panel-group .group-flag{{font-weight:600}}
    #panel-group .group-flag.is-on{{color:#2ecc71}}
    #panel-group .group-flag.is-off,#panel-group .group-flag.is-unknown{{color:var(--muted,#888)}}
    #panel-group .group-empty{{margin-top:12px;font-size:12px;color:var(--muted,#888)}}
    #panel-group .group-note{{margin-top:10px;font-size:11px;color:var(--muted,#888)}}
    #panel-group .group-matrix .group-dev-ctl{{padding:4px 10px}}
    #panel-group .group-matrix .group-ctl-select{{height:24px;min-height:24px;font-size:12px;line-height:20px;padding:1px 4px}}
    #panel-group .group-role-control{{display:flex;align-items:center;justify-content:center;gap:6px;min-height:24px;white-space:nowrap}}
    #panel-group .group-role-assigned{{font-size:10px;line-height:12px;color:var(--muted,#888)}}
    #panel-group .group-role-feedback{{font-size:10px;line-height:12px;color:#2ecc71;white-space:nowrap}}
    #panel-group .group-role-feedback:empty{{display:none}}
    #panel-group .group-role-feedback.is-error{{color:#e74c3c}}
    #panel-group .group-matrix .group-dev-ctl input[type=checkbox]{{width:16px;height:16px;cursor:pointer}}
    #panel-group .group-matrix .group-dev-ctl input[type=checkbox]:disabled,#panel-group .group-matrix .group-ctl-select:disabled{{opacity:.4;cursor:not-allowed}}
    #panel-group .group-led-form{{display:grid;gap:10px;margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}}
    #panel-group .group-led-head{{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}}
    #panel-group .group-led-head h3{{margin:0;font-size:15px}}
    #panel-group .group-led-feedback{{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;font-size:12px;color:var(--muted);font-weight:600}}
    #panel-group .group-led-feedback b{{color:var(--text);font-weight:700}}
    #panel-group .group-led-table-wrap{{overflow-x:auto;border-radius:10px}}
    #panel-group .group-led-table{{width:100%;min-width:520px;border-collapse:collapse;font-size:13px}}
    #panel-group .group-led-table th,#panel-group .group-led-table td{{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:middle}}
    #panel-group .group-led-table thead th{{font-size:12px;color:var(--muted);background:var(--note-bg)}}
    #panel-group .group-led-table tbody th{{font-weight:700;color:var(--text);background:var(--note-bg);width:44%}}
    #panel-group .group-led-select{{width:100%;min-width:132px;min-height:34px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);color:var(--text);font:inherit;padding:6px 8px}}
    #panel-group .group-led-test-cell{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    #panel-group .group-led-test-btn{{display:inline-flex;align-items:center;justify-content:center;width:74px;min-width:74px;min-height:34px;padding:6px 10px;border-radius:8px}}
    #panel-group .group-led-test-btn.is-active,#panel-group .group-led-test-btn[aria-pressed="true"]{{border-color:var(--accent);background:var(--accent-soft);color:var(--text);box-shadow:inset 0 0 0 1px var(--accent)}}
    #panel-group .group-led-test-btn.is-busy{{opacity:.62;cursor:wait}}
    #panel-group .group-nonaddr-led-row{{display:flex;align-items:center;gap:10px 16px;flex-wrap:wrap;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--note-bg)}}
    #panel-group .group-nonaddr-led-label{{display:grid;gap:2px;flex:1 1 260px;color:var(--text)}}
    #panel-group .group-nonaddr-led-label strong{{font-size:13px}}
    #panel-group .group-nonaddr-led-label span{{font-size:11px;color:var(--muted)}}
    #panel-group .group-nonaddr-led-enable{{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:700;white-space:nowrap}}
    #panel-group .group-nonaddr-led-enable input{{width:17px;height:17px;cursor:pointer}}
    #panel-group .group-nonaddr-led-level{{min-width:70px;font-size:12px;font-weight:800;color:var(--accent);text-align:center}}
    #panel-group .group-led-actions{{display:flex;align-items:center;gap:8px;justify-content:flex-end;flex-wrap:wrap}}
    .security-note{{display:none;margin-top:18px;border:1px solid var(--note-border);background:var(--note-bg);
                    color:var(--note-text);border-radius:8px;padding:12px 14px;font-size:12px;line-height:1.55;
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .security-note strong{{color:var(--text)}}
    .config-form{{display:grid;gap:18px;margin-top:18px}}
    .section{{border-top:1px solid var(--line);padding-top:18px}}
    .section h2{{font-size:17px;line-height:1.25;margin-bottom:10px}}
    .mode-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:8px}}
    .mode-option{{display:flex;align-items:center;justify-content:center;min-height:48px;border:1px solid var(--line);
                  border-radius:8px;background:var(--note-bg);cursor:pointer;font-weight:700;color:var(--text)}}
    .mode-option input{{position:absolute;opacity:0;pointer-events:none}}
    .mode-option:has(input:checked){{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent)}}
    .smooth-mode-select{{width:min(100%,180px);min-height:42px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;
                         background:var(--note-bg);color:var(--text);font-family:inherit;font-size:14px;font-weight:800;cursor:pointer}}
    .smooth-mode-select:hover,.smooth-mode-select:focus{{border-color:var(--accent);outline:none}}
    .fields{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}}
    .field{{display:grid;gap:6px}}
    .field span{{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:var(--text)}}
    .field input,.field select{{width:100%;min-height:42px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);
                  color:var(--text);font:inherit;padding:9px 11px;box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .field select{{appearance:auto}}
    .field small{{font-size:12px;line-height:1.45;color:var(--muted)}}
    #panel-detection .config-form{{margin-top:-8px;gap:14px}}
    #panel-detection .section{{padding-top:12px}}
    #panel-detection .section:first-child{{border-top:none;padding-top:0}}
    #panel-detection .section h2{{margin-bottom:8px}}
    #panel-detection .notice{{margin-top:0}}
    .operation-config-form{{gap:12px;margin-top:0;margin-bottom:0}}
    .operation-topline{{display:grid;gap:8px;min-width:0;padding:12px 0;
                        border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
    .operation-topline h3{{margin:0;font-size:13px;color:var(--muted);white-space:nowrap}}
    .dc-timing-row{{display:flex;align-items:flex-start;gap:6px;min-width:0;flex-wrap:wrap}}
    .dc-timing-field{{display:grid;grid-template-rows:auto auto;gap:5px;flex:1 1 88px;min-width:64px;min-height:58px}}
    .dc-timing-label{{display:flex;align-items:center;gap:5px;min-width:0;flex:1 1 auto;color:var(--text);
                      width:100%;max-width:100%;font-size:12px;font-weight:700;line-height:1.2}}
    .dc-timing-text{{display:block;min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .dc-timing-field .help{{flex:0 0 auto;width:16px;height:16px;font-size:11px}}
    .dc-timing-field input{{width:100%;min-width:0;min-height:38px;border:1px solid var(--line);
                            border-radius:8px;background:var(--note-bg);color:var(--text);font:inherit;
                            font-variant-numeric:tabular-nums;padding:8px 5px;text-align:right;
                            box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .operation-lowerline{{display:flex;align-items:end;gap:12px;flex-wrap:wrap}}
    .operation-avg-field{{flex:1 1 220px;max-width:320px}}
    .operation-sound{{display:grid;gap:10px;width:100%;padding:12px 0;border-top:1px solid var(--line)}}
    .operation-sound-head{{display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
    .operation-sound-head h3{{margin:0;font-size:13px;color:var(--muted);white-space:nowrap}}
    .sound-toggle{{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:800;color:var(--text);cursor:pointer}}
    .sound-toggle input{{width:16px;height:16px;accent-color:var(--accent)}}
    .sound-volume{{display:grid;grid-template-columns:auto minmax(160px,1fr) auto;gap:8px;align-items:center;min-width:min(100%,390px);flex:1 1 320px}}
    .sound-volume-label{{font-size:12px;font-weight:800;color:var(--text);white-space:nowrap}}
    .sound-volume input{{width:100%;accent-color:var(--accent)}}
    .sound-volume-output{{font-size:12px;font-weight:900;color:var(--accent);font-variant-numeric:tabular-nums;min-width:44px;text-align:right}}
    .sound-fields{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:8px}}
    .sound-field{{display:grid;gap:4px}}
    .sound-field span{{font-size:12px;font-weight:800;color:var(--text)}}
    .sound-field input{{width:100%;min-height:36px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);color:var(--text);
                        font:inherit;font-variant-numeric:tabular-nums;padding:7px 8px;box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .operation-lcd-role{{display:flex;align-items:center;gap:8px 12px;white-space:nowrap;width:100%;overflow-x:auto;padding:10px 0;border-top:1px solid var(--line)}}
    .operation-lcd-role h3{{margin:0;font-size:13px;color:var(--muted)}}
    .lcd-role-field{{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:800}}
    .lcd-role-field select{{min-height:34px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);color:var(--text);padding:5px 8px}}
    .lcd-role-status{{font-size:12px;font-weight:900;color:var(--accent)}}
    .operation-actions{{width:100%;justify-content:flex-end;padding-top:12px;border-top:1px solid var(--line)}}
    .tag-settings{{width:100%;border-collapse:collapse;margin-top:10px;border-top:1px solid var(--line)}}
    .tag-settings th,.tag-settings td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:middle;text-align:left}}
    .tag-settings th{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
    .tag-settings .tag-desc{{width:40%;min-width:190px;color:var(--text)}}
    .tag-param{{display:inline-flex;align-items:center;gap:6px;min-width:0;font-size:13px;font-weight:800;line-height:1.2}}
    .tag-help{{position:relative;flex:0 0 auto;cursor:help}}
    .tag-help[data-tip]::after{{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 8px);
                 width:max-content;max-width:min(300px,72vw);padding:7px 9px;border:1px solid var(--line);
                 border-radius:6px;background:var(--panel-fallback);color:var(--text);
                 box-shadow:0 12px 28px rgba(0,0,0,.18),inset 0 1px 0 rgba(255,255,255,.18);
                 font-size:12px;font-weight:600;line-height:1.35;text-transform:none;letter-spacing:0;text-align:left;
                 white-space:normal;opacity:0;visibility:hidden;pointer-events:none;z-index:80;
                 transform:translate(-50%,4px);transition:opacity .12s ease,visibility .12s ease,transform .12s ease}}
    .tag-help[data-tip]:hover::after,.tag-help[data-tip]:focus-visible::after{{opacity:1;visibility:visible;transform:translate(-50%,0)}}
    .tag-settings .tag-channel{{width:30%;text-align:center}}
    .tag-control{{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:32px;font-size:13px}}
    .tag-control input[type="checkbox"]{{width:16px;height:16px;accent-color:var(--accent)}}
    .tag-control input[type="number"],.tag-control select{{width:min(100%,112px);min-height:32px;border:1px solid var(--line);border-radius:6px;background:var(--note-bg);
                  color:var(--text);font:inherit;padding:5px 8px;box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .tag-noise-control{{flex-wrap:wrap;justify-content:center;gap:7px 8px}}
    .tag-noise-pair{{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}}
    .tag-settings td[colspan] .tag-noise-pair{{flex-wrap:wrap;white-space:normal;justify-content:flex-start}}
    .tag-inline-check{{margin-right:12px;justify-content:flex-start}}
    .tag-mini-field{{display:inline-flex;align-items:center;gap:4px;color:var(--muted);font-size:11px;font-weight:800}}
    .tag-mini-field input{{width:54px!important;min-height:28px!important;padding:4px 6px!important;text-align:right;font-variant-numeric:tabular-nums}}
    .tag-mini-field.tag-mini-check input[type="checkbox"]{{width:16px!important;min-height:16px!important;padding:0!important;text-align:initial}}
    .tag-mini-field select{{width:94px!important;min-height:28px!important;padding:4px 6px!important;font-size:12px}}
    .tag-control input[readonly]{{opacity:.46;cursor:not-allowed}}
    .privacy-status-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:10px;margin:0 0 14px}}
    .privacy-status{{border:1px solid var(--line);border-radius:8px;background:var(--note-bg);padding:11px 12px;
                     box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .privacy-status h3{{margin:0 0 8px;font-size:14px;display:flex;align-items:center;justify-content:space-between;gap:8px}}
    .status-head{{display:flex;align-items:center;justify-content:flex-start;gap:8px;margin:0 0 8px}}
    .status-head h3{{margin:0;flex:1 1 auto}}
    .channel-permission{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;flex:0 0 auto}}
    .channel-permission input{{width:16px;height:16px;margin:0;accent-color:var(--accent);cursor:pointer}}
    .privacy-status .metric{{padding:7px 0}}
    .privacy-status .metric:first-of-type{{border-top:none}}
    .privacy-status h3 strong[data-connection-count]{{font-size:20px;color:var(--accent);line-height:1}}
    .privacy-forms{{display:grid;gap:14px;margin-top:14px}}
    .privacy-form{{display:grid;gap:10px;border-top:1px solid var(--line);padding-top:14px}}
    .privacy-title-row{{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:24px}}
    .privacy-form h3{{margin-bottom:0}}
    .privacy-toggle{{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:700;color:var(--muted);cursor:pointer}}
    .privacy-toggle input{{width:16px;height:16px;accent-color:var(--accent)}}
    .privacy-fields{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:10px;align-items:end}}
    .privacy-fields .field input,.privacy-fields .field select{{min-height:40px}}
    .privacy-action{{align-self:end}}
    .privacy-action .actions{{margin-top:0}}
    .privacy-action .link{{width:100%;min-height:40px;padding:9px 12px}}
    .privacy-title-actions{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}}
    .privacy-title-actions .link{{min-height:32px;padding:6px 10px;font-size:12px}}
    .privacy-note{{margin-top:0}}
    .modal-backdrop{{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:18px;
                     background:rgba(0,0,0,.38);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}}
    .modal-backdrop[hidden]{{display:none}}
    .modal-panel{{width:min(100%,520px);border:1px solid var(--line);border-radius:8px;background:var(--panel);
                  box-shadow:var(--panel-shadow);padding:18px;display:grid;gap:12px;
                  backdrop-filter:blur(18px) saturate(1.18);-webkit-backdrop-filter:blur(18px) saturate(1.18)}}
    .modal-head{{display:flex;align-items:center;justify-content:space-between;gap:10px}}
    .modal-head h3{{margin:0}}
    .modal-close{{width:34px;height:34px;border-radius:8px;border:1px solid var(--line);background:var(--note-bg);
                  color:var(--text);font:inherit;font-weight:800;cursor:pointer}}
    .help{{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;
           border:1px solid var(--line);color:var(--accent);font-size:12px;font-weight:800;background:var(--panel)}}
    .notice{{margin-top:16px;border:1px solid var(--note-border);background:var(--note-bg);color:var(--note-text);
             border-radius:8px;padding:11px 13px;font-size:13px;line-height:1.45;max-width:none}}
    .notice-error{{border-color:var(--form-error-border);background:var(--form-error-bg);color:var(--form-error-text)}}
    .actions{{display:flex;flex-wrap:wrap;gap:12px;margin-top:24px}}
    .actions-inline{{margin-top:0}}
    button.link{{font:inherit;cursor:pointer}}
    .link{{display:inline-flex;align-items:center;justify-content:center;padding:11px 18px;
           border-radius:8px;background:var(--panel);color:var(--text);text-decoration:none;font-weight:700;
           border:1px solid var(--line);
           box-shadow:0 1px 0 rgba(255,255,255,.42),0 12px 24px rgba(29,42,46,.14),0 24px 48px rgba(15,138,112,.14),
                      inset 1px 1px 0 rgba(255,255,255,.66),inset -1px -1px 0 rgba(29,42,46,.14);
           transition:background-color .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease,color .14s ease}}
    .link:hover{{background:var(--accent-soft);border-color:var(--accent);transform:translateY(-1px);
           box-shadow:0 1px 0 rgba(255,255,255,.48),0 16px 28px rgba(29,42,46,.16),0 30px 58px rgba(15,138,112,.20),
                      inset 1px 1px 0 rgba(255,255,255,.72),inset -1px -1px 0 rgba(29,42,46,.16)}}
    .link:active{{transform:translateY(1px);box-shadow:inset 0 2px 8px rgba(29,42,46,.18),0 4px 12px rgba(29,42,46,.12)}}
    .link:focus-visible{{outline:2px solid rgba(15,138,112,.34);outline-offset:2px;border-color:var(--accent)}}
    .link-secondary{{background:transparent;color:var(--accent);border:1px solid var(--line);
           box-shadow:inset 0 1px 0 rgba(255,255,255,.16)}}
    .link-secondary:hover{{background:var(--accent-soft);border-color:var(--accent);
           box-shadow:0 1px 0 rgba(255,255,255,.38),0 10px 20px rgba(29,42,46,.12),
                      inset 1px 1px 0 rgba(255,255,255,.48),inset -1px -1px 0 rgba(29,42,46,.12)}}
    .doc-tabs{{display:flex;align-items:flex-end;gap:0;margin:0 0 -1px;padding:0 10px;overflow-x:auto;overflow-y:visible;position:relative;z-index:2}}
    .doc-tab{{min-height:40px;padding:10px 16px;border:1px solid var(--line);border-bottom:none;border-radius:12px 12px 0 0;
          background:linear-gradient(180deg,var(--note-bg),rgba(0,0,0,0));color:var(--text);font:inherit;font-weight:700;
          cursor:pointer;position:relative;top:1px;margin-right:-8px;z-index:1;
          transition:background-color .14s ease,border-color .14s ease,transform .14s ease,box-shadow .14s ease}}
    .doc-tab:hover{{background:var(--accent-soft);border-color:var(--accent);z-index:2;transform:translateY(-1px)}}
    .doc-tab[aria-selected="true"],.doc-tab.is-active{{top:0;background:var(--panel);border-color:var(--accent);
          box-shadow:0 -1px 0 rgba(255,255,255,.28),0 6px 14px rgba(0,0,0,.12);z-index:4;transform:none}}
    .doc-reader{{margin-top:0;padding:14px;border:1px solid var(--line);border-radius:0 10px 10px 10px;background:var(--note-bg);position:relative;z-index:1}}
    .doc-page{{display:none}}
    .doc-page.is-active{{display:block}}
    .doc-text{{margin:0;white-space:pre-wrap;line-height:1.5;font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;
               font-size:12px;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}}
    .doc-downloads{{margin-top:12px;align-items:center}}
    .doc-downloads .subtle{{margin-right:2px}}
    @media (max-width:860px){{
      body{{place-items:start center;padding:0}}
      .panel{{padding:6px 2px;border-radius:0;border-left:none;border-right:none;width:100%;box-shadow:none}}
      .portal-head{{margin-bottom:10px;padding:0 6px}}
      .portal-shell{{grid-template-columns:1fr;gap:6px}}
      .portal-menu{{position:sticky;top:0;z-index:20;display:flex;overflow-x:auto;padding:6px 0 8px;
                    margin:0 -2px 4px;
                    padding-left:6px;padding-right:6px;
                    scroll-snap-type:x proximity;background:var(--panel);
                    border-top:1px solid var(--line);border-bottom:1px solid var(--line);
                    box-shadow:var(--panel-shadow);
                    backdrop-filter:blur(18px) saturate(1.18);-webkit-backdrop-filter:blur(18px) saturate(1.18)}}
      .menu-btn{{width:auto;min-width:178px;flex:0 0 auto;scroll-snap-align:start;white-space:normal}}
      .doc-tabs{{padding:0 2px}}
      .doc-tab{{width:auto;min-width:160px;flex:0 0 auto;margin-right:-6px}}
      .doc-reader{{border-radius:0 6px 6px 6px;padding:4px 2px}}
      .pdf-controls{{flex-wrap:wrap;gap:5px;padding:5px 6px}}
      .pdf-page-nav{{flex:0 0 auto;order:0}}
      .pdf-actions{{flex:0 0 auto;order:1;gap:4px}}
      .pdf-pages{{min-height:160px;padding:2px;margin-top:3px;border-radius:3px}}
      html[data-ui-style="neumorph"] .menu-btn{{box-shadow:4px 4px 8px var(--neumo-lo),-4px -4px 8px var(--neumo-hi)}}
      html[data-ui-style="neumorph"] .menu-btn:hover{{box-shadow:5px 5px 10px var(--neumo-lo),-5px -5px 10px var(--neumo-hi)}}
      html[data-ui-style="neumorph"] .menu-btn[aria-selected="true"]{{box-shadow:inset 4px 4px 8px var(--neumo-lo),inset -4px -4px 8px var(--neumo-hi)}}
      .summary-grid{{grid-template-columns:1fr}}
      .mode-grid,.fields{{grid-template-columns:1fr}}
      .operation-config-form{{padding:0 6px;margin-bottom:10px}}
      .operation-topline{{gap:6px;padding:8px 0}}
      .operation-topline h3{{font-size:12px}}
      .dc-timing-row{{gap:4px;flex-basis:500px}}
      .dc-timing-field{{gap:4px;flex-basis:72px;min-width:58px;min-height:54px}}
      .dc-timing-label{{font-size:11px}}
      .dc-timing-field input{{width:100%;min-width:0;min-height:36px;padding:7px 4px;font-size:12px}}
      .operation-lowerline{{gap:8px}}
      .operation-actions{{justify-content:flex-start;padding-top:8px}}
      .tag-settings,.tag-settings tbody,.tag-settings tr,.tag-settings td{{display:block;width:100%}}
      .tag-settings thead{{display:none}}
      .tag-settings tr{{padding:6px 0;border-bottom:1px solid var(--line)}}
      .tag-settings th,.tag-settings td{{border-bottom:none;padding:5px 4px}}
      .tag-settings .tag-desc{{min-width:0;width:100%;font-weight:700}}
      .tag-help[data-tip]::after{{left:0;max-width:min(320px,86vw);transform:translate(0,4px)}}
      .tag-help[data-tip]:hover::after,.tag-help[data-tip]:focus-visible::after{{transform:translate(0,0)}}
      .tag-settings .tag-channel{{width:100%;text-align:left}}
      .tag-settings .tag-channel::before{{display:block;margin-bottom:4px;color:var(--muted);font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}}
      .tag-settings .tag-channel:nth-child(2)::before{{content:"Upper Channel"}}
      .tag-settings .tag-channel:nth-child(3)::before{{content:"Lower Channel"}}
      .tag-settings .tag-channel[data-channel-label]::before{{content:attr(data-channel-label)}}
      .tag-control{{justify-content:flex-start}}
      .tag-noise-control{{justify-content:flex-start}}
      .privacy-status-grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}}
      .privacy-status{{padding:8px 7px}}
      .privacy-status h3{{font-size:12px}}
      .privacy-status .metric{{display:grid;gap:2px;padding:5px 0}}
      .privacy-status .metric span{{font-size:11px}}
      .privacy-status .metric strong{{font-size:12px;text-align:left}}
      .privacy-status h3 strong[data-connection-count]{{font-size:18px}}
      .privacy-fields{{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
      .privacy-fields .field span{{font-size:12px}}
      .privacy-action .link{{min-height:40px;padding:8px 10px}}
      .privacy-title-row{{align-items:flex-start}}
      .privacy-title-actions{{gap:6px}}
      .privacy-title-actions .link{{min-height:30px;padding:5px 8px;font-size:11px}}
      .scroll-top-btn{{right:8px;bottom:8px}}
    }}
    @media (max-width:560px){{
      .portal-title{{min-width:0;width:100%}}
      .session-block{{justify-items:start;width:100%;max-width:none}}
      .session-tag{{width:100%;justify-content:flex-start;white-space:normal}}
      .privacy-status-grid,.privacy-fields{{grid-template-columns:1fr}}
      .privacy-title-row{{display:grid;gap:8px}}
      .actions{{width:100%}}
      .actions .link{{width:100%}}
    }}
    .pdf-viewer{{display:block;position:relative}}
        .pdf-controls{{display:flex;align-items:center;justify-content:space-between;gap:10px;
          position:-webkit-sticky;position:sticky;top:var(--pdf-controls-top,10px);z-index:32;
            width:100%;align-self:flex-start;
            padding:8px 10px;background:color-mix(in srgb, var(--panel) 62%, transparent);
            border:1px solid color-mix(in srgb, var(--line) 70%, transparent);border-radius:8px;
            backdrop-filter:blur(8px) saturate(1.06);-webkit-backdrop-filter:blur(8px) saturate(1.06);
            box-shadow:0 6px 16px rgba(0,0,0,.12);
            flex-wrap:wrap}}
    .pdf-controls-spacer{{display:none;height:0}}
    .pdf-controls-spacer.is-visible{{display:block}}
    .pdf-controls.is-fixed{{position:fixed;z-index:48;top:var(--pdf-controls-top,10px)}}
    .pdf-btn{{padding:4px 10px;min-height:28px;background:color-mix(in srgb, var(--accent-soft) 72%, transparent);border:1px solid var(--accent);color:var(--accent);
              border-radius:5px;cursor:pointer;font-size:12px;font-weight:500;transition:all 0.2s ease;
              white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center}}
    .pdf-btn:hover{{background:var(--accent);color:var(--bg);transform:translateY(-1px)}}
    .pdf-btn:active{{transform:translateY(0);box-shadow:inset 0 1px 3px rgba(0,0,0,0.2)}}
    .pdf-btn:disabled{{opacity:0.5;cursor:not-allowed;transform:none}}
    .pdf-actions{{display:flex;align-items:center;gap:6px;flex-shrink:0}}
    .pdf-update-btn{{padding:4px 10px;min-height:28px;border-radius:999px;border:1px solid var(--accent);
             background:color-mix(in srgb, var(--accent-soft) 78%, transparent);color:var(--accent);
             font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;
             transition:opacity .16s ease,transform .16s ease,background .16s ease}}
    .pdf-update-btn:hover{{background:var(--accent-soft);transform:translateY(-1px)}}
    .pdf-update-btn[hidden]{{display:none !important}}
    .pdf-update-btn.is-loading{{opacity:.7;cursor:wait}}
    .pdf-check-status{{font-size:11px;color:var(--muted);white-space:nowrap;opacity:.75}}
    .pdf-page-nav{{display:flex;align-items:center;gap:6px;justify-content:center}}
    .pdf-page-input{{width:52px;min-height:28px;padding:3px 6px;border:1px solid var(--line);border-radius:4px;
                     background:var(--panel);color:var(--text);font-size:12px;text-align:center}}
    .pdf-page-input:focus-visible{{outline:2px solid rgba(15,138,112,.24);border-color:var(--accent)}}
    .pdf-page-total{{font-size:12px;color:var(--muted);min-width:40px;text-align:left}}
        .pdf-pages{{display:flex;justify-content:center;align-items:flex-start;overflow:visible;
                background:var(--panel);border:1px solid var(--line);border-radius:8px;
          padding:10px;min-height:400px;margin-top:8px}}
    .pdf-canvas{{max-width:100%;max-height:100%;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.15);
                 animation:pageFlip 0.3s ease-out}}
        .scroll-top-btn{{position:fixed;right:16px;bottom:18px;z-index:40;
             width:44px;height:44px;border-radius:999px;border:1px solid var(--line);
             background:color-mix(in srgb, var(--panel) 62%, transparent);
             color:var(--text);font-size:20px;line-height:1;cursor:pointer;
             backdrop-filter:blur(8px) saturate(1.08);-webkit-backdrop-filter:blur(8px) saturate(1.08);
             box-shadow:0 8px 18px rgba(0,0,0,.16);
             opacity:0;pointer-events:none;transform:translateY(8px);
             transition:opacity .18s ease,transform .18s ease,background .16s ease}}
        .scroll-top-btn.is-visible{{opacity:.92;pointer-events:auto;transform:translateY(0)}}
        .scroll-top-btn:hover{{opacity:1;background:color-mix(in srgb, var(--accent-soft) 74%, transparent)}}
    @keyframes pageFlip{{
      from{{opacity:0;transform:rotateX(-10deg)}}
      to{{opacity:1;transform:rotateX(0deg)}}
    }}
  </style>
{render_debug_style_css()}
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
  <script>pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';</script>
</head>
<body>
  <main class="panel">
    <div class="portal-head">
      <div class="portal-title">
        <p class="eyebrow" data-header-en="BMI30 Management Portal" data-header-uk="Портал керування BMI30">BMI30 Management Portal</p>
        <h1 data-header-en="Device Control" data-header-uk="Керування пристроєм">Device Control</h1>
        <p class="device-identity">
          <span class="identity-label" data-header-en="Device" data-header-uk="Пристрій">Device</span><strong class="identity-value identity-device-value">{title}</strong>
        </p>
      </div>
      <div class="portal-side">
        <p class="device-meta">
          <button class="language-switch" id="portal-language-switch" type="button">
            <svg class="language-switch-flag language-switch-flag-uk" viewBox="0 0 38 26" aria-hidden="true" focusable="false">
              <rect width="38" height="13" fill="#0057b7"/><rect y="13" width="38" height="13" fill="#ffd700"/>
            </svg>
            <svg class="language-switch-flag language-switch-flag-en" viewBox="0 0 60 40" aria-hidden="true" focusable="false" hidden>
              <rect width="60" height="40" fill="#012169"/>
              <path d="M0 0l60 40M60 0L0 40" stroke="#fff" stroke-width="8"/>
              <path d="M0 0l60 40M60 0L0 40" stroke="#c8102e" stroke-width="4"/>
              <path d="M30 0v40M0 20h60" stroke="#fff" stroke-width="12"/>
              <path d="M30 0v40M0 20h60" stroke="#c8102e" stroke-width="7"/>
            </svg>
          </button>
          <span class="identity-label">RPI</span><span class="identity-value">{rpi_identity_text}</span>
          <span class="identity-label">STM32</span><span class="identity-value" data-sensor-text="header-stm32">{stm32_identity_text}</span>
        </p>
        <div class="session-block">
          <p class="session-tag" data-header-session data-username="{signed_in_as or 'authorized user'}" data-role="{session_role}">Signed in as {signed_in_as or "authorized user"} · {access_label}</p>
          <div class="session-notice-slot">{notice_html}</div>
        </div>
      </div>
    </div>
    <div class="portal-shell">
      <nav class="portal-menu" aria-label="Management sections">
        <button class="menu-btn" type="button" data-panel="antenna" aria-selected="true" title="Displays current antenna parameters: signal level, noise, temperature readings, and sensor data."><span class="menu-index">1</span>Antenna Status</button>
        <button class="menu-btn" type="button" data-panel="detection" aria-selected="false" title="Shows detection algorithm, thresholds, filtering settings, and tag type selection."><span class="menu-index">2</span>Tag Detection</button>
        <button class="menu-btn" type="button" data-panel="operation" aria-selected="false" title="Shows radar connection state, transmitter schedule, and runtime behavior settings."><span class="menu-index">3</span>Operating Mode</button>
        <button class="menu-btn" type="button" data-panel="group" aria-selected="false" title="Shows master/slave role, synchronization status, and group operation settings."><span class="menu-index">4</span>Group Mode</button>
        <button class="menu-btn" type="button" data-panel="privacy" aria-selected="false" title="Change portal credentials, HotSpot access, and Wi-Fi internet connection."><span class="menu-index">5</span>Privacy</button>
        <button class="menu-btn" type="button" data-panel="statistics" aria-selected="false" title="Shows runtime counters, detection history, communication quality, and service statistics."><span class="menu-index">6</span>Statistics</button>
        <button class="menu-btn" type="button" data-panel="documentation" aria-selected="false"><span class="menu-index">7</span>Documentation</button>
        <button class="menu-btn" type="button" data-panel="about" aria-selected="false" title="Shows device identity, firmware version, host software version, serial number, and hardware info."><span class="menu-index">8</span>About Device</button>
        <a class="menu-btn" href="{core_oscilloscope_url}" target="_blank" rel="noopener noreferrer" title="Open BMI30 core oscilloscope page in a new tab."><span class="menu-index">9</span>Oscilloscope</a>
        <a class="menu-btn" href="/portal-logout" aria-label="Sign Out"><span class="menu-index" aria-hidden="true">&#x21AA;</span>Sign Out</a>
      </nav>
      <div class="portal-content">
        <section class="portal-panel is-active" id="panel-antenna">
          <div class="summary-grid">
            <div class="summary-item"><h3>Signal</h3><div class="metric"><span>TX</span><strong data-sensor-text="local-tx">---</strong></div><div class="metric"><span>Level</span><strong>---</strong></div><div class="metric"><span>Noise</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Sensors</h3>{temp_metrics}{device_sensor_metrics}</div>
            <div class="summary-item"><h3>Device</h3><div class="metric"><span>Stream</span><strong>---</strong></div><div class="metric"><span>DC control</span><strong>RPi → speed only</strong></div></div>
          </div>
        </section>
        <section class="portal-panel" id="panel-detection">
          <form class="config-form" method="post" action="/portal-tag-detection-config">
            <div class="section">
              <h2>Channel Decision Settings</h2>
              <table class="tag-settings">
                <thead>
                  <tr>
                    <th class="tag-desc">Parameter</th>
                    <th class="tag-channel">Upper Channel</th>
                    <th class="tag-channel">Lower Channel</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Detection channel enable <b class="help tag-help" tabindex="0" aria-label="Disabled channels do not participate in the tag decision." data-tip="Disabled channels do not participate in the tag decision.">?</b></span>
                    </td>
                    <td class="tag-channel">
                      <label class="tag-control"><input type="hidden" name="enabled0" value="0"><input type="checkbox" name="enabled0" value="1"{tag_enabled0_checked}>Enabled</label>
                    </td>
                    <td class="tag-channel">
                      <label class="tag-control"><input type="hidden" name="enabled1" value="0"><input type="checkbox" name="enabled1" value="1"{tag_enabled1_checked}>Enabled</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Detection confirmations <b class="help tag-help" tabindex="0" aria-label="Number of detections before accepting the decision. Range 1-6, default 2." data-tip="Number of detections before accepting the decision. Range 1-6, default 2.">?</b></span>
                    </td>
                    <td class="tag-channel"><label class="tag-control"><select name="confirm0">{tag_confirm0_options}</select></label></td>
                    <td class="tag-channel"><label class="tag-control"><select name="confirm1">{tag_confirm1_options}</select></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Confirmation phase gate <b class="help tag-help" tabindex="0" aria-label="Maximum allowed movement of the next detection maximum relative to the previous confirmed maximum, in samples. A larger movement starts a new confirmation chain. Range 0-199, default 3." data-tip="Maximum allowed movement of the next detection maximum relative to the previous confirmed maximum, in samples. A larger movement starts a new confirmation chain. Range 0-199, default 3.">?</b></span>
                    </td>
                    <td class="tag-channel" colspan="2">
                      <label class="tag-control"><input name="confirm_phase_gate" type="number" min="0" max="199" step="1" inputmode="numeric" value="{tag_confirm_phase_gate_value}" aria-label="Confirmation phase gate in samples"> samples</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Automatic threshold <b class="help tag-help" tabindex="0" aria-label="When enabled, the manual threshold field is inactive." data-tip="When enabled, the manual threshold field is inactive.">?</b></span>
                    </td>
                    <td class="tag-channel">
                      <label class="tag-control"><input type="hidden" name="auto0" value="0"><input type="checkbox" name="auto0" value="1" data-tag-auto="upper"{tag_auto0_checked}>Auto</label>
                    </td>
                    <td class="tag-channel">
                      <label class="tag-control"><input type="hidden" name="auto1" value="0"><input type="checkbox" name="auto1" value="1" data-tag-auto="lower"{tag_auto1_checked}>Auto</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Manual low-noise threshold <b class="help tag-help" tabindex="0" aria-label="Low-noise manual coefficient. Range 1.0-100.0 with 0.1 step. The U/L fields on the oscilloscope edit this value." data-tip="Low-noise manual coefficient. Range 1.0-100.0 with 0.1 step. The U/L fields on the oscilloscope edit this value.">?</b></span>
                    </td>
                    <td class="tag-channel"><label class="tag-control"><input name="threshold0" data-tag-threshold="upper" data-tag-manual="upper" type="number" min="1" max="100" step="0.1" value="{tag_threshold0_value}"{tag_threshold0_readonly}></label></td>
                    <td class="tag-channel"><label class="tag-control"><input name="threshold1" data-tag-threshold="lower" data-tag-manual="lower" type="number" min="1" max="100" step="0.1" value="{tag_threshold1_value}"{tag_threshold1_readonly}></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Manual high-noise threshold <b class="help tag-help" tabindex="0" aria-label="High-noise manual coefficient. Range 1.0-100.0 with 0.1 step. The detector interpolates from low-noise to high-noise threshold." data-tip="High-noise manual coefficient. Range 1.0-100.0 with 0.1 step. The detector interpolates from low-noise to high-noise threshold.">?</b></span>
                    </td>
                    <td class="tag-channel"><label class="tag-control"><input name="threshold_high0" data-tag-manual="upper" type="number" min="1" max="100" step="0.1" value="{tag_threshold_high0_value}"{tag_threshold0_readonly}></label></td>
                    <td class="tag-channel"><label class="tag-control"><input name="threshold_high1" data-tag-manual="lower" type="number" min="1" max="100" step="0.1" value="{tag_threshold_high1_value}"{tag_threshold1_readonly}></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Manual noise max display <b class="help tag-help" tabindex="0" aria-label="Display noise level where the manual curve reaches the high-noise threshold." data-tip="Display noise level where the manual curve reaches the high-noise threshold. Below this level the coefficient is interpolated between low and high.">?</b></span>
                    </td>
                    <td class="tag-channel" colspan="2"><label class="tag-control"><input name="ratio_noise_max_u16" type="number" min="0.1" max="65535" step="0.1" inputmode="decimal" value="{tag_ratio_noise_max_u16_value}"></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Auto min trigger level display <b class="help tag-help" tabindex="0" aria-label="Minimum automatic trigger level in oscilloscope display units." data-tip="Minimum automatic trigger level in oscilloscope display units. In AUTO mode the pink line never goes below this level.">?</b></span>
                    </td>
                    <td class="tag-channel" colspan="2"><label class="tag-control"><input name="auto_floor_u16" type="number" min="0" max="65535" step="0.1" inputmode="decimal" value="{tag_auto_floor_u16_value}"></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Auto noise slope <b class="help tag-help" tabindex="0" aria-label="Automatic threshold slope. Range 0.1-100.0 with 0.1 step." data-tip="Automatic threshold slope. Range 0.1-100.0 with 0.1 step. Higher values raise the automatic threshold more strongly as noise grows.">?</b></span>
                    </td>
                    <td class="tag-channel" colspan="2"><label class="tag-control"><input name="auto_slope" type="number" min="0.1" max="100" step="0.1" inputmode="decimal" value="{tag_auto_slope_value}"></label></td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Noise averaging window <b class="help tag-help" tabindex="0" aria-label="Seconds of reference-side noise accumulated for the adaptive trigger threshold." data-tip="Seconds of reference-side noise accumulated for the adaptive trigger threshold. The number of buffers follows the current receive rate.">?</b></span>
                    </td>
                    <td class="tag-channel" colspan="2"><label class="tag-control"><input name="noise_window_s" type="number" min="0.05" max="10" step="0.05" inputmode="decimal" value="{tag_noise_window_s_value}"> s</label></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="section">
              <h2>Detection Filtering</h2>
              <table class="tag-settings">
                <tbody>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Amplitude detection <b class="help tag-help" tabindex="0" aria-label="Enables or disables amplitude-based signal checking for the selected antenna." data-tip="Enables or disables amplitude-based signal checking for the selected antenna.">?</b></span>
                    </td>
                    <td class="tag-channel" data-channel-label="Upper Channel">
                      <label class="tag-control"><input type="hidden" name="filter_amplitude0" value="0"><input type="checkbox" name="filter_amplitude0" value="1"{tag_filter_amplitude0_checked}>Enabled</label>
                    </td>
                    <td class="tag-channel" data-channel-label="Lower Channel">
                      <label class="tag-control"><input type="hidden" name="filter_amplitude1" value="0"><input type="checkbox" name="filter_amplitude1" value="1"{tag_filter_amplitude1_checked}>Enabled</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Shape detection <b class="help tag-help" tabindex="0" aria-label="Enables or disables signal-shape checking for the selected antenna." data-tip="Enables or disables signal-shape checking for the selected antenna.">?</b></span>
                    </td>
                    <td class="tag-channel" data-channel-label="Upper Channel">
                      <label class="tag-control"><input type="hidden" name="filter_shape0" value="0"><input type="checkbox" name="filter_shape0" value="1"{tag_filter_shape0_checked}>Enabled</label>
                    </td>
                    <td class="tag-channel" data-channel-label="Lower Channel">
                      <label class="tag-control"><input type="hidden" name="filter_shape1" value="0"><input type="checkbox" name="filter_shape1" value="1"{tag_filter_shape1_checked}>Enabled</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Phase detection <b class="help tag-help" tabindex="0" aria-label="Enables or disables phase-based signal checking for the selected antenna." data-tip="Enables or disables phase-based signal checking for the selected antenna.">?</b></span>
                    </td>
                    <td class="tag-channel" data-channel-label="Upper Channel">
                      <label class="tag-control"><input type="hidden" name="filter_phase0" value="0"><input type="checkbox" name="filter_phase0" value="1"{tag_filter_phase0_checked}>Enabled</label>
                    </td>
                    <td class="tag-channel" data-channel-label="Lower Channel">
                      <label class="tag-control"><input type="hidden" name="filter_phase1" value="0"><input type="checkbox" name="filter_phase1" value="1"{tag_filter_phase1_checked}>Enabled</label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Burst noise gate <b class="help tag-help" tabindex="0" aria-label="Suppresses very short noisy bursts and overrange spikes before the detector can accept them or adapt the noise baseline to them." data-tip="Suppresses very short noisy bursts and overrange spikes before the detector can accept them or adapt the noise baseline to them.">?</b></span>
                    </td>
                    <td class="tag-channel" data-channel-label="Upper Channel">
                      <label class="tag-control tag-noise-control">
                        <span class="tag-noise-pair">
                          <span class="tag-mini-field tag-mini-check">Gate <input type="hidden" name="burst_gate0" value="0"><input type="checkbox" name="burst_gate0" value="1"{tag_burst_gate0_checked}></span>
                          <span class="tag-mini-field">Blank <input name="burst_blank_s0" type="number" min="0" max="1" step="0.01" inputmode="decimal" value="{tag_burst_blank_s0_value}" aria-label="Upper burst gate blank seconds"></span>
                          <span class="tag-mini-field">Max x <input name="burst_max_ratio0" type="number" min="0" max="100" step="0.1" inputmode="decimal" value="{tag_burst_max_ratio0_value}" aria-label="Upper burst gate maximum ratio"></span>
                        </span>
                      </label>
                    </td>
                    <td class="tag-channel" data-channel-label="Lower Channel">
                      <label class="tag-control tag-noise-control">
                        <span class="tag-noise-pair">
                          <span class="tag-mini-field tag-mini-check">Gate <input type="hidden" name="burst_gate1" value="0"><input type="checkbox" name="burst_gate1" value="1"{tag_burst_gate1_checked}></span>
                          <span class="tag-mini-field">Blank <input name="burst_blank_s1" type="number" min="0" max="1" step="0.01" inputmode="decimal" value="{tag_burst_blank_s1_value}" aria-label="Lower burst gate blank seconds"></span>
                          <span class="tag-mini-field">Max x <input name="burst_max_ratio1" type="number" min="0" max="100" step="0.1" inputmode="decimal" value="{tag_burst_max_ratio1_value}" aria-label="Lower burst gate maximum ratio"></span>
                        </span>
                      </label>
                    </td>
                  </tr>
                  <tr>
                    <td class="tag-desc">
                      <span class="tag-param">Noise-level adaptation <b class="help tag-help" tabindex="0" aria-label="Noise adaptation is always enabled. Up and Down are interpreted as ADC-level units or as percent of the current noise baseline." data-tip="Noise adaptation is always enabled. Up and Down are interpreted as ADC-level units or as percent of the current noise baseline.">?</b></span>
                    </td>
                    <td class="tag-channel" data-channel-label="Upper Channel">
                      <label class="tag-control tag-noise-control">
                        <span class="tag-noise-pair">
                          <span class="tag-mini-field">Unit <select name="noise_unit0" aria-label="Upper noise adaptation units"><option value="adc"{tag_noise_unit0_adc_selected}>ADC units</option><option value="percent"{tag_noise_unit0_percent_selected}>Percent</option></select></span>
                          <span class="tag-mini-field">Up <input name="noise_up0" type="number" min="1" max="65535" step="1" inputmode="numeric" value="{tag_noise_up0_value}" aria-label="Upper noise adaptation up step"></span>
                          <span class="tag-mini-field">Down <input name="noise_down0" type="number" min="1" max="65535" step="1" inputmode="numeric" value="{tag_noise_down0_value}" aria-label="Upper noise adaptation down step"></span>
                        </span>
                      </label>
                    </td>
                    <td class="tag-channel" data-channel-label="Lower Channel">
                      <label class="tag-control tag-noise-control">
                        <span class="tag-noise-pair">
                          <span class="tag-mini-field">Unit <select name="noise_unit1" aria-label="Lower noise adaptation units"><option value="adc"{tag_noise_unit1_adc_selected}>ADC units</option><option value="percent"{tag_noise_unit1_percent_selected}>Percent</option></select></span>
                          <span class="tag-mini-field">Up <input name="noise_up1" type="number" min="1" max="65535" step="1" inputmode="numeric" value="{tag_noise_up1_value}" aria-label="Lower noise adaptation up step"></span>
                          <span class="tag-mini-field">Down <input name="noise_down1" type="number" min="1" max="65535" step="1" inputmode="numeric" value="{tag_noise_down1_value}" aria-label="Lower noise adaptation down step"></span>
                        </span>
                      </label>
                    </td>
	                  </tr>
	                </tbody>
	              </table>
	            </div>
	            <div class="section">
	              <h2>Input Smoothing</h2>
	              <select class="smooth-mode-select" name="smooth_mode" aria-label="Input smoothing mode">
	                {tag_smooth_mode_options}
	              </select>
	              <p class="notice">Choose off, med3, med5, avg7, avg9, or avg11. The selected filter is applied once to each input frame before both detection and oscilloscope display.</p>
	            </div>
	            <div class="section">
	              <h2>Peak Position Limits</h2>
	              <table class="tag-settings">
	                <tbody>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Allowed peak index <b class="help tag-help" tabindex="0" aria-label="Detection is accepted only when the peak index is between the lower and upper limits, inclusive. Both values can be set from 0 through 199." data-tip="Detection is accepted only when the peak index is between the lower and upper limits, inclusive. Both values can be set from 0 through 199.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-mini-field">Lower <input name="peak_index_min" type="number" min="0" max="199" step="1" inputmode="numeric" value="{tag_peak_index_min_value}" aria-label="Minimum allowed peak index"></span>
	                        <span class="tag-mini-field">Upper <input name="peak_index_max" type="number" min="0" max="199" step="1" inputmode="numeric" value="{tag_peak_index_max_value}" aria-label="Maximum allowed peak index"></span>
	                      </label>
	                    </td>
	                  </tr>
	                </tbody>
	              </table>
	              <p class="notice">The limits are inclusive and independent from named filters. Use 0…199 to allow the full detector array.</p>
	            </div>
	            <div class="section">
	              <h2>Named Detection Filters</h2>
	              <table class="tag-settings">
	                <tbody>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Tag response filters <b class="help tag-help" tabindex="0" aria-label="Enabled filters are combined as alternatives. A signal is accepted when any enabled named filter matches, then the common noise and locality gates are applied." data-tip="Enabled filters are combined as alternatives. A signal is accepted when any enabled named filter matches, then the common noise and locality gates are applied.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-inline-check"><input type="hidden" name="filter_casino" value="0"><input type="checkbox" name="filter_casino" value="1"{tag_filter_casino_checked}>Casino</label>
	                      <label class="tag-control tag-inline-check"><input type="hidden" name="filter_barkhausen" value="0"><input type="checkbox" name="filter_barkhausen" value="1"{tag_filter_barkhausen_checked}>Barkhausen</label>
	                      <label class="tag-control tag-inline-check"><input type="hidden" name="filter_microwire" value="0"><input type="checkbox" name="filter_microwire" value="1"{tag_filter_microwire_checked}>Microwire</label>
	                      <label class="tag-control tag-inline-check"><input type="hidden" name="filter_paper" value="0"><input type="checkbox" name="filter_paper" value="1"{tag_filter_paper_checked}>Paper</label>
	                    </td>
	                  </tr>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Barkhausen shape <b class="help tag-help" tabindex="0" aria-label="Compact broad-response gate used by Barkhausen tags. Product level limits reject basket/background peaks outside the expected tag level." data-tip="Compact broad-response gate used by Barkhausen tags. Product level limits reject basket/background peaks outside the expected tag level.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Radius <input name="barkhausen_radius" type="number" min="1" max="120" step="1" inputmode="numeric" value="{tag_barkhausen_radius_value}" aria-label="Barkhausen radius"></span>
	                          <span class="tag-mini-field">Frac <input name="barkhausen_frac" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_barkhausen_frac_value}" aria-label="Barkhausen support fraction"></span>
	                          <span class="tag-mini-field">Width <input name="barkhausen_min_width" type="number" min="1" max="120" step="1" inputmode="numeric" value="{tag_barkhausen_min_width_value}" aria-label="Barkhausen minimum width"></span>
	                          <span class="tag-mini-field">Span <input name="barkhausen_max_span" type="number" min="1" max="200" step="1" inputmode="numeric" value="{tag_barkhausen_max_span_value}" aria-label="Barkhausen maximum span"></span>
	                        </span>
	                      </label>
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Min level <input name="barkhausen_min_product_level" type="number" min="0" max="2147483647" step="1000" inputmode="numeric" value="{tag_barkhausen_min_product_level_value}" aria-label="Barkhausen minimum product level"></span>
	                          <span class="tag-mini-field">Max level <input name="barkhausen_max_product_level" type="number" min="0" max="2147483647" step="1000" inputmode="numeric" value="{tag_barkhausen_max_product_level_value}" aria-label="Barkhausen maximum product level"></span>
	                          <span class="tag-mini-field">Total <input name="barkhausen_max_total_fraction" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_barkhausen_max_total_fraction_value}" aria-label="Barkhausen maximum total fraction"></span>
	                          <span class="tag-mini-field">Quarters <input name="barkhausen_all_quarter_frac" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_barkhausen_all_quarter_frac_value}" aria-label="Barkhausen all-quarter fraction"></span>
	                        </span>
	                      </label>
	                    </td>
	                  </tr>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Adaptive phase <b class="help tag-help" tabindex="0" aria-label="Searches the even/odd time shift only inside the expected tag response window. Penalty suppresses unnecessary large phase jumps." data-tip="Searches the even/odd time shift only inside the expected tag response window. Penalty suppresses unnecessary large phase jumps.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Max shift <input name="phase_max_shift" type="number" min="0" max="80" step="1" inputmode="numeric" value="{tag_phase_max_shift_value}" aria-label="Adaptive phase maximum shift"></span>
	                          <span class="tag-mini-field">Penalty <input name="phase_shift_penalty" type="number" min="0" max="1" step="0.005" inputmode="decimal" value="{tag_phase_shift_penalty_value}" aria-label="Adaptive phase shift penalty"></span>
	                        </span>
	                      </label>
	                    </td>
	                  </tr>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Response window <b class="help tag-help" tabindex="0" aria-label="Fraction of the waveform where the tag response is expected. Peaks outside this window are rejected before shape matching." data-tip="Fraction of the waveform where the tag response is expected. Peaks outside this window are rejected before shape matching.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Start <input name="mark_window_start_frac" type="number" min="0" max="0.95" step="0.01" inputmode="decimal" value="{tag_mark_window_start_frac_value}" aria-label="Response window start fraction"></span>
	                          <span class="tag-mini-field">End <input name="mark_window_end_frac" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_mark_window_end_frac_value}" aria-label="Response window end fraction"></span>
	                        </span>
	                      </label>
	                    </td>
	                  </tr>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Casino shape <b class="help tag-help" tabindex="0" aria-label="Two or three compact humps. Weak Casino responses usually have two humps, strong responses can add a middle hump." data-tip="Two or three compact humps. Weak Casino responses usually have two humps, strong responses can add a middle hump.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Gap <input name="mark_gap" type="number" min="1" max="160" step="1" inputmode="numeric" value="{tag_mark_gap_value}" aria-label="Casino hump gap"></span>
	                          <span class="tag-mini-field">Tol <input name="mark_gap_tol" type="number" min="0" max="80" step="1" inputmode="numeric" value="{tag_mark_gap_tol_value}" aria-label="Casino hump gap tolerance"></span>
	                          <span class="tag-mini-field">Min frac <input name="mark_second_frac" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_mark_second_frac_value}" aria-label="Casino secondary hump fraction"></span>
	                          <span class="tag-mini-field">Valley <input name="mark_valley_frac" type="number" min="0.01" max="0.99" step="0.01" inputmode="decimal" value="{tag_mark_valley_frac_value}" aria-label="Casino valley fraction"></span>
	                          <span class="tag-mini-field">Humps <input name="mark_multi_max_humps" type="number" min="1" max="12" step="1" inputmode="numeric" value="{tag_mark_multi_max_humps_value}" aria-label="Casino maximum humps"></span>
	                        </span>
	                      </label>
	                    </td>
	                  </tr>
	                  <tr>
	                    <td class="tag-desc">
	                      <span class="tag-param">Locality <b class="help tag-help" tabindex="0" aria-label="Limits extra high-energy humps outside the local tag response area." data-tip="Limits extra high-energy humps outside the local tag response area.">?</b></span>
	                    </td>
	                    <td class="tag-channel" colspan="2">
	                      <label class="tag-control tag-noise-control">
	                        <span class="tag-noise-pair">
	                          <span class="tag-mini-field">Outside peaks <input name="locality_max_outside_peaks" type="number" min="0" max="20" step="1" inputmode="numeric" value="{tag_locality_max_outside_peaks_value}" aria-label="Maximum outside peaks"></span>
	                          <span class="tag-mini-field">Peak frac <input name="locality_outside_peak_frac" type="number" min="0.01" max="1" step="0.01" inputmode="decimal" value="{tag_locality_outside_peak_frac_value}" aria-label="Outside peak fraction"></span>
	                        </span>
	                      </label>
	                    </td>
	                  </tr>
	                </tbody>
	              </table>
	            </div>
	            <p class="notice">Upper and Lower channels are independent. Shared detector behavior remains controlled by the core service and DC compensation settings.</p>
            <div class="actions actions-inline">
              <button class="link" type="submit" name="apply" value="1">Save and Apply to Core</button>
              <button class="link link-secondary" type="submit" name="apply" value="0">Save Only</button>
            </div>
          </form>
        </section>
        <section class="portal-panel" id="panel-operation">
          <form class="config-form operation-config-form" method="post" action="/portal-operation-config">
            <div class="operation-topline">
              <h3>Adaptation timing</h3>
              <div class="dc-timing-row">
                <label class="dc-timing-field" title="Background DC compensation settle time in seconds. Range 0..86400 sec; 0 = off, 1 = fastest.">
                  <span class="dc-timing-label"><span class="dc-timing-text">Work, sec.</span><b class="help" title="Background DC compensation settle time in seconds. Range 0..86400 sec; 0 = off, 1 = fastest.">?</b></span>
                  <input name="work_settle_s" type="number" min="0" max="86400" step="1" inputmode="decimal" value="{cfg['work_settle_s']:g}">
                </label>
                <label class="dc-timing-field" title="DC compensation settle time while acquiring a signal before detection. Range 0..86400 sec; 0 = off, 1 = fastest.">
                  <span class="dc-timing-label"><span class="dc-timing-text">Acquisition, sec.</span><b class="help" title="DC compensation settle time while acquiring a signal before detection. Range 0..86400 sec; 0 = off, 1 = fastest.">?</b></span>
                  <input name="acquisition_settle_s" type="number" min="0" max="86400" step="1" inputmode="decimal" value="{cfg['acquisition_settle_s']:g}">
                </label>
                <label class="dc-timing-field" title="DC compensation settle time during detection. Range 0..86400 sec; 0 = off, 1 = fastest.">
                  <span class="dc-timing-label"><span class="dc-timing-text">Detection, sec.</span><b class="help" title="DC compensation settle time during detection. Range 0..86400 sec; 0 = off, 1 = fastest.">?</b></span>
                  <input name="detection_settle_s" type="number" min="0" max="86400" step="1" inputmode="decimal" value="{cfg['detection_settle_s']:g}">
                </label>
                <label class="dc-timing-field" title="Maximum lightning duration. Work is restored when either 99% compensation is reached or this timer expires.">
                  <span class="dc-timing-label"><span class="dc-timing-text">Lightning timer, sec.</span><b class="help" title="Maximum lightning duration. Work is restored when either 99% compensation is reached or this timer expires.">?</b></span>
                  <input name="lightning_timeout_s" type="number" min="0.1" max="86400" step="0.1" inputmode="decimal" value="{cfg['lightning_timeout_s']:g}">
                </label>
              </div>
            </div>
            <div class="operation-lowerline">
              <label class="field operation-avg-field">
                <span>Default averaging</span>
                <select name="avg_n">{avg_n_options}</select>
                <small>Used by BMI30 core on startup; live apply updates the running core.</small>
              </label>
            </div>
            <div class="operation-sound" data-sound-form>
              <div class="operation-sound-head">
                <h3>Sound output</h3>
                <label class="sound-toggle"><input type="hidden" name="sound_enabled" value="0"><input data-sound-live name="sound_enabled" type="checkbox" value="1"{sound_enabled_checked}>Enabled</label>
                <label class="sound-toggle"><input type="hidden" name="sound_test_upper_enabled" value="0"><input data-sound-live data-sound-test name="sound_test_upper_enabled" type="checkbox" value="1"{sound_test_upper_checked}>Test Upper</label>
                <label class="sound-toggle"><input type="hidden" name="sound_test_lower_enabled" value="0"><input data-sound-live data-sound-test name="sound_test_lower_enabled" type="checkbox" value="1"{sound_test_lower_checked}>Test Lower</label>
                <label class="sound-volume">
                  <span class="sound-volume-label">Volume 0-100%</span>
                  <input data-sound-live data-sound-volume name="sound_volume_percent" type="range" min="0" max="100" step="1" value="{sound_volume_value}" aria-label="Sound volume percent">
                  <span class="sound-volume-output" data-sound-volume-output>{sound_volume_value}%</span>
                </label>
              </div>
              <div class="sound-fields">
                <label class="sound-field"><span>Upper tone, Hz</span><input data-sound-live name="sound_upper_frequency_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_upper_frequency_value}"></label>
                <label class="sound-field"><span>Lower tone, Hz</span><input data-sound-live name="sound_lower_frequency_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_lower_frequency_value}"></label>
                <label class="sound-field"><span>Upper phase min, Hz</span><input data-sound-live name="sound_phase_upper_min_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_phase_upper_min_value}"></label>
                <label class="sound-field"><span>Upper phase max, Hz</span><input data-sound-live name="sound_phase_upper_max_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_phase_upper_max_value}"></label>
                <label class="sound-field"><span>Lower phase min, Hz</span><input data-sound-live name="sound_phase_lower_min_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_phase_lower_min_value}"></label>
                <label class="sound-field"><span>Lower phase max, Hz</span><input data-sound-live name="sound_phase_lower_max_hz" type="number" min="1" max="20000" step="1" inputmode="decimal" value="{sound_phase_lower_max_value}"></label>
                <label class="sound-field" title="Once started, the hardware tone stays on for at least this time."><span>Minimum sound, ms</span><input data-sound-live name="sound_minimum_duration_ms" type="number" min="0" max="60000" step="10" inputmode="numeric" value="{sound_minimum_duration_value}"></label>
                <label class="sound-field" title="Consecutive detector/phase calculation cycles required before sound starts; short detections remain silent."><span>Minimum tone cycles</span><input data-sound-live name="sound_minimum_tone_cycles" type="number" min="1" max="1000" step="1" inputmode="numeric" value="{sound_minimum_cycles_value}"></label>
              </div>
            </div>
            <div class="operation-lcd-role" data-lcd-role-form title="Shows full-screen Mxx for a master, Sxx for a slave, or O when sync is off. Changes are sent immediately and saved.">
              <h3>Large LCD role</h3>
              <label class="sound-toggle"><input type="hidden" name="lcd_role_overlay_enabled" value="0"><input data-lcd-role-live name="lcd_role_overlay_enabled" type="checkbox" value="1"{lcd_role_enabled_checked}>Enabled</label>
              <label class="lcd-role-field"><span>Repeat</span><select data-lcd-role-live name="lcd_role_overlay_period_s">{lcd_role_period_options}</select></label>
              <label class="lcd-role-field"><span>Show</span><select data-lcd-role-live name="lcd_role_overlay_duration_s">{lcd_role_duration_options}</select></label>
              <span class="lcd-role-status" data-lcd-role-status>{'Enabled' if lcd_role_cfg['enabled'] else 'Disabled'}</span>
            </div>
            <div class="summary-grid">
              <div class="summary-item"><h3>Radar</h3><div class="metric"><span>Connection</span><strong>---</strong></div></div>
              <div class="summary-item"><h3>Transmission</h3><div class="metric"><span>Work time</span><strong>---</strong></div></div>
              <div class="summary-item"><h3>Profile</h3><div class="metric"><span>Active</span><strong>---</strong></div></div>
              <div class="summary-item"><h3>Optic</h3>{operation_optic_metrics}</div>
            </div>
            <div class="actions actions-inline operation-actions">
              <button class="link" type="submit" name="apply" value="1">Save and Apply</button>
              <button class="link link-secondary" type="submit" name="apply" value="0">Save Only</button>
            </div>
          </form>
        </section>
        <section class="portal-panel" id="panel-group">
          <div class="section group-section">
            <div class="group-head">
              <h2>Group Devices</h2>
              <div class="group-head-actions">
                <span class="group-update">Last status update: <strong data-sensor-text="group-cache">---</strong></span>
                <button class="link link-secondary group-refresh" type="button" data-group-refresh>Refresh device list</button>
              </div>
            </div>
            <p class="group-legend">
              <span><span class="group-dot is-green"></span>Optic active</span>
              <span><span class="group-dot is-off"></span>Optic inactive</span>
            </p>
            <div class="group-matrix-wrap">
              <table class="group-matrix" id="group-matrix">
                <thead>
                  <tr data-group-row="head"><th class="group-param">Device</th></tr>
                </thead>
                <tbody>
                  <tr data-group-row="indicator"><th class="group-param">State optic</th></tr>
                  <tr data-group-row="role"><th class="group-param">Current role</th></tr>
                  <tr data-group-row="syncctl"><th class="group-param">Role assignment</th></tr>
                  <tr data-group-row="node"><th class="group-param">RS485 ID</th></tr>
                  <tr data-group-row="stm32"><th class="group-param">STM32 UID</th></tr>
                  <tr data-group-row="ip"><th class="group-param">IP address</th></tr>
                  <tr data-group-row="optic"><th class="group-param">Optic sensor</th></tr>
                  <tr data-group-row="detadc1"><th class="group-param">DetADC1 (modulation)</th></tr>
                  <tr data-group-row="detadc2"><th class="group-param">DetADC2 (modulation)</th></tr>
                  <tr data-group-row="tx"><th class="group-param">TX</th></tr>
                  <tr data-group-row="online"><th class="group-param">RS485 online</th></tr>
                  <tr data-group-row="reaction"><th class="group-param">Own optic → sound/LED/relay</th></tr>
                  <tr data-group-row="neighbor-reaction"><th class="group-param">RS485 neighbor optics → sound / LED / relay</th></tr>
                  <tr data-group-row="hold"><th class="group-param">Optic trigger hold (sec)</th></tr>
                </tbody>
              </table>
            </div>
            <p class="group-empty" data-group-empty hidden>No available group devices reported yet.</p>
            <p class="group-note">Only devices present in the current STM32 RS485 mask are shown. Click an IP address to open that device. The local optic and the selected neighboring RS485 optic are independent sources; selected sources are combined by OR and gate sound, LED indication, and the relay control signal. Choose Off to disable reaction to neighboring optic sensors. If a selected neighbor disappears, its gate closes without switching to another device. Oscilloscope detection stays visible.</p>
            <form class="group-led-form" method="post" action="/portal-group-led-pattern-config" autocomplete="off">
              <div class="group-led-head">
                <h3>Addressable LED patterns</h3>
                {group_led_feedback_html}
              </div>
              <div class="group-led-table-wrap">
                <table class="group-led-table">
                  <thead>
                    <tr>
                      <th>Situation</th>
                      <th>Pattern</th>
                      <th>Test</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group_led_pattern_rows}
                  </tbody>
                </table>
              </div>
              <div class="group-nonaddr-led-row" data-nonaddr-led-root>
                <div class="group-nonaddr-led-label">
                  <strong>Detection LED strip</strong>
                  <span>Simple LED strip · lights with the detection alarm from either channel</span>
                </div>
                <label class="group-nonaddr-led-enable">
                  <input type="checkbox" data-nonaddr-led-enable{group_nonaddr_led_enabled_checked}>Enabled
                </label>
                <span class="group-nonaddr-led-level" data-nonaddr-led-level>LED: {group_nonaddr_led_level}</span>
                <button class="link link-secondary group-led-test-btn{group_nonaddr_led_test_active_class}" type="button" data-nonaddr-led-test aria-pressed="{group_nonaddr_led_test_pressed}">Test</button>
              </div>
              <div class="group-led-actions">
                <button class="link" type="submit" name="apply" value="1">Save and Apply</button>
                <button class="link link-secondary" type="submit" name="apply" value="0">Save Only</button>
              </div>
            </form>
          </div>
        </section>
        <section class="portal-panel" id="panel-privacy">
          <div class="privacy-status-grid">
            <div class="privacy-status">
              <h3>Portal <strong data-connection-count="portal">{privacy_counts["portal"]}</strong></h3>
              <div class="metric"><span>Login</span><strong>{portal_username}</strong></div>
            </div>
            <div class="privacy-status">
              <div class="status-head">
                <form method="post" action="/portal-channel-config" class="channel-permission" title="Allow HotSpot access">
                  <input type="hidden" name="channel" value="hotspot">
                  <input type="hidden" name="enabled" value="0">
                  <input type="checkbox" name="enabled" value="1"{channel_checked["hotspot"]} onchange="this.form.submit()">
                </form>
                <h3>HotSpot <strong data-connection-count="hotspot">{privacy_counts["hotspot"]}</strong></h3>
              </div>
              <div class="metric"><span>SSID</span><strong>{hotspot_ssid}</strong></div>
            </div>
            <div class="privacy-status">
              <div class="status-head">
                <form method="post" action="/portal-channel-config" class="channel-permission" title="Allow Internet Wi-Fi">
                  <input type="hidden" name="channel" value="wifi">
                  <input type="hidden" name="enabled" value="0">
                  <input type="checkbox" name="enabled" value="1"{channel_checked["wifi"]} onchange="this.form.submit()">
                </form>
                <h3>Internet WiFi <strong data-connection-count="wifi">{privacy_counts["wifi"]}</strong></h3>
              </div>
              <div class="metric"><span>SSID</span><strong>{wifi_saved_ssid or "---"}</strong></div>
            </div>
            <div class="privacy-status">
              <div class="status-head">
                <form method="post" action="/portal-channel-config" class="channel-permission" title="Allow Ethernet access">
                  <input type="hidden" name="channel" value="ethernet">
                  <input type="hidden" name="enabled" value="0">
                  <input type="checkbox" name="enabled" value="1"{channel_checked["ethernet"]} onchange="this.form.submit()">
                </form>
                <h3>Ethernet <strong data-connection-count="ethernet">{privacy_counts["ethernet"]}</strong></h3>
              </div>
              <div class="metric"><span>Wired</span><strong>LAN</strong></div>
            </div>
            <div class="privacy-status">
              <div class="status-head">
                <form method="post" action="/portal-channel-config" class="channel-permission" title="Allow RDP/VNC remote desktop">
                  <input type="hidden" name="channel" value="remote">
                  <input type="hidden" name="enabled" value="0">
                  <input type="checkbox" name="enabled" value="1"{channel_checked["remote"]} onchange="this.form.submit()">
                </form>
                <h3>RDP/VNC <strong data-connection-count="remote">{privacy_counts["remote"]}</strong></h3>
              </div>
              <div class="metric"><span>Login</span><strong>{remote_username}</strong></div>
            </div>
          </div>
          <div class="privacy-forms">
          <form class="privacy-form" method="post" action="/portal-account-config" autocomplete="off">
              <div class="privacy-title-row">
                <h3>Portal Login</h3>
                <label class="privacy-toggle" title="Enable and edit optional BMI30 portal engineer login. This is separate from RDP/VNC desktop access.">
                  <input id="engineer-toggle" type="checkbox"{engineer_checked}>
                  <span>Engineer portal</span>
                </label>
              </div>
              <div class="privacy-fields">
                <label class="field">
                  <span>New login</span>
                  <input name="username" type="text" autocomplete="username" maxlength="64" value="{portal_username}">
                </label>
                <label class="field">
                  <span>Current password</span>
                  <input name="current_password" type="password" autocomplete="current-password" required>
                </label>
                <label class="field">
                  <span>New password</span>
                  <input name="new_password" type="password" autocomplete="new-password" minlength="8" required>
                </label>
                <label class="field">
                  <span>Repeat new password</span>
                  <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" required>
                </label>
                <div class="privacy-action">
                  <div class="actions actions-inline">
                    <button class="link" type="submit">Save Portal Login</button>
                  </div>
                </div>
              </div>
          </form>
          <form class="privacy-form" method="post" action="/portal-remote-config" autocomplete="off">
              <div class="privacy-title-row">
                <h3>Remote Desktop RDP/VNC Login</h3>
                <div class="privacy-title-actions">
                  <button class="link" type="submit">Save Desktop Login</button>
                </div>
              </div>
              <div class="privacy-fields">
                <label class="field">
                  <span>Remote login</span>
                  <input name="username" type="text" autocomplete="username" maxlength="32" value="{remote_username}" required>
                </label>
                <label class="field">
                  <span>New RDP/VNC password</span>
                  <input name="password" type="password" autocomplete="new-password" minlength="8" placeholder="Leave empty to keep current">
                </label>
                <label class="field">
                  <span>Repeat RDP/VNC password</span>
                  <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" placeholder="{remote_password_state_html}">
                </label>
              </div>
          </form>
          <form class="privacy-form" method="post" action="/portal-hotspot-config" autocomplete="off">
              <div class="privacy-title-row">
                <h3>HotSpot Wi-Fi Access</h3>
                <div class="privacy-title-actions">
                  <button class="link" type="submit">Save HotSpot Access</button>
                </div>
              </div>
              <div class="privacy-fields">
                <label class="field">
                  <span>HotSpot network name</span>
                  <input name="ssid" type="text" maxlength="32" value="{hotspot_ssid}" required>
                </label>
                <label class="field">
                  <span>New HotSpot password</span>
                  <input name="password" type="password" autocomplete="new-password" minlength="8" maxlength="63" placeholder="Leave empty to keep current password">
                </label>
                <label class="field">
                  <span>Repeat HotSpot password</span>
                  <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" maxlength="63" placeholder="Only needed when changing password">
                </label>
              </div>
              <p class="notice privacy-note">Applying HotSpot changes restarts the access point. Wi-Fi clients may need to reconnect with the new name or password.</p>
          </form>
          <form class="privacy-form" method="post" action="/portal-wifi-config" autocomplete="off">
              <div class="privacy-title-row">
                <h3>Wi-Fi Internet Access</h3>
                <div class="privacy-title-actions">
                  <a class="link link-secondary" href="/portal#privacy">Refresh Networks</a>
                  <button class="link" type="submit">Connect and Save Wi-Fi</button>
                </div>
              </div>
              <div class="privacy-fields">
                <label class="field">
                  <span>Visible networks</span>
                  <select name="visible_ssid">
                    {wifi_options}
                  </select>
                </label>
                <label class="field">
                  <span>Manual network name</span>
                  <input name="ssid" type="text" maxlength="32" placeholder="Use if the network is hidden">
                </label>
                <label class="field">
                  <span>Wi-Fi password</span>
                  <input name="password" type="password" autocomplete="new-password" placeholder="Required for protected networks">
                </label>
              </div>
          </form>
          </div>
        </section>
        <div id="engineer-modal" class="modal-backdrop" hidden>
          <form class="modal-panel" method="post" action="/portal-engineer-config" autocomplete="off" role="dialog" aria-modal="true" aria-labelledby="engineer-modal-title">
            <div class="modal-head">
              <h3 id="engineer-modal-title">BMI30 Portal Engineer Login</h3>
              <button class="modal-close" type="button" data-modal-close aria-label="Close">x</button>
            </div>
            <div class="fields">
              <label class="field">
                <span>Portal engineer login</span>
                <input name="username" type="text" autocomplete="username" maxlength="64" value="{engineer_username or html.escape(DEFAULT_ENGINEER_USERNAME)}">
              </label>
              <label class="field">
                <span>Portal engineer password</span>
                <input name="password" type="password" autocomplete="new-password" minlength="8" placeholder="Leave empty to keep configured password">
              </label>
              <label class="field">
                <span>Repeat portal engineer password</span>
                <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" placeholder="Leave empty to keep current">
              </label>
            </div>
            <div class="actions actions-inline">
              <button class="link" type="submit" name="enabled" value="1">Save Portal Engineer</button>
              <button class="link link-secondary" type="submit" name="enabled" value="0">Disable Portal Engineer</button>
            </div>
          </form>
        </div>
        <section class="portal-panel" id="panel-statistics">
          <div class="summary-grid">
            <div class="summary-item"><h3>Runtime</h3><div class="metric"><span>Uptime</span><strong>---</strong></div><div class="metric"><span>Frames</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Detection</h3><div class="metric"><span>Events</span><strong>---</strong></div><div class="metric"><span>Last event</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Communication</h3><div class="metric"><span>Errors</span><strong>---</strong></div><div class="metric"><span>Restarts</span><strong>---</strong></div></div>
          </div>
        </section>
        <section class="portal-panel" id="panel-documentation">
          <div class="doc-tabs" role="tablist" aria-label="Documentation tabs">
            {doc_tabs}
          </div>
          <div class="doc-reader">
            {doc_pages}
          </div>

        </section>
        <section class="portal-panel" id="panel-about">
          <div class="summary-grid">
            <div class="summary-item"><h3>Identity</h3><div class="metric"><span>Hostname</span><strong>{title}</strong></div><div class="metric"><span>Serial</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Firmware</h3><div class="metric"><span>Release</span><strong data-firmware-version>{firmware_version}</strong></div><div class="metric"><span>Created</span><strong data-firmware-created-at>{firmware_created_at}</strong></div><div class="metric"><span>Portal</span><strong data-firmware-portal>{firmware_portal_build}</strong></div></div>
            <div class="summary-item"><h3>Split System</h3><div class="metric"><span>Version</span><strong data-split-version>{split_system_label}</strong></div><div class="metric"><span>Source</span><strong data-split-source>{split_system_source}</strong></div></div>
            <div class="summary-item"><h3>Host</h3><div class="metric"><span>Software</span><strong>BMI30 Portal</strong></div><div class="metric"><span>Role</span><strong>{access_label}</strong></div><div class="metric"><span>Core</span><strong data-split-core>{split_system_core}</strong></div><div class="metric"><span>Selected</span><strong data-split-selected-at>{split_system_selected_at}</strong></div></div>
          </div>
        </section>
      </div>
    </div>
  </main>
  <button id="scroll-top-btn" class="scroll-top-btn" type="button" aria-label="Scroll to top">↑</button>
  {render_debug_panel()}
  {render_debug_panel_script()}
  <script>
    (function () {{
      var storageKey = 'bmi30_portal_language';
      function storedLanguage() {{
        try {{ return window.localStorage.getItem(storageKey) === 'uk' ? 'uk' : 'en'; }} catch (error) {{ return 'en'; }}
      }}
      function setHeaderLanguage(language, persist) {{
        language = language === 'uk' ? 'uk' : 'en';
        var button = document.getElementById('portal-language-switch');
        if (!button) {{ return; }}
        document.querySelectorAll('[data-header-en][data-header-uk]').forEach(function (element) {{
          element.textContent = element.getAttribute('data-header-' + language) || '';
        }});
        var session = document.querySelector('[data-header-session]');
        if (session) {{
          var username = session.getAttribute('data-username') || (language === 'uk' ? 'авторизований користувач' : 'authorized user');
          var engineer = session.getAttribute('data-role') === 'engineer';
          var access = language === 'uk' ? (engineer ? 'Інженерний доступ' : 'Користувацький доступ') : (engineer ? 'Engineering access' : 'User access');
          session.textContent = (language === 'uk' ? 'Вхід як ' : 'Signed in as ') + username + ' · ' + access;
        }}
        var header = document.querySelector('.portal-head');
        if (header) {{ header.setAttribute('lang', language); }}
        var targetIsUkrainian = language === 'en';
        var ukrainianFlag = button.querySelector('.language-switch-flag-uk');
        var englishFlag = button.querySelector('.language-switch-flag-en');
        if (targetIsUkrainian) {{
          ukrainianFlag.removeAttribute('hidden');
          englishFlag.setAttribute('hidden', '');
        }} else {{
          ukrainianFlag.setAttribute('hidden', '');
          englishFlag.removeAttribute('hidden');
        }}
        var languageName = targetIsUkrainian ? 'Українська' : 'English';
        var actionLabel = targetIsUkrainian ? 'Switch to Ukrainian' : 'Перемкнути на англійську';
        button.setAttribute('aria-label', actionLabel);
        button.setAttribute('title', languageName);
        button.dataset.currentLanguage = language;
        if (persist) {{
          try {{ window.localStorage.setItem(storageKey, language); }} catch (error) {{}}
        }}
      }}
      var switchButton = document.getElementById('portal-language-switch');
      if (switchButton) {{
        switchButton.addEventListener('click', function () {{
          var currentLanguage = switchButton.dataset.currentLanguage === 'uk' ? 'uk' : 'en';
          setHeaderLanguage(currentLanguage === 'en' ? 'uk' : 'en', true);
        }});
      }}
      setHeaderLanguage(storedLanguage(), false);
    }})();
  </script>
  <script>
    var menuButtons = Array.prototype.slice.call(document.querySelectorAll('.menu-btn[data-panel]'));
    var panels = Array.prototype.slice.call(document.querySelectorAll('.portal-panel'));
    function setActivePanel(name, updateHash) {{
      var found = panels.some(function (panel) {{ return panel.id === 'panel-' + name; }});
      if (!found) {{ name = 'antenna'; }}
      menuButtons.forEach(function (button) {{
        var active = button.dataset.panel === name;
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        if (active && updateHash) {{
          try {{ button.scrollIntoView({{block:'nearest', inline:'center', behavior:'smooth'}}); }} catch (error) {{}}
        }}
      }});
      panels.forEach(function (panel) {{
        panel.classList.toggle('is-active', panel.id === 'panel-' + name);
      }});
      if (updateHash) {{
        try {{ history.replaceState(null, '', '#' + name); }} catch (error) {{}}
      }}
    }}
    menuButtons.forEach(function (button) {{
      button.addEventListener('click', function () {{
        setActivePanel(button.dataset.panel || 'antenna', true);
      }});
    }});
    setActivePanel((window.location.hash || '#antenna').slice(1), false);
    function updateTagThresholdInputs() {{
      ['upper', 'lower'].forEach(function (name) {{
        var auto = document.querySelector('[data-tag-auto="' + name + '"]');
        var inputs = Array.prototype.slice.call(document.querySelectorAll('[data-tag-manual="' + name + '"]'));
        inputs.forEach(function (input) {{
          if (auto && input) {{
            input.readOnly = !!auto.checked;
          }}
        }});
        if (!inputs.length) {{
          var input = document.querySelector('[data-tag-threshold="' + name + '"]');
          if (auto && input) {{
            input.readOnly = !!auto.checked;
          }}
        }}
      }});
    }}
    Array.prototype.slice.call(document.querySelectorAll('[data-tag-auto]')).forEach(function (el) {{
      el.addEventListener('change', updateTagThresholdInputs);
    }});
    updateTagThresholdInputs();
    var soundForm = document.querySelector('[data-sound-form]');
    var soundLiveTimer = null;
    function soundCheckbox(name) {{
      return soundForm ? soundForm.querySelector('input[type="checkbox"][name="' + name + '"]') : null;
    }}
    function soundNumber(name, fallback) {{
      if (!soundForm) {{ return fallback; }}
      var el = soundForm.querySelector('[name="' + name + '"]');
      var value = el ? parseFloat(el.value) : NaN;
      return isFinite(value) ? value : fallback;
    }}
    function soundChecked(name) {{
      var el = soundCheckbox(name);
      return !!(el && el.checked);
    }}
    function updateSoundVolumeOutput() {{
      if (!soundForm) {{ return; }}
      var slider = soundForm.querySelector('[data-sound-volume]');
      var output = soundForm.querySelector('[data-sound-volume-output]');
      if (slider && output) {{
        output.textContent = String(Math.round(parseFloat(slider.value) || 0)) + '%';
      }}
    }}
    function soundCurrentConfig() {{
      return {{
        enabled: soundChecked('sound_enabled'),
        volume_percent: soundNumber('sound_volume_percent', 100),
        upper_frequency_hz: soundNumber('sound_upper_frequency_hz', 4000),
        lower_frequency_hz: soundNumber('sound_lower_frequency_hz', 1000),
        phase_upper_min_hz: soundNumber('sound_phase_upper_min_hz', 1000),
        phase_upper_max_hz: soundNumber('sound_phase_upper_max_hz', 3000),
        phase_lower_min_hz: soundNumber('sound_phase_lower_min_hz', 2000),
        phase_lower_max_hz: soundNumber('sound_phase_lower_max_hz', 4000),
        minimum_duration_ms: Math.round(soundNumber('sound_minimum_duration_ms', 150)),
        minimum_tone_cycles: Math.round(soundNumber('sound_minimum_tone_cycles', 1)),
        test_upper_enabled: soundChecked('sound_test_upper_enabled'),
        test_lower_enabled: soundChecked('sound_test_lower_enabled'),
        persist: false
      }};
    }}
    function soundAnyTestEnabled() {{
      return soundChecked('sound_test_upper_enabled') || soundChecked('sound_test_lower_enabled');
    }}
    function sendSoundLive(immediate) {{
      if (!soundForm) {{ return; }}
      window.clearTimeout(soundLiveTimer);
      var run = function () {{
        fetch('/api/sound-config', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          cache: 'no-store',
          body: JSON.stringify(soundCurrentConfig())
        }}).catch(function () {{}});
      }};
      if (immediate) {{
        run();
      }} else {{
        soundLiveTimer = window.setTimeout(run, 220);
      }}
    }}
    if (soundForm) {{
      updateSoundVolumeOutput();
      Array.prototype.slice.call(soundForm.querySelectorAll('[data-sound-live]')).forEach(function (el) {{
        var handle = function () {{
          updateSoundVolumeOutput();
          if (el.name === 'sound_enabled' && !el.checked) {{
            var upper = soundCheckbox('sound_test_upper_enabled');
            var lower = soundCheckbox('sound_test_lower_enabled');
            if (upper) {{ upper.checked = false; }}
            if (lower) {{ lower.checked = false; }}
            sendSoundLive(true);
            return;
          }}
          if (el.hasAttribute('data-sound-test') && el.checked) {{
            var otherName = el.name === 'sound_test_upper_enabled'
              ? 'sound_test_lower_enabled'
              : 'sound_test_upper_enabled';
            var otherTest = soundCheckbox(otherName);
            if (otherTest) {{ otherTest.checked = false; }}
            var enabled = soundCheckbox('sound_enabled');
            if (enabled) {{ enabled.checked = true; }}
          }}
          if (el.hasAttribute('data-sound-test') || soundAnyTestEnabled()) {{
            sendSoundLive(el.hasAttribute('data-sound-test'));
          }}
        }};
        // Checkboxes fire both input and change in current browsers. Sending
        // both restarts the hardware test sequence twice for one click.
        // Sliders need live input updates; all other controls need one change.
        el.addEventListener(el.type === 'range' ? 'input' : 'change', handle);
      }});
    }}
    var lcdRoleForm = document.querySelector('[data-lcd-role-form]');
    function sendLcdRoleLive() {{
      if (!lcdRoleForm) {{ return; }}
      var enabled = lcdRoleForm.querySelector('[name="lcd_role_overlay_enabled"]:checked');
      var period = lcdRoleForm.querySelector('[name="lcd_role_overlay_period_s"]');
      var duration = lcdRoleForm.querySelector('[name="lcd_role_overlay_duration_s"]');
      var status = lcdRoleForm.querySelector('[data-lcd-role-status]');
      if (status) {{ status.textContent = 'Applying…'; }}
      fetch('/api/lcd-role-overlay', {{method:'POST',headers:{{'Content-Type':'application/json'}},cache:'no-store',body:JSON.stringify({{
        enabled:!!enabled,period_s:period?parseInt(period.value,10):4,duration_s:duration?parseInt(duration.value,10):4,persist:true
      }})}}).then(function(r){{return r.json();}}).then(function(j){{
        if (!j.ok) {{ throw new Error(j.message || 'apply failed'); }}
        var actual=j.lcd_role_overlay||{{}};
        if(status){{status.textContent=(actual.enabled?'Enabled':'Disabled')+(actual.applied?' · applied':' · waiting for USB');}}
      }}).catch(function(){{if(status){{status.textContent='Apply failed';}}}});
    }}
    if (lcdRoleForm) {{ Array.prototype.slice.call(lcdRoleForm.querySelectorAll('[data-lcd-role-live]')).forEach(function(el){{el.addEventListener('change',sendLcdRoleLive);}}); }}
    var groupLedForm = document.querySelector('.group-led-form');
    var groupLedFeedbackEls = {{}};
    var nonAddressableLedRoot = document.querySelector('[data-nonaddr-led-root]');
    var nonAddressableLedEnable = document.querySelector('[data-nonaddr-led-enable]');
    var nonAddressableLedTest = document.querySelector('[data-nonaddr-led-test]');
    var nonAddressableLedLevel = document.querySelector('[data-nonaddr-led-level]');
    var nonAddressableLedBusy = false;
    var nonAddressableLedState = null;
    document.querySelectorAll('[data-group-led-feedback]').forEach(function (el) {{
      groupLedFeedbackEls[el.getAttribute('data-group-led-feedback')] = el;
    }});
    var groupLedEventLabels = {{
      upper_detection: 'Upper antenna detection',
      lower_detection: 'Lower antenna detection',
      both_detection: 'Both antennas detection',
      neighbor_upper_detection: 'Neighbor upper antenna detection',
      neighbor_lower_detection: 'Neighbor lower antenna detection',
      neighbor_both_detection: 'Neighbor both antennas detection',
      fault: 'Fault',
      manual_test: 'Manual test'
    }};
    function groupLedPatternLabel(value) {{
      var n = parseInt(value, 10);
      return isFinite(n) ? ('Pattern ' + String(Math.max(0, Math.min(255, n)))) : '---';
    }}
    function groupLedEventLabel(key) {{
      key = String(key || '');
      if (!key) {{ return 'Idle'; }}
      return groupLedEventLabels[key] || key.replace(/_/g, ' ');
    }}
    function updateGroupLedFeedback(settings) {{
      settings = settings || {{}};
      var desiredEvent = String(settings.led_desired_event || settings.led_event || '');
      var patterns = settings.led_patterns || {{}};
      var targetPattern = desiredEvent && Object.prototype.hasOwnProperty.call(patterns, desiredEvent) ? patterns[desiredEvent] : 0;
      if (desiredEvent === 'manual_test') {{
        targetPattern = settings.led_manual_test_pattern || settings.led_pattern_commanded || targetPattern;
      }}
      if (groupLedFeedbackEls.actual) {{
        groupLedFeedbackEls.actual.textContent = groupLedPatternLabel(settings.led_pattern_actual);
      }}
      if (groupLedFeedbackEls.target) {{
        groupLedFeedbackEls.target.textContent = groupLedPatternLabel(targetPattern);
      }}
      if (groupLedFeedbackEls.event) {{
        groupLedFeedbackEls.event.textContent = groupLedEventLabel(desiredEvent);
      }}
      updateNonAddressableLed(settings, false);
    }}
    function updateNonAddressableLed(settings, force) {{
      settings = settings || {{}};
      var cfg = settings.non_addressable_led || {{}};
      var enabled = cfg.enabled === undefined ? true : !!cfg.enabled;
      var testEnabled = !!cfg.test_enabled;
      var detectionActive = !!cfg.detection_active;
      var level = Number(cfg.level) ? 1 : 0;
      nonAddressableLedState = {{
        enabled: enabled,
        test_enabled: testEnabled,
        detection_active: detectionActive,
        level: level,
        gpio: Number(cfg.gpio) || 22,
        available: cfg.available,
        backend: String(cfg.backend || '')
      }};
      if (nonAddressableLedEnable && (!nonAddressableLedBusy || force)) {{
        nonAddressableLedEnable.checked = enabled;
      }}
      if (nonAddressableLedTest && (!nonAddressableLedBusy || force)) {{
        nonAddressableLedTest.classList.toggle('is-active', testEnabled);
        nonAddressableLedTest.setAttribute('aria-pressed', testEnabled ? 'true' : 'false');
      }}
      if (nonAddressableLedLevel) {{
        nonAddressableLedLevel.textContent = cfg.available === false ? 'LED: unavailable' : ('LED: ' + String(level));
      }}
    }}
    function setNonAddressableLedBusy(busy, control) {{
      nonAddressableLedBusy = !!busy;
      [nonAddressableLedEnable, nonAddressableLedTest].forEach(function (el) {{
        if (el) {{ el.disabled = !!busy; }}
      }});
      if (control) {{ control.classList.toggle('is-busy', !!busy); }}
    }}
    function sendNonAddressableLed(change, control) {{
      if (!nonAddressableLedRoot) {{ return Promise.resolve(false); }}
      var previous = nonAddressableLedState ? Object.assign({{}}, nonAddressableLedState) : null;
      setNonAddressableLedBusy(true, control);
      return fetch('/api/non-addressable-led', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify(change || {{}})
      }}).then(function (response) {{
        return response.json().then(function (data) {{
          if (!response.ok || !data || !data.ok) {{ throw new Error((data && data.message) || 'Detection LED strip update failed'); }}
          updateNonAddressableLed({{non_addressable_led: data.non_addressable_led || {{}}}}, true);
          return true;
        }});
      }}).catch(function () {{
        if (previous) {{ updateNonAddressableLed({{non_addressable_led: previous}}, true); }}
        if (nonAddressableLedLevel) {{ nonAddressableLedLevel.textContent = 'LED: error'; }}
        return false;
      }}).finally(function () {{
        setNonAddressableLedBusy(false, control);
      }});
    }}
    function groupLedSelectFor(key) {{
      return groupLedForm ? groupLedForm.querySelector('[data-group-led-select="' + key + '"]') : null;
    }}
    function groupLedSelectedPattern(key) {{
      var sel = groupLedSelectFor(key);
      if (!sel) {{ return 0; }}
      var pattern = parseInt(sel.value, 10);
      if (!isFinite(pattern)) {{ pattern = 0; }}
      return pattern;
    }}
    function setGroupLedActive(activeKey) {{
      if (!groupLedForm) {{ return; }}
      Array.prototype.slice.call(groupLedForm.querySelectorAll('[data-group-led-test]')).forEach(function (button) {{
        var isActive = !!activeKey && button.getAttribute('data-group-led-test') === activeKey;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      }});
    }}
    function sendGroupLedPattern(key, button, forcedPattern) {{
      if (!groupLedSelectFor(key)) {{ return Promise.resolve(false); }}
      var pattern = typeof forcedPattern === 'number' ? forcedPattern : groupLedSelectedPattern(key);
      if (button) {{ button.classList.add('is-busy'); button.disabled = true; }}
      return fetch('/api/group-led-pattern-test', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify({{event: key, pattern: pattern}})
      }}).then(function (response) {{
        return response.ok;
      }}).catch(function () {{
        return false;
      }}).finally(function () {{
        if (button) {{ button.classList.remove('is-busy'); button.disabled = false; }}
      }});
    }}
    if (groupLedForm) {{
      Array.prototype.slice.call(groupLedForm.querySelectorAll('[data-group-led-test]')).forEach(function (button) {{
        button.addEventListener('click', function () {{
          var key = button.getAttribute('data-group-led-test') || '';
          var isActive = button.getAttribute('aria-pressed') === 'true';
          var nextPattern = isActive ? 0 : groupLedSelectedPattern(key);
          sendGroupLedPattern(key, button, nextPattern).then(function (ok) {{
            if (!ok) {{ return; }}
            setGroupLedActive(!isActive && nextPattern > 0 ? key : '');
          }});
        }});
      }});
    }}
    if (nonAddressableLedRoot) {{
      nonAddressableLedState = {{
        enabled: !!(nonAddressableLedEnable && nonAddressableLedEnable.checked),
        test_enabled: !!(nonAddressableLedTest && nonAddressableLedTest.getAttribute('aria-pressed') === 'true'),
        detection_active: false,
        level: parseInt((nonAddressableLedLevel && nonAddressableLedLevel.textContent.split(':').pop()) || '0', 10) || 0,
        gpio: 22
      }};
      if (nonAddressableLedEnable) {{
        nonAddressableLedEnable.addEventListener('change', function () {{
          sendNonAddressableLed({{
            enabled: !!nonAddressableLedEnable.checked,
            test_enabled: false,
            persist: true
          }}, nonAddressableLedEnable);
        }});
      }}
      if (nonAddressableLedTest) {{
        nonAddressableLedTest.addEventListener('click', function () {{
          var next = nonAddressableLedTest.getAttribute('aria-pressed') !== 'true';
          sendNonAddressableLed({{test_enabled: next, persist: false}}, nonAddressableLedTest);
        }});
      }}
    }}
    var docTabs = Array.prototype.slice.call(document.querySelectorAll('.doc-tab'));
    var docPages = Array.prototype.slice.call(document.querySelectorAll('.doc-page'));
    function setDocPage(name) {{
      if (!docTabs.length || !docPages.length) {{ return; }}
      var found = docPages.some(function (page) {{ return page.dataset.docPage === name; }});
      if (!found) {{
        name = docPages[0].dataset.docPage || 'operation';
      }}
      docTabs.forEach(function (tab) {{
        var active = tab.dataset.docTab === name;
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.classList.toggle('is-active', active);
      }});
      docPages.forEach(function (page) {{
        page.classList.toggle('is-active', page.dataset.docPage === name);
      }});
    }}
    docTabs.forEach(function (tab) {{
      tab.addEventListener('click', function () {{
        setDocPage(tab.dataset.docTab || 'operation');
      }});
    }});
    if (docTabs.length) {{
      setDocPage(docTabs[0].dataset.docTab || 'operation');
    }}
    function updatePdfControlsOffset() {{
      var controls = Array.prototype.slice.call(document.querySelectorAll('.pdf-controls'));
      if (!controls.length) {{ return; }}
      var topPx = 8;
      var menu = document.querySelector('.portal-menu');
      var isMobileMenu = window.matchMedia('(max-width: 860px)').matches;
      if (menu && isMobileMenu) {{
        var menuStyle = window.getComputedStyle(menu);
        if (menuStyle.position === 'sticky') {{
          var rect = menu.getBoundingClientRect();
          if (rect.bottom > 0 && rect.top < window.innerHeight) {{
            topPx = Math.max(8, Math.round(rect.bottom + 6));
          }}
        }}
      }}
      controls.forEach(function (el) {{
        el.style.setProperty('--pdf-controls-top', String(topPx) + 'px');
      }});
    }}
    window.addEventListener('resize', updatePdfControlsOffset);
    window.addEventListener('scroll', updatePdfControlsOffset, {{ passive: true }});
    updatePdfControlsOffset();
    var scrollTopBtn = document.getElementById('scroll-top-btn');
    function updateScrollTopButton() {{
      if (!scrollTopBtn) {{ return; }}
      var show = window.scrollY > 420;
      scrollTopBtn.classList.toggle('is-visible', show);
    }}
    if (scrollTopBtn) {{
      scrollTopBtn.addEventListener('click', function () {{
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
      }});
      window.addEventListener('scroll', updateScrollTopButton, {{ passive: true }});
      updateScrollTopButton();
    }}
    var connectionCountEls = Array.prototype.slice.call(document.querySelectorAll('[data-connection-count]'));
    function updateConnectionCounts() {{
      if (!connectionCountEls.length) {{ return; }}
      fetch('/api/status?v=' + Date.now(), {{ cache: 'no-store' }})
        .then(function (response) {{
          if (!response.ok) {{ throw new Error('status failed'); }}
          return response.json();
        }})
        .then(function (data) {{
          var counts = data && data.connections ? data.connections : {{}};
          connectionCountEls.forEach(function (el) {{
            var key = el.getAttribute('data-connection-count') || '';
            if (Object.prototype.hasOwnProperty.call(counts, key)) {{
              el.textContent = String(counts[key]);
            }}
          }});
          var split = data && data.split_system ? data.split_system : {{}};
          var firmware = data && data.firmware_release ? data.firmware_release : {{}};
          document.querySelectorAll('[data-split-version]').forEach(function (el) {{
            el.textContent = split.label || split.version || '---';
          }});
          document.querySelectorAll('[data-split-source]').forEach(function (el) {{
            el.textContent = split.source || split.selected_by || '---';
          }});
          document.querySelectorAll('[data-split-core]').forEach(function (el) {{
            el.textContent = split.core_path || '---';
          }});
          document.querySelectorAll('[data-split-selected-at]').forEach(function (el) {{
            el.textContent = split.selected_at || '---';
          }});
          document.querySelectorAll('[data-firmware-version]').forEach(function (el) {{
            el.textContent = firmware.label || firmware.version || '---';
          }});
          document.querySelectorAll('[data-firmware-created-at]').forEach(function (el) {{
            el.textContent = firmware.created_at || '---';
          }});
          document.querySelectorAll('[data-firmware-portal]').forEach(function (el) {{
            var portalHash = firmware.runtime_portal_sha256 || '';
            var portalStatus = firmware.portal_matches_release ? 'OK' : 'MISMATCH';
            el.textContent = portalHash ? portalHash.slice(0, 12) + ' ' + portalStatus : '---';
          }});
        }})
        .catch(function () {{}});
    }}
    updateConnectionCounts();
    window.setInterval(updateConnectionCounts, 5000);
    // --- Sensor/status polling from local event cache only ---
    var _activePanel = (window.location.hash || '#antenna').slice(1);
    var _sensorEls = {{}};
    var _sensorTextEls = {{}};
    var _sensorListEls = {{}};
    document.querySelectorAll('[data-sensor]').forEach(function (el) {{
      _sensorEls[el.getAttribute('data-sensor')] = el;
    }});
    document.querySelectorAll('[data-sensor-text]').forEach(function (el) {{
      _sensorTextEls[el.getAttribute('data-sensor-text')] = el;
    }});
    document.querySelectorAll('[data-sensor-list]').forEach(function (el) {{
      _sensorListEls[el.getAttribute('data-sensor-list')] = el;
    }});
    function _updateSensorEl(key, value) {{
      var el = _sensorEls[key];
      if (!el) {{ return; }}
      el.textContent = (value !== null && value !== undefined) ? value.toFixed(1) + '\u00b0C' : '---';
    }}
    function _updateSensorTextEl(key, value) {{
      var el = _sensorTextEls[key];
      if (!el) {{ return; }}
      el.textContent = (value !== null && value !== undefined && value !== '') ? String(value) : '---';
    }}
    function _formatBool(value) {{
      if (value === true) {{ return 'ON'; }}
      if (value === false) {{ return 'off'; }}
      return '---';
    }}
    function _formatCacheAge(age) {{
      if (typeof age !== 'number' || !isFinite(age)) {{ return ''; }}
      var rounded = Math.max(0, Math.round(age));
      if (rounded < 90) {{ return String(rounded) + 's ago'; }}
      if (rounded < 5400) {{ return String(Math.round(rounded / 60)) + 'm ago'; }}
      return String(Math.round(rounded / 3600)) + 'h ago';
    }}
    function _formatClock(ts) {{
      if (typeof ts !== 'number' || !isFinite(ts) || ts <= 0) {{ return ''; }}
      try {{
        return new Date(ts * 1000).toLocaleTimeString([], {{hour:'2-digit', minute:'2-digit', second:'2-digit'}});
      }} catch (error) {{
        return '';
      }}
    }}
    function _formatLastDeviceUpdate(device) {{
      device = device || {{}};
      var service = device.service || {{}};
      var source = device.source || '';
      var evt = (device.evt1 && device.evt1.last) ? device.evt1.last : null;
      var eventNames = {{
        0: 'FW_INFO',
        1: 'TEMP_C',
        2: 'MCU_ADC',
        16: 'OPTIC_STATE',
        17: 'SYNC_STATE',
        18: 'MODE_STATE',
        19: 'ERROR_STATE'
      }};
      var label = 'event-cache';
      if (source === 'bulk_evt1') {{
        label = 'EVT1';
        if (evt && eventNames[evt.event_type]) {{
          label += ' ' + eventNames[evt.event_type];
        }}
        if (evt && evt.event_seq !== null && evt.event_seq !== undefined) {{
          label += ' #' + String(evt.event_seq);
        }}
      }} else if (source === 'bulk_stat') {{
        label = 'STAT event';
      }} else if (source === 'ep0_stat') {{
        label = 'STAT baseline';
      }} else if (source) {{
        label = source;
      }}
      var age = _formatCacheAge(device.age_s);
      var clock = _formatClock(device.updated_at);
      if (service.event_lag) {{
        var lag = _formatCacheAge(service.last_evt1_age_s || service.event_lag_age_s || device.age_s);
        return 'service lag' + (lag ? ', EVT1 ' + lag : '');
      }}
      var parts = [label];
      if (age) {{ parts.push(age); }}
      if (clock) {{ parts.push(clock); }}
      if (device.stale) {{
        return 'stale' + (age ? ', ' + age : '');
      }}
      return device.available ? parts.join(', ') : '---';
    }}
    function _eventAgeLabel(device, key) {{
      device = device || {{}};
      var updates = device.event_updates || {{}};
      var item = updates[key] || {{}};
      var ts = item.updated_at;
      if (typeof ts !== 'number' || !isFinite(ts) || ts <= 0) {{ return ''; }}
      return _formatCacheAge((Date.now() / 1000) - ts);
    }}
    function _formatStm32Identity(device) {{
      device = device || {{}};
      var identity = device.identity || {{}};
      var events = device.events || {{}};
      var info = identity.stm32 || events.fw_info || null;
      if (!info) {{ return '---'; }}
      var uid = info.uid96_words || info.uid96 || '';
      var buildDate = info.build_date || '';
      var buildTime = info.build_time || '';
      var firmware = [buildDate, buildTime].filter(Boolean).join(' ');
      if (!firmware) {{ firmware = info.fw_version || ''; }}
      var parts = [];
      if (uid) {{ parts.push(String(uid)); }}
      if (firmware) {{ parts.push('FW ' + String(firmware)); }}
      return parts.length ? parts.join(' / ') : '---';
    }}
    function _setRemoteSensors(items) {{
      var el = _sensorListEls['remote-sensors'];
      if (!el) {{ return; }}
      el.textContent = '';
      if (!items || !items.length) {{
        var empty = document.createElement('span');
        empty.className = 'sensor-chip';
        empty.textContent = 'Remote: ---';
        el.appendChild(empty);
        return;
      }}
      items.forEach(function (item) {{
        var chip = document.createElement('span');
        chip.className = 'sensor-chip';
        var node = document.createElement('b');
        node.textContent = 'N' + String(item.node_id || item.selector || '?');
        chip.appendChild(node);
        chip.appendChild(document.createTextNode(
          ' O:' + _formatBool(item.optic_active) +
          ' D1:' + _formatBool(item.detadc1) +
          ' D2:' + _formatBool(item.detadc2)
        ));
        el.appendChild(chip);
      }});
    }}
    function _formatReadingValue(item) {{
      if (!item) {{ return '---'; }}
      var value = item.value;
      if (value === null || value === undefined || value === '') {{
        value = item.raw;
      }}
      if (value === null || value === undefined || value === '') {{ return '---'; }}
      var suffix = item.unit ? ' ' + item.unit : '';
      return String(value) + suffix;
    }}
    function _setSensorChips(listKey, title, items) {{
      var el = _sensorListEls[listKey];
      if (!el) {{ return; }}
      el.textContent = '';
      var head = document.createElement('span');
      head.className = 'sensor-chip';
      var titleEl = document.createElement('b');
      titleEl.textContent = title;
      head.appendChild(titleEl);
      if (!items || !items.length) {{
        head.appendChild(document.createTextNode(' ---'));
        el.appendChild(head);
        return;
      }}
      el.appendChild(head);
      items.forEach(function (item) {{
        var chip = document.createElement('span');
        chip.className = 'sensor-chip';
        if (item.path) {{ chip.title = item.path; }}
        var label = document.createElement('b');
        label.textContent = item.label || item.key || '?';
        chip.appendChild(label);
        chip.appendChild(document.createTextNode(' ' + _formatReadingValue(item)));
        el.appendChild(chip);
      }});
    }}
    function _stm32RawSensorItems(device) {{
      var events = (device && device.events) ? device.events : {{}};
      var mcu = events.mcu_adc || {{}};
      var items = [];
      function add(label, value, unit) {{
        if (value !== null && value !== undefined && value !== '') {{
          items.push({{label: label, value: value, unit: unit || ''}});
        }}
      }}
      add('mcu_ver', mcu.payload_version, '');
      add('mcu_flags', mcu.flags, '');
      add('VDDA', mcu.vdda_mv, 'mV');
      add('VBAT', mcu.vbat_mv, 'mV');
      add('raw_temp', mcu.raw_temp, '');
      add('raw_vrefint', mcu.raw_vrefint, '');
      add('raw_vbat', mcu.raw_vbat, '');
      add('mcu_adc_age', _eventAgeLabel(device, 'mcu_adc'), '');
      return items;
    }}
    function _opticSensorItems(device) {{
      var events = (device && device.events) ? device.events : {{}};
      var optic = events.optic_state || {{}};
      var opticSettings = (device && device.optic_settings) ? device.optic_settings : {{}};
      var items = [];
      function add(label, value, unit) {{
        if (value !== null && value !== undefined && value !== '') {{
          items.push({{label: label, value: value, unit: unit || ''}});
        }}
      }}
      add('optic_ver', optic.payload_version, '');
      add('optic_flags', optic.flags, '');
      add('optic_active', optic.optic_active, '');
	      add('indication_optic_active', opticSettings.indication_optic_active, '');
	      add('indication_allowed', opticSettings.indication_allowed, '');
	      add('indication_source', opticSettings.indication_source, '');
	      add('indication_sync_role', opticSettings.indication_sync_role, '');
	      add('indication_local_node_id', opticSettings.indication_local_node_id, '');
	      add('indication_master_node_id', opticSettings.indication_master_node_id, '');
	      add('indication_optic_hold_ds', opticSettings.indication_optic_hold_ds, 'ds');
	      add('indication_host_hold_remaining_s', opticSettings.indication_host_hold_remaining_s, 's');
	      add('indication_local_optic_active', opticSettings.indication_local_optic_active, '');
	      add('indication_master_optic_active', opticSettings.indication_master_optic_active, '');
	      add('indication_any_optic_active', opticSettings.indication_any_optic_active, '');
	      add('indication_sync_local_optic_active', opticSettings.indication_sync_local_optic_active, '');
	      add('optic_power', optic.optic_power, '');
	      add('optic_hold_ds', optic.optic_hold_ds, 'ds');
	      add('led_pattern', optic.led_pattern, '');
      add('optic_age', _eventAgeLabel(device, 'optic_state'), '');
      return items;
    }}
    var _groupMatrix = document.getElementById('group-matrix');
    var _groupEmpty = document.querySelector('[data-group-empty]');
    var _groupRows = {{}};
    if (_groupMatrix) {{
      _groupMatrix.querySelectorAll('[data-group-row]').forEach(function (tr) {{
        _groupRows[tr.getAttribute('data-group-row')] = tr;
      }});
    }}
	    function _padNode2(n) {{
	      var v = (typeof n === 'number' && isFinite(n)) ? Math.max(0, Math.round(n)) : 0;
	      return ('0' + v).slice(-2);
	    }}
	    function _roleChar(role) {{
	      if (role === 'master') {{ return 'M'; }}
	      if (role === 'slave') {{ return 'S'; }}
	      return '?';
	    }}
	    function _readyRoleCode(value) {{
	      var code = String(value || '').trim().toUpperCase();
	      return (/^[MS][0-9]{{2}}$/.test(code)) ? code : '';
	    }}
	    function _readyCodeFrom(source) {{
	      source = source || {{}};
	      return _readyRoleCode(source.code || source.lcd_code || source.role_code || source.display_code);
	    }}
	    function _capitalizeRole(s) {{
	      s = String(s || '');
	      return s ? (s.charAt(0).toUpperCase() + s.slice(1)) : '---';
	    }}
    function _groupShortHostId(value) {{
      var text = String(value || '').trim();
      if (!text) {{ return ''; }}
      text = text.split('.')[0];
      var m = text.match(/BMI30[-_]?([0-9a-f]{{6,}})$/i);
      if (m) {{ return m[1].toUpperCase(); }}
      m = text.match(/([0-9a-f]{{8,}})$/i);
      return m ? m[1].toUpperCase() : text.toUpperCase();
    }}
    function _groupIpLast(value) {{
      var text = String(value || '').trim();
      if (!text) {{ return ''; }}
      if (/^[0-9]+$/.test(text)) {{ return text; }}
      if (text.indexOf('.') >= 0) {{ return text.split('.').pop(); }}
      if (text.indexOf(':') >= 0) {{ return text.split(':').pop(); }}
      return '';
    }}
    function _groupDeviceHeaderLabel(source, fallbackNode) {{
      source = source || {{}};
      var rpiId = source.rpi_id || source.rpi_identifier;
      if (rpiId) {{
        rpiId = _groupShortHostId(rpiId);
        var rpiIpLast = source.ip_last || source.ip_octet || _groupIpLast(source.ip || source.address);
        return rpiIpLast ? (rpiId + '/' + rpiIpLast) : rpiId;
      }}
      var explicit = source.group_label || source.header_label || source.host_label;
      if (explicit) {{ return String(explicit); }}
      var hostId = source.host_id || source.device_id || source.short_id || source.serial || source.hostname || source.host;
      hostId = _groupShortHostId(hostId);
      var ipLast = source.ip_last || source.ip_octet || _groupIpLast(source.ip || source.address);
      if (hostId && ipLast) {{ return hostId + '/' + ipLast; }}
      if (hostId) {{ return hostId; }}
      if (fallbackNode !== undefined && fallbackNode !== null && fallbackNode !== '') {{ return 'RS485 ' + String(fallbackNode); }}
      return '---';
    }}
    function _localSyncRole(sync) {{
      var role = String(sync.role || '').toLowerCase();
      if (role !== 'master' && role !== 'slave' && role !== 'off') {{
        var map = {{0: 'master', 1: 'slave', 2: 'off'}};
        role = map[sync.raw_mode] || '---';
      }}
      return role;
    }}
    function _buildGroupDevices(device) {{
      var sync = device.sync || {{}};
      var events = device.events || {{}};
      var syncEvt = events.sync_state || {{}};
      var sensorMap = events.sensor_map || {{}};
      var presenceEvt = (sensorMap.valid === true) ? sensorMap : syncEvt;
      var local = device.local || {{}};
      var remote = device.remote || [];
      var lanDevices = Array.isArray(device.lan_devices) ? device.lan_devices : [];
      var host = device.host || {{}};
      var rs485Ident = device.rs485_ident || {{}};
      var identNodes = rs485Ident.nodes || {{}};
      var optic = events.optic_state || {{}};
      var opticSettings = device.optic_settings || {{}};
      function _pick(a, b) {{ return (a !== undefined && a !== null) ? a : b; }}
      function _nodeId(value) {{
        var parsed = parseInt(value, 10);
        return (isFinite(parsed) && parsed >= 0 && parsed <= 31) ? parsed : null;
      }}
      var rawMode = _pick(syncEvt.raw_mode, sync.raw_mode);
      var localRole = String(_pick(syncEvt.role, sync.role) || '').toLowerCase();
      if (localRole !== 'master' && localRole !== 'slave' && localRole !== 'off') {{
        var rmap = {{0: 'master', 1: 'slave', 2: 'off'}};
        localRole = rmap[rawMode] || '---';
      }}
      var assignedRole = String(_pick(syncEvt.assigned_role, sync.assigned_role) || '').toLowerCase();
      if (assignedRole !== 'master' && assignedRole !== 'slave') {{
        var savedRoleCode = parseInt(_pick(syncEvt.saved_role_code, sync.saved_role_code), 10);
        assignedRole = (savedRoleCode === 1) ? 'master' : ((savedRoleCode === 2) ? 'slave' : '');
      }}
      if (!assignedRole && (localRole === 'master' || localRole === 'slave')) {{ assignedRole = localRole; }}
      var assignmentStatus = parseInt(_pick(syncEvt.assignment_status, sync.assignment_status), 10);
      var idAssignedRaw = _pick(presenceEvt.device_id_assigned, sync.device_id_assigned);
      var idAssigned = (typeof idAssignedRaw === 'boolean')
        ? idAssignedRaw
        : (isFinite(assignmentStatus) && !!(assignmentStatus & 0x04));
      var localNode = _nodeId(_pick(
        presenceEvt.device_id,
        _pick(presenceEvt.local_node_id, _pick(sync.device_id, _pick(sync.local_node_id, local.node_id)))
      ));
      var localIdent = (rs485Ident.local && typeof rs485Ident.local === 'object') ? rs485Ident.local : {{}};
      if (!idAssigned && localIdent.device_id_assigned === true) {{
        var localIdentNode = _nodeId(localIdent.node_id);
        if (localIdentNode !== null) {{
          localNode = localIdentNode;
          idAssigned = true;
        }}
      }}
      if (!idAssigned) {{ localNode = null; }}
      var seenMaskRaw = _pick(presenceEvt.sync_seen_mask, sync.sync_seen_mask);
      var seenMaskKnown = seenMaskRaw !== undefined && seenMaskRaw !== null;
      var seenMask = Number(seenMaskRaw) >>> 0;
      var remoteById = {{}};
      remote.forEach(function (item) {{
        var visibleNow = !!item && (
          item.local === true ||
          item.seen === true ||
          item.online === true ||
          item.recent === true
        );
        if (!visibleNow) {{ return; }}
        var nid = item ? _nodeId(_pick(item.node_id, item.status_node_id)) : null;
        if (nid !== null) {{ remoteById[nid] = item; }}
      }});
      var identityById = {{}};
      Object.keys(identNodes || {{}}).forEach(function (key) {{
        var entry = identNodes[key] || {{}};
        var nid = _nodeId((entry.node_id !== undefined && entry.node_id !== null) ? entry.node_id : key);
        if (nid !== null) {{ identityById[nid] = entry; }}
      }});
      if (idAssigned && localNode !== null) {{
        identityById[localNode] = Object.assign({{}}, identityById[localNode] || {{}}, localIdent);
      }}
      var presentIds = [];
      for (var i = 0; i < 32; i++) {{
        if (((seenMask >>> i) & 1) === 1) {{ presentIds.push(i); }}
      }}
      Object.keys(identityById || {{}}).forEach(function (key) {{
        var knownNid = parseInt(key, 10);
        var knownEntry = identityById[key] || {{}};
        var visibleNow = knownEntry.local === true || (
          isFinite(knownNid) && (
            seenMaskKnown
              ? (((seenMask >>> knownNid) & 1) === 1)
              : (knownEntry.recent === true || knownEntry.online === true)
          )
        );
        if (visibleNow && isFinite(knownNid) && presentIds.indexOf(knownNid) === -1) {{
          presentIds.push(knownNid);
        }}
      }});
      Object.keys(remoteById || {{}}).forEach(function (key) {{
        var remoteNid = parseInt(key, 10);
        var remotePresent = isFinite(remoteNid) && (
          !seenMaskKnown || (((seenMask >>> remoteNid) & 1) === 1)
        );
        if (remotePresent && presentIds.indexOf(remoteNid) === -1) {{ presentIds.push(remoteNid); }}
      }});
      if (idAssigned && localNode !== null && presentIds.indexOf(localNode) === -1) {{
        presentIds.push(localNode);
      }}
      var remoteCount = 0;
      presentIds.forEach(function (n) {{ if (n !== localNode) {{ remoteCount++; }} }});
		      var devices = presentIds.map(function (nid) {{
		        var isLocal = idAssigned && (nid === localNode);
		        var role;
        if (isLocal) {{
          role = localRole;
        }} else {{
          var roleIdent = identityById[nid] || {{}};
          var explicitRole = String(roleIdent.role || '').toLowerCase();
          if (explicitRole === 'master' || explicitRole === 'slave') {{
            role = explicitRole;
          }} else if (roleIdent.master === true) {{
            role = 'master';
          }} else if (roleIdent.master === false) {{
            role = 'slave';
          }} else if (localRole === 'master') {{
            role = 'slave';
          }} else if (remoteCount === 1) {{
            role = 'master';
          }} else {{
            role = '---';
          }}
		        }}
		        var ident = identityById[nid] || {{}};
		        var st = isLocal ? Object.assign({{}}, ident, localIdent, local) : Object.assign({{}}, ident, remoteById[nid] || {{}});
		        var code = _roleChar(role) + _padNode2(nid);
	        var opticActive = st.optic_active;
	        if (isLocal) {{
	          if (optic.optic_active !== undefined && optic.optic_active !== null) {{
	            opticActive = !!optic.optic_active;
	          }} else if (st.optic_active_event !== undefined && st.optic_active_event !== null) {{
	            opticActive = !!st.optic_active_event;
	          }} else if (st.optic_active_flags_runtime !== undefined && st.optic_active_flags_runtime !== null) {{
	            opticActive = !!st.optic_active_flags_runtime;
	          }}
	        }}
        return {{
          code: code,
          role: role,
          node_id: nid,
          header_label: isLocal ? _groupDeviceHeaderLabel(Object.assign({{}}, ident, host), nid) : _groupDeviceHeaderLabel(st, nid),
          rpi_id: String((isLocal ? (host.rpi_id || st.rpi_id) : st.rpi_id) || ''),
          rpi_id_published: st.rpi_id_valid === true,
          stm32_id: String(st.short_id || st.host_id || ''),
          node_conflict: st.node_conflict === true,
          identity_complete: st.complete === true,
          wire_format: String(st.wire_format || ''),
          optic_active: opticActive,
		          ip: st.ip || '',
		          detadc1: st.detadc1,
		          detadc2: st.detadc2,
		          tx_enabled: isLocal ? ((st.tx_enabled !== undefined) ? st.tx_enabled : optic.tx_enabled) : st.tx_enabled,
		          online: isLocal ? true : !!(st.online || st.seen || st.recent),
		          is_local: isLocal,
		          id_assigned: true
		        }};
		      }});
      if (!idAssigned) {{
        var unassignedState = Object.assign({{}}, localIdent, local);
        var unassignedOptic = unassignedState.optic_active;
        if (optic.optic_active !== undefined && optic.optic_active !== null) {{
          unassignedOptic = !!optic.optic_active;
        }} else if (unassignedState.optic_active_event !== undefined && unassignedState.optic_active_event !== null) {{
          unassignedOptic = !!unassignedState.optic_active_event;
        }} else if (unassignedState.optic_active_flags_runtime !== undefined && unassignedState.optic_active_flags_runtime !== null) {{
          unassignedOptic = !!unassignedState.optic_active_flags_runtime;
        }}
        devices.push({{
          code: _roleChar(localRole) + '--',
          role: localRole,
          node_id: null,
          header_label: _groupDeviceHeaderLabel(Object.assign({{}}, localIdent, host), '--'),
          rpi_id: String(host.rpi_id || localIdent.rpi_id || ''),
          rpi_id_published: localIdent.rpi_id_valid === true,
          stm32_id: String(localIdent.short_id || localIdent.host_id || ''),
          node_conflict: localIdent.node_conflict === true,
          identity_complete: localIdent.complete === true,
          wire_format: String(localIdent.wire_format || ''),
          optic_active: unassignedOptic,
          ip: localIdent.ip || host.ip || '',
          detadc1: unassignedState.detadc1,
          detadc2: unassignedState.detadc2,
          tx_enabled: (unassignedState.tx_enabled !== undefined) ? unassignedState.tx_enabled : optic.tx_enabled,
          online: true,
          is_local: true,
          id_assigned: false
        }});
      }}
      var lanNodeCounts = {{}};
      lanDevices.forEach(function (lan) {{
        var lanNode = lan && lan.device_id_assigned === true ? _nodeId(lan.node_id) : null;
        if (lanNode !== null) {{
          lanNodeCounts[lanNode] = (lanNodeCounts[lanNode] || 0) + 1;
        }}
      }});
      lanDevices.forEach(function (lan) {{
        lan = lan || {{}};
        if (lan.api_ok !== true || lan.online !== true) {{ return; }}
        var lanRpiId = _groupShortHostId(lan.rpi_id || lan.hostname);
        if (!/^[0-9A-F]{{9}}$/.test(lanRpiId)) {{ return; }}
        var lanNode = lan.device_id_assigned === true ? _nodeId(lan.node_id) : null;
        if (seenMaskKnown && lanNode !== null && (((seenMask >>> lanNode) & 1) !== 1)) {{
          return;
        }}
        var lanRole = String(lan.role || '').toLowerCase();
        if (lanRole !== 'master' && lanRole !== 'slave') {{ lanRole = '---'; }}
        var lanIsLocal = String(host.rpi_id || '').toUpperCase() === lanRpiId;
        var existing = null;
        devices.some(function (candidate) {{
          if (String(candidate.rpi_id || '').toUpperCase() === lanRpiId) {{
            existing = candidate;
            return true;
          }}
          return false;
        }});
        if (!existing && lan.ip) {{
          var lanIp = String(lan.ip);
          var ipMatches = devices.filter(function (candidate) {{
            return String(candidate.ip || '') === lanIp && !candidate.rpi_id;
          }});
          if (ipMatches.length === 1) {{ existing = ipMatches[0]; }}
        }}
        if (!existing && lanNode !== null && lanNodeCounts[lanNode] === 1) {{
          var nodeMatches = devices.filter(function (candidate) {{
            return candidate.node_id === lanNode && (seenMaskKnown || !candidate.rpi_id);
          }});
          if (nodeMatches.length === 1) {{ existing = nodeMatches[0]; }}
        }}
        if (existing) {{
          existing.rpi_id = lanRpiId;
          existing.ip = String(lan.ip || existing.ip || '');
          existing.connect_url = String(lan.connect_url || existing.connect_url || '');
          existing.lan_available = true;
          existing.online = true;
          existing.node_conflict = existing.node_conflict || lan.node_conflict === true;
          existing.is_local = existing.is_local || lanIsLocal;
          existing.header_label = _groupDeviceHeaderLabel(lan, lanNode);
          if (!lanIsLocal && !seenMaskKnown) {{
            if (lan.optic_active === true || lan.optic_active === false) {{ existing.optic_active = lan.optic_active; }}
            if (lan.detadc1 === true || lan.detadc1 === false) {{ existing.detadc1 = lan.detadc1; }}
            if (lan.detadc2 === true || lan.detadc2 === false) {{ existing.detadc2 = lan.detadc2; }}
            if (lan.tx_enabled === true || lan.tx_enabled === false) {{ existing.tx_enabled = lan.tx_enabled; }}
          }}
          if (existing.role !== 'master' && existing.role !== 'slave' && lanRole !== '---') {{
            existing.role = lanRole;
          }}
          if (existing.id_assigned === false && lanNode !== null) {{
            existing.node_id = lanNode;
            existing.id_assigned = true;
            existing.code = _roleChar(existing.role) + _padNode2(lanNode);
          }}
          if (lanNode !== null && existing.node_id !== null && existing.node_id !== lanNode) {{
            existing.node_conflict = true;
          }}
          return;
        }}
        if (seenMaskKnown) {{
          return;
        }}
        devices.push({{
          code: _roleChar(lanRole) + (lanNode === null ? '--' : _padNode2(lanNode)),
          role: lanRole,
          node_id: lanNode,
          header_label: _groupDeviceHeaderLabel(lan, lanNode === null ? '--' : lanNode),
          rpi_id: lanRpiId,
          rpi_id_published: false,
          stm32_id: '',
          node_conflict: lan.node_conflict === true,
          identity_complete: false,
          wire_format: 'LAN',
          optic_active: (lan.optic_active === true || lan.optic_active === false) ? lan.optic_active : null,
          ip: String(lan.ip || ''),
          connect_url: String(lan.connect_url || ''),
          detadc1: (lan.detadc1 === true || lan.detadc1 === false) ? lan.detadc1 : null,
          detadc2: (lan.detadc2 === true || lan.detadc2 === false) ? lan.detadc2 : null,
          tx_enabled: (lan.tx_enabled === true || lan.tx_enabled === false) ? lan.tx_enabled : null,
          online: true,
          lan_available: true,
          is_local: lanIsLocal,
          id_assigned: lanNode !== null
        }});
      }});
      var ownersByNode = {{}};
      devices.forEach(function (d) {{
        if (d.id_assigned === false || d.node_id === null) {{ return; }}
        var ownerKey = String(d.rpi_id || d.stm32_id || d.header_label || '');
        ownersByNode[d.node_id] = ownersByNode[d.node_id] || {{}};
        ownersByNode[d.node_id][ownerKey] = true;
      }});
      devices.forEach(function (d) {{
        var owners = d.node_id === null ? [] : Object.keys(ownersByNode[d.node_id] || {{}});
        if (owners.length > 1) {{ d.node_conflict = true; }}
      }});
      devices.sort(function (a, b) {{
        var ar = (a.role === 'master') ? 0 : 1;
        var br = (b.role === 'master') ? 0 : 1;
        if (ar !== br) {{ return ar - br; }}
        if (a.is_local !== b.is_local) {{ return a.is_local ? -1 : 1; }}
        return (a.node_id === null ? 99 : a.node_id) - (b.node_id === null ? 99 : b.node_id);
      }});
      var opticStateLocal = (device.events || {{}}).optic_state || {{}};
      var localHoldSec = 3;
      var _hd = parseInt(opticStateLocal.optic_hold_ds, 10);
      if (isFinite(_hd)) {{ localHoldSec = Math.max(0, Math.min(10, Math.round(_hd / 10))); }}
      var localReaction = !!opticSettings.reaction_enabled;
      var neighborReaction = !!opticSettings.neighbor_reaction_enabled;
      var neighborDeviceId = parseInt(opticSettings.neighbor_device_id, 10);
      if (!isFinite(neighborDeviceId) || neighborDeviceId < 0 || neighborDeviceId > 31) {{
        neighborDeviceId = null;
      }}
      var opticApplyRecent = (Date.now() - _groupLocalApplyT) < 6000;
      if (opticApplyRecent) {{
        if (_groupLocalDesiredReaction !== null) {{ localReaction = !!_groupLocalDesiredReaction; }}
        if (_groupLocalDesiredNeighborReaction !== null) {{ neighborReaction = !!_groupLocalDesiredNeighborReaction; }}
        if (_groupLocalDesiredNeighborDeviceId !== undefined) {{
          var desiredNeighborId = parseInt(_groupLocalDesiredNeighborDeviceId, 10);
          neighborDeviceId = (isFinite(desiredNeighborId) && desiredNeighborId >= 0 && desiredNeighborId <= 31)
            ? desiredNeighborId
            : null;
        }}
        var desiredHold = parseInt(_groupLocalDesiredHold, 10);
        if (isFinite(desiredHold)) {{ localHoldSec = Math.max(0, Math.min(10, desiredHold)); }}
      }}
      var localSyncControlRole = (localRole === 'master' || localRole === 'slave') ? localRole : 'slave';
      devices.forEach(function (d) {{
        if (d.is_local) {{
          d._holdSec = localHoldSec;
          d._reaction = localReaction;
          d._neighborReaction = neighborReaction;
          d._neighborDeviceId = neighborDeviceId;
          d._neighborOptions = devices.filter(function (candidate) {{
            return !candidate.is_local && candidate.id_assigned !== false && candidate.node_id !== null;
          }}).map(function (candidate) {{
            return {{
              node_id: candidate.node_id,
              label: candidate.code + (candidate.header_label ? ' · ' + candidate.header_label : '')
            }};
          }});
          d._syncRole = localSyncControlRole;
          d._syncAssign = assignedRole || localSyncControlRole;
          d._assignedRole = assignedRole || '';
          d._rs485Id = localNode;
          d._idAssigned = idAssigned;
        }}
      }});
      return devices;
    }}
    function _groupStateClass(d) {{
      if (d.optic_active === true) {{ return 'is-green'; }}
      return 'is-off';
    }}
    function _groupStateTitle(d) {{
      if (d.optic_active === true) {{ return 'Optic active'; }}
      if (d.optic_active === false) {{ return 'Optic inactive'; }}
      return 'Optic unknown';
    }}
    var _groupSig = null;
    var _groupPendingSig = null;
    var _groupPendingDevices = null;
    var _groupPendingSince = 0;
    var _groupPendingCount = 0;
    var _groupStableMs = 1800;
    var _groupStablePolls = 3;
    var _groupCols = [];
    var _groupLocalReaction = null;
    var _groupLocalNeighborDeviceId = null;
    var _groupLocalHold = null;
    var _groupLocalDesiredReaction = null;
    var _groupLocalDesiredNeighborReaction = null;
    var _groupLocalDesiredNeighborDeviceId = undefined;
    var _groupLocalDesiredHold = null;
    var _groupLocalSyncRole = null;
    var _groupLocalSyncStatus = null;
    var _groupLocalAssignedRole = null;
    var _groupLocalRs485Id = null;
    var _groupLocalRs485IdStatus = null;
    var _groupLocalApplyT = 0;
    var _groupLocalSyncApplyT = 0;
    var _groupLocalIdApplyT = 0;
    var _groupIdentRefreshT = 0;
    var _groupIdentScanT = 0;
    var _groupIdentRefreshing = false;
    function _groupApplyOptic() {{
      var reaction = _groupLocalReaction ? !!_groupLocalReaction.checked : false;
      var neighborDeviceRaw = _groupLocalNeighborDeviceId ? String(_groupLocalNeighborDeviceId.value || 'off') : 'off';
      var neighborReaction = neighborDeviceRaw !== 'off';
      var neighborDeviceParsed = parseInt(neighborDeviceRaw, 10);
      var neighborDeviceId = (isFinite(neighborDeviceParsed) && neighborDeviceParsed >= 0 && neighborDeviceParsed <= 31)
        ? neighborDeviceParsed
        : null;
      var holdSec = _groupLocalHold ? (parseInt(_groupLocalHold.value, 10) || 0) : 0;
      _groupLocalApplyT = Date.now();
      _groupLocalDesiredReaction = reaction;
      _groupLocalDesiredNeighborReaction = neighborReaction;
      _groupLocalDesiredNeighborDeviceId = neighborDeviceId;
      _groupLocalDesiredHold = holdSec;
      fetch('/api/group-optic-config', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify({{
          reaction: reaction,
          neighbor_reaction: neighborReaction,
          neighbor_device_id: neighborDeviceId,
          hold_seconds: holdSec
        }})
      }}).then(function (r) {{ return r.ok ? r.json() : null; }}).then(function (data) {{
        if (!data || !data.ok) {{ return; }}
        _groupLocalDesiredReaction = !!data.reaction_enabled;
        _groupLocalDesiredNeighborReaction = !!data.neighbor_reaction_enabled;
        _groupLocalDesiredNeighborDeviceId =
          (data.neighbor_device_id === null || data.neighbor_device_id === undefined)
            ? null
            : parseInt(data.neighbor_device_id, 10);
        var savedHold = parseInt(data.hold_seconds, 10);
        if (isFinite(savedHold)) {{ _groupLocalDesiredHold = Math.max(0, Math.min(10, savedHold)); }}
      }}).catch(function () {{}});
    }}
    function _groupApplySyncRole() {{
      var role = _groupLocalSyncRole ? String(_groupLocalSyncRole.value || '') : '';
      if (role !== 'master' && role !== 'slave') {{
        if (_groupLocalSyncStatus) {{
          _groupLocalSyncStatus.textContent = 'Select Master or Slave';
          _groupLocalSyncStatus.classList.add('is-error');
        }}
        return;
      }}
      _groupLocalSyncApplyT = Date.now();
      if (_groupLocalSyncRole) {{ _groupLocalSyncRole.disabled = true; }}
      if (_groupLocalSyncStatus) {{
        _groupLocalSyncStatus.textContent = 'Assigning…';
        _groupLocalSyncStatus.classList.remove('is-error');
      }}
      fetch('/api/group-sync-config', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify({{role: role}})
      }}).then(function (r) {{
        return r.json().catch(function () {{ return {{}}; }}).then(function (data) {{
          if (!r.ok || !data.ok) {{ throw new Error(data.message || 'Role assignment failed'); }}
          return data;
        }});
      }}).then(function (data) {{
        if (_groupLocalAssignedRole) {{
          _groupLocalAssignedRole.textContent = 'Assigned: ' + _capitalizeRole(role);
        }}
        if (_groupLocalSyncStatus) {{
          _groupLocalSyncStatus.textContent = data.message || ('Assigned: ' + _capitalizeRole(role));
          _groupLocalSyncStatus.classList.remove('is-error');
        }}
      }}).catch(function (err) {{
        if (_groupLocalSyncStatus) {{
          _groupLocalSyncStatus.textContent = String((err && err.message) || 'Role assignment failed');
          _groupLocalSyncStatus.classList.add('is-error');
        }}
      }}).finally(function () {{
        if (_groupLocalSyncRole) {{ _groupLocalSyncRole.disabled = false; }}
      }});
    }}
    function _groupApplyRs485Id() {{
      var deviceId = _groupLocalRs485Id ? parseInt(_groupLocalRs485Id.value, 10) : NaN;
      if (!isFinite(deviceId) || deviceId < 0 || deviceId > 31) {{
        if (_groupLocalRs485IdStatus) {{
          _groupLocalRs485IdStatus.textContent = 'Select ID 00–31';
          _groupLocalRs485IdStatus.classList.add('is-error');
        }}
        return;
      }}
      _groupLocalIdApplyT = Date.now();
      if (_groupLocalRs485Id) {{ _groupLocalRs485Id.disabled = true; }}
      if (_groupLocalRs485IdStatus) {{
        _groupLocalRs485IdStatus.textContent = 'Assigning…';
        _groupLocalRs485IdStatus.classList.remove('is-error');
      }}
      fetch('/api/group-rs485-id', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify({{device_id: deviceId}})
      }}).then(function (r) {{
        return r.json().catch(function () {{ return {{}}; }}).then(function (data) {{
          if (!r.ok || !data.ok) {{ throw new Error(data.message || 'RS485 ID assignment failed'); }}
          return data;
        }});
      }}).then(function (data) {{
        if (_groupLocalRs485IdStatus) {{
          _groupLocalRs485IdStatus.textContent = data.message || ('Assigned: ' + _padNode2(deviceId));
          _groupLocalRs485IdStatus.classList.remove('is-error');
        }}
        _groupRefreshIdentity(true);
      }}).catch(function (err) {{
        if (_groupLocalRs485IdStatus) {{
          _groupLocalRs485IdStatus.textContent = String((err && err.message) || 'RS485 ID assignment failed');
          _groupLocalRs485IdStatus.classList.add('is-error');
        }}
      }}).finally(function () {{
        if (_groupLocalRs485Id) {{ _groupLocalRs485Id.disabled = false; }}
      }});
    }}
    function _groupRefreshIdentity(force) {{
      var now = Date.now();
      if (_groupIdentRefreshing || (!force && (now - _groupIdentRefreshT) < 20000)) {{ return; }}
      _groupIdentRefreshing = true;
      _groupIdentRefreshT = now;
      var requestScan = !!force || (now - _groupIdentScanT) >= 30000;
      if (requestScan) {{ _groupIdentScanT = now; }}
      var button = document.querySelector('[data-group-refresh]');
      if (button) {{ button.disabled = true; button.textContent = 'Refreshing…'; }}
      fetch('/api/group-rs485-ident', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        cache: 'no-store',
        body: JSON.stringify({{request_scan: requestScan}})
      }}).catch(function () {{
        return null;
      }}).finally(function () {{
        _groupIdentRefreshing = false;
        if (button) {{ button.disabled = false; button.textContent = 'Refresh device list'; }}
      }});
    }}
    function _groupMakeHead(d) {{
      var th = document.createElement('th');
      th.className = 'group-dev-cell group-dev-head' + (d.is_local ? ' is-local' : '');
      var code = document.createElement('span');
      code.className = 'group-dev-code';
      code.textContent = d.code || '??';
      th.appendChild(code);
      if (d.header_label) {{
        var badge = document.createElement('span');
        badge.className = 'group-dev-badge';
        badge.textContent = d.header_label;
        th.appendChild(badge);
      }}
      return th;
    }}
    function _groupMakeStateCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell group-dev-state' + (d.is_local ? ' is-local' : '');
      td.appendChild(document.createElement('span'));
      return td;
    }}
    function _groupSetState(td, d) {{
      var dot = td.firstChild;
      if (!dot) {{ return; }}
      dot.className = 'group-dot ' + _groupStateClass(d);
      dot.title = _groupStateTitle(d);
    }}
    function _groupMakeTextCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell' + (d.is_local ? ' is-local' : '');
      return td;
    }}
    function _groupSetText(td, text) {{
      td.textContent = (text === null || text === undefined || text === '') ? '---' : text;
    }}
    function _groupMakeIpCell(d) {{
      var td = _groupMakeTextCell(d);
      _groupSetIpCell(td, d);
      return td;
    }}
    function _groupSetIpCell(td, d) {{
      td.textContent = '';
      var ip = String(d.ip || '').trim();
      if (!ip) {{
        td.textContent = '---';
        return;
      }}
      var href = String(d.connect_url || '').trim();
      if (!/^https?:\\/\\//i.test(href)) {{ href = 'http://' + ip + '/'; }}
      var link = document.createElement('a');
      link.className = 'group-ip-link';
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.title = 'Open ' + String(d.rpi_id || d.header_label || ip);
      link.textContent = ip;
      td.appendChild(link);
    }}
    function _groupMakeSyncRoleCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell group-dev-ctl' + (d.is_local ? ' is-local' : '');
      if (d.is_local) {{
        var wrap = document.createElement('div');
        wrap.className = 'group-role-control';
        var sel = document.createElement('select');
        sel.className = 'group-ctl-select';
        var options = [
          ['master', 'Master'],
          ['slave', 'Slave']
        ];
        var selectedValue = d._syncAssign || d._syncRole || 'slave';
        var selectedKnown = options.some(function (pair) {{ return pair[0] === selectedValue; }});
        if (!selectedKnown) {{ selectedValue = 'slave'; }}
        options.forEach(function (pair) {{
          var opt = document.createElement('option');
          opt.value = pair[0];
          opt.textContent = pair[1];
          if (pair[0] === selectedValue) {{ opt.selected = true; }}
          sel.appendChild(opt);
        }});
        sel.addEventListener('change', _groupApplySyncRole);
        wrap.appendChild(sel);
        var assignedLabel = document.createElement('span');
        assignedLabel.className = 'group-role-assigned';
        assignedLabel.textContent = d._assignedRole ? ('Assigned: ' + _capitalizeRole(d._assignedRole)) : 'Assigned: ---';
        wrap.appendChild(assignedLabel);
        var status = document.createElement('span');
        status.className = 'group-role-feedback';
        status.setAttribute('aria-live', 'polite');
        wrap.appendChild(status);
        td.appendChild(wrap);
        td._ctlSelect = sel;
        td._assignedLabel = assignedLabel;
        _groupLocalSyncRole = sel;
        _groupLocalSyncStatus = status;
        _groupLocalAssignedRole = assignedLabel;
      }} else {{
        td.textContent = '\u2014';
      }}
      return td;
    }}
    function _groupMakeRs485IdCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell group-dev-ctl' + (d.is_local ? ' is-local' : '');
      if (!d.is_local) {{
        _groupSetText(td, d.node_id === null ? '--' : _padNode2(d.node_id));
        return td;
      }}
      var wrap = document.createElement('div');
      wrap.className = 'group-role-control';
      var sel = document.createElement('select');
      sel.className = 'group-ctl-select';
      for (var id = 0; id <= 31; id++) {{
        var opt = document.createElement('option');
        opt.value = String(id);
        opt.textContent = _padNode2(id);
        if (d._idAssigned && id === d._rs485Id) {{ opt.selected = true; }}
        sel.appendChild(opt);
      }}
      if (!d._idAssigned) {{ sel.selectedIndex = -1; }}
      sel.addEventListener('change', _groupApplyRs485Id);
      wrap.appendChild(sel);
      var assignedLabel = document.createElement('span');
      assignedLabel.className = 'group-role-assigned';
      assignedLabel.textContent = d._idAssigned ? ('Assigned: ' + _padNode2(d._rs485Id)) : 'Assigned: ---';
      wrap.appendChild(assignedLabel);
      var status = document.createElement('span');
      status.className = 'group-role-feedback';
      status.setAttribute('aria-live', 'polite');
      wrap.appendChild(status);
      td.appendChild(wrap);
      td._ctlSelect = sel;
      td._assignedLabel = assignedLabel;
      _groupLocalRs485Id = sel;
      _groupLocalRs485IdStatus = status;
      return td;
    }}
    function _groupMakeBoolCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell' + (d.is_local ? ' is-local' : '');
      td.appendChild(document.createElement('span'));
      return td;
    }}
    function _groupSetBool(td, value) {{
      var span = td.firstChild;
      if (!span) {{ return; }}
      span.className = 'group-flag ' + (value === true ? 'is-on' : (value === false ? 'is-off' : 'is-unknown'));
      span.textContent = _formatBool(value);
    }}
    function _groupMakeReactionCell(d, neighbor) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell group-dev-ctl' + (d.is_local ? ' is-local' : '');
      if (!d.is_local) {{
        td.textContent = '\u2014';
        return td;
      }}
      var wrap = document.createElement('div');
      wrap.className = 'group-role-control';
      if (!neighbor) {{
        var label = document.createElement('label');
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!d._reaction;
        cb.title = 'Gate local sound, LED, and relay by this device optic sensor';
        cb.addEventListener('change', _groupApplyOptic);
        _groupLocalReaction = cb;
        label.appendChild(cb);
        wrap.appendChild(label);
        td._ctlInput = cb;
      }}
      if (neighbor) {{
        var sel = document.createElement('select');
        sel.className = 'group-ctl-select';
        var offOpt = document.createElement('option');
        offOpt.value = 'off';
        offOpt.textContent = 'Off · ignore neighbor optics';
        sel.appendChild(offOpt);
        var anyOpt = document.createElement('option');
        anyOpt.value = 'any';
        anyOpt.textContent = 'Any current neighbor';
        sel.appendChild(anyOpt);
        var selectedPresent = d._neighborDeviceId === null;
        (d._neighborOptions || []).forEach(function (item) {{
          var opt = document.createElement('option');
          opt.value = String(item.node_id);
          opt.textContent = item.label || ('RS485 ' + _padNode2(item.node_id));
          if (item.node_id === d._neighborDeviceId) {{ selectedPresent = true; }}
          sel.appendChild(opt);
        }});
        if (d._neighborDeviceId !== null && !selectedPresent) {{
          var missingOpt = document.createElement('option');
          missingOpt.value = String(d._neighborDeviceId);
          missingOpt.textContent = 'RS485 ' + _padNode2(d._neighborDeviceId) + ' · absent';
          sel.appendChild(missingOpt);
        }}
        sel.value = !d._neighborReaction
          ? 'off'
          : (d._neighborDeviceId === null ? 'any' : String(d._neighborDeviceId));
        sel.title = 'Off disables neighbor reaction; otherwise select any current neighbor or one RS485 device whose optic controls sound, LED, and relay';
        sel.addEventListener('change', _groupApplyOptic);
        wrap.appendChild(sel);
        td._ctlSelect = sel;
        _groupLocalNeighborDeviceId = sel;
      }}
      td.appendChild(wrap);
      return td;
    }}
    function _groupMakeHoldCell(d) {{
      var td = document.createElement('td');
      td.className = 'group-dev-cell group-dev-ctl' + (d.is_local ? ' is-local' : '');
      if (d.is_local) {{
        var sel = document.createElement('select');
        sel.className = 'group-ctl-select';
        for (var s = 0; s <= 10; s++) {{
          var opt = document.createElement('option');
          opt.value = String(s);
          opt.textContent = String(s);
          if (s === d._holdSec) {{ opt.selected = true; }}
          sel.appendChild(opt);
        }}
        sel.addEventListener('change', _groupApplyOptic);
        td.appendChild(sel);
        td._ctlSelect = sel;
        _groupLocalHold = sel;
      }} else {{
        td.textContent = '\u2014';
      }}
      return td;
    }}
    function _groupRebuildColumns(devices) {{
      Object.keys(_groupRows).forEach(function (key) {{
        var cells = _groupRows[key].querySelectorAll('.group-dev-cell');
        for (var i = 0; i < cells.length; i++) {{ cells[i].remove(); }}
      }});
      _groupCols = [];
      _groupLocalReaction = null;
      _groupLocalNeighborDeviceId = null;
      _groupLocalHold = null;
      _groupLocalSyncRole = null;
      _groupLocalSyncStatus = null;
      _groupLocalAssignedRole = null;
      _groupLocalRs485Id = null;
      _groupLocalRs485IdStatus = null;
      devices.forEach(function (d) {{
        var col = {{is_local: d.is_local, cells: {{}}}};
        if (_groupRows.head) {{ var h = _groupMakeHead(d); _groupRows.head.appendChild(h); col.head = h; }}
        if (_groupRows.indicator) {{ var stc = _groupMakeStateCell(d); _groupSetState(stc, d); _groupRows.indicator.appendChild(stc); col.cells.indicator = stc; }}
        if (_groupRows.role) {{ var rc = _groupMakeTextCell(d); _groupSetText(rc, _capitalizeRole(d.role)); _groupRows.role.appendChild(rc); col.cells.role = rc; }}
        if (_groupRows.syncctl) {{ var sc = _groupMakeSyncRoleCell(d); _groupRows.syncctl.appendChild(sc); col.cells.syncctl = sc; }}
        if (_groupRows.node) {{ var nc = _groupMakeRs485IdCell(d); _groupRows.node.appendChild(nc); col.cells.node = nc; }}
        if (_groupRows.stm32) {{ var uc = _groupMakeTextCell(d); _groupSetText(uc, d.stm32_id); _groupRows.stm32.appendChild(uc); col.cells.stm32 = uc; }}
        if (_groupRows.ip) {{ var ipc = _groupMakeIpCell(d); _groupRows.ip.appendChild(ipc); col.cells.ip = ipc; }}
        if (_groupRows.optic) {{ var oc = _groupMakeBoolCell(d); _groupSetBool(oc, d.optic_active); _groupRows.optic.appendChild(oc); col.cells.optic = oc; }}
        if (_groupRows.detadc1) {{ var c1 = _groupMakeBoolCell(d); _groupSetBool(c1, d.detadc1); _groupRows.detadc1.appendChild(c1); col.cells.detadc1 = c1; }}
        if (_groupRows.detadc2) {{ var c2 = _groupMakeBoolCell(d); _groupSetBool(c2, d.detadc2); _groupRows.detadc2.appendChild(c2); col.cells.detadc2 = c2; }}
        if (_groupRows.tx) {{ var tc = _groupMakeBoolCell(d); _groupSetBool(tc, d.tx_enabled); _groupRows.tx.appendChild(tc); col.cells.tx = tc; }}
        if (_groupRows.online) {{ var lc = _groupMakeBoolCell(d); _groupSetBool(lc, d.online); _groupRows.online.appendChild(lc); col.cells.online = lc; }}
        if (_groupRows.reaction) {{ var rcl = _groupMakeReactionCell(d, false); _groupRows.reaction.appendChild(rcl); col.cells.reaction = rcl; }}
        if (_groupRows['neighbor-reaction']) {{ var nrcl = _groupMakeReactionCell(d, true); _groupRows['neighbor-reaction'].appendChild(nrcl); col.cells.neighborReaction = nrcl; }}
        if (_groupRows.hold) {{ var hcl = _groupMakeHoldCell(d); _groupRows.hold.appendChild(hcl); col.cells.hold = hcl; }}
        _groupCols.push(col);
      }});
    }}
    function _groupUpdateColumns(devices) {{
      var recent = (Date.now() - _groupLocalApplyT) < 6000;
      var syncRecent = (Date.now() - _groupLocalSyncApplyT) < 6000;
      var idRecent = (Date.now() - _groupLocalIdApplyT) < 6000;
      devices.forEach(function (d, idx) {{
        var col = _groupCols[idx];
        if (!col) {{ return; }}
        if (col.head) {{
          col.head.className = 'group-dev-cell group-dev-head' + (d.is_local ? ' is-local' : '');
          var codeEl = col.head.querySelector('.group-dev-code');
          if (codeEl) {{ codeEl.textContent = d.code || '??'; }}
          var badgeEl = col.head.querySelector('.group-dev-badge');
          if (d.header_label) {{
            if (!badgeEl) {{
              badgeEl = document.createElement('span');
              badgeEl.className = 'group-dev-badge';
              col.head.appendChild(badgeEl);
            }}
            badgeEl.textContent = d.header_label;
          }} else if (badgeEl) {{
            badgeEl.remove();
          }}
        }}
        if (col.cells.indicator) {{ _groupSetState(col.cells.indicator, d); }}
        if (col.cells.role) {{ _groupSetText(col.cells.role, _capitalizeRole(d.role)); }}
        if (!d.is_local && col.cells.node) {{ _groupSetText(col.cells.node, d.node_id === null ? '--' : _padNode2(d.node_id)); }}
        if (col.cells.stm32) {{ _groupSetText(col.cells.stm32, d.stm32_id); }}
        if (col.cells.ip) {{ _groupSetIpCell(col.cells.ip, d); }}
        if (col.cells.optic) {{ _groupSetBool(col.cells.optic, d.optic_active); }}
        if (col.cells.detadc1) {{ _groupSetBool(col.cells.detadc1, d.detadc1); }}
        if (col.cells.detadc2) {{ _groupSetBool(col.cells.detadc2, d.detadc2); }}
        if (col.cells.tx) {{ _groupSetBool(col.cells.tx, d.tx_enabled); }}
        if (col.cells.online) {{ _groupSetBool(col.cells.online, d.online); }}
        if (d.is_local && !recent) {{
          var rc = col.cells.reaction;
          if (rc && rc._ctlInput && document.activeElement !== rc._ctlInput) {{ rc._ctlInput.checked = !!d._reaction; }}
          var nrc = col.cells.neighborReaction;
          if (nrc && nrc._ctlSelect && document.activeElement !== nrc._ctlSelect) {{
            nrc._ctlSelect.value = !d._neighborReaction
              ? 'off'
              : (d._neighborDeviceId === null ? 'any' : String(d._neighborDeviceId));
          }}
          var hc = col.cells.hold;
          if (hc && hc._ctlSelect && document.activeElement !== hc._ctlSelect) {{ hc._ctlSelect.value = String(d._holdSec); }}
        }}
        if (d.is_local && !syncRecent) {{
          var sc = col.cells.syncctl;
          var assignedRole = String(d._syncAssign || d._syncRole || 'slave');
          if (assignedRole !== 'master' && assignedRole !== 'slave') {{ assignedRole = 'slave'; }}
          if (sc && sc._ctlSelect && document.activeElement !== sc._ctlSelect) {{ sc._ctlSelect.value = assignedRole; }}
          if (sc && sc._assignedLabel) {{
            sc._assignedLabel.textContent = d._assignedRole ? ('Assigned: ' + _capitalizeRole(d._assignedRole)) : 'Assigned: ---';
          }}
        }}
        if (d.is_local && !idRecent) {{
          var nc = col.cells.node;
          if (nc && nc._ctlSelect && document.activeElement !== nc._ctlSelect) {{
            nc._ctlSelect.value = d._idAssigned ? String(d._rs485Id) : '';
            if (!d._idAssigned) {{ nc._ctlSelect.selectedIndex = -1; }}
          }}
          if (nc && nc._assignedLabel) {{
            nc._assignedLabel.textContent = d._idAssigned ? ('Assigned: ' + _padNode2(d._rs485Id)) : 'Assigned: ---';
          }}
        }}
      }});
    }}
    function _groupCompositionSig(devices) {{
      return devices.map(function (d) {{
        return [
          d.code || '?',
          d.rpi_id || d.stm32_id || '?',
          d.is_local ? 'L' : 'R',
          d.role || '?',
          d.id_assigned === false ? '--' : String(d.node_id)
        ].join(':');
      }}).join('|');
    }}
    function _groupCommitDevices(devices, sig) {{
      if (sig !== _groupSig) {{
        _groupRebuildColumns(devices);
        _groupSig = sig;
      }} else {{
        _groupUpdateColumns(devices);
      }}
    }}
    function _updateGroupMatrix(device) {{
      if (!_groupMatrix) {{ return; }}
      var devices = _buildGroupDevices(device || {{}});
      var sig = _groupCompositionSig(devices);
      if (_groupEmpty) {{ _groupEmpty.hidden = (_groupSig !== null || devices.length > 0); }}
      if (_groupSig === null || sig === _groupSig) {{
        _groupPendingSig = null;
        _groupPendingDevices = null;
        _groupPendingCount = 0;
        _groupPendingSince = 0;
        _groupCommitDevices(devices, sig);
        return;
      }}
      var now = Date.now();
      if (sig !== _groupPendingSig) {{
        _groupPendingSig = sig;
        _groupPendingDevices = devices;
        _groupPendingSince = now;
        _groupPendingCount = 1;
        return;
      }}
      _groupPendingDevices = devices;
      _groupPendingCount += 1;
      if (_groupPendingCount >= _groupStablePolls || (now - _groupPendingSince) >= _groupStableMs) {{
        _groupCommitDevices(_groupPendingDevices || devices, _groupPendingSig);
        _groupPendingSig = null;
        _groupPendingDevices = null;
        _groupPendingCount = 0;
        _groupPendingSince = 0;
      }}
    }}
    function _updateDeviceSensors(device) {{
      device = device || {{}};
      var local = device.local || {{}};
      var events = device.events || {{}};
      var optic = events.optic_state || {{}};
      var updateText = _formatLastDeviceUpdate(device);
      _updateSensorTextEl('device-cache', updateText);
      _updateSensorTextEl('group-cache', updateText);
      var opticSettings = device.optic_settings || {{}};
	      var localOpticValue;
	      if (optic.optic_active !== undefined && optic.optic_active !== null) {{
	        localOpticValue = !!optic.optic_active;
	      }} else if (local.optic_active_event !== undefined && local.optic_active_event !== null) {{
	        localOpticValue = !!local.optic_active_event;
	      }} else if (local.optic_active_flags_runtime !== undefined && local.optic_active_flags_runtime !== null) {{
	        localOpticValue = !!local.optic_active_flags_runtime;
	      }} else {{
	        localOpticValue = local.optic_active;
	      }}
      _updateSensorTextEl('local-optic', _formatBool(localOpticValue));
      _updateSensorTextEl('local-detadc1', _formatBool(local.detadc1));
      _updateSensorTextEl('local-detadc2', _formatBool(local.detadc2));
      _updateSensorTextEl('local-tx', _formatBool(local.tx_enabled !== undefined ? local.tx_enabled : optic.tx_enabled));
      _updateSensorTextEl('header-stm32', _formatStm32Identity(device));
      _setRemoteSensors(device.remote || []);
      _setSensorChips('stm32-raw-sensors', 'STM32 raw', _stm32RawSensorItems(device));
      _setSensorChips('optic-sensors', 'Optic raw', _opticSensorItems(device));
      updateGroupLedFeedback(device.optic_settings || {{}});
      _updateGroupMatrix(device);
    }}
    function _pollSensors() {{
      if (_activePanel !== 'antenna' && _activePanel !== 'operation' && _activePanel !== 'group') {{ return; }}
      if (_activePanel === 'group') {{ _groupRefreshIdentity(false); }}
      fetch('/api/sensors?v=' + Date.now(), {{ cache: 'no-store' }})
        .then(function (r) {{ return r.ok ? r.json() : null; }})
        .then(function (data) {{
          if (!data) {{ return; }}
          var rpi = data.rpi || {{}};
          Object.keys(rpi).forEach(function (k) {{ _updateSensorEl('rpi-' + k, rpi[k]); }});
          _updateSensorEl('stm32-temp', data.stm32);
          var device = data.device || {{}};
          device.host = data.host || {{}};
          _updateDeviceSensors(device);
          _setSensorChips('rpi-hwmon', 'RPI hwmon', data.rpi_hwmon || []);
        }})
        .catch(function () {{}});
    }}
    _pollSensors();
    window.setInterval(_pollSensors, {SENSOR_REFRESH_S * 1000});
    // patch setActivePanel to track current panel
    var _origSetActivePanel = setActivePanel;
    setActivePanel = function (name, updateHash) {{
      _activePanel = name;
      _origSetActivePanel(name, updateHash);
      if (name === 'group') {{ _groupRefreshIdentity(false); }}
    }};
    var groupRefreshButton = document.querySelector('[data-group-refresh]');
    if (groupRefreshButton) {{
      groupRefreshButton.addEventListener('click', function () {{ _groupRefreshIdentity(true); }});
    }}
    var engineerToggle = document.getElementById('engineer-toggle');
    var engineerModal = document.getElementById('engineer-modal');
    var engineerClose = engineerModal ? engineerModal.querySelector('[data-modal-close]') : null;
    function openEngineerModal() {{
      if (!engineerModal) {{ return; }}
      engineerModal.hidden = false;
      var firstInput = engineerModal.querySelector('input[name="username"]');
      if (firstInput) {{ firstInput.focus(); }}
    }}
    function closeEngineerModal() {{
      if (!engineerModal) {{ return; }}
      engineerModal.hidden = true;
      if (engineerToggle && !engineerToggle.defaultChecked) {{
        engineerToggle.checked = false;
      }}
    }}
    if (engineerToggle) {{
      engineerToggle.addEventListener('change', function () {{
        if (engineerToggle.checked) {{
          openEngineerModal();
        }}
      }});
    }}
    if (engineerClose) {{
      engineerClose.addEventListener('click', closeEngineerModal);
    }}
    if (engineerModal) {{
      engineerModal.addEventListener('click', function (event) {{
        if (event.target === engineerModal) {{
          closeEngineerModal();
        }}
      }});
    }}
    document.addEventListener('keydown', function (event) {{
      if (event.key === 'Escape' && engineerModal && !engineerModal.hidden) {{
        closeEngineerModal();
      }}
    }});
  </script>
  <script>
    // PDF Viewer initialization
    (function() {{
      var pdfStates = {{}};
      var docOrder = ['operation', 'safety', 'network'];
      
      // Инициализация для каждого документа
      function initPdfViewer(docId) {{
        if (!pdfStates[docId]) {{
          pdfStates[docId] = {{
            pdf: null,
            currentPage: 1,
            totalPages: 0,
            rendering: false,
            canvas: null,
            ctx: null,
            lastCheckTs: 0
          }};
        }}
        
        var state = pdfStates[docId];
        var viewer = document.querySelector('[data-pdf-id="' + docId + '"]');
        if (!viewer) return;
        
        state.canvas = viewer.querySelector('.pdf-canvas');
        if (!state.canvas) return;
        
        state.ctx = state.canvas.getContext('2d');
        
        // Загружаем PDF
        loadPdf(docId);
        
        // Инициализируем контролы
        var controls = viewer.querySelector('.pdf-controls');
        if (controls && !viewer.querySelector('.pdf-controls-spacer')) {{
          var spacer = document.createElement('div');
          spacer.className = 'pdf-controls-spacer';
          controls.parentNode.insertBefore(spacer, controls);
        }}
        var prevBtn = viewer.querySelector('[data-action="prev-page"]');
        var nextBtn = viewer.querySelector('[data-action="next-page"]');
        var pageInput = viewer.querySelector('.pdf-page-input');
        var updateBtn = viewer.querySelector('[data-action="apply-update"]');
        
        if (prevBtn) {{
          prevBtn.addEventListener('click', function() {{ 
            if (state.currentPage > 1) {{
              state.currentPage--;
              updatePageDisplay(docId);
            }}
          }});
        }}
        
        if (nextBtn) {{
          nextBtn.addEventListener('click', function() {{ 
            if (state.currentPage < state.totalPages) {{
              state.currentPage++;
              updatePageDisplay(docId);
            }}
          }});
        }}
        
        if (pageInput) {{
          pageInput.addEventListener('change', function() {{
            var page = parseInt(pageInput.value) || 1;
            page = Math.max(1, Math.min(page, state.totalPages));
            state.currentPage = page;
            updatePageDisplay(docId);
          }});
        }}

        if (updateBtn) {{
          updateBtn.addEventListener('click', function() {{
            refreshPdfFromServer(docId, updateBtn);
          }});
        }}
      }}
      
      function loadPdf(docId) {{
        fetch('/portal-pdf?doc=' + encodeURIComponent(docId))
          .then(function(response) {{ 
            if (!response.ok) throw new Error('PDF not found');
            return response.arrayBuffer();
          }})
          .then(function(arrayBuffer) {{
            return pdfjsLib.getDocument({{data: arrayBuffer}}).promise;
          }})
          .then(function(pdf) {{
            pdfStates[docId].pdf = pdf;
            pdfStates[docId].totalPages = pdf.numPages;
            
            var viewer = document.querySelector('[data-pdf-id="' + docId + '"]');
            var total = viewer.querySelector('.pdf-page-total');
            if (total) {{
              total.textContent = '/' + pdf.numPages;
            }}
            
            renderPage(docId, 1);
            maybeCheckPdfUpdate(docId);
          }})
          .catch(function(err) {{
            console.error('PDF load error:', err);
          }});
      }}

      function maybeCheckPdfUpdate(docId) {{
        var state = pdfStates[docId];
        if (!state) {{ return; }}
        var now = Date.now();
        if (now - state.lastCheckTs < 120000) {{ return; }}
        state.lastCheckTs = now;

        fetch('/portal-pdf-update-check?doc=' + encodeURIComponent(docId))
          .then(function(response) {{
            if (!response.ok) throw new Error('update-check failed');
            return response.json();
          }})
          .then(function(data) {{
            var viewer = document.querySelector('[data-pdf-id="' + docId + '"]');
            if (!viewer) {{ return; }}
            var btn = viewer.querySelector('[data-action="apply-update"]');
            var statusEl = document.querySelector('[data-doc-status="' + docId + '"]');
            if (btn) {{
              btn.hidden = !(data && data.updateAvailable);
            }}
            if (statusEl) {{
              if (data && !data.online) {{
                statusEl.textContent = 'Offline';
              }} else {{
                statusEl.textContent = 'Checked just now';
              }}
            }}
          }})
          .catch(function() {{
            var statusEl = document.querySelector('[data-doc-status="' + docId + '"]');
            if (statusEl) {{ statusEl.textContent = 'Check failed'; }}
          }});
      }}

      function refreshPdfFromServer(docId, button) {{
        if (!button) {{ return; }}
        button.classList.add('is-loading');
        button.disabled = true;
        var oldText = button.textContent;
        button.textContent = 'Updating...';

        fetch('/portal-pdf-refresh?doc=' + encodeURIComponent(docId))
          .then(function(response) {{
            if (!response.ok) throw new Error('refresh failed');
            return response.json();
          }})
          .then(function(data) {{
            button.hidden = true;
            loadPdf(docId);
          }})
          .catch(function() {{
            button.textContent = 'Update failed';
            window.setTimeout(function() {{
              button.textContent = oldText;
            }}, 1800);
          }})
          .finally(function() {{
            button.classList.remove('is-loading');
            button.disabled = false;
          }});
      }}
      
      function renderPage(docId, pageNum) {{
        var state = pdfStates[docId];
        if (!state.pdf || pageNum < 1 || pageNum > state.totalPages) return;
        
        state.rendering = true;
        state.pdf.getPage(pageNum).then(function(page) {{
          var viewport = page.getViewport({{scale: 2}});
          state.canvas.width = viewport.width;
          state.canvas.height = viewport.height;
          
          var renderCtx = {{
            canvasContext: state.ctx,
            viewport: viewport
          }};
          
          page.render(renderCtx).promise.then(function() {{
            state.rendering = false;
          }}).catch(function() {{
            state.rendering = false;
          }});
        }});
      }}
      
      function updatePageDisplay(docId) {{
        var state = pdfStates[docId];
        var viewer = document.querySelector('[data-pdf-id="' + docId + '"]');
        var pageInput = viewer.querySelector('.pdf-page-input');
        
        if (pageInput) {{
          pageInput.value = state.currentPage;
        }}
        
        var prevBtn = viewer.querySelector('[data-action="prev-page"]');
        var nextBtn = viewer.querySelector('[data-action="next-page"]');
        
        if (prevBtn) {{
          prevBtn.disabled = state.currentPage <= 1;
        }}
        if (nextBtn) {{
          nextBtn.disabled = state.currentPage >= state.totalPages;
        }}
        
        renderPage(docId, state.currentPage);
      }}

      function clearFloatingControls(exceptEl) {{
        var controlsList = Array.prototype.slice.call(document.querySelectorAll('.pdf-controls'));
        controlsList.forEach(function (controls) {{
          if (exceptEl && controls === exceptEl) {{ return; }}
          controls.classList.remove('is-fixed');
          controls.style.left = '';
          controls.style.width = '';
          var spacer = controls.parentElement ? controls.parentElement.querySelector('.pdf-controls-spacer') : null;
          if (spacer) {{
            spacer.classList.remove('is-visible');
            spacer.style.height = '0px';
          }}
        }});
      }}

      function syncFloatingControls() {{
        var panel = document.getElementById('panel-documentation');
        if (!panel || !panel.classList.contains('is-active')) {{
          clearFloatingControls(null);
          return;
        }}
        var activePage = panel.querySelector('.doc-page.is-active');
        if (!activePage) {{
          clearFloatingControls(null);
          return;
        }}
        var controls = activePage.querySelector('.pdf-controls');
        if (!controls) {{
          clearFloatingControls(null);
          return;
        }}

        clearFloatingControls(controls);

        var topPxRaw = getComputedStyle(controls).getPropertyValue('--pdf-controls-top').trim();
        var topPx = parseInt(topPxRaw, 10);
        if (!Number.isFinite(topPx)) {{ topPx = 8; }}

        var uiStyle = (document.documentElement.getAttribute('data-ui-style') || '').toLowerCase();
        var enableFixedFallback = uiStyle === 'neumorph';

        if (!enableFixedFallback) {{
          clearFloatingControls(null);
          return;
        }}

        var pageRect = activePage.getBoundingClientRect();
        var viewerRect = controls.parentElement.getBoundingClientRect();
        // Use viewer top instead of controls rect so fixed controls can return to normal on upward scroll.
        var shouldFix = viewerRect.top <= topPx && pageRect.bottom > (topPx + controls.offsetHeight + 10);
        var spacer = controls.parentElement.querySelector('.pdf-controls-spacer');

        if (shouldFix) {{
          controls.classList.add('is-fixed');
          controls.style.left = Math.round(viewerRect.left) + 'px';
          controls.style.width = Math.round(viewerRect.width) + 'px';
          if (spacer) {{
            spacer.classList.add('is-visible');
            spacer.style.height = Math.round(controls.offsetHeight + 8) + 'px';
          }}
        }} else {{
          controls.classList.remove('is-fixed');
          controls.style.left = '';
          controls.style.width = '';
          if (spacer) {{
            spacer.classList.remove('is-visible');
            spacer.style.height = '0px';
          }}
        }}
      }}
      
      // Инициализируем все документы
      docOrder.forEach(function(docId) {{
        initPdfViewer(docId);
      }});
      
      // Переинициализируем при смене вкладки
      var docTabs = Array.prototype.slice.call(document.querySelectorAll('.doc-tab'));
      docTabs.forEach(function(tab) {{
        tab.addEventListener('click', function() {{
          var docId = tab.dataset.docTab;
          window.setTimeout(function() {{
            var viewer = document.querySelector('[data-pdf-id="' + docId + '"]');
            if (viewer && viewer.closest('.doc-page.is-active')) {{
              updatePageDisplay(docId);
              maybeCheckPdfUpdate(docId);
            }}
            syncFloatingControls();
          }}, 50);
        }});
      }});

      var menuBtns = Array.prototype.slice.call(document.querySelectorAll('.menu-btn'));
      menuBtns.forEach(function(btn) {{
        btn.addEventListener('click', function() {{
          window.setTimeout(syncFloatingControls, 60);
        }});
      }});
      window.addEventListener('scroll', syncFloatingControls, {{ passive: true }});
      window.addEventListener('resize', syncFloatingControls);
      window.setTimeout(syncFloatingControls, 120);
    }})();
  </script>
</body>
</html>
"""
    return body.encode("utf-8")


# Глобальная переменная для отслеживания последнего обновления PDF
_pdf_last_update_ts: dict[str, float] = {}


def update_pdf_documents_background() -> None:
    """Фоновое обновление PDF документов с Google Docs."""
    while True:
        try:
            time.sleep(PDF_UPDATE_INTERVAL_S)
            
            # Обновляем каждый документ
            for doc_id, doc_info in PORTAL_DOCUMENTS.items():
                google_doc_id = doc_info.get("google_doc_id", "").strip()
                if not google_doc_id:
                    continue
                
                cache_path = PDF_CACHE_DIR / f"{google_doc_id}.pdf"
                try:
                    download_google_doc_pdf(google_doc_id, cache_path)
                    _pdf_last_update_ts[doc_id] = time.time()
                except Exception:
                    pass
        except Exception:
            pass


class HotspotInfoHandler(BaseHTTPRequestHandler):
    server_version = "BMI30HotspotInfo/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _is_tls(self) -> bool:
        return isinstance(self.request, ssl.SSLSocket)

    def _preferred_scheme(self) -> str:
        if self._is_tls() or (is_https_enabled() and FORCE_HTTPS):
            return "https"
        return "http"

    def _absolute_url(self, path: str, scheme: str = "http") -> str:
        local_ip = ""
        try:
            local_ip = self.connection.getsockname()[0]
        except Exception:
            local_ip = ""

        if not local_ip or local_ip == "0.0.0.0":
            local_ip = HOTSPOT_IP

        port = HTTPS_PORT if scheme == "https" else PORT
        needs_port = (scheme == "https" and port != 443) or (scheme == "http" and port != 80)
        suffix = f":{port}" if needs_port else ""
        return f"{scheme}://{local_ip}{suffix}{path}"

    def _read_post_form(self) -> dict[str, str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw = self.rfile.read(max(content_length, 0))
        parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
        # Checkbox + hidden fallback fields submit duplicate keys; use the last value.
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def _read_raw_post_body(self) -> bytes:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        return self.rfile.read(max(content_length, 0))

    def _read_cookie(self, name: str) -> str:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return ""

        jar = SimpleCookie()
        try:
            jar.load(raw_cookie)
        except Exception:
            return ""

        morsel = jar.get(name)
        return morsel.value if morsel is not None else ""

    def _get_portal_session(self) -> dict[str, Any] | None:
        session = parse_portal_session_token(self._read_cookie(PORTAL_SESSION_COOKIE))
        if session is None:
            return None
        if int(session["exp"]) <= int(time.time()):
            return None
        return session

    def _send_redirect(
        self,
        location: str,
        *,
        status: HTTPStatus = HTTPStatus.FOUND,
        set_cookie: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _redirect_portal_privacy_error(self, message: str) -> None:
        self._send_redirect(
            self._absolute_url(
                f"/portal?privacy_error=1&message={quote(message[:240])}#privacy",
                scheme=self._preferred_scheme(),
            ),
            status=HTTPStatus.SEE_OTHER,
        )

    def _require_portal_session(self) -> dict[str, Any] | None:
        session = self._get_portal_session()
        if session is None:
            self._send_redirect(
                self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
            )
            return None
        remember_portal_client(self.client_address[0] if self.client_address else "")
        return session

    def _rewrite_core_html_for_portal(self, payload: bytes) -> bytes:
        text = payload.decode("utf-8", errors="replace")
        replacements = {
            "'/api/status'": "'/portal-core/api/status'",
            '"/api/status"': '"/portal-core/api/status"',
            "'/api/command'": "'/portal-core/api/command'",
            '"/api/command"': '"/portal-core/api/command"',
            "'/api/frame.bin?": "'/portal-core/api/frame.bin?",
            '"/api/frame.bin?': '"/portal-core/api/frame.bin?',
            "'/api/frame?": "'/portal-core/api/frame?",
            '"/api/frame?': '"/portal-core/api/frame?',
            "'/api/player-recording-upload?": "'/portal-core/api/player-recording-upload?",
            '"/api/player-recording-upload?': '"/portal-core/api/player-recording-upload?',
            "'/api/player-recording-download?": "'/portal-core/api/player-recording-download?",
            '"/api/player-recording-download?': '"/portal-core/api/player-recording-download?',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.encode("utf-8")

    def _proxy_core_request(self, send_body: bool, method: str = "GET", body: bytes | None = None) -> None:
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path == "/portal-core":
            core_path = "/"
        elif path.startswith("/portal-core/"):
            core_path = "/" + path[len("/portal-core/"):]
        else:
            core_path = "/"
        url = f"{CORE_SERVICE_URL}{core_path}"
        if query:
            url = f"{url}?{query}"
        headers = {"Accept": self.headers.get("Accept", "*/*")}
        content_type = self.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type
        try:
            timeout_s = 60.0 if (core_path.startswith("/api/player-recording-") or core_path == "/api/command") else 4.0
            request = Request(url, data=body if method.upper() != "GET" else None, headers=headers, method=method.upper())
            with urlopen(request, timeout=timeout_s) as response:
                payload = response.read()
                response_type = response.headers.get("Content-Type", "application/octet-stream")
                content_disposition = response.headers.get("Content-Disposition", "")
                status = HTTPStatus(response.status)
        except Exception as exc:
            payload = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            response_type = "application/json; charset=utf-8"
            content_disposition = ""
            status = HTTPStatus.BAD_GATEWAY
        self.send_response(status)
        self.send_header("Content-Type", response_type)
        if content_disposition:
            self.send_header("Content-Disposition", content_disposition)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _send_portal_oscilloscope(self, send_body: bool) -> None:
        if self._require_portal_session() is None:
            return
        try:
            with urlopen(f"{CORE_SERVICE_URL}/", timeout=4.0) as response:
                payload = self._rewrite_core_html_for_portal(response.read())
        except Exception as exc:
            payload = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>BMI30 Oscilloscope</title></head><body>"
                "<h1>BMI30 Oscilloscope</h1>"
                f"<p>Unable to contact BMI30 core service: {html.escape(str(exc))}</p>"
                "</body></html>"
            ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _handle_request(self, send_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        preferred_ip = extract_request_host_ip(self.headers.get("Host", ""))

        # Legacy Android CNA endpoint: return 204 so the popup can close cleanly.
        if path == "/portal-done":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if path == "/favicon.ico":
            icon = load_logo_bytes(detect_logo_path(FAVICON_ICO_CANDIDATES))
            if icon is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            payload, ctype = icon
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/favicon.png":
            icon = load_logo_bytes(detect_logo_path(FAVICON_PNG_CANDIDATES))
            if icon is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            payload, ctype = icon
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/logo-tagit":
            logo = load_logo_bytes(detect_logo_path(TAGIT_LOGO_CANDIDATES))
            if logo is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            payload, ctype = logo
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path in {"/logo-am", "/logo"}:
            logo = load_logo_bytes(detect_logo_path(AM_LOGO_CANDIDATES))
            if logo is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            payload, ctype = logo
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/portal-oscilloscope":
            self._send_portal_oscilloscope(send_body)
            return

        if path.startswith("/portal-core/") or path == "/portal-core":
            if self._require_portal_session() is None:
                return
            self._proxy_core_request(send_body, method="GET")
            return

        # JSON API
        if path == "/api/status":
            if self._get_portal_session() is not None:
                remember_portal_client(self.client_address[0] if self.client_address else "")
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            firmware = data.get("firmware_release") if isinstance(data.get("firmware_release"), dict) else {}
            self.send_header("X-BMI30-Firmware-Version", str(firmware.get("version") or "unknown"))
            self.send_header("X-BMI30-Portal-SHA256", str(firmware.get("runtime_portal_sha256") or "unknown"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/api/sensors":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            rpi_temps = _read_rpi_temperatures()
            rpi_data = {lbl.lower(): round(t, 1) for lbl, t in rpi_temps}
            rpi_hwmon = _read_rpi_hwmon_readings()
            device_cache = _read_device_state_cache()
            stm32_temp = _device_cache_temperature(device_cache)
            device_sensors = _device_cache_sensors(device_cache)
            core_status = _read_core_status_snapshot()
            core_sync = core_status.get("sync") if isinstance(core_status.get("sync"), dict) else {}
            if core_sync:
                device_sensors["sync"] = dict(core_sync)
                events = device_sensors.get("events") if isinstance(device_sensors.get("events"), dict) else {}
                sync_state = events.get("sync_state") if isinstance(events.get("sync_state"), dict) else {}
                events["sync_state"] = {**sync_state, **core_sync}
                device_sensors["events"] = events
            device_sensors["optic_settings"] = _read_core_optic_settings()
            device_sensors["lan_devices"] = _current_group_lan_devices(
                get_lan_bmi30_devices(),
                device_sensors,
            )
            with _LAN_DEVICE_LOCK:
                device_sensors["lan_devices_updated_at"] = float(_LAN_DEVICE_CACHE.get("updated_at", 0.0) or 0.0)
                device_sensors["lan_sensors_updated_at"] = float(_LAN_DEVICE_CACHE.get("sensor_updated_at", 0.0) or 0.0)
            sensors_data: dict = {
                "rpi": rpi_data,
                "rpi_hwmon": rpi_hwmon,
                "stm32": round(stm32_temp, 1) if isinstance(stm32_temp, (int, float)) else None,
                "host": group_local_host_identity(preferred_ip=preferred_ip),
                "device": device_sensors,
            }
            payload = json.dumps(sensors_data, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/portal-logout":
            self._send_redirect(
                self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
                set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
            )
            return

        if path == "/portal":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return
            remember_portal_client(self.client_address[0] if self.client_address else "")
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            notice = ""
            notice_kind = "ok"
            if query.get("saved", [""])[0] == "1":
                notice = "DC configuration saved."
            if query.get("applied", [""])[0] == "1":
                notice = "DC configuration saved and sent to the device."
            if query.get("error", [""])[0] == "1":
                notice = "DC configuration saved, but the device did not accept the live apply. Check USB connection and try again."
                notice_kind = "error"
            if query.get("tag_saved", [""])[0] == "1":
                notice = "Tag Detection settings saved."
            if query.get("tag_applied", [""])[0] == "1":
                notice = "Tag Detection settings saved and sent to BMI30 core."
            if query.get("tag_error", [""])[0] == "1":
                notice = "Tag Detection settings saved, but BMI30 core did not accept the live apply. Check core service and try again."
                notice_kind = "error"
            if query.get("group_applied", [""])[0] == "1":
                notice = "Optic settings saved and sent to BMI30 core."
            if query.get("group_error", [""])[0] == "1":
                notice = "Optic settings could not be applied. Check the BMI30 core service and USB connection."
                notice_kind = "error"
            if query.get("operation_saved", [""])[0] == "1":
                notice = "Operating mode, sound, and DC adaptation timing saved."
            if query.get("operation_applied", [""])[0] == "1":
                notice = "Operating mode, sound, and DC adaptation timing saved and sent to BMI30 core."
            if query.get("operation_error", [""])[0] == "1":
                notice = query.get(
                    "message",
                    ["Operating mode settings saved, but BMI30 core did not accept the live apply. Check core service and try again."],
                )[0][:240]
                notice_kind = "error"
            if query.get("account", [""])[0] == "1":
                notice = "Portal login and password saved."
            if query.get("hotspot", [""])[0] == "1":
                notice = "HotSpot Wi-Fi access settings saved."
            if query.get("wifi", [""])[0] == "1":
                notice = "Wi-Fi internet access saved."
            if query.get("engineer", [""])[0] == "1":
                notice = "BMI30 portal engineer login saved."
            if query.get("remote", [""])[0] == "1":
                notice = "Remote desktop RDP/VNC login saved."
            if query.get("channel", [""])[0] == "1":
                notice = "Communication channel permission saved."
            if query.get("privacy_error", [""])[0] == "1":
                notice = query.get("message", ["Unable to save privacy settings."])[0][:240]
                notice_kind = "error"
            payload = render_portal_page(
                data["hostname"],
                session_username=str(session.get("u", "")),
                session_role=str(session.get("r", "user")),
                notice=notice,
                notice_kind=notice_kind,
                request_host=self.headers.get("Host", ""),
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        # PDF для портала
        if path == "/portal-pdf":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                if send_body:
                    self.wfile.write(b"Not authorized")
                return
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            doc_key = query.get("doc", [""])[0].strip().lower()
            doc = PORTAL_DOCUMENTS.get(doc_key)
            if doc is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                if send_body:
                    self.wfile.write(b"PDF not found")
                return
            
            google_doc_id = doc.get("google_doc_id", "").strip()
            if not google_doc_id:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            
            pdf_data = get_pdf_data(google_doc_id)
            if pdf_data is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                if send_body:
                    self.wfile.write(b"PDF temporarily unavailable")
                return
            
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Cache-Control", "max-age=3600, public")
            self.send_header("Content-Length", str(len(pdf_data)))
            self.end_headers()
            if send_body:
                self.wfile.write(pdf_data)
            return

        if path == "/portal-pdf-update-check":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                if send_body:
                    self.wfile.write(b'{"error":"not authorized"}')
                return

            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            doc_key = query.get("doc", [""])[0].strip().lower()
            doc = PORTAL_DOCUMENTS.get(doc_key)
            if doc is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                if send_body:
                    self.wfile.write(b'{"error":"doc not found"}')
                return

            google_doc_id = doc.get("google_doc_id", "").strip()
            cache_path = PDF_CACHE_DIR / f"{google_doc_id}.pdf"
            cached = _read_cached_pdf(cache_path)

            if cached is None:
                payload = json.dumps({"updateAvailable": True, "hasCache": False}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if send_body:
                    self.wfile.write(payload)
                return

            remote = _fetch_google_doc_pdf_bytes(google_doc_id, timeout=12)
            update_available = False
            online = remote is not None
            if remote is not None:
                update_available = hashlib.sha256(remote).digest() != hashlib.sha256(cached).digest()

            payload = json.dumps(
                {"updateAvailable": update_available, "hasCache": True, "online": online},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/portal-pdf-refresh":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                if send_body:
                    self.wfile.write(b'{"error":"not authorized"}')
                return

            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            doc_key = query.get("doc", [""])[0].strip().lower()
            doc = PORTAL_DOCUMENTS.get(doc_key)
            if doc is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                if send_body:
                    self.wfile.write(b'{"error":"doc not found"}')
                return

            google_doc_id = doc.get("google_doc_id", "").strip()
            cache_path = PDF_CACHE_DIR / f"{google_doc_id}.pdf"
            previous = _read_cached_pdf(cache_path)
            remote = _fetch_google_doc_pdf_bytes(google_doc_id, timeout=20)
            if remote is None:
                self.send_response(HTTPStatus.BAD_GATEWAY)
                payload = json.dumps({"ok": False, "error": "remote unavailable"}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if send_body:
                    self.wfile.write(payload)
                return

            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(remote)
                changed = previous is None or hashlib.sha256(previous).digest() != hashlib.sha256(remote).digest()
                payload = json.dumps({"ok": True, "updated": changed}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if send_body:
                    self.wfile.write(payload)
                return
            except Exception:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                payload = json.dumps({"ok": False, "error": "cache write failed"}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if send_body:
                    self.wfile.write(payload)
                return

        if path == "/portal-doc-download":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            doc_key = query.get("doc", [""])[0].strip().lower()
            doc = PORTAL_DOCUMENTS.get(doc_key)
            if doc is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if send_body:
                    self.wfile.write(b"Documentation file not found.")
                return
            
            # Теперь скачиваем PDF вместо текста
            google_doc_id = doc.get("google_doc_id", "").strip()
            if not google_doc_id:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                if send_body:
                    self.wfile.write(b"PDF not configured")
                return
            
            pdf_data = get_pdf_data(google_doc_id)
            if pdf_data is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                if send_body:
                    self.wfile.write(b"PDF temporarily unavailable")
                return
            
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", f'attachment; filename="{doc["filename"]}"')
            self.send_header("Content-Length", str(len(pdf_data)))
            self.end_headers()
            if send_body:
                self.wfile.write(pdf_data)
            return

        # Connectivity-probe.
        # Android/Chrome OS надёжнее открывают captive portal после 302 redirect
        # на страницу логина. Для Apple/Windows/Linux оставляем HTML прямо на probe URL.
        if path in ANDROID_PROBE_PATHS:
            login_url = self._absolute_url(with_rev("/login"))
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", login_url)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            return

        if path in PROBE_PATHS:
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            payload = render_html_page(data)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        # Информационная страница
        if path in INFO_PATHS:
            if is_https_enabled() and FORCE_HTTPS and not self._is_tls():
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", self._absolute_url(path, scheme="https"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            payload = render_html_page(data)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        # Всё остальное — редирект на страницу входа
        self._send_redirect(self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()))

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/portal-core/") or path == "/portal-core":
            if self._require_portal_session() is None:
                return
            self._proxy_core_request(True, method="POST", body=self._read_raw_post_body())
            return

        if path == "/portal-account-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            current_username = get_portal_username()
            current_password = form.get("current_password", "")
            new_username = form.get("username", "").strip()
            new_password = form.get("new_password", "")
            confirm_password = form.get("confirm_password", "")

            if not verify_portal_user_password(current_username, current_password):
                self._redirect_portal_privacy_error("Current portal password is incorrect.")
                return
            if new_password != confirm_password:
                self._redirect_portal_privacy_error("New portal passwords do not match.")
                return
            try:
                save_portal_credentials(new_username, new_password)
            except ValueError as exc:
                self._redirect_portal_privacy_error(str(exc))
                return
            except Exception:
                self._redirect_portal_privacy_error("Unable to save portal credentials.")
                return

            expires_at = int(time.time()) + PORTAL_SESSION_TTL_S
            session_cookie = build_portal_session_cookie(
                create_portal_session_token(new_username, expires_at, role="user"),
                remember=True,
                secure=self._is_tls(),
            )
            self._send_redirect(
                self._absolute_url("/portal?account=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
                set_cookie=session_cookie,
            )
            return

        if path == "/portal-engineer-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            enabled = form.get("enabled", "1").strip() not in {"0", "false", "off", "no"}
            username = form.get("username", "").strip() or DEFAULT_ENGINEER_USERNAME
            password = form.get("password", "")
            confirm_password = form.get("confirm_password", "")
            if password or confirm_password:
                if password != confirm_password:
                    self._redirect_portal_privacy_error("Portal engineer passwords do not match.")
                    return
            try:
                save_engineer_credentials(enabled, username, password)
            except ValueError as exc:
                self._redirect_portal_privacy_error(str(exc))
                return
            except Exception:
                self._redirect_portal_privacy_error("Unable to save engineer credentials.")
                return
            self._send_redirect(
                self._absolute_url("/portal?engineer=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-channel-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            channel = form.get("channel", "").strip().lower()
            enabled = form.get("enabled", "0").strip() in {"1", "true", "on", "yes"}
            ok, message = apply_channel_permission(channel, enabled)
            if not ok:
                self._redirect_portal_privacy_error(message)
                return
            self._send_redirect(
                self._absolute_url("/portal?channel=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-remote-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            username = form.get("username", "").strip()
            password = form.get("password", "")
            confirm_password = form.get("confirm_password", "")
            if password or confirm_password:
                if password != confirm_password:
                    self._redirect_portal_privacy_error("RDP/VNC passwords do not match.")
                    return
            ok, message = apply_remote_desktop_credentials(username, password)
            if not ok:
                self._redirect_portal_privacy_error(message)
                return
            self._send_redirect(
                self._absolute_url("/portal?remote=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-hotspot-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            ssid = form.get("ssid", "").strip()
            password = form.get("password", "")
            confirm_password = form.get("confirm_password", "")
            if password or confirm_password:
                if password != confirm_password:
                    self._redirect_portal_privacy_error("HotSpot passwords do not match.")
                    return
            ok, message = apply_hotspot_access_settings(ssid, password)
            if not ok:
                self._redirect_portal_privacy_error(message)
                return
            self._send_redirect(
                self._absolute_url("/portal?hotspot=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-wifi-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            selected_ssid = form.get("visible_ssid", "").strip()
            manual_ssid = form.get("ssid", "").strip()
            ssid = manual_ssid or selected_ssid
            password = form.get("password", "")
            ok, message = connect_wifi_internet(ssid, password)
            if not ok:
                self._redirect_portal_privacy_error(message)
                return
            self._send_redirect(
                self._absolute_url("/portal?wifi=1#privacy", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-operation-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            avg_n = avg_n_from_form(form)
            dc_cfg = dc_timing_config_from_form(form, load_dc_config())
            sound_cfg = sound_config_from_form(form)
            lcd_role_cfg = lcd_role_overlay_from_form(form)
            try:
                save_default_avg_n(avg_n)
                save_dc_config(dc_cfg)
                save_sound_config(sound_cfg)
                save_lcd_role_overlay(lcd_role_cfg)
            except Exception:
                payload = render_portal_page(
                    collect_remote_access_targets(preferred_ip=extract_request_host_ip(self.headers.get("Host", "")))["hostname"],
                    session_username=str(session.get("u", "")),
                    session_role=str(session.get("r", "user")),
                    notice="Unable to save Operating Mode settings.",
                    notice_kind="error",
                    request_host=self.headers.get("Host", ""),
                )
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            apply_now = form.get("apply", "1").strip().lower() not in {"0", "false", "off", "no"}
            if apply_now:
                def _apply_step(name: str, call):
                    result = call()
                    if not bool(result[0]):
                        # Core can be briefly busy with USB readback or a mode
                        # transition. All four operations are idempotent, so one
                        # bounded retry prevents a false failure banner.
                        time.sleep(0.15)
                        result = call()
                    return name, bool(result[0]), str(result[1] if len(result) > 1 else "")

                apply_results = [
                    _apply_step("averaging", lambda: apply_avg_n_to_core(avg_n)),
                    _apply_step("DC timing", lambda: apply_dc_config_to_device(dc_cfg)),
                    _apply_step("sound", lambda: apply_sound_config_to_core(sound_cfg, persist=True)),
                    _apply_step("LCD role overlay", lambda: apply_lcd_role_overlay_to_core(lcd_role_cfg, persist=True)),
                ]
                failures = [(name, message) for name, step_ok, message in apply_results if not step_ok]
                if failures:
                    detail = "; ".join(f"{name}: {message}" for name, message in failures)
                    print(f"[OPERATION-APPLY] failed after retry: {detail}", flush=True)
                    notice = f"Settings saved; live apply failed: {detail}"[:240]
                    suffix = f"?operation_error=1&message={quote(notice)}#operation"
                else:
                    suffix = "?operation_applied=1#operation"
            else:
                suffix = "?operation_saved=1#operation"
            self._send_redirect(
                self._absolute_url(f"/portal{suffix}", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/api/sound-config":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            cfg = _normalize_sound_config(body if isinstance(body, dict) else {})
            persist = _bool_form_value({"persist": str((body or {}).get("persist", "0"))}, "persist", False) if isinstance(body, dict) else False
            ok, message = apply_sound_config_to_core(cfg, persist=persist)
            if ok and persist:
                try:
                    save_sound_config(cfg)
                except Exception:
                    ok = False
                    message = "Unable to save sound settings."
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "sound": cfg,
                "persisted": bool(persist and ok),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/lcd-role-overlay":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            cfg = _normalize_lcd_role_overlay(body if isinstance(body, dict) else {})
            persist = _bool_form_value({"persist": str((body or {}).get("persist", "1"))}, "persist", True) if isinstance(body, dict) else True
            ok, message, actual = apply_lcd_role_overlay_to_core(cfg, persist=persist)
            if ok and persist:
                try:
                    save_lcd_role_overlay(cfg)
                except Exception:
                    ok = False
                    message = "Unable to save LCD role overlay settings."
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "lcd_role_overlay": actual,
                "persisted": bool(persist and ok),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/portal-group-led-pattern-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            cfg = group_led_patterns_from_form(form)
            try:
                save_group_led_patterns(cfg)
            except Exception:
                payload = render_portal_page(
                    collect_remote_access_targets(preferred_ip=extract_request_host_ip(self.headers.get("Host", "")))["hostname"],
                    session_username=str(session.get("u", "")),
                    session_role=str(session.get("r", "user")),
                    notice="Unable to save Addressable LED pattern settings.",
                    notice_kind="error",
                    request_host=self.headers.get("Host", ""),
                )
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            apply_now = form.get("apply", "1").strip().lower() not in {"0", "false", "off", "no"}
            if apply_now:
                ok, _message = apply_group_led_patterns_to_core(cfg)
                suffix = "?group_led_applied=1#group" if ok else "?group_led_error=1#group"
            else:
                suffix = "?group_led_saved=1#group"
            self._send_redirect(
                self._absolute_url(f"/portal{suffix}", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/api/group-led-pattern-test":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            pattern_id = _led_pattern_value(body.get("pattern", body.get("pattern_id", 0)))
            ok, message = apply_led_pattern_to_core(pattern_id)
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "pattern": pattern_id,
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/non-addressable-led":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            enabled = None
            if "enabled" in body:
                enabled = _bool_form_value({"enabled": str(body.get("enabled"))}, "enabled", True)
            test_enabled = None
            if "test_enabled" in body:
                test_enabled = _bool_form_value({"test_enabled": str(body.get("test_enabled"))}, "test_enabled", False)
            persist = _bool_form_value(
                {"persist": str(body.get("persist", enabled is not None))},
                "persist",
                enabled is not None,
            )
            ok, message, actual = apply_non_addressable_led_to_core(
                enabled=enabled,
                test_enabled=test_enabled,
                persist=persist,
            )
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "non_addressable_led": actual,
                "persisted": bool(persist and ok),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/group-sync-config":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            role = ""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                role = str(body.get("role", body.get("mode", "")) or "")
                node_id = body.get("node_id", body.get("slave_id", None))
            except Exception:
                node_id = None
            ok, message, applied = apply_group_sync_mode_to_core(role, node_id)
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "role": str(applied.get("role", role)).strip().lower(),
                "node_id": applied.get("node_id"),
            }).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else (HTTPStatus.BAD_REQUEST if not applied else HTTPStatus.BAD_GATEWAY))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/group-rs485-id":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            device_id = body.get("device_id", body.get("node_id")) if isinstance(body, dict) else None
            ok, message, applied = apply_group_rs485_id_to_core(device_id)
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "device_id": applied.get("device_id"),
                "device_id_assigned": bool(ok),
            }).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else (HTTPStatus.BAD_REQUEST if not applied else HTTPStatus.BAD_GATEWAY))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/group-rs485-ident":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            request_scan = bool(body.get("request_scan", body.get("scan", True))) if isinstance(body, dict) else True
            local_ip = _group_publication_ip(extract_request_host_ip(self.headers.get("Host", "")))
            ok, message, ident = refresh_group_rs485_ident_from_core(request_scan=request_scan, local_ip=local_ip)
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "rs485_ident": ident,
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/group-optic-config":
            if self._get_portal_session() is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            reaction_enabled = False
            neighbor_reaction_enabled = False
            neighbor_device_id = None
            hold_seconds = 3
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                reaction_enabled = bool(body.get("reaction", body.get("reaction_enabled", False)))
                neighbor_reaction_enabled = bool(
                    body.get(
                        "neighbor_reaction",
                        body.get("neighbor_reaction_enabled", False),
                    )
                )
                raw_neighbor_device_id = body.get(
                    "neighbor_device_id",
                    body.get("neighbor_id"),
                )
                if raw_neighbor_device_id not in (None, "", -1, "-1", "any", "all"):
                    parsed_neighbor_device_id = int(raw_neighbor_device_id)
                    if 0 <= parsed_neighbor_device_id <= 31:
                        neighbor_device_id = parsed_neighbor_device_id
                hold_seconds = int(body.get("hold_seconds", body.get("seconds", 3)))
            except Exception:
                pass
            hold_seconds = max(0, min(10, hold_seconds))
            ok, message = apply_group_optic_to_core(
                reaction_enabled,
                neighbor_reaction_enabled,
                neighbor_device_id,
                hold_seconds,
            )
            payload = json.dumps({
                "ok": bool(ok),
                "message": message,
                "reaction_enabled": bool(reaction_enabled),
                "neighbor_reaction_enabled": bool(neighbor_reaction_enabled),
                "neighbor_device_id": neighbor_device_id,
                "hold_seconds": hold_seconds,
            }).encode("utf-8")
            self.send_response(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/portal-tag-detection-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            cfg = tag_detection_config_from_form(form)
            try:
                save_tag_detection_config(cfg)
            except Exception:
                payload = render_portal_page(
                    collect_remote_access_targets(preferred_ip=extract_request_host_ip(self.headers.get("Host", "")))["hostname"],
                    session_username=str(session.get("u", "")),
                    session_role=str(session.get("r", "user")),
                    notice="Unable to save Tag Detection settings.",
                    notice_kind="error",
                    request_host=self.headers.get("Host", ""),
                )
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            apply_now = form.get("apply", "1").strip().lower() not in {"0", "false", "off", "no"}
            if apply_now:
                ok, _message = apply_tag_detection_config_to_core(cfg)
                suffix = "?tag_applied=1#detection" if ok else "?tag_error=1#detection"
            else:
                suffix = "?tag_saved=1#detection"
            self._send_redirect(
                self._absolute_url(f"/portal{suffix}", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path == "/portal-dc-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            cfg = dc_config_from_form(form)
            try:
                save_dc_config(cfg)
            except Exception:
                payload = render_portal_page(
                    collect_remote_access_targets(preferred_ip=extract_request_host_ip(self.headers.get("Host", "")))["hostname"],
                    session_username=str(session.get("u", "")),
                    session_role=str(session.get("r", "user")),
                    notice="Unable to save DC configuration.",
                    notice_kind="error",
                    request_host=self.headers.get("Host", ""),
                )
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            apply_now = form.get("apply", "1").strip().lower() not in {"0", "false", "off", "no"}
            if apply_now:
                ok, _message = apply_dc_config_to_device(cfg)
                suffix = "?applied=1#operation" if ok else "?error=1#operation"
            else:
                suffix = "?saved=1#operation"
            self._send_redirect(
                self._absolute_url(f"/portal{suffix}", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        if path != "/portal-login":
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", "GET, HEAD, POST")
            self.end_headers()
            return

        if is_https_enabled() and FORCE_HTTPS and not self._is_tls():
            self._send_redirect(
                self._absolute_url(with_rev("/login"), scheme="https"),
                status=HTTPStatus.SEE_OTHER,
            )
            return

        preferred_ip = extract_request_host_ip(self.headers.get("Host", ""))
        form = self._read_post_form()
        username = form.get("username", "").strip()
        password = form.get("password", "")
        remember_session = form.get("remember", "").strip().lower() not in {"", "0", "false", "off", "no"}

        auth_result = authenticate_portal_credentials(username, password)
        if auth_result is not None:
            expires_at = int(time.time()) + PORTAL_SESSION_TTL_S
            session_cookie = build_portal_session_cookie(
                create_portal_session_token(
                    auth_result["username"],
                    expires_at,
                    role=auth_result["role"],
                ),
                remember=remember_session,
                secure=self._is_tls(),
            )
            self._send_redirect(
                self._absolute_url("/portal", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
                set_cookie=session_cookie,
            )
            return

        data = collect_remote_access_targets(preferred_ip=preferred_ip)
        payload = render_html_page(
            data,
            auth_error="Invalid username or password.",
            entered_username=username,
            remember_session=remember_session,
        )
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    global HTTPS_RUNTIME_ENABLED

    # Запускаем фоновый процесс обновления PDF документов
    pdf_update_thread = threading.Thread(target=update_pdf_documents_background, daemon=True)
    pdf_update_thread.start()

    rpi_identity_thread = threading.Thread(
        target=publish_group_rpi_identity_background,
        name="bmi30-rs485-rpi-identity",
        daemon=True,
    )
    rpi_identity_thread.start()

    lan_discovery_thread = threading.Thread(
        target=lan_bmi30_discovery_background,
        name="bmi30-lan-discovery",
        daemon=True,
    )
    lan_discovery_thread.start()

    lan_sensor_thread = threading.Thread(
        target=lan_bmi30_sensor_refresh_background,
        name="bmi30-lan-sensor-refresh",
        daemon=True,
    )
    lan_sensor_thread.start()

    http_server = ThreadingHTTPServer(("0.0.0.0", PORT), HotspotInfoHandler)

    https_server: ThreadingHTTPServer | None = None
    if ENABLE_HTTPS and HTTPS_PORT != PORT and os.path.isfile(TLS_CERT_PATH) and os.path.isfile(TLS_KEY_PATH):
        try:
            https_server = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), HotspotInfoHandler)
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=TLS_CERT_PATH, keyfile=TLS_KEY_PATH)
            https_server.socket = ssl_ctx.wrap_socket(https_server.socket, server_side=True)
            HTTPS_RUNTIME_ENABLED = True
        except Exception as exc:
            HTTPS_RUNTIME_ENABLED = False
            print(f"[WARN] HTTPS disabled: {exc}")

    if https_server is not None:
        th = threading.Thread(target=https_server.serve_forever, daemon=True)
        th.start()

    http_server.serve_forever()


if __name__ == "__main__":
    main()
