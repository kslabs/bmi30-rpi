from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "utilities" / "install_bmi30_agent_from_project.sh"
UPDATER = ROOT / "utilities" / "update_from_cloud.sh"
PUBLISHER = ROOT / "utilities" / "backup_to_cloud.sh"
COMMON = ROOT / "utilities" / "cloud_sync_common.sh"
SWITCHER = ROOT / "switch_bmi30_split_versions.sh"
MIGRATOR = ROOT / "utilities" / "migrate_system_between_disks.sh"


class CloudAgentBootstrapTests(unittest.TestCase):
    def test_disk_migration_preserves_hardware_bound_emmc_identity(self) -> None:
        source = MIGRATOR.read_text(encoding="utf-8")
        main = source[source.index("\nmain() {") :]

        self.assertLess(
            main.index("preserve_target_bmi30_identity"),
            main.index("partition_and_format_target"),
        )
        self.assertLess(
            main.index("copy_root_files"),
            main.index("restore_or_initialize_target_bmi30_identity"),
        )
        self.assertLess(
            main.index("restore_or_initialize_target_bmi30_identity"),
            main.index("prepare_target_bmi30_agent_boot"),
        )
        self.assertIn("--exclude=/var/backups/bmi30-agent/***", source)
        self.assertIn("bmi30_identity_has_auth_conflict", source)
        self.assertIn("-o TARGET 2>/dev/null", source)

    def test_emmc_boot_preparation_recreates_agent_backup_root_and_autostart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for path in (
                target / "etc" / "systemd" / "system",
                target / "etc" / "bmi30-agent",
                target / "opt" / "bmi30-agent",
            ):
                path.mkdir(parents=True, exist_ok=True)
            for path in (
                target / "etc" / "systemd" / "system" / "bmi30-agent.service",
                target / "etc" / "systemd" / "system" / "bmi30-tunnel.service",
                target / "etc" / "bmi30-agent" / "config.json",
                target / "opt" / "bmi30-agent" / "bmi30_agent.py",
                target / "opt" / "bmi30-agent" / "run_bmi30_tunnel.sh",
            ):
                path.write_text("test\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; '
                    'TARGET_ROLE=internal; TARGET_ROOT_MNT="$2"; '
                    "prepare_target_bmi30_agent_boot",
                    "agent-boot-test",
                    str(MIGRATOR),
                    str(target),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            backup_dir = target / "var" / "backups" / "bmi30-agent"
            tmpfiles_rule = target / "etc" / "tmpfiles.d" / "bmi30-agent.conf"
            enabled_link = (
                target
                / "etc"
                / "systemd"
                / "system"
                / "multi-user.target.wants"
                / "bmi30-agent.service"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(backup_dir.is_dir())
            self.assertEqual(backup_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                tmpfiles_rule.read_text(encoding="utf-8"),
                "# Recreate the private Agent backup root before bmi30-agent.service starts.\n"
                "d /var/backups/bmi30-agent 0700 root root -\n",
            )
            self.assertTrue(enabled_link.is_symlink())
            self.assertEqual(enabled_link.readlink(), Path("../bmi30-agent.service"))

    def test_disk_migration_identity_validation_uses_cpu_serial_binding(self) -> None:
        serial = "0123456789ABCDEF"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / "etc" / "bmi30-agent"
            state_dir = root / "var" / "lib" / "bmi30-agent"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    f"BMI30-{serial}@bmi30-tunnel",
                    "-f",
                    str(config_dir / "id_ed25519"),
                ],
                check=True,
            )
            (state_dir / "device_api_token").write_text("t" * 48 + "\n", encoding="ascii")
            (state_dir / "bound_raspberry_serial").write_text(serial + "\n", encoding="ascii")

            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; '
                    'validate_bmi30_identity_root "$2" "$3"; '
                    '! validate_bmi30_identity_root "$2" FEDCBA9876543210',
                    "identity-test",
                    str(MIGRATOR),
                    str(root),
                    serial,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_expanded_agent_package_is_valid(self) -> None:
        package_version = (ROOT / "host" / "BMI30_Agent" / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        result = subprocess.run(
            [str(HELPER), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(package_version, result.stdout)

    def test_old_updater_can_bootstrap_from_zip_when_txt_files_are_absent(self) -> None:
        package_version = (ROOT / "host" / "BMI30_Agent" / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "host" / "BMI30_Agent").mkdir(parents=True)
            (project / "utilities").mkdir()
            shutil.copy2(ROOT / "host" / "BMI30_Agent" / "VERSION", project / "host" / "BMI30_Agent" / "VERSION")
            package_name = f"BMI30_Agent_{package_version}.zip"
            shutil.copy2(ROOT / "host" / package_name, project / "host" / package_name)
            shutil.copy2(HELPER, project / "utilities" / HELPER.name)
            result = subprocess.run(
                [
                    str(project / "utilities" / HELPER.name),
                    "--check",
                    "--project-root",
                    str(project),
                ],
                cwd=project,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("использую целостный ZIP", result.stderr)

    def test_first_pass_v8_switcher_installs_agent_before_runtime_changes(self) -> None:
        source = SWITCHER.read_text(encoding="utf-8")
        start = source.index("activate_bundle()")
        end = source.index("\nrun_core_service_action()", start)
        activation = source[start:end]
        self.assertIn("install_project_agent", activation)
        self.assertLess(
            activation.index("install_project_agent"),
            activation.index("stop_legacy_monolith"),
        )

    def test_second_pass_updater_installs_agent_before_cloud_access(self) -> None:
        source = UPDATER.read_text(encoding="utf-8")
        start = source.index("main()")
        main = source[start:]
        self.assertLess(
            main.index("install_project_agent_from_cloud"),
            main.index("download_latest_marker"),
        )

    def test_runtime_only_cloud_reactivation_preserves_rollback_version(self) -> None:
        source = UPDATER.read_text(encoding="utf-8")
        start = source.index("restart_runtime_after_update()")
        end = source.index("\nwrite_rollback_state()", start)
        restart = source[start:end]
        self.assertIn("save_previous_release_state", restart)
        self.assertLess(
            restart.index("save_previous_release_state"),
            restart.index('"$switcher" --activate "$bundle_id"'),
        )

    def test_marker_carries_v8_compatibility_and_current_release_signatures(self) -> None:
        publisher = PUBLISHER.read_text(encoding="utf-8")
        updater = UPDATER.read_text(encoding="utf-8")
        self.assertIn("bmi30_v8_project_signature", publisher)
        self.assertIn("PROJECT_SIGNATURE_VERSION=%q", publisher)
        self.assertIn("RELEASE_CONTENT_SIGNATURE=%q", publisher)
        self.assertIn("RELEASE_SIGNATURE_VERSION=%q", publisher)
        self.assertIn("RELEASE_CONTENT_SIGNATURE", updater)
        self.assertIn("marker_local_signature", updater)

    def test_release_label_can_describe_project_update_without_new_runtime_bundle(self) -> None:
        publisher = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn('RELEASE_LABEL_OVERRIDE="${BMI30_RELEASE_LABEL_OVERRIDE:-}"', publisher)
        self.assertIn('--label)', publisher)
        self.assertIn('RELEASE_LABEL="$RELEASE_LABEL_OVERRIDE"', publisher)
        self.assertIn('--notes)', publisher)
        self.assertIn('RELEASE_NOTES="$RELEASE_NOTES_OVERRIDE"', publisher)

    def test_v8_signature_counts_registry_but_v9_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "docs").mkdir()
            (project / "host").mkdir()
            (project / "app.sh").write_text("one\n", encoding="utf-8")
            registry = project / "docs" / "BMI30_version_registry_google_sheet.csv"
            registry.write_text("old\n", encoding="utf-8")

            def signatures() -> tuple[str, str]:
                command = (
                    f"source {COMMON!s}; "
                    f"bmi30_project_signature {project!s}; printf ' '; "
                    f"bmi30_v8_project_signature {project!s}"
                )
                result = subprocess.run(
                    ["bash", "-c", command],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                current, compatibility = result.stdout.strip().split()
                return current, compatibility

            v9_before, v8_before = signatures()
            registry.write_text("new\n", encoding="utf-8")
            v9_after, v8_after = signatures()

        self.assertEqual(v9_before, v9_after)
        self.assertNotEqual(v8_before, v8_after)


if __name__ == "__main__":
    unittest.main()
