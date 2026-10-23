"""Tests for offline project scaffolding, update checks, and network scan scope."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from plugins import local_project_builder as builder
from plugins import linux_network_audit as audit
from plugins import update_manager as updater


class LocalProjectBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.environ.get("MARK56_WORKSPACE")
        os.environ["MARK56_WORKSPACE"] = self.tmp.name
        self.addCleanup(self._restore)

    def _restore(self):
        if self.old is None:
            os.environ.pop("MARK56_WORKSPACE", None)
        else:
            os.environ["MARK56_WORKSPACE"] = self.old

    def test_preview_does_not_create_files(self):
        result = json.loads(builder.run({"template": "portfolio", "project_name": "site"}))
        self.assertTrue(result["needs_confirmation"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "site")))

    def test_confirmed_builder_creates_offline_project(self):
        result = json.loads(builder.run({"template": "game", "project_name": "demo", "confirmed": True}))
        self.assertTrue(result["ok"])
        self.assertFalse(result["provider_required"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "demo", "game.js")))

    def test_existing_folder_is_never_overwritten(self):
        os.mkdir(os.path.join(self.tmp.name, "existing"))
        result = json.loads(builder.run({"template": "portfolio", "project_name": "existing", "confirmed": True}))
        self.assertIn("nothing was overwritten", result["error"])

    def test_rejects_path_traversal(self):
        result = json.loads(builder.run({"template": "game", "project_name": "../outside", "confirmed": True}))
        self.assertIn("Project name", result["error"])


class NetworkAuditScopeTests(unittest.TestCase):
    def test_rejects_public_target(self):
        with self.assertRaises(ValueError):
            audit._validate_target("8.8.8.8")

    def test_rejects_oversized_private_network(self):
        with self.assertRaises(ValueError):
            audit._validate_target("10.0.0.0/8")

    def test_accepts_bounded_private_target(self):
        self.assertEqual(audit._validate_target("192.168.1.0/24"), "192.168.1.0/24")

    @patch("plugins.linux_network_audit.platform.system", return_value="Windows")
    def test_windows_is_disabled(self, _mock):
        result = json.loads(audit.run({"mode": "hosts", "target": "192.168.1.0/24", "confirmed": True}))
        self.assertFalse(result["available"])


class UpdateManagerTests(unittest.TestCase):
    def test_version_comparison_parser(self):
        self.assertEqual(updater._version("v56.1.2"), (56, 1, 2))
        self.assertIsNone(updater._version("56.1"))
        self.assertIsNone(updater._version("latest"))

    def test_check_failure_does_not_claim_update_installed(self):
        with patch("plugins.update_manager.urllib.request.urlopen", side_effect=OSError("offline")):
            status = updater.check_for_update()
        self.assertFalse(status.update_available)
        self.assertIn("not changed", status.message)
        self.assertFalse(updater.as_dict(status)["auto_install_ready"])


if __name__ == "__main__":
    unittest.main()
