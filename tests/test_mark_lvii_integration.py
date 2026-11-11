"""Regression coverage for the Mark-LVII task and routine integration."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.outcome import done, failed, untrusted
from core.tasks.agents import parse
from core.tasks.store import TaskStore
from core.routines.rules import hhmm, parse_hhmm
from actions.background_tasks import TOOL as BACKGROUND_TASK_TOOL
from actions.routines import TOOL as ROUTINES_TOOL


class MarkLVIIIntegrationTests(unittest.TestCase):
    def test_agent_profiles_parse(self):
        root = Path(__file__).resolve().parents[1] / "agents"
        general = parse((root / "general.md").read_text(encoding="utf-8"))
        researcher = parse((root / "researcher.md").read_text(encoding="utf-8"))
        self.assertEqual(general.name, "general")
        self.assertEqual(researcher.name, "researcher")
        self.assertEqual(researcher.mode, "research")

    def test_task_store_persists_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp))
            task = {"id": "task_test_001", "status": "queued", "events": []}
            store.create(task)
            store.save_turns(task["id"], [{"role": "user", "text": "test"}])
            self.assertEqual(store.get(task["id"])["status"], "queued")
            self.assertEqual(store.load_turns(task["id"])[0]["text"], "test")
            store.update(task["id"], status="running")
            self.assertEqual(store.get(task["id"])["status"], "running")

    def test_routine_time_helpers(self):
        self.assertEqual(parse_hhmm("08:05"), (8, 5))
        self.assertEqual(hhmm("08:05"), "08:05")

    def test_action_tools_are_discoverable(self):
        self.assertEqual(BACKGROUND_TASK_TOOL["name"], "background_tasks")
        self.assertTrue(callable(BACKGROUND_TASK_TOOL["handler"]))
        self.assertEqual(ROUTINES_TOOL["name"], "routines")
        self.assertTrue(callable(ROUTINES_TOOL["handler"]))

    def test_outcome_status_is_explicit(self):
        self.assertIn("status=done", done("unit_test", checked=True))
        self.assertIn("status=failed", failed("unit_test", "expected failure"))
        self.assertIn("UNTRUSTED", untrusted("sample", "external text"))


if __name__ == "__main__":
    unittest.main()
