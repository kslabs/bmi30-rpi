import importlib.util
import os
import sys
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import MethodType


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "host" / "BMI30.200.py.2026-08-25-1153"


def _load_source(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class _IndicatorState:
    def __init__(self) -> None:
        self._recovery_outputs_inhibited = False
        self.edges = []
        self.addressable_edges = []

    def _set_det_gpio(self, upper: bool, lower: bool) -> None:
        self.edges.append((bool(upper), bool(lower)))

    def _group_led_apply_current_state(self, force: bool = False) -> bool:
        self.addressable_edges.append(bool(force))
        return True


class _AddressableState:
    def __init__(self, engine) -> None:
        self._engine = engine
        self.event = ""
        self.commands = []
        self._recovery_outputs_inhibited = False
        self._sound_indicator_active = False
        self._sound_test_enabled = False
        self._sound_test_upper_enabled = False
        self._sound_test_lower_enabled = False
        self._group_led_manual_test_pattern = 0
        self._group_led_active_event = ""
        self._group_led_active_pattern = 0
        self._group_led_active_t = 0.0
        self._group_led_base_held_for_optic_gate = False

    def _group_led_detection_allowed(self) -> bool:
        return True

    def _group_led_clear_detection_state(self) -> bool:
        return False

    def _group_led_clear_neighbor_state_if_no_peer(self) -> bool:
        return False

    def _group_led_current_event(self) -> str:
        return self.event

    def _group_led_event_key(self, upper: bool, lower: bool, neighbor: bool = False) -> str:
        return self._engine.ScopeWindow._group_led_event_key(self, upper, lower, neighbor)

    def _group_led_desired_output_event(self) -> str:
        return self._engine.ScopeWindow._group_led_desired_output_event(self)

    def _group_led_patterns_snapshot(self):
        return {
            "upper_detection": 8,
            "lower_detection": 9,
            "both_detection": 12,
            "neighbor_upper_detection": 4,
            "neighbor_lower_detection": 5,
            "neighbor_both_detection": 6,
            "fault": 7,
        }

    def _send_led_pattern(self, pattern: int, update_ui: bool = False, force: bool = False) -> bool:
        self.commands.append(int(pattern))
        return True


class SoundLightSynchronizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "host"))
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.engine = _load_source("bmi30_engine_sound_light_sync_test", ENGINE_PATH)

    def test_pwm_edges_drive_light_on_and_off_from_one_source(self) -> None:
        state = _IndicatorState()
        callback = self.engine.ScopeWindow._on_sound_output_state

        callback(state, True)
        callback(state, False)

        self.assertEqual(state.edges, [(True, True), (False, False)])
        self.assertEqual(state.addressable_edges, [True, True])
        self.assertFalse(state._sound_indicator_active)

    def test_recovery_forces_light_off_even_if_pwm_reports_on(self) -> None:
        state = _IndicatorState()
        state._recovery_outputs_inhibited = True

        self.engine.ScopeWindow._on_sound_output_state(state, True)

        self.assertEqual(state.edges, [(False, False)])
        self.assertEqual(state.addressable_edges, [False])
        self.assertFalse(state._sound_indicator_active)

    def test_addressable_local_patterns_follow_sound_edges_and_location(self) -> None:
        state = _AddressableState(self.engine)
        apply_state = self.engine.ScopeWindow._group_led_apply_current_state_locked

        state.event = "upper_detection"
        apply_state(state)
        self.assertEqual(state.commands, [])

        state._sound_indicator_active = True
        apply_state(state, force=True)
        state.event = "lower_detection"
        apply_state(state)
        state.event = "both_detection"
        apply_state(state)
        state._sound_indicator_active = False
        apply_state(state, force=True)

        self.assertEqual(state.commands, [8, 9, 12, 0])

    def test_addressable_neighbor_detection_is_disabled_for_now(self) -> None:
        state = _AddressableState(self.engine)
        state._sound_indicator_active = True
        apply_state = self.engine.ScopeWindow._group_led_apply_current_state_locked

        state.event = "upper_detection"
        apply_state(state)

        for event in (
            "neighbor_upper_detection",
            "neighbor_lower_detection",
            "neighbor_both_detection",
        ):
            state.event = event
            state._group_led_neighbor_upper_active = "upper" in event or "both" in event
            state._group_led_neighbor_lower_active = "lower" in event or "both" in event
            apply_state(state)

        self.assertEqual(state.commands, [8, 0])

    def test_sound_test_selects_upper_or_lower_strip_pattern(self) -> None:
        state = _AddressableState(self.engine)
        state._sound_indicator_active = True
        state._sound_test_enabled = True
        state._sound_test_upper_enabled = True

        self.engine.ScopeWindow._group_led_apply_current_state_locked(state)
        state._sound_test_upper_enabled = False
        state._sound_test_lower_enabled = True
        self.engine.ScopeWindow._group_led_apply_current_state_locked(state)

        self.assertEqual(state.commands, [8, 9])

    def test_manual_and_fault_patterns_remain_independent_of_sound(self) -> None:
        state = _AddressableState(self.engine)
        apply_state = self.engine.ScopeWindow._group_led_apply_current_state_locked

        state._group_led_manual_test_pattern = 13
        apply_state(state)
        state._group_led_manual_test_pattern = 0
        state.event = "fault"
        apply_state(state)

        self.assertEqual(state.commands, [13, 7])

    def test_beeper_callback_reports_each_physical_edge_once(self) -> None:
        beeper = object.__new__(self.engine.PwmBeeper)
        beeper._output_state_callback = None
        beeper._reported_output_active = None
        beeper._hw_pwm_enabled = False
        edges = []

        self.engine.PwmBeeper.set_output_state_callback(beeper, edges.append)
        self.engine.PwmBeeper._notify_output_state(beeper, True)
        self.engine.PwmBeeper._notify_output_state(beeper, True)
        self.engine.PwmBeeper._notify_output_state(beeper, False)

        self.assertEqual(edges, [False, True, False])

    def test_gpio_request_is_serialized_and_preserved_without_hardware(self) -> None:
        state = type("State", (), {})()
        state._det_gpio_lock = threading.RLock()
        state._recovery_outputs_inhibited = False
        state._non_addressable_led_test_enabled = False
        state._non_addressable_led_enabled = True
        state._det_gpio_backend = None
        state._set_det_gpio_locked = MethodType(
            self.engine.ScopeWindow._set_det_gpio_locked,
            state,
        )

        self.engine.ScopeWindow._set_det_gpio(state, True, True)

        self.assertTrue(state._det_gpio_requested_a)
        self.assertTrue(state._det_gpio_requested_b)

    def test_obsolete_timer_based_gpio22_marker_is_removed(self) -> None:
        source = ENGINE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("_mark_gpio22_sound", source)


if __name__ == "__main__":
    unittest.main()
