"""Tests for the safe, download-only release update checker."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import update_checker as updater


class UpdateCheckerTests(unittest.TestCase):
    def test_version_tuple_accepts_release_version_and_rejects_dev_label(self):
        self.assertEqual(updater.version_tuple("v56.0.1"), (56, 0, 1))
        self.assertEqual(updater.version_tuple("56.0.0"), (56, 0, 0))
        self.assertIsNone(updater.version_tuple("dev"))

    def test_reads_stamped_version_before_installer_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "installer").mkdir()
            (root / "installer" / "version.txt").write_text("55.0.0", encoding="utf-8")
            self.assertEqual(updater.read_current_version(root), "55.0.0")
            (root / "VERSION").write_text("56.0.1\n", encoding="utf-8")
            self.assertEqual(updater.read_current_version(root), "56.0.1")

    def test_selects_platform_asset_for_each_supported_os(self):
        release = {"assets": [
            {"name": "MARK-LV-Setup-56.0.1.exe", "browser_download_url": "https://example.test/w.exe"},
            {"name": "MARK-LV-Linux-x86_64.tar.gz", "browser_download_url": "https://example.test/linux.tar.gz"},
            {"name": "MARK-LV-macOS-arm64.dmg", "browser_download_url": "https://example.test/mac-arm.dmg"},
            {"name": "MARK-LV-macOS-x86_64.dmg", "browser_download_url": "https://example.test/mac-intel.dmg"},
        ]}
        self.assertEqual(updater.select_release_asset(release, "Windows", "AMD64")["name"], "MARK-LV-Setup-56.0.1.exe")
        self.assertEqual(updater.select_release_asset(release, "Linux", "x86_64")["name"], "MARK-LV-Linux-x86_64.tar.gz")
        self.assertEqual(updater.select_release_asset(release, "Darwin", "arm64")["name"], "MARK-LV-macOS-arm64.dmg")
        self.assertEqual(updater.select_release_asset(release, "Darwin", "x86_64")["name"], "MARK-LV-macOS-x86_64.dmg")

    def test_no_update_when_current_version_matches_latest_release(self):
        release = {
            "tag_name": "v56.0.1", "html_url": "https://example.test/release",
            "draft": False, "prerelease": False, "assets": [],
        }
        with patch.object(updater, "fetch_latest_release", return_value=release):
            result = updater.check_for_update("56.0.1")
        self.assertEqual(result["status"], "current")

    def test_new_release_returns_download_link_but_does_not_install(self):
        release = {
            "tag_name": "v56.0.1",
            "html_url": "https://example.test/release",
            "body": "Bug fixes",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": "MARK-LV-Setup-56.0.1.exe",
                "browser_download_url": "https://example.test/jarvis.exe",
                "digest": "sha256:abc123",
            }],
        }
        with patch.object(updater, "fetch_latest_release", return_value=release):
            result = updater.check_for_update("56.0.0", system="Windows", machine="AMD64")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["download_url"], "https://example.test/jarvis.exe")
        self.assertEqual(result["sha256"], "sha256:abc123")
        self.assertNotIn("install", result)

    def test_missing_platform_asset_links_to_release_page(self):
        release = {
            "tag_name": "v56.0.1", "html_url": "https://example.test/release",
            "draft": False, "prerelease": False, "assets": [],
        }
        with patch.object(updater, "fetch_latest_release", return_value=release):
            result = updater.check_for_update("56.0.0", system="Linux", machine="aarch64")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["download_url"], "https://example.test/release")
        self.assertIsNone(result["asset_name"])

    def test_github_errors_are_reported_without_throwing_into_ui(self):
        with patch.object(updater, "fetch_latest_release", side_effect=RuntimeError("offline")):
            result = updater.check_for_update("56.0.0")
        self.assertEqual(result["status"], "error")
        self.assertIn("offline", result["message"])


if __name__ == "__main__":
    unittest.main()
