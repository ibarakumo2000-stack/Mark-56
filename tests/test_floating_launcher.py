"""Regression tests for the floating desktop launcher integration."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FloatingLauncherWiringTests(unittest.TestCase):
    def test_launcher_is_the_default_surface_when_configured(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        jarvis_ui = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "JarvisUI"
        )
        init = next(
            node for node in jarvis_ui.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        init_source = ast.get_source_segment(source, init) or ""
        self.assertIn("self.launcher = FloatingLauncher", init_source)
        self.assertIn("if self._win._ready:", init_source)
        self.assertIn("self.launcher.show_launcher()", init_source)
        self.assertIn("self._win.show()", init_source)

    def test_launcher_commands_use_the_existing_live_runtime_callback(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("self.launcher.on_command = cb", source)
        self.assertIn("self.launcher.on_mute = self._win._toggle_mute", source)
        self.assertIn("self.launcher.on_open = self._show_full_interface", source)

    def test_final_live_transcript_is_forwarded_to_launcher(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        jarvis = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "JarvisLive"
        )
        receive = next(
            node for node in jarvis.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_receive_audio"
        )
        receive_source = ast.get_source_segment(source, receive) or ""
        self.assertIn("self.ui.show_launcher_reply(full_out)", receive_source)
        self.assertIn("if full_out:", receive_source)

    def test_launcher_is_draggable_and_can_collapse_or_hide_to_tray(self):
        source = (ROOT / "floating_launcher.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        widget = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "FloatingLauncher"
        )
        methods = {node.name for node in widget.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent"} <= methods)
        self.assertTrue({"toggle_expanded", "hide_to_tray", "show_launcher"} <= methods)
        self.assertIn("WindowStaysOnTopHint", source)
        self.assertIn("QSystemTrayIcon", source)


if __name__ == "__main__":
    unittest.main()
