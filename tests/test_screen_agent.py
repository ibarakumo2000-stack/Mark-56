"""Safety and dispatch tests for the Mark 56 screen agent."""
import unittest
from unittest.mock import MagicMock, patch

from plugins import screen_agent


class ScreenAgentTests(unittest.TestCase):
    def test_plugin_loader_contract_is_present(self):
        self.assertEqual(screen_agent.PLUGIN["name"], "screen_agent")
        self.assertTrue(screen_agent.PLUGIN["description"])
        self.assertEqual(screen_agent.PLUGIN["parameters"]["type"], "OBJECT")
        self.assertEqual(screen_agent.run({"mode": "unknown"}), screen_agent.screen_agent({"mode": "unknown"}))

    def test_unknown_mode_is_rejected(self):
        self.assertIn("Unknown mode", screen_agent.screen_agent({"mode": "launch"}))

    def test_execute_requires_explicit_confirmation(self):
        with patch.object(screen_agent, "_HAS_PYAUTOGUI", True), patch.object(
            screen_agent, "pyautogui", MagicMock()
        ) as pg:
            result = screen_agent.screen_agent({
                "mode": "execute", "action": "click", "x": 10, "y": 10
            })
            self.assertIn("explicit confirmation", result)
            pg.click.assert_not_called()

    def test_execute_rejects_unallowlisted_action_even_confirmed(self):
        with patch.object(screen_agent, "_HAS_PYAUTOGUI", True), patch.object(
            screen_agent, "pyautogui", MagicMock()
        ) as pg:
            result = screen_agent.screen_agent({
                "mode": "execute", "action": "hotkey", "confirmed": True,
                "keys": "ctrl+alt+delete"
            })
            self.assertIn("Blocked", result)
            pg.hotkey.assert_not_called()

    def test_click_rejects_out_of_bounds(self):
        pg = MagicMock()
        pg.size.return_value = (800, 600)
        with patch.object(screen_agent, "_HAS_PYAUTOGUI", True), patch.object(
            screen_agent, "pyautogui", pg
        ):
            result = screen_agent.screen_agent({
                "mode": "execute", "action": "click", "confirmed": True,
                "x": 900, "y": 10
            })
            self.assertIn("outside the current screen", result)
            pg.click.assert_not_called()

    def test_propose_is_proposal_only(self):
        with patch.object(screen_agent, "_analyze", return_value="suggest click"):
            import json
            result = json.loads(screen_agent.screen_agent({
                "mode": "propose", "task": "Open the harmless test note"
            }))
            self.assertEqual(result["mode"], "proposal_only")
            self.assertIn("No desktop action has been executed", result["next_step"])


if __name__ == "__main__":
    unittest.main()
