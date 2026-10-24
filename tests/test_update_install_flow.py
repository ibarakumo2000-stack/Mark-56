"""Tests for explicit-consent update handoff without launching real installers."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from plugins.update_installer import PreparedUpdate
from plugins.update_install_flow import handoff_to_installer

class InstallFlowTests(unittest.TestCase):
    def _staged(self, folder, name="MARK-LV-Setup-56.1.0.exe", data=b"verified test payload"):
        path = Path(folder) / name
        path.write_bytes(data)
        return PreparedUpdate("56.1.0", name, str(path), hashlib.sha256(data).hexdigest(),
            "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0"), path

    def test_no_confirmation_never_launches_installer(self):
        update = PreparedUpdate("56.1.0", "MARK-LV-Setup-56.1.0.exe", "/missing", "a" * 64,
            "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
        with patch("plugins.update_install_flow.subprocess.Popen") as popen:
            result = handoff_to_installer(update, user_confirmed=False)
        self.assertEqual(result.status, "cancelled")
        popen.assert_not_called()

    def test_missing_file_is_rejected(self):
        update = PreparedUpdate("56.1.0", "MARK-LV-Setup-56.1.0.exe", "/missing/installer.exe", "a" * 64,
            "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0")
        with self.assertRaises(ValueError):
            handoff_to_installer(update, user_confirmed=True)

    def test_changed_file_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            update, path = self._staged(folder)
            path.write_bytes(b"changed after verification")
            with patch("plugins.update_install_flow.platform.system", return_value="Windows"), patch("plugins.update_install_flow.subprocess.Popen") as popen:
                with self.assertRaises(ValueError):
                    handoff_to_installer(update, user_confirmed=True)
            popen.assert_not_called()

    def test_windows_launch_uses_argument_list_not_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            update, path = self._staged(folder)
            with patch("plugins.update_install_flow.platform.system", return_value="Windows"), patch("plugins.update_install_flow.subprocess.Popen") as popen:
                result = handoff_to_installer(update, user_confirmed=True)
            self.assertEqual(result.status, "installer_started")
            popen.assert_called_once_with([str(path.resolve())], shell=False)

    def test_wrong_package_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            update, _ = self._staged(folder, name="untrusted.exe")
            with patch("plugins.update_install_flow.platform.system", return_value="Windows"), patch("plugins.update_install_flow.subprocess.Popen") as popen:
                with self.assertRaises(ValueError):
                    handoff_to_installer(update, user_confirmed=True)
            popen.assert_not_called()

if __name__ == "__main__":
    unittest.main()
