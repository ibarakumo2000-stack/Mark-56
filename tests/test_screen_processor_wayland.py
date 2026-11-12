"""Tests for JARVIS live screen capture routing on Wayland."""
import unittest
from unittest.mock import patch

from actions import screen_processor


class ScreenProcessorWaylandTests(unittest.TestCase):
    def test_wayland_uses_permission_aware_desktop_capture(self):
        frame = (b"portal-png", 1366, 768)
        compressed = (b"vision-jpeg", "image/jpeg")
        with patch.dict("os.environ", {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
        }), patch(
            "plugins.desktop_capture.capture_png", return_value=frame
        ) as capture, patch.object(
            screen_processor, "_compress", return_value=compressed
        ) as compress, patch.object(
            screen_processor, "_MSS", False
        ):
            result = screen_processor._capture_screen()

        self.assertEqual(result, compressed)
        capture.assert_called_once_with()
        compress.assert_called_once_with(b"portal-png", "PNG")

    def test_wayland_capture_does_not_require_mss(self):
        with patch.dict("os.environ", {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
        }), patch(
            "plugins.desktop_capture.capture_png",
            return_value=(b"portal-png", 1366, 768),
        ), patch.object(
            screen_processor, "_compress",
            return_value=(b"vision-jpeg", "image/jpeg"),
        ), patch.object(screen_processor, "_MSS", False):
            try:
                screen_processor._capture_screen()
            except RuntimeError as exc:
                self.fail(f"Wayland capture should not require MSS: {exc}")


if __name__ == "__main__":
    unittest.main()
