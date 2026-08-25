import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))

from usb_vendor.usb_stream import USBStream  # noqa: E402


class DeviceStateCacheWriterTests(unittest.TestCase):
    def _state(self, interval: float = 0.04):
        state = USBStream.__new__(USBStream)
        state.device_state_cache = {}
        state._init_device_state_cache_writer()
        # Production is clamped to 0.5..1.0 s.  Focused tests shorten the
        # already-initialised interval while exercising identical scheduling.
        state._device_state_cache_write_interval_s = float(interval)
        return state

    @staticmethod
    def _wait_until(predicate, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return bool(predicate())

    def test_blocked_persistence_does_not_block_publish_and_final_state_is_flushed(self) -> None:
        state = self._state()
        entered = threading.Event()
        release = threading.Event()
        snapshots = []

        def persist(payload: dict) -> bool:
            snapshots.append(copy.deepcopy(payload))
            if len(snapshots) == 1:
                entered.set()
                release.wait(timeout=1.0)
            return True

        state._persist_device_state_snapshot = persist
        self.assertTrue(state._start_device_state_cache_writer())
        self.assertTrue(state._write_device_state_cache({"source": "bulk_stat", "stat": {"seq": 1}}))
        self.assertTrue(entered.wait(timeout=0.5))

        started = time.monotonic()
        self.assertTrue(state._write_device_state_cache({"rs485": {"node": 7}}))
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.2)
        self.assertEqual(state.device_state_cache["rs485"]["node"], 7)

        release.set()
        self.assertTrue(state._stop_device_state_cache_writer(timeout=1.0))
        self.assertGreaterEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1]["stat"]["seq"], 1)
        self.assertEqual(snapshots[-1]["rs485"]["node"], 7)

    def test_rapid_disjoint_updates_are_coalesced_without_losing_branches(self) -> None:
        state = self._state(interval=0.05)
        writes = []
        writes_lock = threading.Lock()

        def persist(payload: dict) -> bool:
            with writes_lock:
                writes.append((time.monotonic(), copy.deepcopy(payload)))
            return True

        state._persist_device_state_snapshot = persist
        self.assertTrue(state._start_device_state_cache_writer())
        self.assertTrue(state._write_device_state_cache({"events": {"first": {"seq": 1}}}))
        self.assertTrue(self._wait_until(lambda: len(writes) >= 1))

        for seq in range(100):
            self.assertTrue(state._write_device_state_cache({"events": {"second": {"seq": seq}}}))
            self.assertTrue(state._write_device_state_cache({"rs485": {"last": seq}}))

        self.assertTrue(self._wait_until(lambda: len(writes) >= 2))
        self.assertTrue(state._stop_device_state_cache_writer(timeout=1.0))
        with writes_lock:
            observed = list(writes)

        self.assertLessEqual(len(observed), 3)
        self.assertGreaterEqual(observed[1][0] - observed[0][0], 0.035)
        final = observed[-1][1]
        self.assertEqual(final["events"]["first"]["seq"], 1)
        self.assertEqual(final["events"]["second"]["seq"], 99)
        self.assertEqual(final["rs485"]["last"], 99)

    def test_failed_write_retries_at_bounded_rate(self) -> None:
        state = self._state(interval=0.05)
        attempts = []
        succeeded = threading.Event()

        def persist(_payload: dict) -> bool:
            attempts.append(time.monotonic())
            if len(attempts) == 1:
                return False
            succeeded.set()
            return True

        state._persist_device_state_snapshot = persist
        self.assertTrue(state._start_device_state_cache_writer())
        self.assertTrue(state._write_device_state_cache({"retry": {"value": 3}}))
        self.assertTrue(succeeded.wait(timeout=0.5))
        self.assertTrue(state._stop_device_state_cache_writer(timeout=1.0))

        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(attempts[1] - attempts[0], 0.035)
        self.assertEqual(state._device_state_cache_write_fail, 0)
        self.assertEqual(
            state._device_state_cache_persisted_generation,
            state._device_state_cache_generation,
        )

    def test_shutdown_bypasses_rate_limit_flushes_and_rejects_late_publish(self) -> None:
        state = self._state(interval=0.03)
        snapshots = []
        first = threading.Event()

        def persist(payload: dict) -> bool:
            snapshots.append(copy.deepcopy(payload))
            first.set()
            return True

        state._persist_device_state_snapshot = persist
        self.assertTrue(state._start_device_state_cache_writer())
        self.assertTrue(state._write_device_state_cache({"value": 1}))
        self.assertTrue(first.wait(timeout=0.5))

        state._device_state_cache_write_interval_s = 60.0
        self.assertTrue(state._write_device_state_cache({"value": 2}))
        started = time.monotonic()
        self.assertTrue(state._stop_device_state_cache_writer(timeout=1.0))
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(snapshots[-1]["value"], 2)
        self.assertFalse(state._device_state_cache_writer_thread.is_alive())

        before = copy.deepcopy(state.device_state_cache)
        self.assertFalse(state._write_device_state_cache({"value": 3}))
        self.assertEqual(state.device_state_cache, before)

    def test_real_atomic_snapshot_has_actual_write_metadata(self) -> None:
        state = self._state()
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "device-state.json"
            state._device_state_path = lambda: str(target)
            self.assertTrue(state._start_device_state_cache_writer())
            before = time.time()
            self.assertTrue(state._write_device_state_cache({"source": "bulk_stat", "payload": {"ok": True}}))
            self.assertTrue(self._wait_until(target.exists, timeout=0.5))
            self.assertTrue(state._stop_device_state_cache_writer(timeout=1.0))

            on_disk = json.loads(target.read_text(encoding="utf-8"))
            self.assertTrue(on_disk["payload"]["ok"])
            self.assertGreaterEqual(on_disk["cache_written_at"], before)
            self.assertIn("updated_at", on_disk)
            self.assertEqual(list(Path(tmp_dir).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
