#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import html
import ipaddress
import json
import mimetypes
import os
import socket
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


PORT         = int(os.getenv("BMI30_HOTSPOT_INFO_PORT",      "80"))
REFRESH_S    = max(10, int(os.getenv("BMI30_HOTSPOT_INFO_REFRESH_S", "30")))
HOTSPOT_IP   = os.getenv("BMI30_HOTSPOT_IP",   "10.42.0.1")
HOTSPOT_CONN = os.getenv("BMI30_HOTSPOT_CONN",  "BMI30-Hotspot")
SSH_USER     = os.getenv("BMI30_SSH_USER",      "techaid")
SSH_PORT     = int(os.getenv("BMI30_SSH_PORT",  "22"))
RDP_PORT     = int(os.getenv("BMI30_RDP_PORT",  "3389"))
CONFIG_JSON = os.getenv("BMI30_CONFIG_JSON", os.path.join(os.path.dirname(__file__), "host", "bmi30_config.json"))
DEVICE_SYNC_CACHE_S = max(1, int(os.getenv("BMI30_DEVICE_SYNC_CACHE_S", "3")))
SYNC_STATUS_OFFSET_S = os.getenv("BMI30_SYNC_STATUS_OFFSET", "").strip()
LOGO_CANDIDATES = [
    os.getenv("BMI30_PORTAL_LOGO_PATH", "").strip(),
    os.path.join(os.path.dirname(__file__), "docs", "AM-Secure-Logo@4x-100.jpg"),
    os.path.join(os.path.dirname(__file__), "logo.png"),
    os.path.join(os.path.dirname(__file__), "assets", "logo.png"),
    "/usr/local/share/bmi30/logo.jpg",
    "/usr/local/share/bmi30/logo.png",
]

# Connectivity-probe пути каждой ОС.
# Для probe URL мы отдаем саму HTML-страницу, а для прочих путей делаем
# относительный redirect на /login, чтобы портал одинаково работал и по Wi-Fi,
# и по Ethernet, где IP может отличаться от HOTSPOT_IP.
PROBE_PATHS: frozenset[str] = frozenset({
    "/generate_204",              # Android, Chrome, Chrome OS
    "/gen_204",                   # Android alt
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


def run_command(*args: str) -> str:
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


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


def detect_logo_path() -> str:
    for candidate in LOGO_CANDIDATES:
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


def detect_hotspot_connection() -> dict[str, Any]:
    info: dict[str, Any] = {
        "ssid": "",
        "connection_id": "",
        "interface": "wlan0ap",
    }
    output = run_command("nmcli", "-t", "-f", "DEVICE,NAME,UUID,TYPE", "connection", "show", "--active")
    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        device, name, _uuid, conn_type = parts[:4]
        if device == "wlan0ap" or conn_type in {"wifi", "802-11-wireless"}:
            info["interface"] = device or "wlan0ap"
            info["connection_id"] = name
            info["ssid"] = run_command("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name)
            if not info["ssid"]:
                info["ssid"] = name
            break
    return info


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
    logo_path = detect_logo_path()

    payload = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "hostnames": hostnames,
        "default_iface": default_iface,
        "hotspot": {
            "ssid": hotspot.get("ssid") or hotspot.get("connection_id") or "BMI30-Hotspot",
            "interface": hotspot.get("interface") or "wlan0ap",
            "ip": hotspot_ip,
            "web_url": f"http://{hotspot_ip}/",
        },
        "access": {
            "ip": access_ip,
            "role": access_role,
            "interface": access_iface,
            "web_url": f"http://{access_ip}/",
        },
        "sync_mode": sync_mode,
        "logo": {
            "available": bool(logo_path),
            "url": "/logo" if logo_path else "",
        },
        "interfaces": interfaces,
        "services": {
            "ssh_user": SSH_USER,
            "ssh": SSH_PORT,
            "rdp": RDP_PORT,
            "web": PORT,
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


def render_html_page(data: dict[str, Any]) -> bytes:
    hostname   = html.escape(data["hostname"])
    ssid       = html.escape(data["hotspot"]["ssid"])
    hotspot_ip = html.escape(data["hotspot"]["ip"])
    access_ip  = html.escape(data.get("access", {}).get("ip", data["hotspot"]["ip"]))
    access_role = html.escape(data.get("access", {}).get("role", "hotspot"))
    sync_mode  = html.escape(data.get("sync_mode", {}).get("value", "off").upper())
    sync_src   = html.escape(data.get("sync_mode", {}).get("source", "unknown"))
    sync_ok    = bool(data.get("sync_mode", {}).get("device_responded", False))
    has_logo   = bool(data.get("logo", {}).get("available", False))
    ssh_user   = html.escape(data["services"].get("ssh_user", "techaid"))
    rdp_port   = data["services"]["rdp"]
    generated  = html.escape(data["generated_at"])

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
            f'<tr><td class="role">{rlabel}</td>'
            f'<td class="iname">{iname}</td>'
            f'<td class="mono">{ip}</td></tr>'
        )
    iface_table = "\n".join(iface_rows) or '<tr><td colspan="3">no data</td></tr>'
    logo_html = '<img class="logo" src="/logo" alt="Company logo">' if has_logo else ''

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="{REFRESH_S}">
    <title>BMI30 - Connection Info</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
          background:#f0ece5;color:#1d2a2e;padding:14px;min-height:100vh}}
    .page{{max-width:600px;margin:0 auto;display:flex;flex-direction:column;gap:12px}}
    .logo{{max-height:40px;max-width:160px;object-fit:contain;display:block}}
    /* Hero */
    .hero{{background:linear-gradient(140deg,#e2f4ef 0%,#fff8ed 100%);
           border:1px solid #b8ddd3;border-radius:18px;padding:18px 20px}}
    .hero-top{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
    .badge{{display:flex;align-items:center;background:#0f8a70;color:#fff;
            font-size:16px;font-weight:800;letter-spacing:.08em;
            padding:0 16px;border-radius:12px;height:40px;white-space:nowrap}}
    .hero h1{{font-size:20px;font-weight:700;line-height:1.2;margin-bottom:4px;text-align:center}}
    .hero p{{font-size:13px;color:#5e7077;text-align:center}}
    /* Cards */
    .card{{background:#fff;border:1px solid #ddd6cc;border-radius:14px;padding:14px 16px}}
    .card h2{{font-size:14px;font-weight:600;margin-bottom:10px;color:#1d2a2e}}
    /* Definition list */
    dl{{display:grid;grid-template-columns:auto 1fr;gap:7px 14px;align-items:center}}
    dt{{font-size:12px;color:#607079;white-space:nowrap}}
    dd{{font-size:13px}}
    .mono{{font-family:ui-monospace,"SFMono-Regular",Consolas,monospace;word-break:break-all}}
    /* Copy row */
    .cr{{display:flex;align-items:center;gap:8px}}
    .cbtn{{background:none;border:1px solid #ddd6cc;border-radius:7px;
           padding:2px 9px;font-size:11px;cursor:pointer;color:#0f8a70;white-space:nowrap}}
    .cbtn:active{{background:#e2f4ef}}
    /* Tables */
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{text-align:left;font-size:11px;font-weight:600;color:#607079;
        padding:0 0 7px;border-bottom:1px solid #ddd6cc}}
    td{{padding:7px 0;border-bottom:1px solid #f0ebe4;vertical-align:middle}}
    tr:last-child td{{border-bottom:none}}
    .role{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
           color:#607079;padding-right:10px;white-space:nowrap}}
    .iname{{padding-right:10px;color:#3d5059}}
    /* Portal card */
    .portal{{border-color:#f8d9b3}}
    .portal h2 span{{color:#f28f3b;font-size:11px;font-weight:400;margin-left:6px}}
    fieldset{{border:1px solid #ddd6cc;border-radius:10px;
              padding:10px 12px;margin-top:8px;opacity:.6}}
    legend{{font-size:11px;color:#607079;padding:0 5px}}
    .fld{{display:flex;flex-direction:column;gap:7px}}
    .fld label{{font-size:12px;color:#607079;display:flex;flex-direction:column;gap:3px}}
    .fld input{{border:1px solid #ddd6cc;border-radius:7px;
                padding:7px 10px;font-size:13px;background:#f9f7f5;width:100%}}
    .sbtn{{background:#0f8a70;color:#fff;border:none;border-radius:9px;
           padding:9px;font-size:14px;width:100%;margin-top:8px;opacity:.45;cursor:not-allowed}}
    .footer{{text-align:center;font-size:11px;color:#8a979c;padding:2px 0 6px}}
    a{{color:#0f8a70;text-decoration:none}}
  </style>
</head>
<body>
<div class="page">

  <div class="hero">
    <div class="hero-top">
      <div class="badge">BMI30</div>
      {logo_html}
    </div>
    <h1>{hostname}</h1>
    <p>IM Mark Detection System</p>
  </div>

  <div class="card">
        <h2>Wi-Fi Network</h2>
    <dl>
            <dt>SSID</dt>
      <dd class="mono">{ssid}</dd>
            <dt>Hotspot IP</dt>
      <dd class="mono">{hotspot_ip}</dd>
            <dt>Sync Mode</dt>
            <dd class="mono">{sync_mode} <span style="color:#607079">({sync_src})</span></dd>
            <dt>Device Link</dt>
            <dd>{'online' if sync_ok else '---'}</dd>
    </dl>
  </div>

  <div class="card">
        <h2>Remote Access</h2>
        <p style="font-size:12px;color:#607079;margin-bottom:8px">Current access path: {access_role} via {access_ip}</p>
    <table>
            <tr><th>Method</th><th>Address / command</th></tr>
      <tr>
        <td>SSH</td>
                <td class="mono">ssh {ssh_user}@{access_ip}</td>
      </tr>
      <tr>
        <td>RDP</td>
                <td class="mono">{access_ip}:{rdp_port}</td>
      </tr>
      <tr>
                <td>Web</td>
                <td><a href="http://{access_ip}/">http://{access_ip}/</a></td>
      </tr>
    </table>
  </div>

  <div class="card">
        <h2>Device Network Addresses</h2>
    <table>
            <tr><th>Type</th><th>Interface</th><th>IP Address</th></tr>
      {iface_table}
    </table>
  </div>

  <div class="card portal">
        <h2>Management Portal <span>(coming soon)</span></h2>
    <p style="font-size:13px;color:#607079;margin-bottom:2px">
            Authentication for advanced device management features.
    </p>
    <fieldset disabled>
            <legend>Sign in</legend>
      <div class="fld">
                <label>Username<input type="text" placeholder="admin"></label>
                <label>Password<input type="password" placeholder="••••••••"></label>
      </div>
            <button class="sbtn" disabled>Sign In</button>
    </fieldset>
  </div>

  <div style="text-align:center;padding:4px 0 2px">
    <a href="/portal-done" style="display:inline-block;background:#0f8a70;color:#fff;text-decoration:none;
       border-radius:10px;padding:10px 32px;font-size:14px;font-weight:600;">Continue</a>
  </div>

    <p class="footer">Updated: {generated} · auto-refresh {REFRESH_S}&#x202f;s
        &nbsp;·&nbsp; <a href="/api/status">JSON API</a></p>

</div>
</body>
</html>
"""
    return body.encode("utf-8")


class HotspotInfoHandler(BaseHTTPRequestHandler):
    server_version = "BMI30HotspotInfo/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _handle_request(self, send_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        preferred_ip = extract_request_host_ip(self.headers.get("Host", ""))

        # Android CNA: пользователь нажал "Continue" → отдаём 204, браузер закрывается
        if path == "/portal-done":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if path == "/logo":
            logo = load_logo_bytes(detect_logo_path())
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
            data = collect_remote_access_targets(preferred_ip=preferred_ip)
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        # Connectivity-probe.
        # Для iOS/macOS надёжнее отдать HTML напрямую на probe URL,
        # чем редиректить на другой адрес. Аналогично это корректно работает
        # и для Android/Windows/Linux: ответ отличается от ожидаемого "internet ok",
        # поэтому ОС помечает сеть как captive portal и показывает страницу входа.
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
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/login")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HotspotInfoHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()