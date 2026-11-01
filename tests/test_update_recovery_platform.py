"""Native-OS integration tests for installer recovery command hand-offs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RECOVERY = REPO / "core" / "update_recovery.py"
CLI = REPO / "core" / "update_recovery_cli.py"
WORKER = REPO / "core" / "update_recovery_worker.py"


class NativeInstallerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.recovery_dir = self.base / "recovery-state"

    def _seed_install(self, app_root: Path, nested: Path | None = None):
        root = nested if nested else app_root
        (root / "core").mkdir(parents=True)
        (root / "runtime").mkdir(parents=True)
        shutil.copy2(RECOVERY, root / "core" / "update_recovery.py")
        shutil.copy2(CLI, root / "core" / "update_recovery_cli.py")
        shutil.copy2(WORKER, root / "core" / "update_recovery_worker.py")
        (root / "main.py").write_text("original version", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "settings.json").write_text('{"keep": true}', encoding="utf-8")
        return root

    def _run(self, python: str, script: Path, *args: str):
        return subprocess.run(
            [python, str(script), *args, "--recovery-dir", str(self.recovery_dir)],
            capture_output=True, text=True, check=True, timeout=30,
        )

    def test_linux_windows_style_app_directory_upgrade_and_rollback(self):
        install = self.base / "Programs" / "MARK-LV"
        app = self._seed_install(install)
        prepare = self._run(sys.executable, app / "core" / "update_recovery_cli.py",
                            "--prepare", str(install))
        tx = json.loads(prepare.stdout)["transaction_id"]
        self._run(sys.executable, app / "core" / "update_recovery_cli.py", "--mark-awaiting")
        (install / "main.py").write_text("broken update", encoding="utf-8")
        (install / "config" / "settings.json").write_text('{"keep": false}', encoding="utf-8")
        backup_cli = self.recovery_dir / tx / "backup" / "core" / "update_recovery_cli.py"
        self._run(sys.executable, backup_cli, "--rollback-id", tx)
        self.assertEqual((install / "main.py").read_text(encoding="utf-8"), "original version")
        self.assertEqual((install / "config" / "settings.json").read_text(encoding="utf-8"), '{"keep": true}')

    def test_macos_app_bundle_layout_rolls_back_whole_bundle(self):
        bundle = self.base / "Applications" / "JARVIS.app"
        nested = bundle / "Contents" / "Resources" / "MARK-LV"
        self._seed_install(bundle, nested)
        info = bundle / "Contents" / "Info.plist"
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("old bundle metadata", encoding="utf-8")

        prepare = self._run(sys.executable, nested / "core" / "update_recovery_cli.py",
                            "--prepare", str(bundle))
        tx = json.loads(prepare.stdout)["transaction_id"]
        self._run(sys.executable, nested / "core" / "update_recovery_cli.py", "--mark-awaiting")
        (info).write_text("new broken bundle metadata", encoding="utf-8")
        (nested / "main.py").write_text("broken app", encoding="utf-8")

        backup_cli = self.recovery_dir / tx / "backup" / "Contents" / "Resources" / "MARK-LV" / "core" / "update_recovery_cli.py"
        self._run(sys.executable, backup_cli, "--rollback-id", tx)

        self.assertEqual(info.read_text(encoding="utf-8"), "old bundle metadata")
        self.assertEqual((nested / "main.py").read_text(encoding="utf-8"), "original version")

    def test_cli_refuses_to_upgrade_without_a_valid_existing_runtime(self):
        install = self.base / "incomplete-install"
        install.mkdir()
        (install / "partial.txt").write_text("incomplete", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CLI), "--prepare", str(install),
             "--recovery-dir", str(self.recovery_dir)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
