"""Security and behavior tests for the guarded coding workspace plugin."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins import coding_workspace


class CodingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        (self.root / "note.txt").write_text("original\n", encoding="utf-8")
        self.env = patch.dict(os.environ, {"MARK56_WORKSPACE": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call_plugin(self, **kwargs):
        return coding_workspace.run(kwargs)

    def test_read_returns_content_and_hash(self):
        result = json.loads(self.call_plugin(operation="read", path="note.txt"))
        self.assertEqual(result["content"], "original\n")
        self.assertEqual(result["sha256"], hashlib.sha256(b"original\n").hexdigest())

    def test_path_traversal_rejected(self):
        result = self.call_plugin(operation="read", path="../outside.txt")
        self.assertIn("rejected", result.lower())

    def test_propose_does_not_modify_file(self):
        result = json.loads(self.call_plugin(
            operation="propose", path="note.txt", content="updated\n"
        ))
        self.assertEqual(result["mode"], "proposal_only")
        self.assertIn("-original", result["diff"])
        self.assertEqual((self.root / "note.txt").read_text(), "original\n")

    def test_apply_requires_confirmation(self):
        result = self.call_plugin(operation="apply", path="note.txt", content="updated\n",
                                  expected_sha256=hashlib.sha256(b"original\n").hexdigest())
        self.assertIn("confirmed=true", result)
        self.assertEqual((self.root / "note.txt").read_text(), "original\n")

    def test_apply_rejects_stale_hash(self):
        result = self.call_plugin(operation="apply", path="note.txt", content="updated\n",
                                  expected_sha256="stale", confirmed=True)
        self.assertIn("changed since review", result)
        self.assertEqual((self.root / "note.txt").read_text(), "original\n")

    def test_apply_after_confirmation_and_matching_hash(self):
        result = json.loads(self.call_plugin(
            operation="apply", path="note.txt", content="updated\n",
            expected_sha256=hashlib.sha256(b"original\n").hexdigest(), confirmed=True
        ))
        self.assertTrue(result["ok"])
        self.assertEqual((self.root / "note.txt").read_text(), "updated\n")

    def test_test_suite_is_allowlisted(self):
        result = self.call_plugin(operation="test", suite="shell", command="rm -rf /")
        self.assertIn("Blocked", result)


if __name__ == "__main__":
    unittest.main()
