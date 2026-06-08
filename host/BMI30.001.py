#!/usr/bin/env python3
"""BMI30 core service v001.

Headless service entrypoint for the current BMI30 engine.  The service keeps the
existing ScopeWindow core alive in Qt offscreen mode and exposes a small local
HTTP API for GUI and portal clients.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import queue
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np  # type: ignore


SERVICE_VERSION = "001"
HOST_DIR = Path(__file__).resolve().parent
REPO_DIR = HOST_DIR.parent
DEFAULT_ENGINE_FILE = HOST_DIR / "BMI30.200.py.2026-06-08-realtime-prevbuf"
ENGINE_FILE = Path(os.getenv("BMI30_ENGINE_SOURCE", str(DEFAULT_ENGINE_FILE))).expanduser()
API_HOST = os.getenv("BMI30_SERVICE_HOST", "127.0.0.1")
API_PORT = int(os.getenv("BMI30_SERVICE_PORT", "8765"))


def _load_engine_module(path: Path):
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"BMI30 engine source not found: {path}")
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    loader = SourceFileLoader("bmi30_engine_current", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Cannot load BMI30 engine source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _text_from_label(label: Any) -> str:
    try:
        return str(label.text())
    except Exception:
        return ""


class ScopeApi:
    def __init__(self, scope: Any, qtcore: Any):
        self.scope = scope
        self.qtcore = qtcore
        self.commands: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._timer = qtcore.QTimer()
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._drain_commands)
        self._timer.start()

    def submit(self, action: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
        item: dict[str, Any] = {
            "action": str(action),
            "params": dict(params or {}),
            "event": threading.Event(),
            "result": None,
        }
        self.commands.put(item)
        if not item["event"].wait(max(0.1, float(timeout))):
            return {"ok": False, "error": "command timeout", "action": action}
        result = item.get("result")
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "empty command result", "action": action}

    def _drain_commands(self) -> None:
        while True:
            try:
                item = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                item["result"] = self._execute(str(item.get("action") or ""), dict(item.get("params") or {}))
            except Exception as exc:
                item["result"] = {"ok": False, "error": str(exc), "trace": traceback.format_exc(limit=5)}
            finally:
                try:
                    item["event"].set()
                except Exception:
                    pass

    def _execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        scope = self.scope
        action = action.strip().lower()
        if action in {"mode", "set_mode"}:
            idx = int(params.get("idx", params.get("mode", 0)))
            if idx < 0 or idx > 7:
                raise ValueError("mode must be 0..7")
            btn = scope.num_group.button(idx)
            if btn is not None:
                btn.setChecked(True)
            scope._num_clicked(idx)
            try:
                scope._on_num_clicked_extra(idx)
            except Exception:
                pass
            return {"ok": True, "mode": idx}
        if action in {"start", "connect"}:
            scope._activate_stream()
            return {"ok": True, "action": action}
        if action in {"stop", "disconnect"}:
            btn = scope.num_group.button(0)
            if btn is not None:
                btn.setChecked(True)
            scope._num_clicked(0)
            return {"ok": True, "mode": 0}
        if action in {"frequency", "freq", "set_freq"}:
            freq = int(params.get("hz", params.get("freq", 200)))
            scope._on_freq_change(f"{freq} Hz")
            try:
                scope.freq_box.setCurrentText(f"{freq} Hz")
            except Exception:
                pass
            return {"ok": True, "freq_hz": freq}
        if action in {"avg", "avg_n", "set_avg"}:
            avg_n = int(params.get("avg_n", params.get("n", 24)))
            scope.avg_n = avg_n
            try:
                scope.avg_box.setCurrentText(str(avg_n))
            except Exception:
                pass
            scope._on_avg_change(0)
            return {"ok": True, "avg_n": avg_n}
        if action in {"det_ratio", "ratio", "set_det_ratio"}:
            val = float(params.get("value", params.get("ratio", 2.0)))
            scope._on_det_ratio_change(f"{val:.1f}")
            try:
                scope.det_ratio_box.setCurrentText(f"{val:.1f}")
            except Exception:
                pass
            return {"ok": True, "det_ratio": float(getattr(scope, "_det_ratio", val))}
        if action in {"tim2", "tx", "set_tim2"}:
            enabled = bool(params.get("enabled", params.get("value", True)))
            try:
                scope.btn_tim2.setChecked(enabled)
            except Exception:
                pass
            scope._on_toggle_tim2(enabled)
            return {"ok": True, "tim2_enabled": enabled}
        if action in {"sound", "set_sound"}:
            enabled = bool(params.get("enabled", params.get("value", True)))
            scope._set_sound_enabled(enabled, reason="api", announce=True)
            return {"ok": True, "sound_enabled": enabled}
        if action in {"reconnect", "restart"}:
            scope._manual_reconnect()
            return {"ok": True, "action": action}
        if action in {"reset_detector", "det_reset"}:
            scope._reset_det_adapt()
            return {"ok": True, "action": action}
        if action == "dc_config":
            stream = getattr(scope, "stream", None)
            if stream is None:
                raise RuntimeError("stream is not connected")
            if not hasattr(stream, "set_dc_config_seconds"):
                raise RuntimeError("stream does not support set_dc_config_seconds")
            stream.set_dc_config_seconds(
                mode=int(params.get("mode", 1)),
                work_settle_s=float(params.get("work_settle_s", 900.0)),
                detect_settle_s=float(params.get("detect_settle_s", params.get("detect_initial_settle_s", 30.0))),
                fast_settle_s=float(params.get("fast_settle_s", 5.0)),
                fast_duration_s=float(params.get("fast_duration_s", 30.0)),
            )
            return {"ok": True, "action": action}
        raise ValueError(f"unknown action: {action}")

    def status(self) -> dict[str, Any]:
        scope = self.scope
        stream = getattr(scope, "stream", None)
        connected = bool(stream is not None and not bool(getattr(stream, "disconnected", False)))
        try:
            selected_mode = int(scope.num_group.checkedId())
        except Exception:
            selected_mode = 0
        try:
            data_lock = getattr(scope, "data_lock", None)
            if data_lock is not None:
                data_lock.acquire()
            base_len = int(getattr(scope, "base_buf_len", 0) or 0)
            frame_ts = float(getattr(scope, "last_frame_t", 0.0) or 0.0)
            seq0_even = getattr(scope, "seq0_even", None)
            seq0_odd = getattr(scope, "seq0_odd", None)
            seq1_even = getattr(scope, "seq1_even", None)
            seq1_odd = getattr(scope, "seq1_odd", None)
        finally:
            try:
                if data_lock is not None:
                    data_lock.release()
            except Exception:
                pass
        stream_stats: dict[str, Any] = {}
        if stream is not None:
            for key in (
                "rx_cnt_ch0",
                "rx_cnt_ch1",
                "seq_gap_ch0",
                "seq_gap_ch1",
                "seq_dup_ch0",
                "seq_dup_ch1",
                "crc_bad",
                "magic_bad",
                "host_rx_ack_fail",
            ):
                try:
                    stream_stats[key] = int(getattr(stream, key, 0) or 0)
                except Exception:
                    stream_stats[key] = 0
            try:
                stream_stats["queues"] = stream.get_buffer_depths()
            except Exception:
                stream_stats["queues"] = {}
        now = time.time()
        last_age = (now - frame_ts) if frame_ts > 0 else None
        return _json_safe(
            {
                "ok": True,
                "service": {"version": SERVICE_VERSION, "engine_source": str(ENGINE_FILE), "uptime_s": now - START_T},
                "connection": {
                    "connected": connected,
                    "connecting": bool(getattr(scope, "_connecting", False)),
                    "disconnected": bool(getattr(stream, "disconnected", False)) if stream is not None else False,
                    "last_frame_age_s": last_age,
                },
                "mode": {
                    "selected": selected_mode,
                    "stream_mode": int(getattr(scope, "stream_mode", 0) or 0),
                    "view_mode": int(getattr(scope, "view_mode", 0) or 0),
                    "base_buf_len": base_len,
                    "freq_hz": int(getattr(scope, "freq_hz", 0) or getattr(scope, "desired_freq", 0) or 0),
                    "desired_freq": int(getattr(scope, "desired_freq", 0) or 0),
                    "avg_n": int(getattr(scope, "avg_n", 0) or 0),
                    "det_ratio": float(getattr(scope, "_det_ratio", 0.0) or 0.0),
                },
                "tim2": {
                    "enabled": bool(getattr(scope, "tim2_enabled", False)),
                    "applied": bool(getattr(scope, "tim2_applied", False)),
                    "pending": bool(getattr(scope, "tim2_pending", False)),
                },
                "sound": {"enabled": bool(getattr(scope, "_sound_enabled", False))},
                "detector": {
                    "enabled": bool(getattr(scope, "_det_enabled", False)),
                    "active": bool(getattr(scope, "_rt_detection_mode_enabled", False)),
                    "thr0": int(getattr(scope, "_det_thr0", 0) or 0),
                    "thr1": int(getattr(scope, "_det_thr1", 0) or 0),
                    "lvl0": int(getattr(scope, "_det_last_lvl0", 0) or 0),
                    "lvl1": int(getattr(scope, "_det_last_lvl1", 0) or 0),
                    "hold0": bool(getattr(scope, "_det_hold0", False)),
                    "hold1": bool(getattr(scope, "_det_hold1", False)),
                    "frozen": bool(getattr(scope, "_det_dc_frozen", False)),
                },
                "frames": {
                    "seq0_even": seq0_even,
                    "seq0_odd": seq0_odd,
                    "seq1_even": seq1_even,
                    "seq1_odd": seq1_odd,
                    "last_frame_t": frame_ts,
                },
                "fps": {
                    "a": float(getattr(scope, "afps", 0.0) or 0.0),
                    "b": float(getattr(scope, "bfps", 0.0) or 0.0),
                    "a_even": float(getattr(scope, "afps_even", 0.0) or 0.0),
                    "a_odd": float(getattr(scope, "afps_odd", 0.0) or 0.0),
                    "b_even": float(getattr(scope, "bfps_even", 0.0) or 0.0),
                    "b_odd": float(getattr(scope, "bfps_odd", 0.0) or 0.0),
                },
                "stream_stats": stream_stats,
                "status_text": _text_from_label(getattr(scope, "legend_lbl", None)),
            }
        )

    def frame(self, max_points: int = 600) -> dict[str, Any]:
        scope = self.scope
        max_points = max(16, min(4096, int(max_points)))
        data_lock = getattr(scope, "data_lock", None)
        try:
            if data_lock is not None:
                data_lock.acquire()
            n = int(getattr(scope, "base_buf_len", 0) or 0)
            if n <= 0:
                return {"ok": True, "available": False, "base_buf_len": 0}
            n = min(n, int(getattr(scope, "max_samples", n) or n))
            step = max(1, int(np.ceil(float(n) / float(max_points))))

            def _arr(name: str) -> list[int]:
                arr = getattr(scope, name, None)
                if arr is None:
                    return []
                try:
                    return np.asarray(arr[:n:step], dtype=np.uint16).astype(int).tolist()
                except Exception:
                    return []

            x = list(range(0, n, step))
            return {
                "ok": True,
                "available": True,
                "base_buf_len": n,
                "step": step,
                "x": x,
                "data0_even": _arr("data0_even"),
                "data0_odd": _arr("data0_odd"),
                "data1_even": _arr("data1_even"),
                "data1_odd": _arr("data1_odd"),
                "last_frame_t": float(getattr(scope, "last_frame_t", 0.0) or 0.0),
            }
        finally:
            try:
                if data_lock is not None:
                    data_lock.release()
            except Exception:
                pass


START_T = time.time()
API: ScopeApi | None = None


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(_json_safe(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class ServiceHandler(BaseHTTPRequestHandler):
    server_version = "BMI30CoreService/001"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("BMI30_SERVICE_HTTP_LOG", "0").lower() in {"1", "true", "yes", "on"}:
            super().log_message(fmt, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        api = API
        if api is None:
            _send_json(self, {"ok": False, "error": "service not ready"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed.path in {"/", "/index.html"}:
            html = SERVICE_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if parsed.path in {"/health", "/api/health"}:
            _send_json(self, {"ok": True, "service": "BMI30", "version": SERVICE_VERSION})
            return
        if parsed.path == "/api/status":
            _send_json(self, api.status())
            return
        if parsed.path == "/api/frame":
            query = parse_qs(parsed.query)
            max_points = int((query.get("max_points") or ["600"])[0])
            _send_json(self, api.frame(max_points=max_points))
            return
        _send_json(self, {"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        api = API
        if api is None:
            _send_json(self, {"ok": False, "error": "service not ready"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed.path != "/api/command":
            _send_json(self, {"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(min(length, 1024 * 1024))
            payload = json.loads(raw.decode("utf-8") or "{}") if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
            action = str(payload.get("action") or "")
            params = payload.get("params")
            if not isinstance(params, dict):
                params = {k: v for k, v in payload.items() if k not in {"action", "params"}}
            if not action:
                raise ValueError("missing action")
            _send_json(self, api.submit(action, params))
        except Exception as exc:
            _send_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


SERVICE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>BMI30 Service</title>
<style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.45}button{margin:3px;padding:8px 12px}pre{background:#111;color:#eee;padding:12px;overflow:auto}</style></head>
<body><h1>BMI30 Service</h1><div id="buttons"></div><pre id="status">loading...</pre>
<script>
function cmd(action, params){return fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action,params:params||{}})}).then(r=>r.json()).then(refresh)}
var b=document.getElementById('buttons');
[0,1,2,3,4,5,6,7].forEach(function(i){var x=document.createElement('button');x.textContent='Mode '+i;x.onclick=function(){cmd('mode',{idx:i})};b.appendChild(x)});
['start','stop','reconnect','reset_detector'].forEach(function(a){var x=document.createElement('button');x.textContent=a;x.onclick=function(){cmd(a,{})};b.appendChild(x)});
function refresh(){fetch('/api/status').then(r=>r.json()).then(j=>{document.getElementById('status').textContent=JSON.stringify(j,null,2)}).catch(e=>{document.getElementById('status').textContent=String(e)})}
refresh();setInterval(refresh,1000);
</script></body></html>"""


def start_http_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((API_HOST, API_PORT), ServiceHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print(f"[BMI30.001] API listening on http://{API_HOST}:{API_PORT}", flush=True)
    return server


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("BMI30_SERVICE_MODE", "1")
    os.chdir(str(REPO_DIR))
    engine = _load_engine_module(ENGINE_FILE)
    if getattr(engine, "PG_IMPORT_ERR", None):
        print(f"[BMI30.001] engine Qt import failed: {engine.PG_IMPORT_ERR}", flush=True)
        return 2
    scope = engine.ScopeWindow()
    try:
        scope.win.hide()
        scope.win.setWindowTitle(f"BMI30 core service {SERVICE_VERSION}")
    except Exception:
        pass
    global API
    API = ScopeApi(scope, engine.QtCore)
    server = start_http_server()
    try:
        engine.QtCore.QTimer.singleShot(20, scope._run_deferred_autostart)
    except Exception:
        scope._run_deferred_autostart()
    app = engine.QtWidgets.QApplication.instance()
    try:
        if hasattr(app, "exec_"):
            app.exec_()
        else:
            app.exec()
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            scope._rt_detector_process_stop()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
