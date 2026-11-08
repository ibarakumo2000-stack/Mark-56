"""Unit tests for the autonomous screen observe/act/verify workflow."""
import json
import unittest
from unittest.mock import MagicMock, patch

from plugins import screen_task_workflow as workflow
from plugins import screen_agent as screen_agent_module


class ScreenTaskWorkflowTests(unittest.TestCase):
    def test_json_parser_accepts_fenced_json(self):
        result = workflow._json_object('```json\n{"status":"done","action":null}\n```')
        self.assertEqual(result["status"], "done")

    def test_json_parser_rejects_non_json(self):
        with self.assertRaises(ValueError):
            workflow._json_object("I think it is done.")

    def test_outward_or_destructive_tasks_require_approval(self):
        for task in ("send email to the client", "send a message to my friend", "delete the old project", "purchase this item"):
            self.assertFalse(workflow._policy_allows(task))

    def test_safe_local_ui_task_is_allowed(self):
        self.assertTrue(workflow._policy_allows("Open the settings window"))

    def test_enter_is_available_for_local_dialogs_but_shortcuts_are_blocked(self):
        pg = MagicMock()
        pg.size.return_value = (1280, 720)
        with patch.object(screen_agent_module, "_HAS_PYAUTOGUI", True), patch.object(
            screen_agent_module, "pyautogui", pg
        ):
            self.assertIn("enter", workflow._execute(
                {"type": "press", "key": "enter"}, 1280, 720
            ))
            pg.press.assert_called_once_with("enter")
            with self.assertRaisesRegex(ValueError, "shortcuts are blocked"):
                workflow._execute({"type": "press", "key": "ctrl+alt+delete"}, 1280, 720)

    def test_action_rejects_out_of_bounds_coordinates(self):
        pg = MagicMock()
        pg.size.return_value = (1280, 720)
        with patch.object(screen_agent_module, "_HAS_PYAUTOGUI", True), patch.object(
            screen_agent_module, "pyautogui", pg
        ):
            with self.assertRaisesRegex(ValueError, "outside"):
                workflow._execute({"type": "click", "x": 1300, "y": 10}, 1280, 720)
            pg.click.assert_not_called()

    def test_wayland_uses_ydotool_when_pyautogui_is_unavailable(self):
        from types import SimpleNamespace
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}), \
             patch.object(screen_agent_module, "_HAS_PYAUTOGUI", False), \
             patch.object(screen_agent_module, "pyautogui", None), \
             patch.object(workflow.shutil, "which", return_value="/usr/bin/ydotool"), \
             patch.object(workflow.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stderr=b""
             )) as run:
            result = workflow._execute({"type": "click", "x": 100, "y": 200}, 1280, 720)
        self.assertIn("click", result)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], [
            "/usr/bin/ydotool", "mousemove", "--absolute", "100", "200"
        ])
        self.assertEqual(commands[1], ["/usr/bin/ydotool", "click", "0xC0"])

    def test_run_task_observes_acts_verifies_and_stops_stream(self):
        frame = (b"png", 1280, 720)
        decisions = [
            {"status": "continue", "message": "The settings icon is visible.",
             "action": {"type": "click", "x": 100, "y": 100}},
            {"status": "done", "message": "The settings window is now visible.", "action": None},
        ]
        with patch.object(workflow, "_ensure_vision_ready", return_value="llava:7b"), \
             patch.object(workflow.wayland_screencast, "monitoring_active", side_effect=[False, True, False]), \
             patch.object(workflow.wayland_screencast, "start_monitoring", return_value="started"), \
             patch.object(workflow.wayland_screencast, "capture_monitor_frame", return_value=frame), \
             patch.object(workflow.wayland_screencast, "stop_monitoring", return_value="stopped") as stop, \
             patch.object(workflow, "_decision", side_effect=decisions), \
             patch.object(workflow, "_execute", return_value="click at (100, 100)"), \
             patch.object(workflow.time, "sleep"):
            result = json.loads(workflow.run_task("Open the settings window"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps_executed"], 1)
        self.assertFalse(result["screen_monitoring_active"])
        stop.assert_called_once()

    def test_run_task_always_stops_stream_after_capture_failure(self):
        with patch.object(workflow, "_ensure_vision_ready", return_value="llava:7b"), \
             patch.object(workflow.wayland_screencast, "monitoring_active", return_value=False), \
             patch.object(workflow.wayland_screencast, "start_monitoring", return_value="started"), \
             patch.object(workflow.wayland_screencast, "capture_monitor_frame", side_effect=RuntimeError("portal failed")), \
             patch.object(workflow.wayland_screencast, "stop_monitoring", return_value="stopped") as stop:
            result = json.loads(workflow.run_task("Open the settings window"))
        self.assertEqual(result["status"], "failed")
        stop.assert_called_once()

    def test_cancel_does_not_block_on_an_active_vision_step(self):
        with patch.object(workflow, "_task_is_running", return_value=True), patch.object(
            workflow.wayland_screencast, "stop_monitoring"
        ) as stop:
            result = workflow.cancel_task()
        self.assertIn("Cancellation requested", result)
        stop.assert_not_called()

    def test_task_requires_approval_before_opening_screen_stream(self):
        with patch.object(workflow.wayland_screencast, "start_monitoring") as start:
            result = json.loads(workflow.run_task("delete the old project"))
        self.assertEqual(result["status"], "approval_required")
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
