"""Regression tests for the Android companion chat desktop-runtime wiring."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


MAIN_SOURCE = Path(__file__).resolve().parents[1] / "main.py"


class CompanionChatRuntimeWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"))

    def test_dashboard_publishes_companion_app_to_assistant_runtime(self):
        calls = [
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_companion_app_callback"
        ]
        self.assertTrue(
            any(
                node.args
                and isinstance(node.args[0], ast.Attribute)
                and node.args[0].attr == "_on_companion_app_changed"
                for node in calls
            ),
            "DashboardServer must notify the assistant when the secure companion app starts or stops.",
        )

    def test_live_session_starts_phone_chat_consumer(self):
        calls = [
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_task"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Attribute)
            and node.args[0].func.attr == "_process_companion_chat_messages"
        ]
        self.assertTrue(
            calls,
            "The active Live session must run the consumer that forwards phone messages to JARVIS.",
        )


if __name__ == "__main__":
    unittest.main()
