"""Unit tests for Mark 56 release checks; all HTTP responses are mocked."""
from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from plugins import update_manager


def _response(payload: dict, status: int = 200):
    response = MagicMock()
    entered = response.__enter__.return_value
    entered.status = status
    entered.read.return_value = json.dumps(payload).encode("utf-8")
    return response


class UpdateManagerTests(unittest.TestCase):
    @patch("plugins.update_manager.urllib.request.urlopen")
    def test_no_published_release_is_reported_as_up_to_date(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            update_manager.RELEASE_API, 404, "Not Found", {}, None
        )

        result = update_manager.check_for_update()

        self.assertEqual(result.status, "up_to_date")
        self.assertFalse(result.update_available)
        self.assertIn("up to date", result.message.lower())
        self.assertEqual(result.release_url, update_manager.RELEASES_PAGE)

    @patch("plugins.update_manager.urllib.request.urlopen")
    def test_same_version_is_up_to_date(self, urlopen):
        urlopen.return_value = _response({
            "tag_name": "v56.0.0",
            "html_url": "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.0.0",
            "draft": False,
            "prerelease": False,
        })

        result = update_manager.check_for_update("56.0.0")

        self.assertEqual(result.status, "up_to_date")
        self.assertFalse(result.update_available)
        self.assertEqual(result.latest_version, "56.0.0")
        self.assertEqual(result.message, "Mark 56 is up to date.")

    @patch("plugins.update_manager.urllib.request.urlopen")
    def test_newer_version_is_available_but_not_auto_installed(self, urlopen):
        urlopen.return_value = _response({
            "tag_name": "v56.1.0",
            "html_url": "https://github.com/ibarakumo2000-stack/Mark-56/releases/tag/v56.1.0",
            "draft": False,
            "prerelease": False,
        })

        result = update_manager.check_for_update("56.0.0")

        self.assertEqual(result.status, "update_available")
        self.assertTrue(result.update_available)
        self.assertIn("56.1.0", result.message)
        self.assertFalse(update_manager.as_dict(result)["auto_install_ready"])

    @patch("plugins.update_manager.urllib.request.urlopen")
    def test_network_failure_is_not_misreported_as_up_to_date(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("network offline")

        result = update_manager.check_for_update()

        self.assertEqual(result.status, "unavailable")
        self.assertFalse(result.update_available)
        self.assertNotIn("up to date", result.message.lower())
        self.assertIn("internet connection", result.message.lower())

    def test_invalid_current_version_is_reported(self):
        result = update_manager.check_for_update("not-a-version")

        self.assertEqual(result.status, "invalid_version")
        self.assertFalse(result.update_available)

    @patch("plugins.update_manager.urllib.request.urlopen")
    def test_plugin_result_exposes_status_for_ui(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            update_manager.RELEASE_API, 404, "Not Found", {}, None
        )

        result = json.loads(update_manager.run({"operation": "check"}))

        self.assertEqual(result["status"], "up_to_date")
        self.assertFalse(result["update_available"])
        self.assertIn("up to date", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
