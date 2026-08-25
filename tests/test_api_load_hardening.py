import importlib.util
import json
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

import hotspot_info_server as portal


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "host" / "BMI30.001.py.2026-08-25-1221"


def _load_source(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class _BusyLock:
    def __init__(self) -> None:
        self.timeouts: list[float] = []
        self.release_count = 0

    def acquire(self, *, timeout: float) -> bool:
        self.timeouts.append(float(timeout))
        return False

    def release(self) -> None:
        self.release_count += 1


class _NumGroup:
    @staticmethod
    def checkedId() -> int:
        return 6


class _Scope:
    def __init__(self, data_lock: _BusyLock) -> None:
        self.data_lock = data_lock
        self.num_group = _NumGroup()
        self.stream = None
        self.last_frame_t = 123.5


class _BrokenWriter:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def write(self, _data: bytes) -> None:
        raise self.error


class _FakeHandler:
    def __init__(self, error: Exception, fail_headers: bool = False) -> None:
        self.wfile = _BrokenWriter(error)
        self.error = error
        self.fail_headers = fail_headers
        self.close_connection = False

    def send_response(self, _status) -> None:
        if self.fail_headers:
            raise self.error

    def send_header(self, _name: str, _value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


class ScopeApiLoadHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = _load_source("bmi30_core_api_load_test", CORE_PATH)

    def _api(self, lock: _BusyLock):
        api = object.__new__(self.core.ScopeApi)
        api.scope = _Scope(lock)
        api._status_cache = {
            "ok": True,
            "mode": {"selected": 6, "base_buf_len": 200},
            "connection": {"connected": True},
            "detector": {"fire_seq0": 9},
        }
        return api

    def test_busy_data_lock_never_blocks_or_releases_unowned_lock(self) -> None:
        lock = _BusyLock()
        api = self._api(lock)

        status = api.status()
        frame = api.frame()
        binary = api.frame_binary()
        header_length = int.from_bytes(binary[4:8], "little")
        binary_header = json.loads(binary[8:8 + header_length].decode("utf-8"))

        self.assertTrue(status["ok"])
        self.assertTrue(status["busy"])
        self.assertTrue(status["stale"])
        self.assertEqual(status["detector"]["fire_seq0"], 9)
        for payload in (frame, binary_header):
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["busy"])
            self.assertTrue(payload["not_modified"])
            self.assertFalse(payload["available"])
            self.assertEqual(payload["last_frame_t"], 123.5)
        self.assertEqual(lock.release_count, 0)
        self.assertEqual(len(lock.timeouts), 3)
        self.assertTrue(all(0.0 <= timeout <= 0.100 for timeout in lock.timeouts))

    def test_disconnected_clients_are_quiet_for_json_and_binary(self) -> None:
        json_handler = _FakeHandler(BrokenPipeError("gone"))
        binary_handler = _FakeHandler(ConnectionResetError("reset"), fail_headers=True)

        self.core._send_json(json_handler, {"ok": True})
        self.core._send_binary(binary_handler, b"frame")

        self.assertTrue(json_handler.close_connection)
        self.assertTrue(binary_handler.close_connection)

    def test_browser_polling_is_500ms_serial_and_guarded(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("refreshTimer=setInterval(refresh,500)", source)
        self.assertIn("leavingPage||refreshInFlight||document.hidden", source)
        self.assertNotIn("Promise.all([status,fetchFrame(opts)])", source)

    def test_buffer_rate_is_fixed_at_200_and_has_no_web_selector(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        engine = (ROOT / "host" / "BMI30.200.py.2026-08-25-1221").read_text(encoding="utf-8")
        remote_gui = (ROOT / "host" / "BMI30.GUI.001.py").read_text(encoding="utf-8")

        self.assertIn('requested != 200', source)
        self.assertIn('BMI30 buffer rate is fixed at 200 Hz', source)
        self.assertNotIn('id="freqSel"', source)
        self.assertNotIn('function sendFreq()', source)
        self.assertIn('FIXED_BUFFER_RATE_HZ = 200', engine)
        self.assertNotIn('self.freq_box =', engine)
        self.assertNotIn('self.freq_box =', remote_gui)


class PortalRemoteStatusCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        portal._invalidate_remote_access_targets_cache()

    def tearDown(self) -> None:
        portal._invalidate_remote_access_targets_cache()

    @staticmethod
    def _snapshot() -> dict:
        return {
            "generated_at": "now",
            "access": {
                "ip": "10.42.0.1",
                "role": "hotspot",
                "interface": "wlan0ap",
                "web_url": "http://10.42.0.1/",
            },
            "interfaces": [
                {"ip": "10.42.0.1", "role": "hotspot", "iface": "wlan0ap"},
                {"ip": "192.168.1.5", "role": "ethernet", "iface": "eth0"},
            ],
            "services": {"web_scheme": "http"},
        }

    def test_cache_is_shared_across_clients_and_returns_independent_payloads(self) -> None:
        calls = 0

        def collect() -> dict:
            nonlocal calls
            calls += 1
            return self._snapshot()

        with mock.patch.object(portal, "_collect_remote_access_targets_uncached", side_effect=collect):
            ethernet = portal.collect_remote_access_targets("192.168.1.5")
            hotspot = portal.collect_remote_access_targets("10.42.0.1")
            ethernet["interfaces"].clear()
            again = portal.collect_remote_access_targets("192.168.1.5")

        self.assertEqual(calls, 1)
        self.assertEqual(ethernet["access"]["interface"], "eth0")
        self.assertEqual(hotspot["access"]["interface"], "wlan0ap")
        self.assertEqual(len(again["interfaces"]), 2)

    def test_expired_refresh_is_single_flight(self) -> None:
        calls = 0
        calls_lock = threading.Lock()

        def collect() -> dict:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            return self._snapshot()

        with mock.patch.object(portal, "_collect_remote_access_targets_uncached", side_effect=collect):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(portal.collect_remote_access_targets, [None] * 8))

        self.assertEqual(calls, 1)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result["access"]["ip"] == "10.42.0.1" for result in results))

    def test_explicit_invalidation_forces_new_collection(self) -> None:
        calls = 0

        def collect() -> dict:
            nonlocal calls
            calls += 1
            return self._snapshot()

        with mock.patch.object(portal, "_collect_remote_access_targets_uncached", side_effect=collect):
            portal.collect_remote_access_targets()
            portal._invalidate_remote_access_targets_cache()
            portal.collect_remote_access_targets()

        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
