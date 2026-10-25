"""Tests for isolated, validate-before-save Website Studio credentials."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from core import website_studio_credentials as credentials


class WebsiteStudioCredentialTests(unittest.TestCase):
    def setUp(self):
        self.keyring = MagicMock()
        self.backend = SimpleNamespace(priority=5, __class__=SimpleNamespace())
        # keyring.get_keyring() returns a backend whose class resembles SecretService.
        Backend = type("SecretServiceKeyring", (), {"priority": 5, "__module__": "keyring.backends.SecretService"})
        self.backend = Backend()
        self.keyring.get_keyring.return_value = self.backend

    def test_saves_only_after_successful_validation(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"{}"
        with patch.object(credentials, "_keyring_module", return_value=self.keyring), \
             patch.object(credentials, "urlopen", return_value=response) as open_url:
            credentials.save_api_key("sk-test-example")
        open_url.assert_called_once()
        self.keyring.set_password.assert_called_once_with(
            credentials._SERVICE, credentials._ACCOUNT, "sk-test-example"
        )

    def test_rejected_key_is_never_saved(self):
        with patch.object(credentials, "_keyring_module", return_value=self.keyring), \
             patch.object(credentials, "validate_api_key", side_effect=credentials.CredentialError("rejected")):
            with self.assertRaisesRegex(credentials.CredentialError, "rejected"):
                credentials.save_api_key("bad-key")
        self.keyring.set_password.assert_not_called()

    def test_invalid_input_does_not_make_network_request(self):
        with patch.object(credentials, "urlopen") as open_url:
            with self.assertRaises(credentials.CredentialError):
                credentials.validate_api_key("contains whitespace")
        open_url.assert_not_called()

    def test_status_never_returns_secret(self):
        self.keyring.get_password.return_value = "sk-secret"
        with patch.object(credentials, "_keyring_module", return_value=self.keyring):
            result = credentials.status()
        self.assertTrue(result["configured"])
        self.assertNotIn("sk-secret", repr(result))
        self.assertNotIn("api_key", result)

    def test_keyring_backend_failure_is_not_silently_accepted(self):
        Backend = type("FailKeyring", (), {"priority": 0, "__module__": "keyring.backends.fail"})
        self.keyring.get_keyring.return_value = Backend()
        with patch.dict("sys.modules", {"keyring": self.keyring}):
            with self.assertRaises(credentials.CredentialError):
                credentials._keyring_module()


if __name__ == "__main__":
    unittest.main()
