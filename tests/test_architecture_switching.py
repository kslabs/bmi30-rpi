from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MONO_SWITCH = ROOT / "switch_version.sh"
SPLIT_SWITCH = ROOT / "switch_bmi30_split_versions.sh"


class ArchitectureSwitchingTests(unittest.TestCase):
    def test_mono_switch_stops_both_split_services_before_launch(self) -> None:
        source = MONO_SWITCH.read_text(encoding="utf-8")
        run_start = source.index("run_version()")
        run_end = source.index("\n}\n", run_start)
        run_body = source[run_start:run_end]
        self.assertIn('sudo systemctl stop "$CORE_SERVICE" "$PORTAL_SERVICE"', source)
        self.assertLess(run_body.index("stop_split_runtime"), run_body.index('exec "$PYTHON_BIN"'))
        self.assertIn("pkill -f 'host/BMI30[.]200[.]py'", run_body)

    def test_split_switch_stops_mono_before_starting_services(self) -> None:
        source = SPLIT_SWITCH.read_text(encoding="utf-8")
        activation_start = source.index("activate_bundle()")
        activation_end = source.index("\nrun_core_service_action()", activation_start)
        activation = source[activation_start:activation_end]
        self.assertIn("stop_legacy_monolith", activation)
        self.assertLess(
            activation.index("stop_legacy_monolith"),
            activation.index('sudo systemctl stop "$CORE_SERVICE" "$PORTAL_SERVICE"'),
        )
        self.assertIn("BMI30[.]200[.]py", source)


if __name__ == "__main__":
    unittest.main()
