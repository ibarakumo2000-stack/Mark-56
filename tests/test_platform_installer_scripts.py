"""Exercise the real Linux and macOS installer scripts on native runners."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import build_portable  # noqa: E402

CORE_FILES = (
    "update_recovery.py",
    "update_recovery_cli.py",
    "update_recovery_worker.py",
)


def make_runtime_shim(runtime_root: Path) -> None:
    binary = runtime_root / "bin" / "python3.12"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)


def make_mark56_tree(root: Path, version: str) -> Path:
    (root / "core").mkdir(parents=True)
    for filename in CORE_FILES:
        shutil.copy2(REPO / "core" / filename, root / "core" / filename)
    make_runtime_shim(root / "runtime")
    (root / "config").mkdir()
    (root / "config" / "defaults.json").write_text('{"fresh": true}', encoding="utf-8")
    if version == "56.0.2":
        (root / "config" / "new-default.json").write_text('{"added": true}', encoding="utf-8")
    (root / "plugins").mkdir()
    (root / "plugins" / "builtin.py").write_text("builtin-" + version, encoding="utf-8")
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "launch.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "launch.sh").chmod(0o755)
    return root


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux installer script runs on Ubuntu")
class LinuxInstallerScriptTests(unittest.TestCase):
    def test_install_upgrade_preserve_user_data_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            source_v1 = make_mark56_tree(base / "source-v1", "56.0.1")
            source_v2 = make_mark56_tree(base / "source-v2", "56.0.2")
            (source_v1 / "install.sh").write_text(build_portable.LINUX_INSTALLER, encoding="utf-8")
            (source_v2 / "install.sh").write_text(build_portable.LINUX_INSTALLER, encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            env.pop("XDG_STATE_HOME", None)

            def install(source: Path):
                return subprocess.run(
                    ["bash", str(source / "install.sh")],
                    env=env, capture_output=True, text=True, timeout=90,
                )

            first = install(source_v1)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            install_root = home / ".local/share/Programs/MARK-LV"
            self.assertEqual((install_root / "VERSION").read_text().strip(), "56.0.1")
            personal = install_root / "config" / "personal-settings.json"
            personal.write_text('{"user_data":"keep"}', encoding="utf-8")
            user_plugin = install_root / "plugins" / "user_plugin.py"
            user_plugin.write_text("custom-plugin", encoding="utf-8")

            second = install(source_v2)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual((install_root / "VERSION").read_text().strip(), "56.0.2")
            self.assertEqual(personal.read_text(encoding="utf-8"), '{"user_data":"keep"}')
            self.assertTrue((install_root / "config/new-default.json").is_file())
            self.assertEqual((install_root / "plugins/builtin.py").read_text(encoding="utf-8"), "builtin-56.0.2")
            self.assertEqual(user_plugin.read_text(encoding="utf-8"), "custom-plugin")

            recovery = home / ".local/state/mark56/update-recovery"
            transaction_id = (recovery / "latest.txt").read_text(encoding="ascii").strip()
            backup = recovery / transaction_id / "backup"
            failed = install_root.parent / f".{install_root.name}.failed-{transaction_id}"
            install_root.rename(failed)
            launcher = home / ".local/bin/mark56"
            rollback = subprocess.run(
                [str(launcher)], env=env, capture_output=True, text=True, timeout=90,
            )
            self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
            self.assertEqual((install_root / "VERSION").read_text().strip(), "56.0.1")
            self.assertEqual(personal.read_text(encoding="utf-8"), '{"user_data":"keep"}')
            self.assertFalse((install_root / "config/new-default.json").exists())
            self.assertEqual((install_root / "plugins/builtin.py").read_text(encoding="utf-8"), "builtin-56.0.1")
            self.assertEqual(user_plugin.read_text(encoding="utf-8"), "custom-plugin")


@unittest.skipUnless(sys.platform == "darwin", "macOS installer script runs on macOS")
class MacOSInstallerScriptTests(unittest.TestCase):
    def _make_app(self, root: Path, version: str) -> Path:
        app = root / "JARVIS.app"
        app_root = app / "Contents" / "Resources" / "MARK-LV"
        make_mark56_tree(app_root, version)
        (app / "Contents" / "Info.plist").write_text("test bundle metadata", encoding="utf-8")
        return app

    def test_install_upgrade_preserve_user_data_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home = base / "home"
            dmg1 = base / "dmg-v1"
            dmg2 = base / "dmg-v2"
            dmg1.mkdir()
            dmg2.mkdir()
            self._make_app(dmg1, "56.0.1")
            self._make_app(dmg2, "56.0.2")
            (dmg1 / "Install.command").write_text(build_portable.MAC_INSTALLER, encoding="utf-8")
            (dmg2 / "Install.command").write_text(build_portable.MAC_INSTALLER, encoding="utf-8")
            (dmg1 / "Install.command").chmod(0o755)
            (dmg2 / "Install.command").chmod(0o755)
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["JARVIS_INSTALLER_NO_LAUNCH"] = "1"

            def install(dmg: Path):
                return subprocess.run(
                    ["bash", str(dmg / "Install.command")],
                    env=env, capture_output=True, text=True, timeout=90,
                )

            first = install(dmg1)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            target = home / "Applications/JARVIS.app"
            app_root = target / "Contents/Resources/MARK-LV"
            self.assertEqual((app_root / "VERSION").read_text().strip(), "56.0.1")
            personal = app_root / "config" / "personal-settings.json"
            personal.write_text('{"user_data":"keep"}', encoding="utf-8")
            user_plugin = app_root / "plugins" / "user_plugin.py"
            user_plugin.write_text("custom-plugin", encoding="utf-8")

            second = install(dmg2)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual((app_root / "VERSION").read_text().strip(), "56.0.2")
            self.assertEqual(personal.read_text(encoding="utf-8"), '{"user_data":"keep"}')
            self.assertTrue((app_root / "config/new-default.json").is_file())
            self.assertEqual((app_root / "plugins/builtin.py").read_text(encoding="utf-8"), "builtin-56.0.2")
            self.assertEqual(user_plugin.read_text(encoding="utf-8"), "custom-plugin")

            recovery = home / "Library/Application Support/MARK-LV/update-recovery"
            transaction_id = (recovery / "latest.txt").read_text(encoding="ascii").strip()
            backup = recovery / transaction_id / "backup"
            backup_root = backup / "Contents/Resources/MARK-LV"
            failed = target.parent / f".{target.name}.failed-{transaction_id}"
            target.rename(failed)
            recovery_env = env.copy()
            recovery_env["JARVIS_RECOVERY_ONLY"] = "1"
            rollback = subprocess.run(
                ["bash", str(dmg2 / "Install.command")],
                env=recovery_env, capture_output=True, text=True, timeout=90,
            )
            self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
            restored_root = target / "Contents/Resources/MARK-LV"
            self.assertEqual((restored_root / "VERSION").read_text().strip(), "56.0.1")
            self.assertEqual((restored_root / "config/personal-settings.json").read_text(encoding="utf-8"),
                             '{"user_data":"keep"}')
            self.assertFalse((restored_root / "config/new-default.json").exists())
            self.assertEqual((restored_root / "plugins/builtin.py").read_text(encoding="utf-8"), "builtin-56.0.1")
            self.assertEqual((restored_root / "plugins/user_plugin.py").read_text(encoding="utf-8"), "custom-plugin")


if __name__ == "__main__":
    unittest.main()
