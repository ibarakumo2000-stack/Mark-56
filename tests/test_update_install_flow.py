"""Tests for explicit-consent installer handoff without launching processes."""
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.update_installer import PreparedUpdate
from plugins.update_install_flow import handoff_to_installer


class InstallFlowTests(unittest.TestCase):
    def test_no_confirmation_never_launches_installer(self):
        update = PreparedUpdate("56.1.0", "MARK-LV-Setup-56.1.0.exe", "/missing", "a" * 64, "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
        result = handoff_to_installer(update, user_confirmed=False)
        self.assertEqual(result.status, "cancelled")

    def test_missing_file_is_rejected(self):
        update = PreparedUpdate("56.1.0", "MARK-LV-Setup-56.1.0.exe", "/missing/installer.exe", "a" * 64, "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
        with self.assertRaises(ValueError):
            handoff_to_installer(update, user_confirmed=True)

    @patch("plugins.update_install_flow.subprocess.Popen")
    @patch("plugins.update_install_flow.platform.system", return_value="Windows")
    def test_windows_launch_uses_argument_list_not_shell(self, _system, popen):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "MARK-LV-Setup-56.1.0.exe"
            path.write_bytes(b"test placeholder")
            update = PreparedUpdate("56.1.0", path.name, str(path), "a" * 64, "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
            result = handoff_to_installer(update, user_confirmed=True)
            self.assertEqual(result.status, "installer_started")
            popen.assert_called_once_with([str(path.resolve())], shell=False)

    @patch("plugins.update_install_flow.subprocess.Popen")
    @patch("plugins.update_install_flow.platform.system", return_value="Windows")
    def test_wrong_package_name_is_rejected(self, _system, popen):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "untrusted.exe"
            path.write_bytes(b"test placeholder")
            update = PreparedUpdate("56.1.0", path.name, str(path), "a" * 64, "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
            with self.assertRaises(ValueError):
                handoff_to_installer(update, user_confirmed=True)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
