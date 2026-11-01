"""Unit tests for local update backup, confirmation and rollback behaviour."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import update_recovery


class UpdateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.install = self.base / "app"
        self.recovery = self.base / "state" / "recovery"
        self.install.mkdir()
        (self.install / "main.py").write_text("old version", encoding="utf-8")
        (self.install / "runtime").mkdir()
        (self.install / "runtime" / "python.bin").write_bytes(b"old runtime")

    def _prepare_and_start(self):
        info = update_recovery.prepare_update(self.install, recovery_dir=self.recovery)
        update_recovery.mark_installing(info["transaction_id"], recovery_dir=self.recovery)
        return info["transaction_id"]

    def test_prepare_creates_verified_local_snapshot(self):
        info = update_recovery.prepare_update(self.install, recovery_dir=self.recovery)
        self.assertEqual(info["status"], "prepared")
        self.assertEqual(info["file_count"], "2")
        self.assertTrue(Path(info["backup_dir"], "main.py").is_file())
        self.assertEqual(
            update_recovery.get_update_recovery_status(
                info["transaction_id"], recovery_dir=self.recovery
            )["status"],
            "prepared",
        )

    def test_rejects_recovery_directory_inside_installation(self):
        with self.assertRaises(ValueError):
            update_recovery.prepare_update(
                self.install, recovery_dir=self.install / ".recovery"
            )

    def test_rejects_symlinks_in_installation(self):
        link = self.install / "outside-link"
        try:
            link.symlink_to(self.base, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable in this environment")
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            update_recovery.prepare_update(self.install, recovery_dir=self.recovery)

    def test_failed_update_can_be_rolled_back(self):
        transaction_id = self._prepare_and_start()
        (self.install / "main.py").write_text("broken update", encoding="utf-8")
        (self.install / "new-file.txt").write_text("partial install", encoding="utf-8")

        result = update_recovery.rollback_update(
            transaction_id, recovery_dir=self.recovery
        )

        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.install / "main.py").read_text(encoding="utf-8"), "old version")
        self.assertEqual((self.install / "runtime" / "python.bin").read_bytes(), b"old runtime")
        self.assertFalse((self.install / "new-file.txt").exists())

    def test_interrupted_install_is_recovered(self):
        transaction_id = self._prepare_and_start()
        (self.install / "main.py").write_text("interrupted update", encoding="utf-8")

        results = update_recovery.recover_if_interrupted(recovery_dir=self.recovery)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["transaction_id"], transaction_id)
        self.assertEqual(results[0]["status"], "rolled_back")
        self.assertEqual((self.install / "main.py").read_text(encoding="utf-8"), "old version")

    def test_awaiting_health_check_is_still_rollback_eligible(self):
        transaction_id = self._prepare_and_start()
        update_recovery.mark_awaiting_health_check(
            transaction_id, recovery_dir=self.recovery
        )
        (self.install / "main.py").write_text("new version did not start", encoding="utf-8")

        result = update_recovery.rollback_update(
            transaction_id, recovery_dir=self.recovery
        )

        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.install / "main.py").read_text(encoding="utf-8"), "old version")

    def test_confirmed_update_discards_backup_and_is_not_rolled_back(self):
        transaction_id = self._prepare_and_start()
        update_recovery.mark_awaiting_health_check(
            transaction_id, recovery_dir=self.recovery
        )
        result = update_recovery.confirm_update(
            transaction_id, recovery_dir=self.recovery
        )
        self.assertEqual(result["status"], "confirmed")
        status = update_recovery.get_update_recovery_status(
            transaction_id, recovery_dir=self.recovery
        )
        self.assertEqual(status["status"], "confirmed")
        backup = self.recovery / transaction_id / "backup"
        self.assertFalse(backup.exists())
        self.assertEqual(
            update_recovery.recover_if_interrupted(recovery_dir=self.recovery), []
        )

    def test_corrupt_backup_is_never_restored(self):
        transaction_id = self._prepare_and_start()
        backup_file = self.recovery / transaction_id / "backup" / "main.py"
        backup_file.write_text("tampered backup", encoding="utf-8")
        (self.install / "main.py").write_text("current installation", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "integrity"):
            update_recovery.rollback_update(
                transaction_id, recovery_dir=self.recovery
            )
        self.assertEqual(
            (self.install / "main.py").read_text(encoding="utf-8"),
            "current installation",
        )

    def test_invalid_transaction_id_is_rejected(self):
        with self.assertRaises(ValueError):
            update_recovery.get_update_recovery_status(
                "../escape", recovery_dir=self.recovery
            )


    def test_interrupted_rollback_can_resume_after_directory_swap_started(self):
        transaction_id = self._prepare_and_start()
        (self.install / "main.py").write_text("partial new version", encoding="utf-8")
        tx_state = self.recovery / transaction_id / "state.json"
        import json
        state = json.loads(tx_state.read_text(encoding="utf-8"))
        state["status"] = "rollback_started"
        tx_state.write_text(json.dumps(state), encoding="utf-8")
        failed = self.install.parent / f".{self.install.name}.failed-{transaction_id}"
        self.install.rename(failed)

        results = update_recovery.recover_if_interrupted(recovery_dir=self.recovery)

        self.assertEqual(results[0]["status"], "rolled_back")
        self.assertEqual((self.install / "main.py").read_text(encoding="utf-8"), "old version")
        self.assertFalse(failed.exists())


    def test_internal_runtime_symlink_is_preserved_in_snapshot_and_rollback(self):
        link = self.install / "runtime" / "python-link"
        try:
            link.symlink_to("python.bin")
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable in this environment")
        transaction_id = self._prepare_and_start()
        link.unlink()
        link.symlink_to("missing-target")
        result = update_recovery.rollback_update(
            transaction_id, recovery_dir=self.recovery
        )
        self.assertEqual(result["status"], "rolled_back")
        restored = self.install / "runtime" / "python-link"
        self.assertTrue(restored.is_symlink())
        self.assertEqual(restored.readlink().as_posix(), "python.bin")


if __name__ == "__main__":
    unittest.main()
