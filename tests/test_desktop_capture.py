"""Regression tests for screenshot validation and blank-frame rejection."""
import io
import unittest
from unittest.mock import patch

from PIL import Image

from plugins import desktop_capture


def png_bytes(color, size=(320, 200), varied=False):
    image = Image.new("RGB", size, color)
    if varied:
        # A large, high-contrast patch simulates visible desktop content.
        for x in range(size[0] // 3):
            for y in range(size[1] // 2):
                image.putpixel((x, y), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class DesktopCaptureTests(unittest.TestCase):
    def test_rejects_uniform_black_frame(self):
        with self.assertRaisesRegex(RuntimeError, "almost uniform/blank"):
            desktop_capture._decode_png(png_bytes((0, 0, 0)))

    def test_rejects_uniform_nonblack_frame(self):
        with self.assertRaisesRegex(RuntimeError, "almost uniform/blank"):
            desktop_capture._decode_png(png_bytes((28, 28, 28)))

    def test_accepts_image_with_visible_content(self):
        data, width, height = desktop_capture._decode_png(
            png_bytes((20, 30, 40), varied=True)
        )
        self.assertGreater(len(data), 0)
        self.assertEqual((width, height), (320, 200))

    def test_rejects_tiny_image(self):
        with self.assertRaisesRegex(RuntimeError, "suspiciously small"):
            desktop_capture._decode_png(png_bytes((20, 30, 40), size=(16, 16), varied=True))

    def test_gnome_wayland_prefers_permission_aware_portal(self):
        good = (png_bytes((20, 30, 40), varied=True), 320, 200)
        with patch.dict("os.environ", {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
            "XDG_CURRENT_DESKTOP": "GNOME",
        }), patch.object(desktop_capture.shutil, "which", return_value="/usr/bin/gnome-screenshot"), patch.object(
            desktop_capture, "_portal_capture_wayland", return_value=good
        ) as portal, patch.object(desktop_capture, "_file_capture") as legacy:
            result = desktop_capture.capture_png()
        self.assertEqual(result, good)
        portal.assert_called_once()
        legacy.assert_not_called()

    def test_capture_tries_next_backend_after_blank_native_frame(self):
        good = (png_bytes((20, 30, 40), varied=True), 320, 200)
        with patch.dict("os.environ", {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
            "XDG_CURRENT_DESKTOP": "GNOME",
        }), patch.object(desktop_capture.shutil, "which", side_effect=lambda name: {
            "gnome-screenshot": "/usr/bin/gnome-screenshot",
            "spectacle": None,
        }.get(name)), patch.object(
            desktop_capture, "_file_capture",
            side_effect=RuntimeError("Capture returned an almost uniform/blank frame"),
        ), patch.object(desktop_capture, "_python_capture_mss", return_value=good) as mss:
            result = desktop_capture.capture_png()
        self.assertEqual(result, good)
        mss.assert_called_once()


if __name__ == "__main__":
    unittest.main()
