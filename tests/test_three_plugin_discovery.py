"""Regression tests for the three repaired Mark 56 plugins.

These tests exercise discovery and safe, non-destructive actions only. They do not
open the screen-sharing portal, simulate game input, or contact OpenAI.
"""
from __future__ import annotations

import importlib.util
import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"


def _load_module(filename: str, module_name: str):
    path = PLUGINS / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not import {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class ThreePluginDiscoveryTests(unittest.TestCase):
    def test_all_three_files_are_python_plugins_and_discovered(self):
        from core.plugin_loader import discover_plugins

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for filename in (
                "game_autoplay.py",
                "wayland_screencast.py",
                "website_studio_setup.py",
            ):
                source = PLUGINS / filename
                self.assertTrue(source.is_file(), f"Missing discoverable .py file: {filename}")
                self.assertEqual(source.suffix, ".py")
                shutil.copy2(source, directory / filename)

            logs = []
            registry = discover_plugins(directory, set(), logger=logs.append)
            records = {record["file"]: record for record in registry.list_for_ui()}
            expected = {
                "game_autoplay.py": "game_autoplay_plugin",
                "wayland_screencast.py": "wayland_screencast",
                "website_studio_setup.py": "website_studio_setup",
            }
            for filename, plugin_name in expected.items():
                self.assertIn(filename, records)
                self.assertTrue(records[filename]["valid"], records[filename]["error"])
                self.assertEqual(records[filename]["name"], plugin_name)
                self.assertTrue(registry.has(plugin_name), f"{plugin_name} was not registered")
            self.assertTrue(any("Plugin discovery complete: 3 active" in line for line in logs))

    def test_game_autoplay_status_does_not_start_game(self):
        module = _load_module("game_autoplay.py", "test_game_autoplay_repair")
        with patch.object(module._autoplayer, "is_running", return_value=False):
            result = module.run({"action": "status"})
        self.assertIn("not playing", result.lower())

    def test_wayland_status_and_stop_are_safe_without_a_portal_session(self):
        module = _load_module("wayland_screencast.py", "test_wayland_screencast_repair")
        with patch.object(module, "monitoring_active", return_value=False):
            self.assertIn("not active", module.run({"action": "status"}).lower())
        with patch.object(module, "stop_monitoring", return_value="Persistent ScreenCast session closed."):
            self.assertIn("closed", module.run({"action": "stop"}).lower())

    def test_wayland_capture_without_session_does_not_start_portal(self):
        module = _load_module("wayland_screencast.py", "test_wayland_screencast_capture_repair")
        with patch.object(module, "capture_monitor_frame", return_value=None), \
             patch.object(module, "start_monitoring") as start:
            result = module.run({"action": "capture"})
        self.assertIn("no screencast stream is active", result.lower())
        start.assert_not_called()

    def test_website_studio_status_never_returns_a_secret(self):
        module = _load_module("website_studio_setup.py", "test_website_studio_setup_repair")
        fake_credentials = type("FakeCredentials", (), {"is_configured": staticmethod(lambda: True)})
        core_package = importlib.import_module("core")
        with patch.object(core_package, "website_studio_credentials", fake_credentials(), create=True):
            result = module.run({"action": "status"})
        self.assertIn("configured", result.lower())
        self.assertNotIn("sk-", result)

    def test_website_studio_setup_requires_running_qt_app(self):
        module = _load_module("website_studio_setup.py", "test_website_studio_setup_no_qt_app")
        fake_credentials = type("FakeCredentials", (), {"is_configured": staticmethod(lambda: False)})
        core_package = importlib.import_module("core")
        with patch.object(core_package, "website_studio_credentials", fake_credentials(), create=True), \
             patch("PyQt6.QtWidgets.QApplication.instance", return_value=None):
            result = module.run({"action": "setup"})
        self.assertIn("running mark 56 desktop application", result.lower())


if __name__ == "__main__":
    unittest.main()
