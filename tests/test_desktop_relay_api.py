import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.device_gateway import DeviceRegistry
from dashboard.device_api import build_device_router


class FakeKeyring:
    def __init__(self, priority=1):
        self.priority = priority
        self.values = {}

    def get_keyring(self):
        return self

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


class DesktopRelayApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.registry = DeviceRegistry()
        self.keyring = FakeKeyring()
        self.keyring_module = types.ModuleType("keyring")
        self.keyring_module.get_keyring = self.keyring.get_keyring
        self.keyring_module.set_password = self.keyring.set_password
        self.keyring_module.get_password = self.keyring.get_password
        self.keyring_module.delete_password = self.keyring.delete_password
        with patch("dashboard.device_api.Path.home", return_value=self.home):
            router = build_device_router(self.registry, owner_auth=lambda _request: True)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.registry.close()
        self.temp.cleanup()

    def test_configuration_stores_token_in_keyring_and_never_returns_it(self):
        channel = "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11"
        principal = "desktop-owner"
        token = "rly_" + "a" * 56
        with patch.dict(sys.modules, {"keyring": self.keyring_module}):
            response = self.client.post(
                "/api/devices/relay/configure",
                base_url="https://localhost",
                json={
                    "endpoint": "https://relay.example.com",
                    "channel_id": channel,
                    "principal_id": principal,
                    "token": token,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(token, response.text)
            self.assertEqual(
                self.keyring.get_password("mark56-relay", f"{channel}:{principal}"),
                token,
            )
            saved = self.client.get("/api/devices/relay", base_url="https://localhost")
            self.assertTrue(saved.json()["configured"])
            self.assertNotIn("token", saved.json())
            config_path = self.home / ".jarvis" / "relay.json"
            self.assertTrue(config_path.is_file())
            self.assertNotIn(token, config_path.read_text(encoding="utf-8"))

    def test_configuration_rejects_plaintext_and_non_origin_urls(self):
        with patch.dict(sys.modules, {"keyring": self.keyring_module}):
            for endpoint in ("http://relay.example.com", "https://relay.example.com/path"):
                response = self.client.post(
                    "/api/devices/relay/configure",
                    base_url="https://localhost",
                    json={
                        "endpoint": endpoint,
                        "channel_id": "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11",
                        "principal_id": "desktop-owner",
                        "token": "rly_" + "b" * 56,
                    },
                )
                self.assertEqual(response.status_code, 400)

    def test_configuration_fails_closed_without_secure_os_keyring(self):
        unavailable = FakeKeyring(priority=0)
        module = types.ModuleType("keyring")
        module.get_keyring = unavailable.get_keyring
        with patch.dict(sys.modules, {"keyring": module}):
            response = self.client.post(
                "/api/devices/relay/configure",
                base_url="https://localhost",
                json={
                    "endpoint": "https://relay.example.com",
                    "channel_id": "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11",
                    "principal_id": "desktop-owner",
                    "token": "rly_" + "c" * 56,
                },
            )
        self.assertEqual(response.status_code, 503)

    def test_forget_removes_saved_configuration_and_keyring_credential(self):
        channel = "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11"
        principal = "desktop-owner"
        config_dir = self.home / ".jarvis"
        config_dir.mkdir()
        (config_dir / "relay.json").write_text(json.dumps({
            "endpoint": "https://relay.example.com",
            "channel_id": channel,
            "principal_id": principal,
        }), encoding="utf-8")
        self.keyring.set_password("mark56-relay", f"{channel}:{principal}", "rly_" + "d" * 56)
        with patch.dict(sys.modules, {"keyring": self.keyring_module}):
            response = self.client.delete(
                "/api/devices/relay/configuration", base_url="https://localhost"
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse((config_dir / "relay.json").exists())
        self.assertIsNone(self.keyring.get_password("mark56-relay", f"{channel}:{principal}"))


if __name__ == "__main__":
    unittest.main()
