import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "switch_bmi30_split_versions.sh"


class SplitVersionMenuTests(unittest.TestCase):
    def test_list_contains_only_requested_month(self) -> None:
        env = dict(os.environ)
        env["BMI30_VERSION_MENU_MONTH"] = "2026-08"
        result = subprocess.run(
            [str(SCRIPT), "--list"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        ids = re.findall(r"\((\d{4}-\d{2}-[^)]+)\)", result.stdout)
        self.assertTrue(ids)
        self.assertTrue(all(version.startswith("2026-08-") for version in ids))
        self.assertNotIn("2026-07-31-1113", result.stdout)

    def test_interactive_menu_contains_only_versions_and_exit(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("interactive_menu()")
        end = source.index("\nmain()", start)
        menu = source[start:end]
        for removed_label in (
            "Запустить активный BMI30 core",
            "Остановить BMI30 core",
            "Перезапустить BMI30 core",
            "Показать подробный статус",
            "Проверить SHA-256 всех полных комплектов",
        ):
            self.assertNotIn(removed_label, menu)


if __name__ == "__main__":
    unittest.main()
