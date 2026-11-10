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

    def test_closing_main_window_exits_launcher_and_application(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_window = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        close_event = next(
            node for node in main_window.body
            if isinstance(node, ast.FunctionDef) and node.name == "closeEvent"
        )
        close_source = ast.get_source_segment(source, close_event) or ""
        self.assertIn("launcher.close()", close_source)
        self.assertIn("event.accept()", close_source)
        self.assertIn("app.quit()", close_source)
        self.assertNotIn("launcher.show_launcher()", close_source)

    def test_launcher_is_a_transparent_holographic_face_not_a_panel(self):
        source = (ROOT / "floating_launcher.py").read_text(encoding="utf-8")
        self.assertIn("WA_TranslucentBackground", source)
        self.assertIn("def paintEvent", source)
        self.assertIn("self._avatar.paint(", source)
        self.assertNotIn("QFrame", source)
        self.assertNotIn("QVBoxLayout", source)
        self.assertNotIn("QLineEdit", source)

    def test_hologram_reuses_the_main_holo_avatar(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("self.launcher.set_avatar(", source)
        self.assertIn("self._win.hud._avatar", source)
        self.assertIn("QColor(C.PRI)", source)

    def test_right_click_menu_exposes_quick_chat_voice_and_exit(self):
        source = (ROOT / "floating_launcher.py").read_text(encoding="utf-8")
        self.assertIn("def contextMenuEvent", source)
        self.assertIn("def _build_context_menu", source)
        self.assertIn("Quick chat with JARVIS", source)
        self.assertIn("Mute microphone", source)
        self.assertIn("Open full JARVIS interface", source)
        self.assertIn("Quit JARVIS completely", source)
        self.assertIn("QInputDialog.getText", source)

    def test_hologram_speech_and_blink_are_driven_by_live_hud_avatar(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("self.hud.speaking = (state == \"SPEAKING\")", source)
        self.assertIn("self._win.hud._avatar", source)
        avatar_source = (ROOT / "core/avatar.py").read_text(encoding="utf-8")
        self.assertIn("self._blink_at", avatar_source)
        self.assertIn("self._mouth", avatar_source)
        self.assertIn("def step(", avatar_source)
        self.assertIn("def paint(", avatar_source)

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
