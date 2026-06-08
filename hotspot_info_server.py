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
import ssl
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote
from urllib.request import Request, urlopen


PORT         = int(os.getenv("BMI30_HOTSPOT_INFO_PORT",      "80"))
HTTPS_PORT   = int(os.getenv("BMI30_HOTSPOT_INFO_HTTPS_PORT", "443"))
REFRESH_S    = max(10, int(os.getenv("BMI30_HOTSPOT_INFO_REFRESH_S", "30")))
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
if _CONFIG_JSON_ENV:
    CONFIG_JSON = _CONFIG_JSON_ENV
else:
    _CONFIG_JSON_CANDIDATES = [
        "/etc/bmi30/portal_config.json",
        "/usr/local/bin/host/bmi30_config.json",
        os.path.join(os.path.dirname(__file__), "host", "bmi30_config.json"),
    ]
    _CONFIG_JSON_FALLBACK = _CONFIG_JSON_CANDIDATES[0] if getattr(os, "geteuid", lambda: 0)() == 0 else _CONFIG_JSON_CANDIDATES[-1]
    CONFIG_JSON = next((path for path in _CONFIG_JSON_CANDIDATES if os.path.isfile(path)), _CONFIG_JSON_FALLBACK)
DEVICE_SYNC_CACHE_S = max(1, int(os.getenv("BMI30_DEVICE_SYNC_CACHE_S", "3")))
SYNC_STATUS_OFFSET_S = os.getenv("BMI30_SYNC_STATUS_OFFSET", "").strip()
PAGE_REV = os.getenv("BMI30_PAGE_REV", str(int(os.path.getmtime(__file__))))
BMI30_SERVICE_URL = os.getenv("BMI30_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")
BMI30_REPO_DIR = os.getenv("BMI30_REPO_DIR", "/home/techaid/Documents").rstrip("/")
BMI30_HOST_DIR = os.getenv("BMI30_HOST_DIR", os.path.join(BMI30_REPO_DIR, "host")).rstrip("/")
BMI30_SPLIT_ACTIVE_ENV = os.getenv(
    "BMI30_SPLIT_ACTIVE_ENV",
    os.path.join(BMI30_HOST_DIR, "bmi30_split_active_version.env"),
)
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
    "source": "device",
}

_PORTAL_CLIENTS: dict[str, float] = {}
PORTAL_CLIENT_TTL_S = 15.0

HTTPS_RUNTIME_ENABLED = False

DC_MODE_NAMES = {
    0: "FREEZE",
    1: "WORK",
    2: "DETECT",
    3: "BOOT_FAST",
}

DC_MODE_VALUES = {name: value for value, name in DC_MODE_NAMES.items()}

DEFAULT_DC_CONFIG: dict[str, Any] = {
    "mode": "WORK",
    "work_settle_s": 900.0,
    "detect_initial_settle_s": 60.0,
    "detect_final_settle_s": 15.0,
    "detect_ramp_s": 300.0,
    "fast_settle_s": 5.0,
    "fast_duration_s": 30.0,
}

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
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
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


def _normalize_dc_config(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_DC_CONFIG)
    cfg.update({k: source.get(k, v) for k, v in DEFAULT_DC_CONFIG.items()})
    mode = str(cfg.get("mode", "WORK")).strip().upper().replace("-", "_")
    if mode not in DC_MODE_VALUES:
        mode = "WORK"
    cfg["mode"] = mode
    cfg["work_settle_s"] = _float_form_value(cfg, "work_settle_s", 900.0, 1.0, 86400.0)
    cfg["detect_initial_settle_s"] = _float_form_value(cfg, "detect_initial_settle_s", 60.0, 0.1, 86400.0)
    cfg["detect_final_settle_s"] = _float_form_value(cfg, "detect_final_settle_s", 15.0, 0.1, 86400.0)
    cfg["detect_ramp_s"] = _float_form_value(cfg, "detect_ramp_s", 300.0, 0.0, 86400.0)
    cfg["fast_settle_s"] = _float_form_value(cfg, "fast_settle_s", 5.0, 0.1, 3600.0)
    cfg["fast_duration_s"] = _float_form_value(cfg, "fast_duration_s", 30.0, 0.0, 86400.0)
    return cfg


def load_dc_config() -> dict[str, Any]:
    return _normalize_dc_config(_load_config_json().get("dc_config"))


def save_dc_config(cfg: dict[str, Any]) -> None:
    payload = _load_config_json()
    payload["dc_config"] = _normalize_dc_config(cfg)
    payload["dc_config_updated_at"] = int(time.time())
    _save_config_json(payload)


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
    mode = form.get("mode", "WORK").strip().upper().replace("-", "_")
    return _normalize_dc_config({
        "mode": mode,
        "work_settle_s": _float_form_value(form, "work_settle_s", 900.0, 1.0, 86400.0),
        "detect_initial_settle_s": _float_form_value(form, "detect_initial_settle_s", 60.0, 0.1, 86400.0),
        "detect_final_settle_s": _float_form_value(form, "detect_final_settle_s", 15.0, 0.1, 86400.0),
        "detect_ramp_s": _float_form_value(form, "detect_ramp_s", 300.0, 0.0, 86400.0),
        "fast_settle_s": _float_form_value(form, "fast_settle_s", 5.0, 0.1, 3600.0),
        "fast_duration_s": _float_form_value(form, "fast_duration_s", 30.0, 0.0, 86400.0),
    })


def _bmi30_service_request(path: str, payload: dict[str, Any] | None = None, timeout: float = 1.2) -> dict[str, Any] | None:
    url = f"{BMI30_SERVICE_URL}{path}"
    try:
        if payload is None:
            with urlopen(url, timeout=timeout) as response:
                data = response.read()
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=timeout) as response:
                data = response.read()
        parsed = json.loads(data.decode("utf-8") or "{}")
        return parsed if isinstance(parsed, dict) else {"ok": False, "error": "BMI30 service returned non-object JSON"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "service_url": BMI30_SERVICE_URL}


def bmi30_service_status() -> dict[str, Any]:
    data = _bmi30_service_request("/api/status", timeout=1.0)
    if not isinstance(data, dict):
        return {"ok": False, "error": "BMI30 service unavailable", "service_url": BMI30_SERVICE_URL}
    return data


def bmi30_service_command(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _bmi30_service_request(
        "/api/command",
        {"action": str(action), "params": dict(params or {})},
        timeout=6.0,
    )
    if not isinstance(data, dict):
        return {"ok": False, "error": "BMI30 service unavailable", "service_url": BMI30_SERVICE_URL}
    return data


def _split_env_unquote(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value.replace("\\ ", " ")


def load_bmi30_split_active_env() -> dict[str, str]:
    payload = {
        "BMI30_CORE_PATH": "host/BMI30.001.py",
        "BMI30_GUI_PATH": "host/BMI30.GUI.001.py",
        "BMI30_SERVICE_URL": BMI30_SERVICE_URL,
    }
    try:
        with open(BMI30_SPLIT_ACTIVE_ENV, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in payload:
                    payload[key] = _split_env_unquote(value)
    except Exception:
        pass
    return payload


def _repo_relative_path(path_value: str) -> str:
    value = str(path_value or "").strip()
    if not value:
        raise ValueError("Empty BMI30 path.")
    if os.path.isabs(value):
        rel = os.path.relpath(value, BMI30_REPO_DIR)
    else:
        rel = value
    rel = rel.replace("\\", "/")
    if rel.startswith("../") or rel == ".." or rel.startswith("/"):
        raise ValueError("BMI30 path must stay inside repository.")
    return rel


def list_bmi30_core_versions() -> list[dict[str, str]]:
    host_dir = pathlib.Path(BMI30_HOST_DIR)
    versions: list[dict[str, str]] = []
    try:
        candidates = sorted(host_dir.glob("BMI30.[0-9][0-9][0-9].py"))
    except Exception:
        candidates = []
    for path in candidates:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:8192]
        except Exception:
            continue
        if "BMI30 core service" not in head and "SERVICE_VERSION" not in head:
            continue
        rel = os.path.relpath(str(path), BMI30_REPO_DIR).replace("\\", "/")
        versions.append({"path": rel, "name": path.name})
    return versions


def save_bmi30_core_version(core_path: str) -> str:
    rel = _repo_relative_path(core_path)
    allowed = {item["path"] for item in list_bmi30_core_versions()}
    if rel not in allowed:
        raise ValueError("Selected Core service version is not available or not service-compatible.")
    active = load_bmi30_split_active_env()
    active["BMI30_CORE_PATH"] = rel
    active.setdefault("BMI30_GUI_PATH", "host/BMI30.GUI.001.py")
    active.setdefault("BMI30_SERVICE_URL", BMI30_SERVICE_URL)
    directory = os.path.dirname(BMI30_SPLIT_ACTIVE_ENV) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{BMI30_SPLIT_ACTIVE_ENV}.tmp"
    try:
        owner_stat = os.stat(BMI30_SPLIT_ACTIVE_ENV)
    except FileNotFoundError:
        owner_stat = os.stat(directory)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated by BMI30 web portal.\n")
        f.write("# GUI version can be selected from the debug terminal menu.\n")
        f.write(f"BMI30_CORE_PATH={active['BMI30_CORE_PATH']}\n")
        f.write(f"BMI30_GUI_PATH={active['BMI30_GUI_PATH']}\n")
        f.write(f"BMI30_SERVICE_URL={active['BMI30_SERVICE_URL']}\n")
    try:
        os.chown(tmp_path, owner_stat.st_uid, owner_stat.st_gid)
    except Exception:
        pass
    try:
        os.chmod(tmp_path, 0o644)
    except Exception:
        pass
    os.replace(tmp_path, BMI30_SPLIT_ACTIVE_ENV)
    return rel


def apply_dc_config_to_device(cfg: dict[str, Any]) -> tuple[bool, str]:
    cfg = _normalize_dc_config(cfg)
    mode_value = DC_MODE_VALUES.get(str(cfg["mode"]), 1)
    detect_settle_s = cfg["detect_initial_settle_s"]
    service_result = bmi30_service_command(
        "dc_config",
        {
            "mode": mode_value,
            "work_settle_s": cfg["work_settle_s"],
            "detect_settle_s": detect_settle_s,
            "fast_settle_s": cfg["fast_settle_s"],
            "fast_duration_s": cfg["fast_duration_s"],
        },
    )
    if service_result.get("ok"):
        return True, "SET_DC_CONFIG sent via BMI30 core service"
    service_error = str(service_result.get("error", "") or "")
    script = (
        "import sys;"
        "sys.path.insert(0, '/home/techaid/Documents/host');"
        "from usb_vendor.usb_stream import USBStream;"
        f"s=USBStream(profile=1, full=True, fast_mode=True);"
        "\n"
        "try:\n"
        f" s.set_dc_config_seconds(mode={mode_value}, work_settle_s={cfg['work_settle_s']!r}, detect_settle_s={detect_settle_s!r}, fast_settle_s={cfg['fast_settle_s']!r}, fast_duration_s={cfg['fast_duration_s']!r})\n"
        " print('SET_DC_CONFIG sent')\n"
        " try:\n"
        "  print(s.get_dc_config())\n"
        " except Exception as e:\n"
        "  print('readback unavailable: %s' % e)\n"
        "finally:\n"
        " s._running=False\n"
    )
    try:
        proc = subprocess.run(
            ["python3", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
    except Exception as exc:
        prefix = f"Core service unavailable: {service_error}. " if service_error else ""
        return False, f"{prefix}Unable to contact device: {exc}"

    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        prefix = f"Core service unavailable: {service_error}. " if service_error else ""
        return False, prefix + (output or f"USB apply failed with exit code {proc.returncode}")
    return True, output or "SET_DC_CONFIG sent"


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


def _read_device_status_packet() -> bytes | None:
    """Query device via USB GET_STATUS and return raw STAT packet if available."""
    script = (
        "import sys;"
        "sys.path.insert(0, '/home/techaid/Documents/host');"
        "from usb_vendor.usb_stream import USBStream;"
        "s=USBStream(profile=1, full=True, fast_mode=True);"
        "ok=None;"
        "\n"
        "try:\n"
        " s._get_status_ep0();\n"
        " st=getattr(s,'last_stat',None);\n"
        " ok=st if isinstance(st,(bytes,bytearray)) and len(st)>=8 else None\n"
        "finally:\n"
        " s.close()\n"
        "\n"
        "import sys as _s;"
        "_s.stdout.buffer.write(ok if ok else b'')"
    )
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


def detect_sync_mode() -> dict[str, Any]:
    """
    Source is the device.
    - If device does not respond: show '---'.
    - If device responds: show mode (from STAT offset if configured, otherwise
      use last known UI mode as fallback while still requiring device response).
    """
    now = time.time()
    if (now - float(_SYNC_CACHE.get("ts", 0.0))) < DEVICE_SYNC_CACHE_S:
        return {
            "value": str(_SYNC_CACHE.get("value", "---")),
            "source": str(_SYNC_CACHE.get("source", "device")),
            "device_responded": bool(_SYNC_CACHE.get("responded", False)),
        }

    st = _read_device_status_packet()
    if not st:
        _SYNC_CACHE.update({"ts": now, "responded": False, "value": "---", "source": "device"})
        return {"value": "---", "source": "device", "device_responded": False}

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
                source = f"device:STAT[{off}]"
        except Exception:
            pass

    # If STAT layout is unknown, still require live device response,
    # but use last known UI mode as fallback.
    if mode == "---":
        mode = _load_ui_sync_mode_from_config()
        source = "device+ui_cache" if mode != "---" else "device"

    _SYNC_CACHE.update({"ts": now, "responded": True, "value": mode, "source": source})
    return {"value": mode, "source": source, "device_responded": True}


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
      --bg:#f5f7fa;--bg-2:#f0f3f8;--glass:rgba(255,255,255,.65);--glass-strong:rgba(255,255,255,.78);
      --glass-fallback:#fafbfc;--panel:rgba(255,255,255,.68);--panel-fallback:#fafbfc;--text:#1a1f2e;
      --muted:#6b7280;--line:rgba(255,255,255,.85);--line-soft:rgba(30,41,59,.08);--accent:#0f766e;
      --accent-2:#2563eb;--accent-soft:rgba(15,118,110,.12);--warm:rgba(59,130,246,.10);--grid-line:rgba(30,41,59,.04);
      --edge-shadow:rgba(15,23,42,.12);--input-bg:rgba(255,255,255,.70);--portal-border:rgba(59,130,246,.30);
      --form-error-border:#fed7d7;--form-error-bg:rgba(254,242,242,.90);--form-error-text:#c53030;
      --footer:#6b7280;--note-bg:rgba(255,255,255,.60);--note-border:rgba(59,130,246,.20);--note-text:#3f4655;--shine:.88;
      --panel-shadow:0 0 0 1px rgba(255,255,255,.80),0 2px 4px rgba(0,0,0,.04),0 12px 24px rgba(59,130,246,.10),0 20px 48px rgba(15,23,42,.08),inset 0 1px 1px rgba(255,255,255,.95),inset 0 -12px 24px rgba(59,130,246,.05);
      --panel-hover-shadow:0 0 0 1px rgba(255,255,255,.88),0 3px 6px rgba(0,0,0,.06),0 16px 32px rgba(59,130,246,.14),0 28px 64px rgba(15,23,42,.12),inset 0 1px 1px rgba(255,255,255,.98),inset 0 -14px 28px rgba(59,130,246,.08);
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
        radial-gradient(800px 400px at 20% 10%,rgba(59,130,246,.08),rgba(59,130,246,0) 60%),
        radial-gradient(600px 300px at 80% 90%,rgba(20,184,166,.06),rgba(20,184,166,0) 55%),
        linear-gradient(180deg,#f5f7fa 0%,#f0f3f8 100%);
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
      background:linear-gradient(135deg,rgba(255,255,255,.80),rgba(255,255,255,.50) 60%,rgba(255,255,255,.72));
      border:1px solid rgba(255,255,255,.90);
      box-shadow:var(--panel-shadow);
      backdrop-filter:blur(20px) saturate(1.20) brightness(1.05);
      -webkit-backdrop-filter:blur(20px) saturate(1.20) brightness(1.05);
    }
    html[data-ui-style="crystal"] .hero::before,
    html[data-ui-style="crystal"] .card::before,
    html[data-ui-style="crystal"] .security-note::before,
    html[data-ui-style="crystal"] .panel::before{
      top:0;left:0;right:0;height:45%;
      background:linear-gradient(180deg,rgba(255,255,255,.85),rgba(255,255,255,.30),rgba(255,255,255,0));
      mix-blend-mode:screen;
      opacity:var(--shine);
    }
    html[data-ui-style="crystal"] .hero::after,
    html[data-ui-style="crystal"] .card::after,
    html[data-ui-style="crystal"] .security-note::after,
    html[data-ui-style="crystal"] .panel::after{
      inset:0;
      border-radius:inherit;
      background:linear-gradient(125deg,rgba(255,255,255,.60),rgba(255,255,255,0) 30%,rgba(255,255,255,0) 70%,rgba(255,255,255,.40));
      mix-blend-mode:normal;
      opacity:.50;
    }
    html[data-ui-style="crystal"] .card:hover{
      box-shadow:var(--panel-hover-shadow);
    }
    html[data-ui-style="crystal"] .hero{
      background:linear-gradient(180deg,rgba(255,255,255,.82),rgba(255,255,255,.55) 60%,rgba(255,255,255,.74));
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
      background:linear-gradient(135deg,rgba(255,255,255,.80),rgba(255,255,255,.50) 60%,rgba(255,255,255,.72));
      border:1px solid rgba(255,255,255,.88);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(255,255,255,.70),0 4px 12px rgba(59,130,246,.10),0 12px 28px rgba(15,23,42,.06),inset 0 1px 1px rgba(255,255,255,.95),inset 0 -8px 16px rgba(59,130,246,.04);
    }
    html[data-ui-style="crystal"] .sbtn::before,
    html[data-ui-style="crystal"] .link::before,
    html[data-ui-style="crystal"] .menu-btn::before,
    html[data-ui-style="crystal"] .mode-option::before{
      content:"";position:absolute;inset:0;
      background:linear-gradient(180deg,rgba(255,255,255,.70),rgba(255,255,255,.20),rgba(255,255,255,0));
      pointer-events:none;opacity:.60;
    }
    html[data-ui-style="crystal"] .sbtn:hover,
    html[data-ui-style="crystal"] .link:hover,
    html[data-ui-style="crystal"] .menu-btn:hover,
    html[data-ui-style="crystal"] .mode-option:hover{
      background:linear-gradient(135deg,rgba(255,255,255,.86),rgba(255,255,255,.58) 60%,rgba(255,255,255,.80));
      border-color:rgba(255,255,255,.94);
      transform:translateY(-2px);
      box-shadow:0 0 0 1px rgba(255,255,255,.76),0 6px 16px rgba(59,130,246,.14),0 16px 36px rgba(15,23,42,.10),inset 0 1px 1px rgba(255,255,255,.98),inset 0 -8px 16px rgba(59,130,246,.06);
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
      background:linear-gradient(135deg,rgba(255,255,255,.80),rgba(255,255,255,.50) 60%,rgba(255,255,255,.72));
      border:1px solid rgba(255,255,255,.88);
      color:var(--text);
      box-shadow:0 0 0 1px rgba(255,255,255,.70),0 4px 12px rgba(59,130,246,.08),inset 0 1px 1px rgba(255,255,255,.95),inset 0 -6px 12px rgba(59,130,246,.04);
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
      --bg:#25282d;--bg-2:#25282d;--glass:#25282d;--glass-strong:#2b2f35;
      --glass-fallback:#25282d;--panel:#25282d;--panel-fallback:#25282d;--text:#edf0f4;
      --muted:#a9afb8;--line:rgba(255,255,255,.08);--line-soft:rgba(255,255,255,.07);--accent:#c7ccd4;
      --accent-2:#ff8a55;--accent-soft:rgba(255,255,255,.05);--warm:rgba(255,255,255,0);--grid-line:rgba(0,0,0,0);
      --edge-shadow:rgba(0,0,0,.52);--input-bg:#25282d;--portal-border:rgba(255,255,255,.08);
      --form-error-border:rgba(255,138,110,.24);--form-error-bg:#322927;--form-error-text:#ffc1b6;
      --footer:#999fa8;--note-bg:#25282d;--note-border:rgba(255,255,255,.08);--note-text:#bac1cb;--shine:.0;
      --neumo-hi:rgba(255,255,255,.07);--neumo-lo:rgba(0,0,0,.48);
      --panel-shadow:12px 12px 24px var(--neumo-lo),-12px -12px 24px var(--neumo-hi);
      --panel-hover-shadow:14px 14px 28px rgba(0,0,0,.54),-14px -14px 28px rgba(255,255,255,.08);
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
    sync_mode  = html.escape(data.get("sync_mode", {}).get("value", "off").upper())
    sync_src   = html.escape(data.get("sync_mode", {}).get("source", "unknown"))
    sync_ok    = bool(data.get("sync_mode", {}).get("device_responded", False))
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
    <p>IM Mark Detection System</p>
  </div>

  <div class="card wifi-card">
        <h2>Wi-Fi Network</h2>
    <dl>
            <dt>SSID</dt>
      <dd class="mono">{ssid}</dd>
            <dt>Hotspot IP</dt>
      <dd class="mono">{hotspot_ip}</dd>
            <dt>Sync Mode</dt>
            <dd class="mono">{sync_mode} <span class="subtle">({sync_src})</span></dd>
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


def render_portal_page(hostname: str, session_username: str = "", session_role: str = "user", notice: str = "", notice_kind: str = "ok") -> bytes:
    title = html.escape(hostname)
    signed_in_as = html.escape(session_username)
    access_label = "Engineering access" if session_role == "engineer" else "User access"
    cfg = load_dc_config()
    portal_auth = load_portal_auth_config()
    portal_username = html.escape(portal_auth["username"])
    hotspot_cfg = detect_hotspot_connection()
    hotspot_ssid = html.escape(hotspot_cfg.get("ssid") or hotspot_cfg.get("connection_id") or "BMI30-Hotspot")
    hotspot_profile = html.escape(hotspot_cfg.get("connection_id") or "NetworkManager")
    config_payload = _load_config_json()
    split_active = load_bmi30_split_active_env()
    core_versions = list_bmi30_core_versions()
    active_core_note = ""
    try:
        active_core_path = _repo_relative_path(split_active.get("BMI30_CORE_PATH", "host/BMI30.001.py"))
    except ValueError as exc:
        active_core_path = "host/BMI30.001.py"
        active_core_note = f" Saved Core path in env is invalid: {exc}"
    core_version_paths = {item["path"] for item in core_versions}
    if core_versions:
        core_options_parts = []
        if active_core_path not in core_version_paths:
            core_options_parts.append(
                f'<option value="{html.escape(active_core_path, quote=True)}" selected>{html.escape(os.path.basename(active_core_path))} (saved, unavailable)</option>'
            )
        core_options_parts.extend(
            f'<option value="{html.escape(item["path"], quote=True)}"{" selected" if item["path"] == active_core_path else ""}>{html.escape(item["name"])}</option>'
            for item in core_versions
        )
        core_options = "".join(core_options_parts)
    else:
        core_options = '<option value="">No service-compatible Core versions found</option>'
    core_select_disabled = "" if core_versions else " disabled"
    active_core_label = html.escape(os.path.basename(active_core_path))
    active_core_rel = html.escape(active_core_path)
    active_core_notice = html.escape(active_core_note)
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
    mode_options = "\n".join(
        f'<label class="mode-option" title="{html.escape(desc)}"><input type="radio" name="mode" value="{name}" {"checked" if cfg["mode"] == name else ""}><span>{label}</span></label>'
        for name, label, desc in (
            ("WORK", "Work", "Slow continuous DC learning for long unattended operation."),
            ("DETECT", "Detect", "Medium tracking during detection; host settings define how it ramps faster over time."),
            ("BOOT_FAST", "Boot-fast", "Fast DC adaptation after a host-controlled forced reboot, then firmware returns to Work."),
            ("FREEZE", "Freeze", "Keep subtracting the stored DC value but stop learning new DC."),
        )
    )
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
            f'        <button class="pdf-update-btn" data-action="apply-update" data-doc="{doc_id}" hidden>↑ Обновить</button>'
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
    body{{min-height:100vh;padding:clamp(18px,3vw,30px);display:grid;place-items:center;
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
    .panel{{position:relative;overflow:visible;width:min(100%,1180px);background:var(--panel);
            border:1px solid var(--line);border-radius:8px;padding:clamp(22px,4vw,42px);
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
    .session-block{{display:grid;justify-items:end;align-content:start;gap:8px;max-width:min(540px,100%)}}
    .session-notice-slot{{width:min(540px,100%);min-height:0}}
    .session-notice-slot .notice{{margin:0}}
    .session-notice-slot .notice-error{{margin:0}}
    .host{{display:inline-block;margin-top:8px;font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;color:var(--text)}}
    .portal-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}}
    .portal-title{{min-width:240px}}
    .portal-shell{{display:grid;grid-template-columns:minmax(190px,240px) minmax(0,1fr);gap:20px;align-items:start}}
    .portal-menu{{display:grid;gap:8px;position:sticky;top:18px}}
    .menu-btn{{width:100%;min-height:44px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);
               color:var(--text);font:inherit;font-weight:700;text-align:left;padding:10px 12px;cursor:pointer;
               display:flex;align-items:center;gap:10px;transition:background-color .14s ease,border-color .14s ease,transform .14s ease}}
    .menu-btn:hover{{background:var(--accent-soft);border-color:var(--accent)}}
    .menu-btn[aria-selected="true"]{{background:var(--accent-soft);border-color:var(--accent);transform:translateY(1px);box-shadow:inset 0 2px 6px rgba(0,0,0,.12),inset 0 0 0 1px var(--accent)}}
    .menu-index{{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;
                 background:var(--panel);border:1px solid var(--line);font-size:12px;color:var(--accent);flex:0 0 auto}}
    .portal-content{{min-width:0}}
    .portal-panel{{display:none}}
    .portal-panel.is-active{{display:block}}
    .summary-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}}
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
    .security-note{{display:none;margin-top:18px;border:1px solid var(--note-border);background:var(--note-bg);
                    color:var(--note-text);border-radius:8px;padding:12px 14px;font-size:12px;line-height:1.55;
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .security-note strong{{color:var(--text)}}
    .config-form{{display:grid;gap:18px;margin-top:18px}}
    .section{{border-top:1px solid var(--line);padding-top:18px}}
    .section h2{{font-size:17px;line-height:1.25;margin-bottom:10px}}
    .mode-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}}
    .mode-option{{display:flex;align-items:center;justify-content:center;min-height:48px;border:1px solid var(--line);
                  border-radius:8px;background:var(--note-bg);cursor:pointer;font-weight:700;color:var(--text)}}
    .mode-option input{{position:absolute;opacity:0;pointer-events:none}}
    .mode-option:has(input:checked){{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent)}}
    .fields{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
    .field{{display:grid;gap:6px}}
    .field span{{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:var(--text)}}
    .field input,.field select{{width:100%;min-height:42px;border:1px solid var(--line);border-radius:8px;background:var(--note-bg);
                  color:var(--text);font:inherit;padding:9px 11px;box-shadow:inset 0 1px 0 rgba(255,255,255,.18)}}
    .field select{{appearance:auto}}
    .field small{{font-size:12px;line-height:1.45;color:var(--muted)}}
    .privacy-status-grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:0 0 14px}}
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
    .privacy-fields{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}}
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
        <p class="eyebrow">BMI30 Management Portal</p>
        <h1>Device Control</h1>
        <p><span class="host">Device: {title}</span></p>
      </div>
      <div class="session-block">
        <p class="session-tag">Signed in as {signed_in_as or "authorized user"} · {access_label}</p>
        <div class="session-notice-slot">{notice_html}</div>
      </div>
    </div>
    <div class="portal-shell">
      <nav class="portal-menu" aria-label="Management sections">
        <button class="menu-btn" type="button" data-panel="antenna" aria-selected="true" title="Displays current antenna parameters: signal level, noise, temperature readings, and sensor data."><span class="menu-index">1</span>Antenna Status</button>
        <button class="menu-btn" type="button" data-panel="detection" aria-selected="false" title="Shows detection algorithm, thresholds, filtering settings, and tag type selection."><span class="menu-index">2</span>Tag Detection</button>
        <button class="menu-btn" type="button" data-panel="operation" aria-selected="false" title="Shows radar connection state, transmitter schedule, and runtime behavior settings."><span class="menu-index">3</span>Operating Mode</button>
        <button class="menu-btn" type="button" data-panel="group" aria-selected="false" title="Shows master/slave role, synchronization status, and group operation settings."><span class="menu-index">4</span>Group Mode</button>
        <button class="menu-btn" type="button" data-panel="dc" aria-selected="false" title="Configures firmware DC subtraction mode and adaptation timing."><span class="menu-index">5</span>DC Compensation</button>
        <button class="menu-btn" type="button" data-panel="privacy" aria-selected="false" title="Change portal credentials, HotSpot access, and Wi-Fi internet connection."><span class="menu-index">6</span>Privacy</button>
        <button class="menu-btn" type="button" data-panel="statistics" aria-selected="false" title="Shows runtime counters, detection history, communication quality, and service statistics."><span class="menu-index">7</span>Statistics</button>
        <button class="menu-btn" type="button" data-panel="documentation" aria-selected="false"><span class="menu-index">8</span>Documentation</button>
        <button class="menu-btn" type="button" data-panel="about" aria-selected="false" title="Shows device identity, firmware version, host software version, serial number, and hardware info."><span class="menu-index">9</span>About Device</button>
        <a class="menu-btn" href="/portal-logout" aria-label="Sign Out"><span class="menu-index" aria-hidden="true">&#x21AA;</span>Sign Out</a>
      </nav>
      <div class="portal-content">
        <section class="portal-panel is-active" id="panel-antenna">
          <div class="summary-grid">
            <div class="summary-item"><h3>Signal</h3><div class="metric"><span>Level</span><strong data-bmi30="level">---</strong></div><div class="metric"><span>Thresholds</span><strong data-bmi30="thresholds">---</strong></div></div>
            <div class="summary-item"><h3>Sensors</h3>{temp_metrics}<div class="metric"><span>Optic active</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Device</h3><div class="metric"><span>Stream</span><strong data-bmi30="stream">---</strong></div><div class="metric"><span>DC mode</span><strong>{html.escape(str(cfg['mode']))}</strong></div></div>
          </div>
        </section>
        <section class="portal-panel" id="panel-detection">
          <div class="summary-grid">
            <div class="summary-item"><h3>Algorithm</h3><div class="metric"><span>Selected</span><strong data-bmi30="mode">---</strong></div></div>
            <div class="summary-item"><h3>Tag Type</h3><div class="metric"><span>Current</span><strong data-bmi30="detector">---</strong></div></div>
            <div class="summary-item"><h3>Thresholds</h3><div class="metric"><span>Ratio</span><strong data-bmi30="ratio">---</strong></div></div>
          </div>
        </section>
        <section class="portal-panel" id="panel-operation">
          <div class="summary-grid">
            <div class="summary-item"><h3>Radar</h3><div class="metric"><span>Connection</span><strong data-bmi30="connection">---</strong></div></div>
            <div class="summary-item"><h3>Transmission</h3><div class="metric"><span>Work time</span><strong data-bmi30="uptime">---</strong></div></div>
            <div class="summary-item"><h3>Profile</h3><div class="metric"><span>Active</span><strong data-bmi30="profile">---</strong></div></div>
          </div>
          <div class="actions actions-inline bmi30-controls">
            <button class="link" type="button" data-bmi30-cmd="mode" data-idx="3">Mode 3</button>
            <button class="link" type="button" data-bmi30-cmd="mode" data-idx="5">Mode 5</button>
            <button class="link" type="button" data-bmi30-cmd="mode" data-idx="6">Mode 6</button>
            <button class="link link-secondary" type="button" data-bmi30-cmd="start">Start</button>
            <button class="link link-secondary" type="button" data-bmi30-cmd="stop">Stop</button>
            <button class="link link-secondary" type="button" data-bmi30-cmd="reconnect">Reconnect</button>
          </div>
          <form class="config-form" method="post" action="/portal-core-version-config">
            <div class="section">
              <h3>Core service version</h3>
              <div class="fields">
                <label class="field">
                  <span>Active Core</span>
                  <select name="core_path"{core_select_disabled}>{core_options}</select>
                </label>
                <div class="metric"><span>Saved</span><strong>{active_core_label}</strong></div>
              </div>
              <p class="notice">Current active path: {active_core_rel}. GUI debug versions are selected from the terminal task menu.{active_core_notice}</p>
            </div>
            <div class="actions actions-inline">
              <button class="link" type="submit" name="apply" value="1"{core_select_disabled}>Save and Restart Core</button>
              <button class="link link-secondary" type="submit" name="apply" value="0"{core_select_disabled}>Save Only</button>
            </div>
          </form>
        </section>
        <section class="portal-panel" id="panel-group">
          <div class="summary-grid">
            <div class="summary-item"><h3>Role</h3><div class="metric"><span>Mode</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Sync</h3><div class="metric"><span>Status</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Peers</h3><div class="metric"><span>Count</span><strong>---</strong></div></div>
          </div>
        </section>
        <section class="portal-panel" id="panel-dc">
          <form class="config-form" method="post" action="/portal-dc-config">
            <div class="section">
              <h3>Mode</h3>
              <div class="mode-grid">{mode_options}</div>
            </div>
            <div class="section">
              <h3>Adaptation timing</h3>
              <div class="fields">
                <label class="field">
                  <span>Work settle time, seconds <b class="help" title="Slow permanent DC tracking. Recommended default is 900 seconds for long operation.">?</b></span>
                  <input name="work_settle_s" type="number" min="1" max="86400" step="1" value="{cfg['work_settle_s']:g}">
                </label>
                <label class="field">
                  <span>Detect initial settle time, seconds <b class="help" title="Starting Detect adaptation speed. Larger values adapt more slowly at the beginning of detection.">?</b></span>
                  <input name="detect_initial_settle_s" type="number" min="0.1" max="86400" step="0.1" value="{cfg['detect_initial_settle_s']:g}">
                </label>
                <label class="field">
                  <span>Detect final settle time, seconds <b class="help" title="Final Detect adaptation speed after the ramp. Smaller values adapt faster.">?</b></span>
                  <input name="detect_final_settle_s" type="number" min="0.1" max="86400" step="0.1" value="{cfg['detect_final_settle_s']:g}">
                </label>
                <label class="field">
                  <span>Detect ramp time, seconds <b class="help" title="How long the host should take to move from initial Detect speed to final Detect speed. Use 0 for immediate final speed.">?</b></span>
                  <input name="detect_ramp_s" type="number" min="0" max="86400" step="1" value="{cfg['detect_ramp_s']:g}">
                </label>
                <label class="field">
                  <span>Boot-fast settle time, seconds <b class="help" title="Fast DC learning speed used after a host-controlled forced reboot. Recommended default is 5 seconds.">?</b></span>
                  <input name="fast_settle_s" type="number" min="0.1" max="3600" step="0.1" value="{cfg['fast_settle_s']:g}">
                </label>
                <label class="field">
                  <span>Boot-fast duration, seconds <b class="help" title="How long firmware stays in BOOT_FAST before automatically switching to WORK. Recommended default is 30 seconds.">?</b></span>
                  <input name="fast_duration_s" type="number" min="0" max="86400" step="1" value="{cfg['fast_duration_s']:g}">
                </label>
              </div>
              <p class="notice">Detect ramp values are saved for the host. The immediate firmware command uses the Detect initial settle time as the current detect_settle_s.</p>
            </div>
            <div class="actions actions-inline">
              <button class="link" type="submit" name="apply" value="1">Save and Apply to Device</button>
              <button class="link link-secondary" type="submit" name="apply" value="0">Save Only</button>
            </div>
          </form>
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
            <div class="summary-item"><h3>Firmware</h3><div class="metric"><span>Version</span><strong>---</strong></div><div class="metric"><span>Build</span><strong>---</strong></div></div>
            <div class="summary-item"><h3>Host</h3><div class="metric"><span>Software</span><strong>BMI30 Portal</strong></div><div class="metric"><span>Role</span><strong>{access_label}</strong></div></div>
          </div>
        </section>
      </div>
    </div>
  </main>
  <button id="scroll-top-btn" class="scroll-top-btn" type="button" aria-label="Scroll to top">↑</button>
  {render_debug_panel()}
  {render_debug_panel_script()}
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
        }})
        .catch(function () {{}});
    }}
    updateConnectionCounts();
    window.setInterval(updateConnectionCounts, 5000);
    // --- Sensor polling (panel-antenna only) ---
    var _activePanel = (window.location.hash || '#antenna').slice(1);
    var _sensorEls = {{}};
    document.querySelectorAll('[data-sensor]').forEach(function (el) {{
      _sensorEls[el.getAttribute('data-sensor')] = el;
    }});
    function _updateSensorEl(key, value) {{
      var el = _sensorEls[key];
      if (!el) {{ return; }}
      el.textContent = (value !== null && value !== undefined) ? value.toFixed(1) + '\u00b0C' : '---';
    }}
    function _pollSensors() {{
      if (_activePanel !== 'antenna') {{ return; }}
      fetch('/api/sensors?v=' + Date.now(), {{ cache: 'no-store' }})
        .then(function (r) {{ return r.ok ? r.json() : null; }})
        .then(function (data) {{
          if (!data) {{ return; }}
          var rpi = data.rpi || {{}};
          Object.keys(rpi).forEach(function (k) {{ _updateSensorEl('rpi-' + k, rpi[k]); }});
          if (data.stm32 !== null && data.stm32 !== undefined) {{
            _updateSensorEl('stm32-temp', data.stm32);
          }}
        }})
        .catch(function () {{}});
    }}
    _pollSensors();
    window.setInterval(_pollSensors, 5000);
    // --- BMI30 core service polling and controls ---
    var _bmi30Els = {{}};
    document.querySelectorAll('[data-bmi30]').forEach(function (el) {{
      _bmi30Els[el.getAttribute('data-bmi30')] = el;
    }});
    function _setBmi30(key, value) {{
      var el = _bmi30Els[key];
      if (el) {{ el.textContent = value; }}
    }}
    function _fmtAge(seconds) {{
      if (seconds === null || seconds === undefined) {{ return '---'; }}
      var s = Math.max(0, Number(seconds) || 0);
      if (s < 60) {{ return s.toFixed(1) + 's'; }}
      return Math.floor(s / 60) + 'm ' + Math.floor(s % 60) + 's';
    }}
    function _pollBmi30() {{
      if (!Object.keys(_bmi30Els).length) {{ return; }}
      fetch('/api/bmi30/status?v=' + Date.now(), {{ cache: 'no-store' }})
        .then(function (r) {{ return r.ok ? r.json() : null; }})
        .then(function (data) {{
          if (!data) {{ return; }}
          if (!data.ok) {{
            _setBmi30('connection', 'service offline');
            _setBmi30('stream', 'offline');
            return;
          }}
          var conn = data.connection || {{}};
          var mode = data.mode || {{}};
          var det = data.detector || {{}};
          var service = data.service || {{}};
          var connected = conn.connected ? 'connected' : (conn.connecting ? 'connecting' : 'offline');
          _setBmi30('connection', connected);
          _setBmi30('stream', (mode.base_buf_len || 0) + ' samples, age ' + _fmtAge(conn.last_frame_age_s));
          _setBmi30('mode', 'mode ' + (mode.selected || 0) + ', stream ' + (mode.stream_mode || 0));
          _setBmi30('detector', (det.active ? 'active' : 'idle') + ' hold ' + (det.hold0 ? '1' : '0') + '/' + (det.hold1 ? '1' : '0'));
          _setBmi30('ratio', Number(mode.det_ratio || 0).toFixed(1));
          _setBmi30('level', (det.lvl0 || 0) + ' / ' + (det.lvl1 || 0));
          _setBmi30('thresholds', (det.thr0 || 0) + ' / ' + (det.thr1 || 0));
          _setBmi30('uptime', _fmtAge(service.uptime_s));
          _setBmi30('profile', (mode.freq_hz || mode.desired_freq || 0) + ' Hz, avg ' + (mode.avg_n || 0));
        }})
        .catch(function () {{
          _setBmi30('connection', 'service offline');
          _setBmi30('stream', 'offline');
        }});
    }}
    document.querySelectorAll('[data-bmi30-cmd]').forEach(function (btn) {{
      btn.addEventListener('click', function () {{
        var action = btn.getAttribute('data-bmi30-cmd') || '';
        var params = {{}};
        if (btn.hasAttribute('data-idx')) {{ params.idx = Number(btn.getAttribute('data-idx')); }}
        btn.disabled = true;
        fetch('/api/bmi30/command', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ action: action, params: params }})
        }})
          .then(function () {{ window.setTimeout(_pollBmi30, 350); }})
          .catch(function () {{}})
          .finally(function () {{ btn.disabled = false; }});
      }});
    }});
    _pollBmi30();
    window.setInterval(_pollBmi30, 2000);
    // patch setActivePanel to track current panel
    var _origSetActivePanel = setActivePanel;
    setActivePanel = function (name, updateHash) {{
      _activePanel = name;
      _origSetActivePanel(name, updateHash);
    }};
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
                statusEl.textContent = 'Нет интернета';
              }} else {{
                statusEl.textContent = 'Проверено только что';
              }}
            }}
          }})
          .catch(function() {{
            var statusEl = document.querySelector('[data-doc-status="' + docId + '"]');
            if (statusEl) {{ statusEl.textContent = 'Ошибка проверки'; }}
          }});
      }}

      function refreshPdfFromServer(docId, button) {{
        if (!button) {{ return; }}
        button.classList.add('is-loading');
        button.disabled = true;
        var oldText = button.textContent;
        button.textContent = 'Обновление...';

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
            button.textContent = 'Ошибка обновления';
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

    def _read_json_body(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw = self.rfile.read(max(0, min(content_length, 1024 * 1024)))
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        return payload if isinstance(payload, dict) else {}

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

        # JSON API
        if path == "/api/status":
            if self._get_portal_session() is not None:
                remember_portal_client(self.client_address[0] if self.client_address else "")
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            data["bmi30"] = bmi30_service_status()
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if path == "/api/bmi30/status":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            remember_portal_client(self.client_address[0] if self.client_address else "")
            data = bmi30_service_status()
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
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
            sensors_data: dict = {"rpi": rpi_data, "stm32": None}
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
            if query.get("core_saved", [""])[0] == "1":
                notice = "Core service version saved."
            if query.get("core_restarted", [""])[0] == "1":
                notice = "Core service version saved and restarted."
            if query.get("core_error", [""])[0] == "1":
                notice = query.get("message", ["Unable to save Core service version."])[0][:240]
                notice_kind = "error"
            if query.get("privacy_error", [""])[0] == "1":
                notice = query.get("message", ["Unable to save privacy settings."])[0][:240]
                notice_kind = "error"
            payload = render_portal_page(
                data["hostname"],
                session_username=str(session.get("u", "")),
                session_role=str(session.get("r", "user")),
                notice=notice,
                notice_kind=notice_kind,
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
        if path == "/api/bmi30/command":
            session = self._get_portal_session()
            if session is None:
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                payload = self._read_json_body()
                action = str(payload.get("action") or "")
                params = payload.get("params")
                if not isinstance(params, dict):
                    params = {k: v for k, v in payload.items() if k not in {"action", "params"}}
                result = bmi30_service_command(action, params)
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        if path == "/portal-core-version-config":
            session = self._get_portal_session()
            if session is None:
                self._send_redirect(
                    self._absolute_url(with_rev("/login"), scheme=self._preferred_scheme()),
                    status=HTTPStatus.SEE_OTHER,
                    set_cookie=build_expired_portal_session_cookie(secure=self._is_tls()),
                )
                return

            form = self._read_post_form()
            core_path = form.get("core_path", "").strip()
            apply_now = form.get("apply", "1").strip().lower() not in {"0", "false", "off", "no"}
            try:
                save_bmi30_core_version(core_path)
                if apply_now:
                    ok, message = _systemctl("restart", "bmi30-core.service", timeout=25.0)
                    if not ok:
                        self._send_redirect(
                            self._absolute_url(
                                f"/portal?core_error=1&message={quote((message or 'Unable to restart Core service')[:240])}#operation",
                                scheme=self._preferred_scheme(),
                            ),
                            status=HTTPStatus.SEE_OTHER,
                        )
                        return
                    suffix = "core_restarted=1"
                else:
                    suffix = "core_saved=1"
            except Exception as exc:
                self._send_redirect(
                    self._absolute_url(
                        f"/portal?core_error=1&message={quote(str(exc)[:240])}#operation",
                        scheme=self._preferred_scheme(),
                    ),
                    status=HTTPStatus.SEE_OTHER,
                )
                return
            self._send_redirect(
                self._absolute_url(f"/portal?{suffix}#operation", scheme=self._preferred_scheme()),
                status=HTTPStatus.SEE_OTHER,
            )
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
                suffix = "?applied=1#dc" if ok else "?error=1#dc"
            else:
                suffix = "?saved=1#dc"
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
