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

    def test_test_suite_requires_explicit_execution_approval(self):
        result = self.call_plugin(operation="test", suite="unittest")
        self.assertIn("confirmed=true", result)

    def test_test_suite_is_allowlisted_after_approval(self):
        result = self.call_plugin(operation="test", suite="shell", confirmed=True, command="rm -rf /")
        self.assertIn("Blocked", result)

    def test_sensitive_files_are_not_read_or_edited(self):
        for name in (".env", "secrets/token.txt", "relay-data/relay.sqlite3", "signing.jks"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("secret", encoding="utf-8")
            result = self.call_plugin(operation="read", path=name)
            self.assertIn("protected", result.lower())

    def test_symlink_paths_are_rejected(self):
        outside = self.root.parent / "outside-mark56-workspace.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        result = self.call_plugin(operation="read", path="linked.txt")
        self.assertIn("symbolic links", result.lower())

    def test_missing_workspace_uses_dedicated_user_directory_not_current_directory(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"MARK56_WORKSPACE": "", "HOME": home}):
                result = json.loads(coding_workspace.run({"operation": "list"}))
            self.assertEqual(Path(result["root"]), Path(home) / "Mark56-workspaces")
            self.assertTrue((Path(home) / "Mark56-workspaces").is_dir())


if __name__ == "__main__":
    unittest.main()
