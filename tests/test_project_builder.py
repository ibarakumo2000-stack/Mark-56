import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins import project_builder


class ProjectBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"MARK56_WORKSPACE": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_list_templates_without_provider(self):
        result = json.loads(project_builder.run({"operation": "list"}))
        self.assertEqual(result["templates"], ["game", "portfolio", "webapp"])

    def test_preview_does_not_write(self):
        result = json.loads(project_builder.run({
            "operation": "preview", "template": "portfolio", "name": "my-site"
        }))
        self.assertTrue(result["ok"])
        self.assertFalse((self.root / "my-site").exists())

    def test_create_requires_confirmation(self):
        result = json.loads(project_builder.run({
            "operation": "create", "template": "game", "name": "tap-game"
        }))
        self.assertFalse(result["ok"])
        self.assertFalse((self.root / "tap-game").exists())

    def test_create_generates_expected_files(self):
        result = json.loads(project_builder.run({
            "operation": "create", "template": "webapp", "name": "todo", "confirmed": True
        }))
        self.assertEqual(result["operation"], "created")
        self.assertTrue((self.root / "todo" / "index.html").is_file())
        self.assertTrue((self.root / "todo" / "app.js").is_file())
        self.assertTrue((self.root / "todo" / "style.css").is_file())

    def test_existing_directory_never_overwritten(self):
        dest = self.root / "already-there"
        dest.mkdir()
        (dest / "keep.txt").write_text("keep", encoding="utf-8")
        result = json.loads(project_builder.run({
            "operation": "create", "template": "portfolio",
            "name": "already-there", "confirmed": True
        }))
        self.assertFalse(result["ok"])
        self.assertEqual((dest / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_invalid_template_rejected(self):
        result = json.loads(project_builder.run({
            "operation": "preview", "template": "unknown", "name": "project"
        }))
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
