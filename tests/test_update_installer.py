"""Tests for platform selection and safe update staging primitives."""
import unittest
from unittest.mock import MagicMock, patch

from plugins import update_installer


class UpdateInstallerTests(unittest.TestCase):
    def test_platform_asset_selection(self):
        self.assertEqual(
            update_installer.platform_asset_names("Windows", "AMD64"),
            ("MARK-LV-Setup-{version}.exe",),
        )
        self.assertEqual(
            update_installer.platform_asset_names("Linux", "x86_64"),
            ("MARK-LV-Linux-x86_64.tar.gz",),
        )
        self.assertEqual(
            update_installer.platform_asset_names("Darwin", "arm64"),
            ("MARK-LV-macOS-arm64.dmg",),
        )
        self.assertEqual(update_installer.platform_asset_names("Linux", "aarch64"), ())

    def test_rejects_non_https_or_unapproved_hosts(self):
        for url in ("http://github.com/release", "https://example.com/release"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                update_installer._request(url, max_bytes=10)

    def test_release_url_is_pinned_to_official_repo(self):
        self.assertEqual(
            update_installer._safe_release_url(
                "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0"
            ),
            "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0",
        )
        self.assertEqual(
            update_installer._safe_release_url("https://evil.example/update"),
            update_installer.update_manager.RELEASES_PAGE,
        )


if __name__ == "__main__":
    unittest.main()
