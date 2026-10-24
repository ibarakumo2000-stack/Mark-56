"""Unit tests for the offline Ollama adapter; all HTTP calls are mocked."""
import json
import unittest
from unittest.mock import MagicMock, patch

from core import local_model


class LocalModelTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.object(local_model, "_settings", return_value={}):
            self.assertFalse(local_model.enabled())
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                local_model.generate("hello")

    def test_rejects_remote_url(self):
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": True, "local_model_base_url": "https://example.com"
        }):
            with self.assertRaisesRegex(ValueError, "loopback"):
                local_model.generate("hello", model="test")

    def test_generate_posts_to_local_ollama(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "  Hello offline.  "}}).encode()
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": True,
            "local_model_base_url": "http://127.0.0.1:11434",
            "local_model_name": "qwen2.5:7b"
        }), patch.object(local_model.urllib.request, "urlopen", return_value=response) as urlopen:
            result = local_model.generate("hello", timeout_ms=5000)
        self.assertEqual(result, "Hello offline.")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen2.5:7b")
        self.assertFalse(payload["stream"])

    def test_image_uses_vision_model_and_base64(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": '{"action":"complete"}'}}).encode()
        with patch.object(local_model, "_settings", return_value={
            "local_model_enabled": True, "local_model_base_url": "http://localhost:11434",
            "local_model_name": "qwen2.5:7b", "local_vision_model_name": "llava:7b"
        }), patch.object(local_model.urllib.request, "urlopen", return_value=response) as urlopen:
            result = local_model.generate("inspect", images=[b"png-bytes"])
        self.assertIn("complete", result)
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "llava:7b")
        self.assertEqual(payload["messages"][0]["images"], ["cG5nLWJ5dGVz"])


if __name__ == "__main__":
    unittest.main()
