"""Regression checks for the Windows in-place upgrade contract.

These static checks complement the Windows CI build, which compiles the Inno
Setup script and exercises the packaged runtime on a real Windows runner.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer" / "MarkLV.iss"


class InstallerUpgradeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_installer_has_one_inno_code_section(self):
        sections = re.findall(r"(?m)^\\[Code\\]\\s*$", self.source)
        self.assertEqual(
            len(sections),
            1,
            "Inno Setup must have one [Code] section; declarations and handlers "
            "belong together so the release build can compile.",
        )

    def test_installer_keeps_stable_identity_and_previous_install_path(self):
        self.assertIn("AppId={#AppGuid}", self.source)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\MARK-LV", self.source)
        self.assertIn("UsePreviousAppDir=yes", self.source)
        self.assertIn("Uninstallable=yes", self.source)

    def test_upgrade_cleanup_only_replaces_bundled_runtime(self):
        section = self.source.split("[InstallDelete]", 1)[1].split("[UninstallDelete]", 1)[0]
        self.assertIn('Name: "{app}\\runtime"', section)
        for user_data in ("config", "memory", "cache", "uploads", "plugins"):
            self.assertNotIn(
                f'Name: "{{app}}\\{user_data}"',
                section,
                f"Upgrade must not delete the user's {user_data} folder.",
            )

    def test_user_data_removal_is_an_explicit_uninstall_choice(self):
        self.assertIn("Do you also want to delete your personal data?", self.source)
        self.assertIn("MB_YESNO or MB_DEFBUTTON2", self.source)
        self.assertIn("WipeData := False", self.source)


if __name__ == "__main__":
    unittest.main()
