"""Regression tests for D-Bus variant decoding in the GNOME ScreenCast adapter."""
import unittest

from plugins.wayland_screencast import _unwrap_variants


class FakeVariant:
    def __init__(self, value):
        self.signature = "v"
        self.value = value


class WaylandScreenCastVariantTests(unittest.TestCase):
    def test_unwraps_nested_dbus_variants_and_stream_tuples(self):
        payload = {
            "session_handle": FakeVariant("/org/freedesktop/portal/session/1"),
            "streams": FakeVariant([
                (42, {"position": FakeVariant((0, 0))}),
            ]),
        }
        result = _unwrap_variants(payload)
        self.assertEqual(result["session_handle"], "/org/freedesktop/portal/session/1")
        self.assertEqual(result["streams"][0][0], 42)
        self.assertEqual(result["streams"][0][1]["position"], (0, 0))

    def test_plain_values_remain_unchanged(self):
        value = {"streams": [(7, {})], "enabled": True}
        self.assertEqual(_unwrap_variants(value), value)


if __name__ == "__main__":
    unittest.main()
