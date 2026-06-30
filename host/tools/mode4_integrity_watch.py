#!/usr/bin/env python3
"""Long-running mode 4 integrity watcher for the BMI30 split web service.

The watcher uses only the service HTTP API:
  - POST /api/command set_mode idx=4
  - GET  /api/status
  - GET  /api/frame.bin

It does not smooth, drop, or modify data. It records suspicious in-frame
mid-scale jumps in the same arrays that the web oscilloscope renders.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:8765"
OSC_ARRAYS = ("data0_even", "data0_odd", "data1_even", "data1_odd")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_line(fp, obj: dict[str, Any]) -> None:
    fp.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    fp.flush()


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 2.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _http_bytes(url: str, timeout: float = 2.0) -> bytes:
    req = Request(url, headers={"Accept": "application/octet-stream"}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_status(base_url: str) -> dict[str, Any]:
    return _http_json("GET", base_url.rstrip("/") + "/api/status")


def _post_command(base_url: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _http_json("POST", base_url.rstrip("/") + "/api/command", {"action": action, "params": params or {}})


def _parse_frame_bin(data: bytes) -> tuple[dict[str, Any], dict[str, list[int]]]:
    if len(data) < 8 or data[:4] != b"BMF1":
        raise ValueError("bad BMF1 frame")
    header_len = int.from_bytes(data[4:8], "little")
    header_end = 8 + header_len
    if header_end > len(data):
        raise ValueError("truncated BMF1 header")
    header = json.loads(data[8:header_end].decode("utf-8"))
    offset = (header_end + 1) & ~1
    count = int(header.get("count") or 0)
    arrays: dict[str, list[int]] = {}
    if not header.get("available") or count <= 0:
        return header, arrays
    for name in header.get("arrays") or []:
        size = count * 2
        payload = data[offset:offset + size]
        offset += size
        if len(payload) != size:
            break
        if name in OSC_ARRAYS:
            arrays[str(name)] = list(struct.unpack("<" + ("H" * count), payload))
    return header, arrays


def _get_frame_bin(base_url: str, max_points: int, since: float) -> tuple[dict[str, Any], dict[str, list[int]]]:
    query = urlencode({"max_points": int(max_points), "channels": "both", "since": repr(float(since))})
    data = _http_bytes(base_url.rstrip("/") + "/api/frame.bin?" + query)
    return _parse_frame_bin(data)


def _status_counter(status: dict[str, Any], key: str) -> int:
    try:
        return int(((status.get("stream_stats") or {}).get(key)) or 0)
    except Exception:
        return 0


def _status_mode(status: dict[str, Any]) -> dict[str, int]:
    mode = status.get("mode") or {}
    return {
        "selected": int(mode.get("selected") or 0),
        "stream_mode": int(mode.get("stream_mode") or 0),
        "base_buf_len": int(mode.get("base_buf_len") or 0),
        "avg_n": int(mode.get("avg_n") or 0),
    }


def _find_jumps(
    values: list[int],
    jump_threshold: int,
    mid_min: int,
    mid_max: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for idx in range(0, max(0, len(values) - 1)):
        prev_v = int(values[idx])
        curr_v = int(values[idx + 1])
        jump = curr_v - prev_v
        if abs(jump) < jump_threshold:
            continue
        if not (mid_min < prev_v < mid_max and mid_min < curr_v < mid_max):
            continue
        lo = max(0, idx - 8)
        hi = min(len(values), idx + 9)
        events.append(
            {
                "idx": idx,
                "prev": prev_v,
                "curr": curr_v,
                "jump": jump,
                "window_start": lo,
                "window": [int(x) for x in values[lo:hi]],
            }
        )
    if len(events) <= 1:
        return events
    events.sort(key=lambda e: abs(int(e["jump"])), reverse=True)
    return events[:1]


def _wait_for_mode4(base_url: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, timeout_s)
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = _get_status(base_url)
        mode = _status_mode(last_status)
        conn = last_status.get("connection") or {}
        if conn.get("connected") and mode["selected"] == 4 and mode["stream_mode"] == 1 and mode["base_buf_len"] == 200:
            return last_status
        time.sleep(0.25)
    return last_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch BMI30 mode 4 oscilloscope frames for in-frame jumps.")
    parser.add_argument("--url", default=os.getenv("BMI30_SERVICE_URL", DEFAULT_URL))
    parser.add_argument("--duration-min", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.20)
    parser.add_argument("--progress-sec", type=float, default=10.0)
    parser.add_argument("--max-points", type=int, default=4096)
    parser.add_argument("--jump-threshold", type=int, default=7000)
    parser.add_argument("--mid-min", type=int, default=8000)
    parser.add_argument("--mid-max", type=int, default=57000)
    parser.add_argument("--out", default="")
    parser.add_argument("--no-set-mode", action="store_true")
    args = parser.parse_args()

    base_url = str(args.url).rstrip("/")
    duration_s = max(1.0, float(args.duration_min) * 60.0)
    interval_s = max(0.05, float(args.interval))
    progress_s = max(1.0, float(args.progress_sec))

    if args.out:
        out_path = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("test_logs") / f"mode4_integrity_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not args.no_set_mode:
            _post_command(base_url, "set_mode", {"idx": 4})
        status0 = _wait_for_mode4(base_url, timeout_s=10.0)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f"failed to contact {base_url}: {exc}", file=sys.stderr)
        return 2

    mode0 = _status_mode(status0)
    if mode0["selected"] != 4 or mode0["stream_mode"] != 1 or mode0["base_buf_len"] != 200:
        print(f"warning: service is not confirmed in mode 4: {mode0}", file=sys.stderr)

    base_counters = {
        "crc_bad": _status_counter(status0, "crc_bad"),
        "magic_bad": _status_counter(status0, "magic_bad"),
        "seq_gap_ch0": _status_counter(status0, "seq_gap_ch0"),
        "seq_gap_ch1": _status_counter(status0, "seq_gap_ch1"),
        "seq_dup_ch0": _status_counter(status0, "seq_dup_ch0"),
        "seq_dup_ch1": _status_counter(status0, "seq_dup_ch1"),
    }
    base_engine_integrity = int(((status0.get("frame_integrity") or {}).get("count")) or 0)

    summary: dict[str, Any] = {
        "started_at": _now_iso(),
        "base_url": base_url,
        "duration_s": duration_s,
        "mode_start": mode0,
        "baseline_counters": base_counters,
        "baseline_frame_integrity_count": base_engine_integrity,
        "frames_seen": 0,
        "status_samples": 0,
        "jumps": 0,
        "jumps_by_array": {name: 0 for name in OSC_ARRAYS},
        "max_abs_jump": 0,
        "max_jump_event": None,
        "http_errors": 0,
    }

    last_frame_t = 0.0
    last_status_t = 0.0
    last_progress_t = 0.0
    last_engine_integrity = base_engine_integrity
    t0 = time.monotonic()

    print(f"mode4 watch started: {out_path} duration={duration_s:.0f}s interval={interval_s:.2f}s")
    with out_path.open("a", encoding="utf-8") as fp:
        _json_line(fp, {"type": "start", **summary})
        while True:
            now_m = time.monotonic()
            elapsed = now_m - t0
            if elapsed >= duration_s:
                break

            status: dict[str, Any] | None = None
            try:
                if now_m - last_status_t >= 1.0:
                    status = _get_status(base_url)
                    summary["status_samples"] += 1
                    last_status_t = now_m
                    fi = status.get("frame_integrity") or {}
                    fi_count = int(fi.get("count") or 0)
                    if fi_count != last_engine_integrity:
                        _json_line(
                            fp,
                            {
                                "type": "engine_frame_integrity",
                                "ts": _now_iso(),
                                "elapsed_s": round(elapsed, 3),
                                "count": fi_count,
                                "delta": fi_count - last_engine_integrity,
                                "last": fi.get("last"),
                            },
                        )
                        last_engine_integrity = fi_count

                header, arrays = _get_frame_bin(base_url, int(args.max_points), last_frame_t)
                if header.get("not_modified") or not header.get("available"):
                    time.sleep(interval_s)
                    continue
                last_frame_t = float(header.get("last_frame_t") or last_frame_t)
                summary["frames_seen"] += 1
                for name, values in arrays.items():
                    for jump_event in _find_jumps(values, int(args.jump_threshold), int(args.mid_min), int(args.mid_max)):
                        event = {
                            "type": "jump",
                            "ts": _now_iso(),
                            "elapsed_s": round(elapsed, 3),
                            "frame_t": last_frame_t,
                            "array": name,
                            "base_buf_len": int(header.get("base_buf_len") or 0),
                            "step": int(header.get("step") or 0),
                            **jump_event,
                        }
                        if status is not None:
                            event["mode"] = _status_mode(status)
                            event["frames"] = status.get("frames")
                            event["stream_stats"] = status.get("stream_stats")
                        _json_line(fp, event)
                        summary["jumps"] += 1
                        summary["jumps_by_array"][name] = int(summary["jumps_by_array"].get(name, 0)) + 1
                        if abs(int(jump_event["jump"])) > int(summary["max_abs_jump"]):
                            summary["max_abs_jump"] = abs(int(jump_event["jump"]))
                            summary["max_jump_event"] = event

                if now_m - last_progress_t >= progress_s:
                    last_progress_t = now_m
                    print(
                        f"{elapsed:7.1f}s frames={summary['frames_seen']} jumps={summary['jumps']} "
                        f"engine_fi={last_engine_integrity} http_errors={summary['http_errors']}",
                        flush=True,
                    )
                time.sleep(interval_s)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                summary["http_errors"] += 1
                _json_line(fp, {"type": "error", "ts": _now_iso(), "elapsed_s": round(elapsed, 3), "error": str(exc)})
                time.sleep(min(1.0, interval_s * 2.0))

        try:
            status1 = _get_status(base_url)
        except Exception:
            status1 = {}
        final_counters = {
            "crc_bad": _status_counter(status1, "crc_bad"),
            "magic_bad": _status_counter(status1, "magic_bad"),
            "seq_gap_ch0": _status_counter(status1, "seq_gap_ch0"),
            "seq_gap_ch1": _status_counter(status1, "seq_gap_ch1"),
            "seq_dup_ch0": _status_counter(status1, "seq_dup_ch0"),
            "seq_dup_ch1": _status_counter(status1, "seq_dup_ch1"),
        }
        summary["finished_at"] = _now_iso()
        summary["mode_final"] = _status_mode(status1) if status1 else None
        summary["final_counters"] = final_counters
        summary["counter_delta"] = {k: int(final_counters.get(k, 0)) - int(base_counters.get(k, 0)) for k in base_counters}
        summary["final_frame_integrity_count"] = int(((status1.get("frame_integrity") or {}).get("count")) or 0) if status1 else None
        _json_line(fp, {"type": "summary", **summary})

    print(json.dumps({"summary": summary, "log": str(out_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
