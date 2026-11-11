"""Tests for read-only desktop capability reporting."""
import os
import unittest
from unittest.mock import patch

from core.platform_awareness import format_platform_report, get_platform_report


class PlatformAwarenessTests(unittest.TestCase):
    def test_report_has_platform_and_capabilities(self):
        report = get_platform_report()
        self.assertIn("system", report)
        self.assertIn("session", report)
        self.assertTrue(report["capabilities"])
        for item in report["capabilities"]:
            self.assertIn(item["status"], {
                "available", "limited", "permission-required", "check", "unknown"
            })
            self.assertTrue(item["name"])
            self.assertTrue(item["detail"])

    def test_wayland_report_explains_portal_consent(self):
        with patch("platform.system", return_value="Linux"), \
             patch("platform.release", return_value="test"), \
             patch("platform.machine", return_value="x86_64"), \
             patch.dict(os.environ, {
                 "XDG_SESSION_TYPE": "wayland",
                 "XDG_CURRENT_DESKTOP": "GNOME",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/test-bus",
             }, clear=True):
            report = get_platform_report()
        screen = next(x for x in report["capabilities"] if x["name"] == "Screen capture")
        self.assertIn(screen["status"], {"limited", "permission-required"})
        self.assertIn("portal", screen["detail"].lower())
        self.assertIn("wayland", report["session"])

    def test_formatted_report_warns_that_permissions_are_not_verified(self):
        text = format_platform_report()
        self.assertIn("DESKTOP PLATFORM STATUS", text)
        self.assertIn("not proof", text.lower())


if __name__ == "__main__":
    unittest.main()
