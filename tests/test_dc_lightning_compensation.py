import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


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


class _Stream:
    def __init__(self) -> None:
        self.sent_ms: list[int] = []

    def set_dc_speed_ms(self, settle_ms: int) -> None:
        self.sent_ms.append(int(settle_ms))


class _ModeFive:
    @staticmethod
    def checkedId() -> int:
        return 5


class _Scope:
    def __init__(self) -> None:
        self.stream = _Stream()
        self.num_group = _ModeFive()
        self.statuses: list[str] = []

    def _set_status(self, text: str, hold_sec: float = 0.0) -> None:
        self.statuses.append(str(text))


class DcLightningCompensationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = _load_source("bmi30_core_dc_lightning_test", CORE_PATH)

    @staticmethod
    def _config() -> dict[str, float]:
        return {
            "work_settle_s": 20.0,
            "acquisition_settle_s": 15.0,
            "detection_settle_s": 10.0,
            "startup_settle_s": 1.0,
            "lightning_timeout_s": 10.0,
        }

    def test_forced_lightning_repeats_1000_ms_packet(self) -> None:
        scope = _Scope()
        scope._host_dc_stream_identity = id(scope.stream)
        scope._host_dc_settle_ms = 1000

        ok = self.core._apply_default_dc_config(
            scope,
            profile="startup",
            force=True,
            cfg=self._config(),
        )

        self.assertTrue(ok)
        self.assertEqual(scope.stream.sent_ms, [1000])
        self.assertEqual(scope._host_dc_profile, "startup")

    def test_lightning_starts_fast_profile_not_work_profile(self) -> None:
        scope = _Scope()
        api = object.__new__(self.core.ScopeApi)
        api.scope = scope
        profiles: list[tuple[str, bool]] = []

        def apply_dc(_scope, **kwargs):
            profiles.append((str(kwargs.get("profile")), bool(kwargs.get("force"))))
            return True

        with (
            mock.patch.object(self.core, "_load_default_dc_config", return_value=self._config()),
            mock.patch.object(self.core, "_dc_lightning_offset_metric", return_value={"ready": False}),
            mock.patch.object(self.core, "_apply_default_dc_config", side_effect=apply_dc),
            mock.patch.object(self.core, "_call_qt_later_s"),
        ):
            ok = api._start_dc_startup_compensation(5, "test", force=True)

        self.assertTrue(ok)
        self.assertEqual(profiles, [("startup", True)])
        self.assertEqual(scope._host_dc_settle_ms if hasattr(scope, "_host_dc_settle_ms") else None, None)
        self.assertEqual(scope._host_dc_desired_profile, "work")
        self.assertEqual(scope._host_dc_lightning_completion_reason, "running")

    def test_portal_led_status_items_are_one_line_until_width_runs_out(self) -> None:
        source = (ROOT / "hotspot_info_server.py").read_text(encoding="utf-8")

        self.assertIn(".group-legend{{display:flex", source)
        self.assertIn("flex-wrap:wrap;width:100%;max-width:none", source)
        self.assertIn(".group-legend>span{{display:inline-flex", source)
        self.assertIn(".group-led-feedback>span{{display:inline-flex", source)
        self.assertGreaterEqual(source.count("flex:0 0 auto;white-space:nowrap"), 2)
        self.assertIn(".group-led-feedback{{display:flex", source)
        self.assertIn("flex-wrap:wrap", source)

    def test_group_table_uses_single_role_and_optic_status_rows(self) -> None:
        source = (ROOT / "hotspot_info_server.py").read_text(encoding="utf-8")

        self.assertIn('data-group-row="indicator"', source)
        self.assertIn('data-group-row="syncctl"', source)
        self.assertIn('data-group-row="node"', source)
        self.assertNotIn('data-group-row="role"', source)
        self.assertNotIn('data-group-row="optic"', source)
        self.assertNotIn('data-group-row="online"', source)
        self.assertNotIn("Current role", source)
        self.assertNotIn("Optic sensor", source)
        self.assertNotIn("RS485 online", source)
        self.assertNotIn("Assigned:", source)
        self.assertIn("_groupSetText(td, _capitalizeRole(d.role));", source)


if __name__ == "__main__":
    unittest.main()
