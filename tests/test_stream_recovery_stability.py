import importlib.util
import gc
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "host" / "BMI30.001.py.2026-08-25-1221"
ENGINE_PATH = ROOT / "host" / "BMI30.200.py.2026-08-25-1221"


def _load_source(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class _FakeStream:
    def __init__(self) -> None:
        self.commands = []
        self.det_adc = []
        self.disconnected = False

    def send_cmd(self, cmd: int, payload: bytes) -> None:
        self.commands.append((int(cmd), bytes(payload)))

    def set_det_adc(self, bits: int) -> None:
        self.det_adc.append(int(bits))


class _FakeTimer:
    instances = []

    def __init__(self, delay: float, callback) -> None:
        self.delay = float(delay)
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.daemon = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


class _RecoveryOutputState:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.stream = _FakeStream()
        self._recovery_outputs_inhibited = True
        self._recovery_outputs_off_last_t = 0.0
        self._group_led_fault_active = True
        self._group_led_active_event = "fault"
        self._group_led_active_pattern = 7
        self._group_led_active_t = 0.0
        self._group_led_local_upper_active = False
        self._group_led_local_lower_active = False
        self._group_led_neighbor_upper_active = False
        self._group_led_neighbor_lower_active = False
        self._det_adc_status_bits = -1
        self._det_adc_status_stream_token = 0

    def _stop_sound_now(self) -> None:
        return None

    def _set_det_gpio(self, _a: bool, _b: bool) -> None:
        return None

    def _group_led_clear_detection_state(self) -> bool:
        return self.engine.ScopeWindow._group_led_clear_detection_state(self)

    def _send_det_adc_status(self, a: bool, b: bool, force: bool = False) -> bool:
        return self.engine.ScopeWindow._send_det_adc_status(self, a, b, force=force)

    def _send_led_pattern(self, pattern: int, update_ui: bool = False, force: bool = False) -> bool:
        return self.engine.ScopeWindow._send_led_pattern(
            self,
            pattern,
            update_ui=update_ui,
            force=force,
        )

    def _group_led_apply_current_state_locked(self, force: bool = False) -> bool:
        return self.engine.ScopeWindow._group_led_apply_current_state_locked(self, force=force)

    def _group_led_apply_current_state(self, force: bool = False) -> bool:
        return self.engine.ScopeWindow._group_led_apply_current_state(self, force=force)


class _NumGroup:
    @staticmethod
    def checkedId() -> int:
        return 6


class _NumGroupFive:
    @staticmethod
    def checkedId() -> int:
        return 5


class _ThreadState:
    def __init__(self, alive: bool) -> None:
        self.alive = bool(alive)

    def is_alive(self) -> bool:
        return self.alive


class StreamRecoveryStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "host"))
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.core = _load_source("bmi30_core_recovery_test", CORE_PATH)
        cls.engine = _load_source("bmi30_engine_recovery_test", ENGINE_PATH)

    def test_prefire_restore_debounce_keeps_only_one_pending_timer(self) -> None:
        _FakeTimer.instances = []
        delivered = []
        debounce = self.core._SinglePendingQtCall(
            queue_fn=lambda fn: fn(),
            timer_factory=_FakeTimer,
        )

        for index in range(1000):
            debounce.schedule(10.0, lambda index=index: delivered.append(index))

        self.assertEqual(debounce.pending_count(), 1)
        self.assertEqual(sum(not timer.cancelled for timer in _FakeTimer.instances), 1)
        for timer in _FakeTimer.instances:
            timer.fire()
        self.assertEqual(delivered, [999])
        self.assertEqual(debounce.pending_count(), 0)

    def test_fault_classifier_ignores_service_only_tx_completions(self) -> None:
        verdict = self.engine.ScopeWindow._fault_probe_verdict
        state = object()
        running = {"valid": True, "flags_rt": 0x0001}

        service_only = {
            "sent0": 0,
            "sent1": 0,
            "dbg_tx_cplt": 7,
            "produced_seq": 1,
            "cur_stream_seq": 1,
            "dma0": 400,
            "dma1": 400,
            "wr": 400,
        }
        self.assertEqual(verdict(state, running, running, service_only), "stm32_tx_stalled")

        adc0_only = dict(service_only, sent0=1)
        self.assertEqual(verdict(state, running, running, adc0_only), "stm32_tx_stalled")

        adc1_only = dict(service_only, sent1=1)
        self.assertEqual(verdict(state, running, running, adc1_only), "stm32_tx_stalled")

        both_adc_frames_sent = dict(service_only, sent0=1, sent1=1)
        self.assertEqual(verdict(state, running, running, both_adc_frames_sent), "host_bulk_lost")

        no_progress = {name: 0 for name in service_only}
        self.assertEqual(verdict(state, running, running, no_progress), "stm32_adc_stalled")
        self.assertEqual(
            verdict(state, running, {"valid": True, "flags_rt": 0}, no_progress),
            "stream_stopped",
        )
        self.assertEqual(verdict(state, {}, running, no_progress), "usb_control_lost")

    def test_counter_reset_is_not_misclassified_as_host_bulk_progress(self) -> None:
        delta_fn = self.engine.ScopeWindow._fault_probe_delta
        verdict = self.engine.ScopeWindow._fault_probe_verdict
        state = type("DeltaState", (), {})()
        state._u32_delta = lambda a, b: self.engine.ScopeWindow._u32_delta(state, a, b)
        before = {
            "valid": True,
            "flags_rt": 0x0001,
            "sent0": 1000,
            "sent1": 1000,
            "dbg_tx_cplt": 1000,
            "produced_seq": 1000,
            "cur_stream_seq": 1000,
            "dma0": 1000,
            "dma1": 1000,
            "wr": 1000,
        }
        after_reset = dict(before)
        for name in ("sent0", "sent1", "dbg_tx_cplt", "produced_seq", "cur_stream_seq", "dma0", "dma1", "wr"):
            after_reset[name] = 0

        reset_delta = delta_fn(state, before, after_reset)
        self.assertNotEqual(verdict(state, before, after_reset, reset_delta), "host_bulk_lost")

        before_wrap = dict(before, sent0=0xFFFFFFFE, sent1=0xFFFFFFFE)
        after_wrap = dict(before_wrap, sent0=2, sent1=2)
        wrap_delta = delta_fn(state, before_wrap, after_wrap)
        self.assertEqual(wrap_delta["sent0"], 4)
        self.assertEqual(wrap_delta["sent1"], 4)
        self.assertEqual(verdict(state, before_wrap, after_wrap, wrap_delta), "host_bulk_lost")

    def test_probe_result_is_bound_to_current_stream_and_generation(self) -> None:
        state = type("State", (), {})()
        state.stream = _FakeStream()
        state._last_fault_probe_result = {
            "verdict": "stm32_tx_stalled",
            "captured_at": 20.0,
            "stream_token": id(state.stream),
        }
        current = self.engine.ScopeWindow._current_stream_fault_probe

        self.assertEqual(current(state, newer_than=19.0)["verdict"], "stm32_tx_stalled")
        self.assertEqual(current(state, newer_than=20.0), {})

        state.stream = _FakeStream()
        self.assertEqual(current(state, newer_than=0.0), {})

        source = ENGINE_PATH.read_text(encoding="utf-8")
        start = source.index("\tdef _finalize_connect_success")
        stop = source.index("\n\tdef ", start + 2)
        finalize = source[start:stop]
        self.assertIn("self._last_fault_probe_result = None", finalize)
        self.assertIn("self._usb_err_count = 0", finalize)
        self.assertIn("self._usb_err_last_t = 0.0", finalize)

    def test_old_reader_error_cannot_disconnect_replacement_stream(self) -> None:
        state = type("State", (), {})()
        replacement = _FakeStream()
        state.reader_debug = False
        state.reader_running = True
        state._usb_err_count = 0
        state._usb_err_last_t = 0.0
        state._usb_err_need_hw_reset = False
        state.fault_notes = []
        state._note_stream_fault = lambda reason: state.fault_notes.append(reason)

        class _OldStream:
            disconnected = False

            def get_stereo(self, timeout=0.1):
                state.stream = replacement
                state.reader_running = False
                raise OSError("[Errno 19] old stream disappeared")

        old_stream = _OldStream()
        state.stream = old_stream

        self.engine.ScopeWindow._reader_thread_func(state)

        self.assertIs(state.stream, replacement)
        self.assertFalse(replacement.disconnected)
        self.assertFalse(old_stream.disconnected)
        self.assertEqual(state._usb_err_count, 0)
        self.assertFalse(state._usb_err_need_hw_reset)
        self.assertEqual(state.fault_notes, [])

    def test_recovery_output_enforcement_is_deduplicated(self) -> None:
        state = _RecoveryOutputState(self.engine)
        apply_led = self.engine.ScopeWindow._group_led_apply_current_state
        enforce = self.engine.ScopeWindow._enforce_recovery_outputs_off

        for _ in range(100):
            apply_led(state)
            state._recovery_outputs_off_last_t = 0.0
            enforce(state)

        led_off = [item for item in state.stream.commands if item == (0x3B, b"\x00")]
        self.assertEqual(len(led_off), 1)
        self.assertEqual(state.stream.det_adc, [0])
        self.assertTrue(state._group_led_fault_active)

    def test_fault_led_waits_for_committed_recovery(self) -> None:
        state = type("FaultLedState", (), {})()
        state.stream = _FakeStream()
        state._stream_user_stopped = False
        state._stall_reset_inflight = False
        state._auto_reset_just_occurred = False
        state._group_led_fault_active = False
        state._group_led_lock = threading.RLock()
        state.apply_calls = []
        state.poll_calls = []
        state._group_led_apply_current_state = (
            lambda force=False: state.apply_calls.append(bool(force)) or True
        )
        state._group_led_poll_sync_status = (
            lambda force=False: state.poll_calls.append(bool(force)) or True
        )
        state._group_led_update_fault_state_locked = (
            lambda kind: self.engine.ScopeWindow._group_led_update_fault_state_locked(state, kind)
        )
        update = self.engine.ScopeWindow._group_led_update_fault_state

        # These are only candidates until the one-second probe commits a
        # recovery.  A self-recovered frame gap must not flash fault state.
        update(state, "pairing_stall")
        update(state, "stm32_stream_stall")
        self.assertFalse(state._group_led_fault_active)
        self.assertEqual(state.apply_calls, [False, False])

        state._stall_reset_inflight = True
        update(state, "pairing_stall")
        self.assertTrue(state._group_led_fault_active)
        self.assertTrue(state.apply_calls[-1])

        state._stall_reset_inflight = False
        state._auto_reset_just_occurred = False
        state.stream.disconnected = True
        update(state, "usb_disconnected")
        self.assertTrue(state._group_led_fault_active)

        # An intentional stop is never presented as a fault, even if the old
        # USB object still carries its disconnected marker.
        state._stream_user_stopped = True
        update(state, "usb_disconnected")
        self.assertFalse(state._group_led_fault_active)
        self.assertEqual(state.poll_calls, [True])

    def test_detection_falling_edge_uses_stm32_optic_gate_without_base_off(self) -> None:
        state = type("LedState", (), {})()
        state.stream = _FakeStream()
        state._recovery_outputs_inhibited = False
        state._group_led_active_event = "neighbor_upper_detection"
        state._group_led_active_pattern = 6
        state._group_led_active_t = 0.0
        state._group_led_manual_test_pattern = 0
        # Pattern 6 was already installed as the persistent STM32 base while
        # the detector optic gate was active.
        state._led_pattern_last_sent = 6
        state._led_pattern_last_sent_t = 0.0
        state._led_pattern_last_stream_token = id(state.stream)
        state._group_led_base_held_for_optic_gate = False
        state._group_led_detection_allowed = lambda: True
        state._group_led_clear_neighbor_state_if_no_peer = lambda: False
        state._group_led_current_event = lambda: ""
        state._group_led_desired_output_event = lambda: state._group_led_current_event()
        state._group_led_patterns_snapshot = lambda: {}
        state._group_led_actual_pattern_info = lambda: {
            "pattern": 6,
            "source": "stat",
            "age_s": 0.0,
        }
        state._send_led_pattern = lambda pattern, update_ui=False, force=False: (
            self.engine.ScopeWindow._send_led_pattern(
                state,
                pattern,
                update_ui=update_ui,
                force=force,
            )
        )
        state._group_led_apply_current_state_locked = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state_locked(state, force=force)
        )
        apply_led = self.engine.ScopeWindow._group_led_apply_current_state

        apply_led(state)
        for _ in range(100):
            state._group_led_active_t = 0.0
            apply_led(state)

        self.assertEqual(state.stream.commands, [])
        self.assertEqual(state._group_led_active_event, "")
        self.assertEqual(state._group_led_active_pattern, 0)
        self.assertTrue(state._group_led_base_held_for_optic_gate)

        # The same event reuses the persistent base without USB traffic; a
        # different event changes it once.
        state._group_led_current_event = lambda: "neighbor_upper_detection"
        state._group_led_patterns_snapshot = lambda: {"neighbor_upper_detection": 6}
        apply_led(state)
        self.assertEqual(state.stream.commands, [])
        self.assertFalse(state._group_led_base_held_for_optic_gate)

        state._group_led_current_event = lambda: ""
        apply_led(state)
        state._group_led_current_event = lambda: "neighbor_lower_detection"
        state._group_led_patterns_snapshot = lambda: {"neighbor_lower_detection": 5}
        apply_led(state)
        self.assertEqual(state.stream.commands, [(0x3B, b"\x05")])
        source = ENGINE_PATH.read_text(encoding="utf-8")
        start = source.index("\tdef _group_led_apply_current_state")
        stop = source.index("\n\tdef ", start + 2)
        self.assertNotIn("resend_due", source[start:stop])

    def test_forced_gate_close_clears_a_held_led_base(self) -> None:
        state = type("HeldLedState", (), {})()
        state.stream = _FakeStream()
        state._recovery_outputs_inhibited = False
        state._group_led_active_event = ""
        state._group_led_active_pattern = 0
        state._group_led_active_t = 0.0
        state._group_led_manual_test_pattern = 0
        state._group_led_base_held_for_optic_gate = True
        state._led_pattern_last_sent = 6
        state._led_pattern_last_sent_t = 0.0
        state._led_pattern_last_stream_token = id(state.stream)
        state._group_led_detection_allowed = lambda: False
        state._group_led_clear_detection_state = lambda: False
        state._group_led_clear_neighbor_state_if_no_peer = lambda: False
        state._group_led_current_event = lambda: ""
        state._group_led_desired_output_event = lambda: state._group_led_current_event()
        state._group_led_patterns_snapshot = lambda: {}
        state._send_led_pattern = lambda pattern, update_ui=False, force=False: (
            self.engine.ScopeWindow._send_led_pattern(
                state,
                pattern,
                update_ui=update_ui,
                force=force,
            )
        )
        state._group_led_apply_current_state_locked = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state_locked(state, force=force)
        )

        self.assertTrue(self.engine.ScopeWindow._group_led_apply_current_state(state, force=True))
        self.assertEqual(state.stream.commands, [(0x3B, b"\x00")])
        self.assertFalse(state._group_led_base_held_for_optic_gate)

    def test_zero_mapped_detection_clears_a_previous_held_base(self) -> None:
        state = type("ZeroMappedLedState", (), {})()
        state.stream = _FakeStream()
        state._recovery_outputs_inhibited = False
        state._group_led_active_event = ""
        state._group_led_active_pattern = 0
        state._group_led_active_t = 0.0
        state._group_led_manual_test_pattern = 0
        state._group_led_base_held_for_optic_gate = True
        state._led_pattern_last_sent = 6
        state._led_pattern_last_sent_t = 0.0
        state._led_pattern_last_stream_token = id(state.stream)
        state._group_led_detection_allowed = lambda: True
        state._group_led_clear_neighbor_state_if_no_peer = lambda: False
        state._group_led_current_event = lambda: "lower_detection"
        state._group_led_desired_output_event = lambda: state._group_led_current_event()
        state._group_led_patterns_snapshot = lambda: {"lower_detection": 0}
        state._send_led_pattern = lambda pattern, update_ui=False, force=False: (
            self.engine.ScopeWindow._send_led_pattern(
                state,
                pattern,
                update_ui=update_ui,
                force=force,
            )
        )
        state._group_led_apply_current_state_locked = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state_locked(state, force=force)
        )

        self.assertTrue(self.engine.ScopeWindow._group_led_apply_current_state(state))
        self.assertEqual(state.stream.commands, [(0x3B, b"\x00")])
        self.assertFalse(state._group_led_base_held_for_optic_gate)

    def test_concurrent_identical_led_requests_send_exactly_once(self) -> None:
        class SlowStream(_FakeStream):
            def send_cmd(self, cmd: int, payload: bytes) -> None:
                time.sleep(0.01)
                super().send_cmd(cmd, payload)

        state = type("ConcurrentLedState", (), {})()
        state.stream = SlowStream()
        state._recovery_outputs_inhibited = False
        state._led_pattern_last_sent = None
        state._led_pattern_last_sent_t = 0.0
        state._led_pattern_last_stream_token = 0
        state._group_led_base_held_for_optic_gate = False
        barrier = threading.Barrier(16)
        errors = []

        def send_pattern() -> None:
            try:
                barrier.wait(timeout=2.0)
                self.engine.ScopeWindow._send_led_pattern(
                    state,
                    6,
                    update_ui=False,
                )
            except Exception as exc:  # pragma: no cover - assertion captures it
                errors.append(exc)

        workers = [threading.Thread(target=send_pattern) for _ in range(16)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2.0)

        self.assertEqual(errors, [])
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(state.stream.commands, [(0x3B, b"\x06")])

    def test_manual_and_detection_led_commits_are_serialized(self) -> None:
        class OrderedStream(_FakeStream):
            def __init__(self) -> None:
                super().__init__()
                self.first_send_entered = threading.Event()
                self.release_first_send = threading.Event()

            def send_cmd(self, cmd: int, payload: bytes) -> None:
                if bytes(payload) == b"\x06" and not self.first_send_entered.is_set():
                    self.first_send_entered.set()
                    self.release_first_send.wait(timeout=2.0)
                super().send_cmd(cmd, payload)

        state = type("AtomicLedState", (), {})()
        state.stream = OrderedStream()
        state._recovery_outputs_inhibited = False
        state._group_led_active_event = ""
        state._group_led_active_pattern = 0
        state._group_led_active_t = 0.0
        state._group_led_manual_test_pattern = 0
        state._group_led_base_held_for_optic_gate = False
        state._group_led_local_upper_active = False
        state._group_led_local_lower_active = False
        state._sound_indicator_active = True
        state._led_pattern_last_sent = None
        state._led_pattern_last_sent_t = 0.0
        state._led_pattern_last_stream_token = 0
        state._group_led_detection_allowed = lambda: True
        state._group_led_clear_neighbor_state_if_no_peer = lambda: False
        state._group_led_current_event = lambda: (
            "upper_detection" if state._group_led_local_upper_active else ""
        )
        state._group_led_desired_output_event = lambda: (
            "manual_test"
            if state._group_led_manual_test_pattern
            else state._group_led_current_event()
        )
        state._group_led_patterns_snapshot = lambda: {"upper_detection": 6}
        state._send_led_pattern = lambda pattern, update_ui=False, force=False: (
            self.engine.ScopeWindow._send_led_pattern(
                state,
                pattern,
                update_ui=update_ui,
                force=force,
            )
        )
        state._group_led_apply_current_state = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state(state, force=force)
        )
        state._group_led_apply_current_state_locked = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state_locked(state, force=force)
        )
        state._group_led_apply_detection_locked = lambda upper, lower, neighbor=False: (
            self.engine.ScopeWindow._group_led_apply_detection_locked(
                state,
                upper,
                lower,
                neighbor=neighbor,
            )
        )
        state._set_group_led_manual_test_pattern_locked = lambda pattern: (
            self.engine.ScopeWindow._set_group_led_manual_test_pattern_locked(state, pattern)
        )

        detection = threading.Thread(
            target=self.engine.ScopeWindow._group_led_apply_detection,
            args=(state, True, False),
        )
        manual_started = threading.Event()

        def set_manual() -> None:
            manual_started.set()
            self.engine.ScopeWindow._set_group_led_manual_test_pattern(state, 13)

        manual = threading.Thread(target=set_manual)
        detection.start()
        self.assertTrue(state.stream.first_send_entered.wait(timeout=2.0))
        manual.start()
        self.assertTrue(manual_started.wait(timeout=2.0))
        time.sleep(0.02)
        state.stream.release_first_send.set()
        detection.join(timeout=2.0)
        manual.join(timeout=2.0)

        self.assertFalse(detection.is_alive())
        self.assertFalse(manual.is_alive())
        self.assertEqual(state.stream.commands, [(0x3B, b"\x06"), (0x3B, b"\x0d")])
        self.assertEqual(state._led_pattern_last_sent, 13)
        self.assertEqual(state._group_led_active_event, "manual_test")
        self.assertEqual(state._group_led_active_pattern, 13)

    def test_detector_output_stop_does_not_force_led_resend(self) -> None:
        source = ENGINE_PATH.read_text(encoding="utf-8")
        start = source.index("\tdef _rt_stop_detection_outputs")
        stop = source.index("\n\tdef ", start + 2)
        body = source[start:stop]
        self.assertIn("_group_led_poll_sync_status(force=False)", body)
        self.assertNotIn("_group_led_poll_sync_status(force=True)", body)

    def test_new_stream_gets_one_fresh_output_off_command(self) -> None:
        state = _RecoveryOutputState(self.engine)
        enforce = self.engine.ScopeWindow._enforce_recovery_outputs_off
        enforce(state)
        first_stream = state.stream

        state.stream = _FakeStream()
        state._recovery_outputs_off_last_t = 0.0
        enforce(state)
        enforce(state)

        self.assertEqual(first_stream.commands, [(0x3B, b"\x00")])
        self.assertEqual(first_stream.det_adc, [0])
        self.assertEqual(state.stream.commands, [(0x3B, b"\x00")])
        self.assertEqual(state.stream.det_adc, [0])

    def test_normal_reconnect_invalidates_group_led_cache_once(self) -> None:
        state = type("LedReconnectState", (), {})()
        state.stream = _FakeStream()
        state._recovery_outputs_inhibited = False
        state._led_pattern_last_sent = 0
        state._led_pattern_last_sent_t = 10.0
        state._led_pattern_last_stream_token = id(state.stream)
        state._det_adc_status_bits = 0
        state._det_adc_status_stream_token = id(state.stream)
        state._group_led_active_event = ""
        state._group_led_active_pattern = 0
        state._group_led_active_t = 10.0
        state._group_led_manual_test_pattern = 0
        state._group_led_detection_allowed = lambda: True
        state._group_led_clear_neighbor_state_if_no_peer = lambda: False
        state._group_led_current_event = lambda: ""
        state._group_led_desired_output_event = lambda: state._group_led_current_event()
        state._group_led_patterns_snapshot = lambda: {}
        state._send_led_pattern = lambda pattern, update_ui=False, force=False: (
            self.engine.ScopeWindow._send_led_pattern(
                state,
                pattern,
                update_ui=update_ui,
                force=force,
            )
        )
        state._group_led_apply_current_state_locked = lambda force=False: (
            self.engine.ScopeWindow._group_led_apply_current_state_locked(state, force=force)
        )

        self.engine.ScopeWindow._reset_stream_output_command_cache(state)
        apply_led = self.engine.ScopeWindow._group_led_apply_current_state
        apply_led(state)
        apply_led(state)

        self.assertEqual(state.stream.commands, [(0x3B, b"\x00")])
        self.assertEqual(state._group_led_active_pattern, 0)

    def test_detector_backend_defaults_to_spawned_process(self) -> None:
        source = ENGINE_PATH.read_text(encoding="utf-8")
        init_start = source.index("os.getenv('BMI30_RT_DET_PROCESS', '1')")
        init_stop = source.index("\n\t\tself._rt_det_proc = None", init_start)
        init_body = source[init_start:init_stop]

        self.assertIn("os.getenv('BMI30_RT_DET_PROCESS', '1')", init_body)
        self.assertIn("os.getenv('BMI30_RT_DET_SYNC_FALLBACK', '0')", init_body)
        self.assertIn("_mp.get_context('spawn')", init_body)
        start = source.index("\tdef _rt_detector_process_start")
        stop = source.index("\n\tdef ", start + 2)
        start_body = source[start:stop]
        self.assertIn("ctx.Process(", start_body)
        self.assertIn("target=run_rt_detector_process", start_body)
        self.assertNotIn("threading.Thread(", start_body)
        for method_name in ("_rt_detector_submit_process", "_rt_detector_submit_process_block"):
            submit_start = source.index(f"\tdef {method_name}")
            submit_stop = source.index("\n\tdef ", submit_start + 2)
            submit_body = source[submit_start:submit_stop]
            self.assertIn("_rt_detector_worker_ready_fast()", submit_body)
            self.assertNotIn("_rt_detector_process_start()", submit_body)
        reader_start = source.index("\tdef _reader_thread_func")
        reader_stop = source.index("\n\tdef ", reader_start + 2)
        reader_body = source[reader_start:reader_stop]
        self.assertIn("frame skipped to protect USB reader", reader_body)
        self.assertIn("_rt_det_sync_fallback_enabled", reader_body)

        core_source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn('"mode": "process" if det_worker_enabled', core_source)

    def test_detector_process_starts_with_spawn_and_stops_cleanly(self) -> None:
        state = type("DetectorThreadState", (), {})()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_process_enabled = True
        state._rt_det_proc = None
        state._rt_det_worker_generation = 1
        state.max_samples = 32

        start = self.engine.ScopeWindow._rt_detector_process_start
        stop = self.engine.ScopeWindow._rt_detector_process_stop
        self.assertTrue(start(state))
        self.assertEqual(state._rt_det_mp_ctx.get_start_method(), "spawn")
        self.assertEqual(state._rt_det_proc.name, "bmi30-rt-detector-process")
        self.assertIsNotNone(state._rt_det_proc.pid)
        self.assertTrue(state._rt_det_proc.is_alive())
        self.assertTrue(stop(state))
        self.assertIsNone(state._rt_det_proc)

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "requires Linux procfs")
    def test_detector_process_full_queue_crash_stop_does_not_leak_feeders(self) -> None:
        start = self.engine.ScopeWindow._rt_detector_process_start
        stop = self.engine.ScopeWindow._rt_detector_process_stop

        def make_state():
            state = type("DetectorQueueLifecycleState", (), {})()
            state._rt_det_process_lock = threading.RLock()
            state._rt_det_result_apply_lock = threading.RLock()
            state._rt_det_process_enabled = True
            state._rt_det_proc = None
            state._rt_det_worker_generation = 1
            state._rt_det_start_retry_not_before_t = 0.0
            state.max_samples = 4096
            state._det_break_confirmation_chains = lambda _reason: None
            return state

        # Warm imports and the multiprocessing resource tracker before taking
        # the baseline.  Every measured cycle still launches a fresh spawn child.
        warm = make_state()
        self.assertTrue(start(warm))
        ready_deadline = time.monotonic() + 15.0
        while time.monotonic() < ready_deadline and not warm._rt_det_ready_event.is_set():
            time.sleep(0.01)
        self.assertTrue(warm._rt_det_ready_event.is_set())
        self.assertTrue(stop(warm))
        del warm
        gc.collect()
        time.sleep(0.20)

        def snapshot():
            return (
                len(os.listdir("/proc/self/fd")),
                len(os.listdir("/proc/self/task")),
                sum(thread.name == "QueueFeederThread" for thread in threading.enumerate()),
            )

        baseline = snapshot()
        samples = self.engine.np.arange(4096, dtype=self.engine.np.int32)
        payload = tuple(samples.copy() for _ in range(4))

        for cycle in range(20):
            state = make_state()
            self.assertTrue(start(state), f"cycle {cycle}: spawn failed")
            generation = int(state._rt_det_worker_generation)
            request = (
                -1,
                cycle + 1,
                False,
                4,
                "prod",
                1.0,
                payload,
                {
                    "worker_generation": generation,
                    "stream_token": 0,
                    "updated_channels": [],
                },
            )
            saw_full = False
            for _ in range(97):
                try:
                    state._rt_det_req_q.put_nowait(request)
                except queue.Full:
                    saw_full = True
                    break
            self.assertTrue(saw_full, f"cycle {cycle}: request queue did not fill")

            # Alternate an orderly stop with the already-dead-child cleanup path.
            if cycle % 2:
                state._rt_det_proc.terminate()
                state._rt_det_proc.join(timeout=3.0)
                self.assertFalse(state._rt_det_proc.is_alive(), f"cycle {cycle}: child survived terminate")
            self.assertTrue(stop(state), f"cycle {cycle}: stop failed")
            self.assertIsNone(state._rt_det_proc)
            del state
            gc.collect()

        deadline = time.monotonic() + 3.0
        current = snapshot()
        while time.monotonic() < deadline and current != baseline:
            gc.collect()
            time.sleep(0.05)
            current = snapshot()
        self.assertEqual(current, baseline, f"resource drift baseline={baseline} current={current}")
        self.assertEqual(mp.active_children(), [])

    def test_detector_process_repeated_crash_uses_bounded_backoff(self) -> None:
        start = self.engine.ScopeWindow._rt_detector_process_start
        stop = self.engine.ScopeWindow._rt_detector_process_stop
        state = type("DetectorCrashBackoffState", (), {})()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_process_enabled = True
        state._rt_det_proc = None
        state._rt_det_worker_generation = 1
        state._rt_det_start_retry_not_before_t = 0.0
        state.max_samples = 32
        state._det_break_confirmation_chains = lambda _reason: None
        state._rt_detector_note_start_failure = (
            lambda reason="", exitcode=None:
            self.engine.ScopeWindow._rt_detector_note_start_failure(
                state,
                reason,
                exitcode,
            )
        )

        try:
            for failure_count, expected_delay in ((1, 2.0), (2, 5.0)):
                self.assertTrue(start(state))
                state._rt_det_proc.terminate()
                state._rt_det_proc.join(timeout=3.0)
                self.assertFalse(state._rt_det_proc.is_alive())

                before = time.time()
                self.assertFalse(start(state))
                self.assertEqual(state._rt_det_start_fail_count, failure_count)
                remaining = state._rt_det_start_retry_not_before_t - before
                self.assertGreaterEqual(remaining, expected_delay - 0.25)
                self.assertLessEqual(remaining, expected_delay + 0.25)
                self.assertIsNone(state._rt_det_proc)
                self.assertFalse(start(state))

                # Advance the deterministic harness to the next crash without
                # sleeping through the production backoff interval.
                state._rt_det_start_retry_not_before_t = 0.0
        finally:
            worker = getattr(state, "_rt_det_proc", None)
            if worker is not None:
                try:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(timeout=3.0)
                except Exception:
                    pass
                stop(state)

    def test_detector_process_restart_is_bound_to_the_connected_stream(self) -> None:
        state = type("DetectorRestartState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_process_enabled = True
        state._rt_det_proc = _ThreadState(False)
        state._rt_det_worker_generation = 8
        state.max_samples = 32
        state._det_break_confirmation_chains = lambda reason: setattr(state, "break_reason", reason)

        start = self.engine.ScopeWindow._rt_detector_process_start
        stop = self.engine.ScopeWindow._rt_detector_process_stop
        self.assertTrue(start(state))
        self.assertEqual(state._rt_det_worker_generation, 9)
        self.assertEqual(state.break_reason, "worker_restart")

        samples = self.engine.np.array([1, 2, 4, 8, 4, 2, 1, 0], dtype=self.engine.np.int32)
        shifted = self.engine.np.array([0, 1, 2, 4, 8, 4, 2, 1], dtype=self.engine.np.int32)
        meta = {
            "worker_generation": 9,
            "stream_token": id(state.stream),
            "updated_channels": [0],
            "source_seq0": 1,
            "want_plot": True,
            "ratio0": 2.0,
            "ratio1": 2.0,
            "thr0": 1,
            "thr1": 1,
        }
        state._rt_det_req_q.put(
            (-1, 1, True, 4, "prod", 1.0, (samples, shifted, samples, shifted), meta)
        )
        # A spawned child imports the exact timestamped engine in a fresh
        # interpreter.  On a loaded Raspberry Pi that cold import can exceed
        # the former 3 s test timeout even though the worker is healthy.
        item = state._rt_det_res_q.get(timeout=10.0)
        self.assertEqual(item[-2:], (9, id(state.stream)))

        self.assertTrue(
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                "test_shared_fence",
                stream_token=id(state.stream),
            )
        )
        self.assertEqual(state._rt_det_worker_generation, 10)
        self.assertEqual(state._rt_det_shared_generation.value, 10)
        self.assertEqual(state._rt_det_shared_stream_token.value, id(state.stream))
        meta["worker_generation"] = 10
        meta["source_seq0"] = 2
        state._rt_det_req_q.put(
            (-1, 2, True, 4, "prod", 1.0, (samples, shifted, samples, shifted), meta)
        )
        item = state._rt_det_res_q.get(timeout=10.0)
        self.assertEqual(item[-2:], (10, id(state.stream)))
        self.assertTrue(stop(state))

    def test_detector_thread_fences_results_by_generation_and_stream(self) -> None:
        env_name = "BMI30_RT_PEAK_INDEX_MIN"
        old_env = os.environ.get(env_name)
        os.environ[env_name] = "77"
        requests = queue.Queue()
        results = queue.Queue()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=self.engine._rt_detector_process_main,
            args=([], 32, requests, results, stop_event, False, 1),
            daemon=True,
        )
        worker.start()
        samples = self.engine.np.array([1, 2, 4, 8, 4, 2, 1, 0], dtype=self.engine.np.int32)
        shifted = self.engine.np.array([0, 1, 2, 4, 8, 4, 2, 1], dtype=self.engine.np.int32)

        def request(generation: int, stream_token: int, seq: int):
            meta = {
                "worker_generation": generation,
                "stream_token": stream_token,
                "updated_channels": [0],
                "source_seq0": seq,
                "want_plot": True,
                "ratio0": 2.0,
                "ratio1": 2.0,
                "thr0": 1,
                "thr1": 1,
                # This intentionally stale snapshot must not overwrite the
                # main-process setting when the backend is a thread.
                "peak_index_min": 3,
            }
            return (-1, seq, True, 4, "prod", 1.0, (samples, shifted, samples, shifted), meta)

        try:
            requests.put(("__reset__", 2, 111))
            requests.put(request(1, 111, 1))
            requests.put(request(2, 999, 2))
            requests.put(request(2, 111, 3))
            item = results.get(timeout=3.0)
            self.assertEqual(item[-2:], (2, 111))
            self.assertEqual(item[1], 3)
            self.assertEqual(os.environ.get(env_name), "77")
            with self.assertRaises(queue.Empty):
                results.get(timeout=0.15)
        finally:
            stop_event.set()
            worker.join(timeout=2.0)
            if old_env is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = old_env
        self.assertFalse(worker.is_alive())

    def test_detector_health_reset_gets_a_fresh_grace_window(self) -> None:
        state = type("DetectorResetState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_worker_generation = 4
        state._rt_det_req_q = queue.Queue()
        state._rt_det_res_q = queue.Queue()
        state._rt_det_req_q.put(("old",))
        state._rt_det_res_q.put(("old",))
        state._rt_det_proc_submit_count = 99
        state._rt_det_proc_result_count = 0
        state._rt_det_proc_last_submit_t = 10.0
        state._rt_det_proc_last_result_t = 0.0
        state._rt_det_proc_first_submit_t = 1.0
        state._rt_det_proc_started_t = 1.0
        state._rt_det_prev0 = object()
        state._rt_det_prev1 = object()
        state._det_break_confirmation_chains = lambda reason: setattr(state, "break_reason", reason)
        state._rt_det_proc = _ThreadState(True)

        before = time.time()
        self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
            state,
            "worker_backpressure",
            stream_token=123,
        )

        self.assertEqual(state._rt_det_worker_generation, 5)
        self.assertEqual(state._rt_det_req_q.get_nowait(), ("__reset__", 5, 123))
        self.assertTrue(state._rt_det_res_q.empty())
        self.assertEqual(state._rt_det_proc_submit_count, 0)
        self.assertEqual(state._rt_det_proc_result_count, 0)
        self.assertEqual(state._rt_det_proc_first_submit_t, 0.0)
        self.assertGreaterEqual(state._rt_det_proc_started_t, before)
        self.assertEqual(state.break_reason, "worker_backpressure")

    def test_reader_reset_never_drains_full_multiprocessing_queues(self) -> None:
        ctx = mp.get_context("spawn")
        state = type("DetectorMpResetState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_reset_pending = None
        state._rt_det_worker_generation = 4
        state._rt_det_req_q = ctx.Queue(maxsize=96)
        state._rt_det_res_q = ctx.Queue(maxsize=128)
        state._rt_det_shared_generation = ctx.Value("Q", 4, lock=False)
        state._rt_det_shared_stream_token = ctx.Value("Q", id(state.stream), lock=False)
        state._rt_det_proc = _ThreadState(True)
        state._rt_det_proc_submit_count = 32
        state._rt_det_proc_result_count = 0
        state._rt_det_proc_last_submit_t = time.time()
        state._rt_det_proc_last_result_t = 0.0
        state._rt_det_proc_first_submit_t = time.time()
        state._rt_det_proc_started_t = time.time()
        state._det_break_confirmation_chains = lambda reason: setattr(state, "break_reason", reason)
        payload = b"x" * (256 * 1024)
        for _ in range(32):
            state._rt_det_req_q.put_nowait(payload)
            state._rt_det_res_q.put_nowait(payload)
        try:
            started = time.monotonic()
            applied = self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                "reader_full_fifo",
                stream_token=id(state.stream),
                wait_for_apply=False,
            )
            elapsed = time.monotonic() - started

            self.assertFalse(applied)
            self.assertLess(elapsed, 0.010)
            self.assertEqual(state._rt_det_worker_generation, 4)
            self.assertEqual(state._rt_det_reset_pending, ("reader_full_fifo", id(state.stream)))

            self.assertTrue(
                self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                    state,
                    "reader_full_fifo",
                    stream_token=id(state.stream),
                    wait_for_apply=True,
                )
            )
            self.assertEqual(state._rt_det_worker_generation, 5)
            self.assertEqual(state._rt_det_shared_generation.value, 5)
            # Shared control does not synchronously deserialize either data FIFO.
            self.assertEqual(state._rt_det_req_q.get(timeout=2.0), payload)
            self.assertEqual(state._rt_det_res_q.get(timeout=2.0), payload)
        finally:
            for q_obj in (state._rt_det_req_q, state._rt_det_res_q):
                try:
                    while True:
                        q_obj.get(timeout=0.01)
                except Exception:
                    pass
                q_obj.close()
                q_obj.join_thread()

    def test_worker_transport_failures_exit_instead_of_spinning(self) -> None:
        class EofRequests:
            @staticmethod
            def get(timeout=0.1):
                raise EOFError("closed")

        eof_worker = threading.Thread(
            target=self.engine._rt_detector_process_main,
            args=([], 32, EofRequests(), queue.Queue(), threading.Event(), False),
            daemon=True,
        )
        eof_worker.start()
        eof_worker.join(timeout=1.0)
        self.assertFalse(eof_worker.is_alive())

        class BrokenResults:
            @staticmethod
            def put(_item, timeout=0.1):
                raise BrokenPipeError("closed")

        requests = queue.Queue()
        samples = self.engine.np.array([1, 2, 4, 8, 4, 2, 1, 0], dtype=self.engine.np.int32)
        shifted = self.engine.np.array([0, 1, 2, 4, 8, 4, 2, 1], dtype=self.engine.np.int32)
        meta = {
            "worker_generation": 0,
            "stream_token": 0,
            "updated_channels": [0],
            "source_seq0": 1,
            "want_plot": True,
            "ratio0": 2.0,
            "ratio1": 2.0,
            "thr0": 1,
            "thr1": 1,
        }
        requests.put((-1, 1, True, 4, "prod", 1.0, (samples, shifted, samples, shifted), meta))
        broken_worker = threading.Thread(
            target=self.engine._rt_detector_process_main,
            args=([], 32, requests, BrokenResults(), threading.Event(), False),
            daemon=True,
        )
        broken_worker.start()
        broken_worker.join(timeout=2.0)
        self.assertFalse(broken_worker.is_alive())

    def test_detector_reset_cannot_be_overtaken_by_a_dequeued_old_result(self) -> None:
        state = type("DetectorApplyRaceState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_worker_generation = 1
        state._rt_det_req_q = queue.Queue()
        state._rt_det_res_q = queue.Queue()
        state._rt_det_proc = _ThreadState(True)
        state._rt_det_proc_submit_count = 1
        state._rt_det_proc_result_count = 0
        state._rt_det_proc_last_submit_t = time.time()
        state._rt_det_proc_last_result_t = 0.0
        state._rt_det_proc_first_submit_t = time.time()
        state._rt_det_proc_started_t = time.time()
        state._rt_det_prev0 = None
        state._rt_det_prev1 = None
        state._player_realtime_suspended = lambda: False
        entered_apply = threading.Event()
        release_apply = threading.Event()
        reset_done = threading.Event()
        events = []

        def detection_active() -> bool:
            entered_apply.set()
            release_apply.wait(timeout=2.0)
            return True

        state._rt_detection_active = detection_active
        state._update_realtime_prevbuf_detection = lambda *args, **kwargs: events.append("update")
        state._det_break_confirmation_chains = lambda reason: events.append("reset")
        item = (
            0, 1, 10, 0, 3, 10.0,
            None, None, None, None, None, None, None, None,
            None, None, None, None,
            False, True, 1,
            1, id(state.stream),
        )
        state._rt_det_res_q.put(item)

        drain_thread = threading.Thread(
            target=self.engine.ScopeWindow._rt_detector_drain_results,
            args=(state,),
        )

        def reset_worker() -> None:
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                "race_reset",
                stream_token=id(state.stream),
            )
            reset_done.set()

        drain_thread.start()
        self.assertTrue(entered_apply.wait(timeout=2.0))
        reset_thread = threading.Thread(target=reset_worker)
        reset_thread.start()
        time.sleep(0.05)
        self.assertFalse(reset_done.is_set())
        release_apply.set()
        drain_thread.join(timeout=2.0)
        reset_thread.join(timeout=2.0)

        self.assertFalse(drain_thread.is_alive())
        self.assertFalse(reset_thread.is_alive())
        self.assertEqual(events, ["update", "reset"])

    def test_pending_reset_is_flushed_before_next_result_in_same_batch(self) -> None:
        state = type("DetectorBatchFenceState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_reset_pending = None
        state._rt_det_worker_generation = 1
        state._rt_det_req_q = queue.Queue()
        state._rt_det_res_q = queue.Queue()
        state._rt_det_proc = _ThreadState(True)
        state._rt_det_proc_submit_count = 2
        state._rt_det_proc_result_count = 0
        state._player_realtime_suspended = lambda: False
        entered_first = threading.Event()
        release_first = threading.Event()
        events = []
        active_calls = 0

        def detection_active() -> bool:
            nonlocal active_calls
            active_calls += 1
            if active_calls == 1:
                entered_first.set()
                release_first.wait(timeout=2.0)
            return True

        state._rt_detection_active = detection_active
        state._update_realtime_prevbuf_detection = lambda *args, **kwargs: events.append("update")
        state._det_break_confirmation_chains = lambda reason: events.append("reset")
        state._rt_detector_worker_reset_for_stream = (
            lambda reason="stream_reconnect", stream_token=None, wait_for_apply=True:
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                reason,
                stream_token=stream_token,
                wait_for_apply=wait_for_apply,
            )
        )

        def result_item(seq: int):
            return (
                0, seq, 10, 0, 3, 10.0,
                None, None, None, None, None, None, None, None,
                None, None, None, None,
                False, True, seq,
                1, id(state.stream),
            )

        state._rt_det_res_q.put(result_item(1))
        state._rt_det_res_q.put(result_item(2))
        drain_thread = threading.Thread(
            target=self.engine.ScopeWindow._rt_detector_drain_results,
            args=(state,),
        )
        drain_thread.start()
        self.assertTrue(entered_first.wait(timeout=2.0))
        self.assertFalse(
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                "worker_backpressure",
                stream_token=id(state.stream),
                wait_for_apply=False,
            )
        )
        release_first.set()
        drain_thread.join(timeout=2.0)

        self.assertFalse(drain_thread.is_alive())
        self.assertEqual(events, ["update", "reset"])
        self.assertEqual(state._rt_det_worker_generation, 2)
        self.assertIsNone(state._rt_det_reset_pending)

    def test_result_apply_never_blocks_normal_detector_start(self) -> None:
        state = type("DetectorLockIsolationState", (), {})()
        state._rt_det_process_enabled = True
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_proc = _ThreadState(True)
        state._rt_det_stop_event = threading.Event()
        apply_entered = threading.Event()
        release_apply = threading.Event()

        def hold_apply_lock() -> None:
            with state._rt_det_result_apply_lock:
                apply_entered.set()
                release_apply.wait(timeout=2.0)

        holder = threading.Thread(target=hold_apply_lock)
        holder.start()
        self.assertTrue(apply_entered.wait(timeout=2.0))
        started_at = time.monotonic()
        self.assertTrue(self.engine.ScopeWindow._rt_detector_process_start(state))
        elapsed = time.monotonic() - started_at
        release_apply.set()
        holder.join(timeout=2.0)

        self.assertLess(elapsed, 0.1)
        self.assertFalse(holder.is_alive())

    def test_reader_defers_busy_result_reset_without_blocking_bulk_input(self) -> None:
        state = type("DetectorPendingResetState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_reset_pending = None
        state._rt_det_worker_generation = 7
        state._rt_det_req_q = queue.Queue()
        state._rt_det_res_q = queue.Queue()
        state._rt_det_proc = _ThreadState(True)
        state._player_realtime_suspended = lambda: False
        state._det_break_confirmation_chains = lambda reason: setattr(state, "break_reason", reason)
        state._rt_detector_worker_reset_for_stream = (
            lambda reason="stream_reconnect", stream_token=None, wait_for_apply=True:
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                reason,
                stream_token=stream_token,
                wait_for_apply=wait_for_apply,
            )
        )
        apply_entered = threading.Event()
        release_apply = threading.Event()

        def hold_apply_lock() -> None:
            with state._rt_det_result_apply_lock:
                apply_entered.set()
                release_apply.wait(timeout=2.0)

        holder = threading.Thread(target=hold_apply_lock)
        holder.start()
        self.assertTrue(apply_entered.wait(timeout=2.0))
        started_at = time.monotonic()
        applied = self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
            state,
            "worker_backpressure",
            stream_token=id(state.stream),
            wait_for_apply=False,
        )
        elapsed = time.monotonic() - started_at

        self.assertFalse(applied)
        self.assertLess(elapsed, 0.1)
        self.assertEqual(state._rt_det_worker_generation, 7)
        self.assertEqual(state._rt_det_reset_pending, ("worker_backpressure", id(state.stream)))
        release_apply.set()
        holder.join(timeout=2.0)
        self.engine.ScopeWindow._rt_detector_drain_results(state)

        self.assertFalse(holder.is_alive())
        self.assertEqual(state._rt_det_worker_generation, 8)
        self.assertIsNone(state._rt_det_reset_pending)
        self.assertEqual(state.break_reason, "worker_backpressure")

    def test_reader_also_defers_reset_when_lifecycle_lock_is_busy(self) -> None:
        state = type("DetectorBusyLifecycleState", (), {})()
        state.stream = _FakeStream()
        state._rt_det_process_lock = threading.RLock()
        state._rt_det_result_apply_lock = threading.RLock()
        state._rt_det_reset_pending = None
        state._rt_det_worker_generation = 3
        state._rt_det_req_q = queue.Queue()
        state._rt_det_res_q = queue.Queue()
        state._rt_det_proc = _ThreadState(True)
        state._player_realtime_suspended = lambda: False
        state._det_break_confirmation_chains = lambda reason: setattr(state, "break_reason", reason)
        state._rt_detector_worker_reset_for_stream = (
            lambda reason="stream_reconnect", stream_token=None, wait_for_apply=True:
            self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
                state,
                reason,
                stream_token=stream_token,
                wait_for_apply=wait_for_apply,
            )
        )
        lock_entered = threading.Event()
        release_lock = threading.Event()

        def hold_process_lock() -> None:
            with state._rt_det_process_lock:
                lock_entered.set()
                release_lock.wait(timeout=2.0)

        holder = threading.Thread(target=hold_process_lock)
        holder.start()
        self.assertTrue(lock_entered.wait(timeout=2.0))
        started_at = time.monotonic()
        applied = self.engine.ScopeWindow._rt_detector_worker_reset_for_stream(
            state,
            "worker_backpressure",
            stream_token=id(state.stream),
            wait_for_apply=False,
        )
        elapsed = time.monotonic() - started_at

        self.assertFalse(applied)
        self.assertLess(elapsed, 0.1)
        self.assertEqual(state._rt_det_worker_generation, 3)
        self.assertIsNotNone(state._rt_det_reset_pending)
        release_lock.set()
        holder.join(timeout=2.0)
        self.engine.ScopeWindow._rt_detector_drain_results(state)

        self.assertFalse(holder.is_alive())
        self.assertEqual(state._rt_det_worker_generation, 4)
        self.assertIsNone(state._rt_det_reset_pending)
        self.assertEqual(state.break_reason, "worker_backpressure")

    def test_slow_connect_worker_keeps_exclusive_usb_open_ownership(self) -> None:
        state = type("ConnectState", (), {})()
        state._connect_worker_thread = _ThreadState(True)
        alive = self.engine.ScopeWindow._connect_worker_is_alive
        self.assertTrue(alive(state))
        state._connect_worker_thread.alive = False
        self.assertFalse(alive(state))

        source = ENGINE_PATH.read_text(encoding="utf-8")
        tick_start = source.index("\tdef _tick(self)")
        tick_stop = source.index("\n\tdef ", tick_start + 2)
        tick_body = source[tick_start:tick_stop]
        self.assertIn("if self._connect_worker_is_alive():", tick_body)
        self.assertIn("жду освобождения USB", tick_body)
        connect_start = source.index("\tdef _try_connect(self, first=False)")
        connect_stop = source.index("\n\tdef ", connect_start + 2)
        connect_body = source[connect_start:connect_stop]
        self.assertLess(
            connect_body.index("if self._connect_worker_is_alive():"),
            connect_body.index("USBStream("),
        )
        owner_guard = connect_body[
            connect_body.index("if self._connect_worker_is_alive():"):
            connect_body.index("if self._connecting or self.stream is not None:")
        ]
        self.assertNotIn("self._connecting = True", owner_guard)
        self.assertIn("self._connect_worker_thread = worker_thread", connect_body)

        tick_start = source.index("\tdef _tick(self)")
        tick_stop = source.index("\n\tdef ", tick_start + 2)
        tick_body = source[tick_start:tick_stop]
        self.assertGreaterEqual(tick_body.count("self._process_connect_results()"), 2)

    def test_recovery_is_cancelled_when_frames_resume_during_probe(self) -> None:
        state = type("State", (), {})()
        state.num_group = _NumGroup()
        state.stream = _FakeStream()
        state.auto_reset_on_stall = True
        state.stall_reset_after = 2.0
        state.stall_reset_cooldown = 0.0
        state._stream_user_stopped = False
        state._stall_reset_inflight = False
        state._stall_reset_last_t = 0.0
        state.last_frame_t = 10.0
        state._stable_last_fault_recovery_cancelled = False
        state._last_fault_probe_result = None
        state.actions = []
        state.muted = False

        def note(_reason: str) -> bool:
            state.last_frame_t = time.time()
            state._last_fault_probe_result = {
                "verdict": "host_bulk_lost",
                "captured_at": time.time(),
                "stream_token": id(state.stream),
            }
            return True

        state._note_stream_fault = note
        state._current_stream_fault_probe = lambda newer_than=0.0: (
            self.engine.ScopeWindow._current_stream_fault_probe(state, newer_than=newer_than)
        )
        state._log_recovery_action = lambda action, reason="": state.actions.append((action, reason))
        state._mark_stream_good = lambda _reason="": None
        state._set_status = lambda *_args, **_kwargs: None
        state._mute_detection_after_fault = lambda _reason="": setattr(state, "muted", True)

        self.engine.ScopeWindow._maybe_auto_reset_on_stall(state, "нет кадров", 6.0)

        self.assertIn(("cancel_frames_resumed", "нет кадров"), state.actions)
        self.assertFalse(state.muted)
        self.assertFalse(getattr(state, "_auto_reset_just_occurred", False))
        self.assertTrue(state._stable_last_fault_recovery_cancelled)
        self.assertTrue(state._last_fault_probe_result["recovery_cancelled"])
        self.assertFalse(self.engine.ScopeWindow._recent_stream_fault_for_mode_transition(state))

    def test_stale_probe_is_not_reused_while_fresh_fault_probe_is_inflight(self) -> None:
        state = type("State", (), {})()
        state.num_group = _NumGroup()
        state.stream = _FakeStream()
        state.auto_reset_on_stall = True
        state.stall_reset_after = 2.0
        state.stall_reset_cooldown = 0.0
        state._stream_user_stopped = False
        state._stall_reset_inflight = False
        state._stall_reset_last_t = 0.0
        state.last_frame_t = 10.0
        state._last_fault_probe_result = {
            "verdict": "host_bulk_lost",
            "captured_at": 1.0,
        }
        state.actions = []
        state.muted = False
        state._note_stream_fault = lambda _reason: False
        state._log_recovery_action = lambda action, reason="": state.actions.append((action, reason))
        state._mute_detection_after_fault = lambda _reason="": setattr(state, "muted", True)

        self.engine.ScopeWindow._maybe_auto_reset_on_stall(state, "нет кадров", 6.0)

        self.assertFalse(state.muted)
        self.assertFalse(getattr(state, "_auto_reset_just_occurred", False))

    def test_direct_mode6_restore_does_not_start_via5_transition(self) -> None:
        state = type("State", (), {})()
        state._mode6_via5_pending = True
        state._mode6_via5_finish_t = 123.0
        state._mode6_via5_guard = False
        state.checked = []
        state.clicked = []
        state.extra = []
        state.via5_starts = 0
        state._set_mode_button_checked = lambda idx: state.checked.append(int(idx))

        def clicked(idx: int) -> None:
            state.clicked.append(int(idx))
            if int(idx) == 6 and not bool(state._mode6_via5_guard):
                state.via5_starts += 1

        state._num_clicked = clicked
        state._on_num_clicked_extra = lambda idx: state.extra.append(int(idx))

        self.engine.ScopeWindow._select_mode_direct(state, 6)

        self.assertEqual(state.checked, [6])
        self.assertEqual(state.clicked, [6])
        self.assertEqual(state.extra, [6])
        self.assertEqual(state.via5_starts, 0)
        self.assertFalse(state._mode6_via5_pending)
        self.assertEqual(state._mode6_via5_finish_t, 0.0)
        self.assertFalse(state._mode6_via5_guard)

    def test_recovery_uses_intended_mode_during_transient_mode5(self) -> None:
        target = self.engine.ScopeWindow._recovery_target_mode_idx
        state = type("State", (), {})()
        state.num_group = _NumGroupFive()
        state._restore_mode_after_buf_idx = 0
        state._mode6_via5_pending = True
        state._auto_reset_just_occurred = False
        state._auto_reset_restore_idx = None
        state._dc_autotune_active = False
        state._dc_autotune_return_mode = None
        self.assertEqual(target(state), 6)

        # A current explicit transition wins over a stale deferred-autostart
        # target left by an earlier BUF negotiation.
        state._restore_mode_after_buf_idx = 7
        self.assertEqual(target(state), 6)

        state._mode6_via5_pending = False
        self.assertEqual(target(state), 7)

        state._restore_mode_after_buf_idx = 0
        state._auto_reset_just_occurred = True
        state._auto_reset_restore_idx = 6
        self.assertEqual(target(state), 6)

        # An active recovery target is authoritative even if a stale BUF
        # transition still remembers another high-numbered mode.
        state._restore_mode_after_buf_idx = 7
        self.assertEqual(target(state), 6)

        state._auto_reset_just_occurred = False
        state._auto_reset_restore_idx = None
        state._dc_autotune_active = True
        state._dc_autotune_return_mode = 6
        self.assertEqual(target(state), 6)

        state._dc_autotune_active = False
        state._dc_autotune_return_mode = None
        state._restore_mode_after_buf_idx = 0
        self.assertEqual(target(state), 5)

    def test_prefire_dc_restore_waits_for_sustained_quiet(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn('"BMI30_DC_PREFIRE_RESTORE_DELAY_S", 10.0', source)
        self.assertIn("min(30.0, float(delay_s))", source)
        self.assertIn("dc_state_lock = threading.RLock()", source)
        self.assertIn("including one\n                    # on the other channel during Detection", source)
        self.assertIn("_host_dc_prefire_deadline_t", source)


if __name__ == "__main__":
    unittest.main()
