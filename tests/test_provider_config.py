from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import config_manager


class ProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_file = self.root / "api_keys.json"
        self.config_file.write_text(
            json.dumps({"gemini_api_key": "existing-key", "user_name": "Tester"}),
            encoding="utf-8",
        )
        self._dir_patch = patch.object(config_manager, "CONFIG_DIR", self.root)
        self._file_patch = patch.object(config_manager, "CONFIG_FILE", self.config_file)
        self._dir_patch.start()
        self._file_patch.start()

    def tearDown(self):
        self._file_patch.stop()
        self._dir_patch.stop()
        self.temp.cleanup()

    def test_default_engine_remains_gemini(self):
        self.assertEqual(config_manager.get_provider_mode(), "gemini")

    def test_provider_settings_merge_without_losing_existing_config(self):
        config_manager.save_providers(
            mode="pipeline",
            pipeline={"stt": "whisper@local", "llm": "openai_compat@ollama", "tts": "system_tts@system"},
            creds={"openai_compat@ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"}},
        )
        saved = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["gemini_api_key"], "existing-key")
        self.assertEqual(saved["user_name"], "Tester")
        self.assertEqual(config_manager.get_provider_mode(), "pipeline")
        self.assertEqual(config_manager.get_pipeline()["llm"], "openai_compat@ollama")
        self.assertEqual(config_manager.get_provider_config("openai_compat@ollama")["model"], "qwen2.5:7b")

    def test_individual_provider_updates_preserve_other_slots_and_credentials(self):
        config_manager.save_pipeline(stt="whisper@local", llm="openai_compat@ollama")
        config_manager.save_provider_config("openai_compat@ollama", {"model": "qwen2.5:7b"})
        config_manager.save_provider_config("openai_compat@ollama", {"base_url": "http://localhost:11434/v1"})
        self.assertEqual(config_manager.get_pipeline()["stt"], "whisper@local")
        cfg = config_manager.get_provider_config("openai_compat@ollama")
        self.assertEqual(cfg["model"], "qwen2.5:7b")
        self.assertEqual(cfg["base_url"], "http://localhost:11434/v1")

    def test_provider_catalogs_and_engine_import(self):
        from providers import registry
        from providers.engine_pipeline import PipelineEngine

        declarations = registry.discover()
        ids = {item["id"] for item in declarations}
        self.assertIn("openai_compat", ids)
        self.assertIn("whisper", ids)
        self.assertIn("piper", ids)
        self.assertTrue(callable(PipelineEngine))

    def test_native_panel_imports_when_qt_is_installed(self):
        try:
            import PyQt6  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyQt6 is installed in desktop packaging, not headless unit jobs")
        from providers.panel import ProviderSettingsDialog
        self.assertTrue(callable(ProviderSettingsDialog))

    def test_invalid_mode_falls_back_to_gemini(self):
        config_manager.save_provider_mode("not-a-provider")
        self.assertEqual(config_manager.get_provider_mode(), "gemini")


if __name__ == "__main__":
    unittest.main()
