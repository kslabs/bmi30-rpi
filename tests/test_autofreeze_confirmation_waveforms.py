import importlib.util
import json
import os
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "host" / "BMI30.001.py.2026-08-25-1221"
ENGINE_PATH = ROOT / "host" / "BMI30.200.py.2026-08-25-1221"
PORTAL_PATH = ROOT / "hotspot_info_server.py"


def _load_source(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class _DetectorState:
    _det_confirm_phase_gate = 3
    _rt_det_confirm_count0 = 3
    _rt_det_confirm_count1 = 3

    def _det_channel_confirm_count(self, _channel: int) -> int:
        return 3


class _NumGroup:
    @staticmethod
    def checkedId() -> int:
        return 6


class AutoFreezeConfirmationWaveformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "host"))
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.engine = _load_source("bmi30_engine_autofreeze_test", ENGINE_PATH)
        cls.core = _load_source("bmi30_core_autofreeze_test", CORE_PATH)

    def test_detector_keeps_products_in_confirmation_order(self) -> None:
        state = _DetectorState()
        note = self.engine.ScopeWindow._det_note_confirmation_step
        products = (
            np.array([10.0, 11.0]),
            np.array([20.0, 21.0]),
            np.array([30.0, 31.0]),
        )

        note(state, 0, 0, None, 1, 40, True, True, source_seq=101, product=products[0])
        note(state, 0, 1, 40, 2, 41, True, True, source_seq=102, product=products[1])
        note(state, 0, 2, 41, 3, 42, True, True, source_seq=103, product=products[2])

        self.assertEqual(state._det_confirm_peaks0, (40, 41, 42))
        self.assertEqual(state._det_confirm_source_seqs0, (101, 102, 103))
        self.assertEqual(len(state._det_confirm_products0), 3)
        for saved, expected in zip(state._det_confirm_products0, products):
            np.testing.assert_array_equal(saved, expected)
            self.assertIsNot(saved, expected)

        replacement = np.array([90.0, 91.0])
        note(state, 0, 3, 42, 1, 80, True, False, source_seq=104, product=replacement)
        self.assertEqual(state._det_confirm_peaks0, (80,))
        self.assertEqual(len(state._det_confirm_products0), 1)
        np.testing.assert_array_equal(state._det_confirm_products0[0], replacement)

    def test_confirmation_phase_gate_uses_full_chain_span(self) -> None:
        step = self.engine._rt_detector_confirmation_step

        count, peak = step(0, None, 100, True, 50, True, ())
        self.assertEqual((count, peak), (1, 100))
        count, peak = step(count, peak, 145, True, 50, True, (100,))
        self.assertEqual((count, peak), (2, 145))

        # The last movement is only 45 samples, but the whole chain spans 90.
        count, peak = step(count, peak, 190, True, 50, True, (100, 145))
        self.assertEqual((count, peak), (1, 190))

        # The candidate that reset the old chain is immediately confirmation 1.
        count, peak = step(count, peak, 191, True, 50, True, (190,))
        self.assertEqual((count, peak), (2, 191))

    def test_confirmation_phase_gate_accepts_exact_window_boundary(self) -> None:
        count, peak = self.engine._rt_detector_confirmation_step(
            2,
            149,
            150,
            True,
            50,
            True,
            (100, 149),
        )
        self.assertEqual((count, peak), (3, 150))

    def test_zero_phase_gate_requires_identical_peak_samples(self) -> None:
        step = self.engine._rt_detector_confirmation_step
        self.assertEqual(step(1, 80, 80, True, 0, True, (80,)), (2, 80))
        self.assertEqual(step(1, 80, 81, True, 0, True, (80,)), (1, 81))

    def test_candidate_miss_and_frame_gap_keep_existing_reset_semantics(self) -> None:
        step = self.engine._rt_detector_confirmation_step
        self.assertEqual(step(2, 101, 102, False, 50, True, (100, 101)), (0, None))
        self.assertEqual(step(2, 101, 102, True, 50, False, (100, 101)), (1, 102))

    def test_missing_or_inconsistent_phase_history_resets_fail_closed(self) -> None:
        step = self.engine._rt_detector_confirmation_step
        self.assertEqual(step(2, 145, 190, True, 50, True, (145,)), (1, 190))
        self.assertEqual(step(2, 145, 146, True, 50, True, None), (1, 146))
        self.assertEqual(step(2, 145, 146, True, 50, True, (100, 144)), (1, 146))

    def test_phase_window_reset_replaces_saved_confirmation_chain(self) -> None:
        state = _DetectorState()
        state._det_confirm_phase_gate = 50
        state._det_confirm_peaks0 = (100, 145)
        state._det_confirm_source_seqs0 = (201, 202)
        state._det_confirm_products0 = (
            np.array([1.0, 2.0]),
            np.array([3.0, 4.0]),
        )
        replacement = np.array([9.0, 10.0])

        count, peak = self.engine._rt_detector_confirmation_step(
            2,
            145,
            190,
            True,
            50,
            True,
            state._det_confirm_peaks0,
        )
        self.engine.ScopeWindow._det_note_confirmation_step(
            state,
            0,
            2,
            145,
            count,
            peak,
            True,
            True,
            source_seq=203,
            product=replacement,
        )

        self.assertEqual(state._det_confirm_step_reason0, "phase_window_reset")
        self.assertEqual(state._det_confirm_peaks0, (190,))
        self.assertEqual(state._det_confirm_source_seqs0, (203,))
        self.assertEqual(len(state._det_confirm_products0), 1)
        np.testing.assert_array_equal(state._det_confirm_products0[0], replacement)

    def test_fire_snapshot_copies_complete_confirmation_chain(self) -> None:
        state = _DetectorState()
        state._web_det_flash_active0 = False
        state._web_det_flash_seq0 = 0
        state._web_det_fire_candidate_prod0 = np.array([30.0, 31.0])
        state._web_det_fire_candidate_frame0 = {
            "product": state._web_det_fire_candidate_prod0,
            "detector_frame_id": 77,
        }
        state._det_confirm_products0 = (
            np.array([10.0, 11.0]),
            np.array([20.0, 21.0]),
            np.array([30.0, 31.0]),
        )
        state._det_confirm_peaks0 = (40, 41, 42)
        state._det_confirm_source_seqs0 = (101, 102, 103)
        state._det_last_lvl0 = 300
        state._det_trigger0 = 200
        state._det_noise_ref0 = 100.0
        state._det_noise_avg0 = 80.0
        state._phase_peak_idx_adc0 = 42
        state._det_last_peak_position_ok0 = True
        state._det_last_noise_ok0 = True
        state._det_last_shape_ok0 = True
        state._det_output_min_s = lambda: 0.25
        state._det_noise_window_seconds = lambda: 1.0
        state._det_channel_auto_enabled = lambda _channel: False
        state._det_auto_floor_u16_value = lambda: 0.0
        state._det_auto_slope_value = lambda: 1.0
        state._det_manual_curve_ratio = lambda _channel, _noise: 2.0
        state._det_channel_ratio = lambda _channel: 2.0
        state._rt_detector_level_scale = lambda: 1.0

        self.engine.ScopeWindow._mark_web_detection_fire(state, True, False)

        saved = state._web_det_fire_frames0[1]["confirmation_products"]
        self.assertEqual(len(saved), 3)
        np.testing.assert_array_equal(saved[0], [10.0, 11.0])
        np.testing.assert_array_equal(saved[-1], [30.0, 31.0])
        snapshot = state._web_det_fire_snapshot0
        self.assertTrue(snapshot["threshold_passed"])
        self.assertEqual(snapshot["instant_snr"], 3.0)
        self.assertEqual(snapshot["instant_ratio_required"], 2.0)
        self.assertTrue(snapshot["instant_noise_ok"])
        self.assertTrue(snapshot["peak_position_ok"])
        self.assertEqual(snapshot["confirm_count"], 3)
        self.assertEqual(snapshot["confirm_required"], 3)

    def test_frame_api_exports_all_confirmation_products(self) -> None:
        scope = type("Scope", (), {})()
        scope.num_group = _NumGroup()
        scope.base_buf_len = 4
        scope.max_samples = 4
        scope.last_frame_t = 123.0
        scope.xcorr_norm_enabled = False
        scope.data_lock = None
        scope.data0_even = np.array([32768, 32769, 32770, 32771])
        scope.data0_odd = np.array([32768, 32767, 32766, 32765])
        scope.data1_even = np.array([32768, 32768, 32768, 32768])
        scope.data1_odd = np.array([32768, 32768, 32768, 32768])
        scale = self.core._product_display_scale()
        confirmation_products = tuple(
            np.array([0.0, scale * value, 0.0, 0.0])
            for value in (1000.0, 2000.0, 3000.0)
        )
        scope._web_det_fire_frames0 = {
            5: {
                "product": confirmation_products[-1],
                "confirmation_products": confirmation_products,
                "detector_frame_id": 77,
                "fire_timestamp": 10.0,
                "fire_channel": 0,
                "fire_seq": 5,
                "even": scope.data0_even,
                "odd": scope.data0_odd,
            }
        }
        scope._web_det_fire_products0 = {5: confirmation_products[-1]}

        api = object.__new__(self.core.ScopeApi)
        api.scope = scope
        frame = api.frame(max_points=600, fire_seq0=5)

        self.assertEqual(len(frame["prod_confirm0"]), 3)
        self.assertLess(frame["prod_confirm0"][0][1], frame["prod_confirm0"][1][1])
        self.assertEqual(frame["prod_confirm0"][-1], frame["prod0"])

        scope.xcorr_norm_enabled = True
        normalized = api.frame(max_points=600, fire_seq0=5)
        normalized_maxima = [max(product) for product in normalized["prod_confirm0"]]
        self.assertEqual(normalized_maxima[-1], 65535)
        self.assertTrue(
            normalized_maxima[0] < normalized_maxima[1] < normalized_maxima[2],
            normalized_maxima,
        )
        self.assertAlmostEqual(normalized_maxima[0] / normalized_maxima[-1], 1 / 3, places=3)
        self.assertAlmostEqual(normalized_maxima[1] / normalized_maxima[-1], 2 / 3, places=3)
        self.assertEqual(normalized["prod_norm0"]["normalization_scope"], "confirmation-group")
        self.assertAlmostEqual(normalized["prod_norm0"]["normalization_display_max"], 3000.0)

        packed = api.frame_binary(max_points=600, channels="upper", fire_seq0=5)
        header_length = int.from_bytes(packed[4:8], "little")
        header = json.loads(packed[8:8 + header_length].decode("utf-8"))
        self.assertEqual(
            header["confirmation_product_arrays0"],
            ["prod_confirm0_0", "prod_confirm0_1", "prod_confirm0_2"],
        )
        self.assertTrue(all(name in header["arrays"] for name in header["confirmation_product_arrays0"]))
        self.assertEqual(header["prod_norm0"]["normalization_scope"], "confirmation-group")
        self.assertAlmostEqual(header["prod_norm0"]["normalization_display_max"], 3000.0)
        payload_offset = 8 + header_length + (header_length % 2)
        count = int(header["count"])
        binary_arrays = {}
        for array_name in header["arrays"]:
            payload_end = payload_offset + (count * 2)
            binary_arrays[array_name] = np.frombuffer(
                packed[payload_offset:payload_end], dtype="<u2"
            )
            payload_offset = payload_end
        binary_maxima = [
            int(np.max(binary_arrays[name]))
            for name in header["confirmation_product_arrays0"]
        ]
        self.assertEqual(binary_maxima[-1], 65535)
        self.assertTrue(binary_maxima[0] < binary_maxima[1] < binary_maxima[2], binary_maxima)

    def test_browser_draws_older_products_with_lower_opacity(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("return .28+(.48*agePosition)", source)
        self.assertIn("showConfirmations=freezeMode==='auto'", source)
        self.assertIn("older results are darker and the final result is brightest", source)

    def test_fire_readout_shows_only_real_decision_gates_with_delayed_help(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        decision_source = source.split("function detectorDecisionParts", 1)[1].split(
            "function renderScopeReadoutParts", 1
        )[0]
        self.assertIn("AMP:", decision_source)
        self.assertIn("S/Ninst:", decision_source)
        self.assertIn("POS:", decision_source)
        self.assertIn("CONF:", decision_source)
        self.assertNotIn("S/N(avg):", decision_source)
        self.assertIn("const TOOLTIP_HOVER_DELAY_MS=2000", source)
        self.assertIn("scope-readout-part", source)
        readout_source = source.split("function detectorDecisionParts", 1)[1].split(
            "function setV7Readout", 1
        )[0]
        self.assertNotRegex(readout_source, r"[А-Яа-яЁё]")
        self.assertIn("FIRE — accepted detection", readout_source)
        self.assertIn("All AutoFreeze confirmation waveforms share one normalization maximum", readout_source)
        self.assertNotIn("not shown", readout_source)
        self.assertNotIn("not used here", readout_source)
        self.assertNotIn("no longer", readout_source)
        self.assertIn("function detectorLevelNumber(v)", source)
        self.assertIn("return String(Math.round(v))", source)
        self.assertNotIn("detectorDecimalNumber", source)
        self.assertIn("S/Ninst:'+detectorRatioText(instantSnr)", readout_source)

    def test_autofreeze_readout_is_latched_until_the_snapshot_changes(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("let scopeReadoutKeys={}", source)
        self.assertIn("if(scopeReadoutKeys[id]===readoutKey)return", source)
        self.assertIn("if(freezeMode==='live')frameRedrawNeeded=true", source)

    def test_peak_sample_numbers_follow_trace_brightness_and_rows(self) -> None:
        source = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("label=String(Math.round(marker.sample))", source)
        self.assertIn("labelCenter=marker.x-(spaceWidth*2)", source)
        self.assertIn("opacity:confirmationTraceOpacity(i,items.length),row:i", source)
        self.assertIn("drawPeakSampleLabel(ctx,entry.marker,color,entry.opacity,entry.row", source)
        self.assertNotIn("fillText('sample '+", source)

    def test_all_detector_paths_supply_confirmation_peak_history(self) -> None:
        source = ENGINE_PATH.read_text(encoding="utf-8")
        self.assertIn("confirmation_peaks=det_confirm_peaks[ch]", source)
        self.assertEqual(source.count("confirmation_peaks=getattr(self"), 2)

    def test_phase_gate_help_describes_whole_chain_window_and_reset(self) -> None:
        portal = PORTAL_PATH.read_text(encoding="utf-8")
        core = CORE_PATH.read_text(encoding="utf-8")
        self.assertIn("Maximum total span of peak sample numbers across the whole consecutive confirmation chain", portal)
        self.assertIn("The highest sample number minus the lowest must not exceed this value", portal)
        self.assertIn("the previous chain is reset and that candidate becomes confirmation 1", portal)
        self.assertNotIn("next detection maximum relative to the previous confirmed maximum", portal)
        self.assertIn("full-chain span", core)
        self.assertNotIn("next/previous gate", core)


if __name__ == "__main__":
    unittest.main()
