"""Regression tests for canonical desktop runtime feature wiring."""
from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnifiedRuntimeWiringTests(unittest.TestCase):
    def test_desktop_pairing_button_is_connected_to_jarvis_runtime(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        jarvis = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "JarvisLive"
        )
        initializer = next(
            node for node in jarvis.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
        )
        initializer_source = ast.get_source_segment(source, initializer) or ""
        self.assertIn(
            "self.ui.on_pair_device_clicked = self._make_device_pairing_url",
            initializer_source,
            "The Setup drawer's PAIR PHONE / DEVICE button must be wired to "
            "the same DashboardServer instance created by JarvisLive.",
        )

    def test_mail_plugin_imports_its_sibling_helper_as_a_package(self):
        source = (ROOT / "plugins" / "mail_manager.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports_package_helper = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "plugins"
            and any(alias.name == "_mail_core" and alias.asname == "core"
                    for alias in node.names)
            for node in tree.body
        )
        self.assertTrue(
            imports_package_helper,
            "mail_manager must import plugins/_mail_core.py through the "
            "plugins package so dynamic plugin discovery can resolve it.",
        )

    def test_gui_actions_remain_discoverable_without_x11_authorization(self):
        from core.action_loader import discover_actions

        filenames = (
            "computer_control.py",
            "computer_settings.py",
            "desktop.py",
            "send_message.py",
            "youtube_video.py",
        )
        with tempfile.TemporaryDirectory() as temp:
            action_dir = Path(temp)
            for filename in filenames:
                shutil.copy2(ROOT / "actions" / filename, action_dir / filename)
            logs = []
            registry = discover_actions(action_dir, set(), logger=logs.append)

        for name in (
            "computer_control",
            "computer_settings",
            "desktop_control",
            "send_message",
            "youtube_video",
        ):
            self.assertTrue(
                registry.has(name),
                f"{name} should remain registered if PyAutoGUI cannot connect "
                "to the current display; invocation can report that backend "
                "limitation without disabling the whole action.",
            )


if __name__ == "__main__":
    unittest.main()
