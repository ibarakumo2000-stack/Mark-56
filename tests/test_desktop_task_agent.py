"""Tests for bounded desktop task lifecycle and safety."""
import json
import unittest
from unittest.mock import patch

from plugins import desktop_task_agent as agent


class DesktopTaskAgentTests(unittest.TestCase):
    def setUp(self):
        with agent._state_lock:
            agent._state.update(active=False, task=None, step=0, started_at=None,
                                last_action=None, status="idle", stop_reason=None)
        agent._stop_event.clear()

    def test_start_requires_task(self):
        self.assertIn("Provide a task", agent.run({"operation": "start"}))

    def test_start_then_status(self):
        result = json.loads(agent.run({"operation": "start", "task": "Draw a penguin"}))
        self.assertTrue(result["active"])
        status = json.loads(agent.run({"operation": "status"}))
        self.assertEqual(status["task"], "Draw a penguin")
        self.assertTrue(status["active"])

    def test_stop_deactivates_task(self):
        agent.run({"operation": "start", "task": "Draw a penguin"})
        result = json.loads(agent.run({"operation": "stop"}))
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "stopped")

    def test_pause_and_resume(self):
        agent.run({"operation": "start", "task": "Draw a penguin"})
        paused = json.loads(agent.run({"operation": "pause"}))
        self.assertEqual(paused["status"], "paused")
        self.assertTrue(paused["active"])
        blocked = json.loads(agent.run({"operation": "step"}))
        self.assertEqual(blocked["status"], "paused")
        resumed = json.loads(agent.run({"operation": "resume"}))
        self.assertEqual(resumed["status"], "running")

    def test_consequential_task_waits_for_explicit_confirmation(self):
        result = json.loads(agent.run({"operation": "start", "task": "Delete my files"}))
        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertTrue(result["approval_required"])
        blocked = json.loads(agent.run({"operation": "step"}))
        self.assertEqual(blocked["status"], "awaiting_confirmation")
        denied = agent.run({"operation": "confirm", "confirmed": False})
        self.assertIn("explicit user approval", denied)
        approved = json.loads(agent.run({"operation": "confirm", "confirmed": True}))
        self.assertEqual(approved["status"], "running")

    def test_completed_state_cannot_be_forged(self):
        result = json.loads(agent.run({"operation": "completed"}))
        self.assertEqual(result["status"], "idle")
        self.assertIn("cannot be marked completed", result["message"])

    def test_request_stop_sets_interrupt_event(self):
        agent.request_stop()
        self.assertTrue(agent._stop_event.is_set())

    def test_step_without_active_task_does_nothing(self):
        result = json.loads(agent.run({"operation": "step"}))
        self.assertFalse(result["active"])

    def test_capture_failure_stops_and_never_claims_blank_screen(self):
        agent.run({"operation": "start", "task": "Draw a penguin"})
        with patch.object(agent, "_vision_step", side_effect=RuntimeError("display unavailable")):
            result = json.loads(agent.run({"operation": "step"}))
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "error")
        self.assertIn("couldn't reliably observe or control", result["message"])
        self.assertNotIn("blank", result["message"].lower())

    def test_app_launch_rejects_unapproved_app(self):
        with self.assertRaises(ValueError):
            agent._launch_app("bash")

    def test_model_cannot_propose_out_of_bounds_click(self):
        class FakePG:
            def size(self):
                return (100, 100)
            def click(self, *_args):
                raise AssertionError("must not click")
        with patch.object(agent.screen_agent, "_HAS_PYAUTOGUI", True), patch.object(
            agent.screen_agent, "pyautogui", FakePG()
        ):
            with self.assertRaises(ValueError):
                agent._perform({"action": "click", "x": 101, "y": 10})

    def test_action_budget_stops(self):
        agent.run({"operation": "start", "task": "Draw a penguin"})
        with agent._state_lock:
            agent._state["step"] = agent.MAX_TASK_STEPS
        result = json.loads(agent.run({"operation": "step"}))
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
