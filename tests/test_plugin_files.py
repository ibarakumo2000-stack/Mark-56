"""Tests for adding/removing plugin files without executing plugin source."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import plugin_files
from memory import config_manager


def plugin_source(name: str, extra: str = "") -> str:
    return (
        f'PLUGIN = {{"name": "{name}", "description": "Test plugin"}}\n'
        "def run(parameters):\n"
        "    return 'ok'\n"
        f"{extra}"
    )


class PluginFileManagementTests(unittest.TestCase):
    def test_install_validates_and_copies_without_executing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "trusted_example.py"
            sentinel = root / "must_not_exist.txt"
            source.write_text(
                plugin_source("trusted_example", f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"),
                encoding="utf-8",
            )
            plugins_dir = root / "app" / "plugins"
            target, metadata = plugin_files.install_plugin_file(source, plugins_dir, persist_state=False)
            self.assertTrue(target.is_file())
            self.assertEqual(metadata["name"], "trusted_example")
            self.assertFalse(sentinel.exists(), "source code must not run during install")

    def test_rejects_invalid_plugin_and_does_not_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "not_a_plugin.py"
            source.write_text("def run(parameters):\n    return 'not enough'\n", encoding="utf-8")
            with self.assertRaises(plugin_files.PluginFileError):
                plugin_files.install_plugin_file(source, root / "plugins", persist_state=False)
            self.assertFalse((root / "plugins" / source.name).exists())

    def test_duplicate_plugin_name_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            plugins_dir.mkdir()
            existing = plugins_dir / "first.py"
            existing.write_text(plugin_source("same_name"), encoding="utf-8")
            source = root / "second.py"
            source.write_text(plugin_source("same_name"), encoding="utf-8")
            original = existing.read_text(encoding="utf-8")
            with self.assertRaises(plugin_files.PluginFileError):
                plugin_files.install_plugin_file(source, plugins_dir, persist_state=False)
            self.assertEqual(existing.read_text(encoding="utf-8"), original)
            self.assertFalse((plugins_dir / "second.py").exists())

    def test_remove_keeps_backup_and_accepts_legacy_plugin_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            plugins_dir.mkdir()
            filename = "legacy plugin (2).py"
            target = plugins_dir / filename
            target.write_text("invalid but removable plugin code", encoding="utf-8")
            backup = plugin_files.remove_plugin_file(
                filename, plugins_dir, plugin_name="legacy_plugin", persist_state=False
            )
            self.assertFalse(target.exists())
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_text(encoding="utf-8"), "invalid but removable plugin code")

    def test_removed_plugin_setting_is_persisted_without_wiping_other_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_dir = root / "config"
            cfg_file = cfg_dir / "api_keys.json"
            cfg_dir.mkdir()
            cfg_file.write_text('{"gemini_api_key": "keep-me"}', encoding="utf-8")
            with patch.object(config_manager, "CONFIG_DIR", cfg_dir), patch.object(config_manager, "CONFIG_FILE", cfg_file):
                config_manager.save_plugin_removed("custom_plugin.py", True, "custom_plugin")
                self.assertIn("custom_plugin.py", config_manager.get_removed_plugin_files())
                saved = config_manager.load_api_keys()
                self.assertEqual(saved["gemini_api_key"], "keep-me")
                self.assertFalse(saved["plugins_enabled"]["custom_plugin"])
                config_manager.save_plugin_removed("custom_plugin.py", False, "custom_plugin")
                self.assertNotIn("custom_plugin.py", config_manager.get_removed_plugin_files())
                self.assertTrue(config_manager.load_api_keys()["plugins_enabled"]["custom_plugin"])


if __name__ == "__main__":
    unittest.main()
