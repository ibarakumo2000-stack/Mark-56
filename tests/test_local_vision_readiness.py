"""Regression tests for local image-model readiness and task preflight."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core import local_model


class VisionReadinessTests(unittest.TestCase):
    def test_ready_when_configured_model_is_installed_and_local_mode_enabled(self):
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": True,
            "local_vision_model_name": "llava:7b",
        }), patch.object(local_model, "status", return_value={
            "ok": True, "enabled": True, "models": ["qwen2.5:7b", "llava:7b"],
        }):
            result = local_model.vision_status()
        self.assertTrue(result["ready"])
        self.assertTrue(result["installed"])
        self.assertEqual(result["model"], "llava:7b")

    def test_not_ready_when_configured_vision_model_is_missing(self):
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": True,
            "local_vision_model_name": "llava:7b",
        }), patch.object(local_model, "status", return_value={
            "ok": True, "enabled": True, "models": ["qwen2.5:7b"],
        }):
            result = local_model.vision_status()
        self.assertFalse(result["ready"])
        self.assertFalse(result["installed"])
        self.assertIn("setup_local_vision.py", result["message"])

    def test_not_ready_when_local_model_mode_is_disabled(self):
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": False,
            "local_vision_model_name": "llava:7b",
        }), patch.object(local_model, "status", return_value={
            "ok": True, "enabled": False, "models": ["llava:7b"],
        }):
            result = local_model.vision_status()
        self.assertFalse(result["ready"])
        self.assertIn("disabled", result["message"].lower())


class TaskAgentVisionGateTests(unittest.TestCase):
    def test_task_is_rejected_before_start_when_vision_model_is_unavailable(self):
        from plugins import desktop_task_agent

        with patch.object(desktop_task_agent.local_model, "vision_status", return_value={
            "ready": False,
            "message": "Vision model 'llava:7b' is not installed.",
        }):
            result = json.loads(desktop_task_agent.run({
                "operation": "start",
                "task": "Open Firefox and inspect the home page",
            }))
        self.assertEqual(result["status"], "vision_model_unavailable")
        self.assertFalse(result["active"])


if __name__ == "__main__":
    unittest.main()
