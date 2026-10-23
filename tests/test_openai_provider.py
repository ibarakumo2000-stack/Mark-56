"""Unit tests for the optional Mark 56 OpenAI text provider."""
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, patch

from core import openai_provider


class OpenAIProviderTests(unittest.TestCase):
    def test_converts_text_and_sdk_inline_image(self):
        image = SimpleNamespace(
            inline_data=SimpleNamespace(data=b"abc", mime_type="image/png"),
            text=None,
        )
        parts = openai_provider._content_parts(["describe this", image])
        self.assertEqual(parts[0], {"type": "input_text", "text": "describe this"})
        self.assertEqual(parts[1]["type"], "input_image")
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(parts[1]["detail"], "auto")

    def test_requires_openai_key_without_revealing_it(self):
        with patch.object(openai_provider, "_settings", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "openai_api_key is not configured"):
                openai_provider.generate("hello")

    def test_calls_responses_api_and_returns_text(self):
        response = SimpleNamespace(output_text="  Ready.  ")
        client = MagicMock()
        client.responses.create.return_value = response
        fake_sdk = ModuleType("openai")
        fake_sdk.OpenAI = MagicMock(return_value=client)
        with patch.object(openai_provider, "_settings", return_value={
            "openai_api_key": "test-key",
            "openai_model": "gpt-4.1-mini",
        }), patch.dict(sys.modules, {"openai": fake_sdk}):
            result = openai_provider.generate("hello", timeout_ms=5000)

        self.assertEqual(result, "Ready.")
        client.responses.create.assert_called_once()
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4.1-mini")
        self.assertEqual(kwargs["input"][0]["role"], "user")


if __name__ == "__main__":
    unittest.main()
