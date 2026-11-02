import unittest
import uuid
from fastapi.testclient import TestClient
from relay.app import create_relay_app
from relay.registry import RelayRegistry


class RelayAppTests(unittest.TestCase):
    def setUp(self):
        self.registry = RelayRegistry(":memory:")
        self.channel = str(uuid.uuid4())
        self.desktop = self.registry.provision(
            channel_id=self.channel, role="desktop",
            scopes=["command.send", "media.control"],
        )
        self.device = self.registry.provision(
            channel_id=self.channel, role="device",
            scopes=["command.send", "media.control"],
        )
        self.app = create_relay_app(self.registry)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.registry.close()

    def test_device_to_desktop_and_desktop_to_device_are_channel_scoped(self):
        desktop_path = f"/v1/connect/{self.channel}/{self.desktop['principal_id']}"
        device_path = f"/v1/connect/{self.channel}/{self.device['principal_id']}"
        with self.client.websocket_connect(
            desktop_path, headers={"Authorization": "Bearer " + self.desktop["token"]}
        ) as desktop_ws:
            with self.client.websocket_connect(
                device_path, headers={"Authorization": "Bearer " + self.device["token"]}
            ) as device_ws:
                device_ws.send_json({
                    "type": "command", "target_device_id": None,
                    "payload": {"action": "assistant.ping"},
                })
                delivered = desktop_ws.receive_json()
                self.assertEqual(delivered["device_id"], self.device["principal_id"])
                self.assertEqual(delivered["payload"]["action"], "assistant.ping")
                self.assertEqual(device_ws.receive_json()["type"], "ack")

                desktop_ws.send_json({
                    "type": "media", "target_device_id": self.device["principal_id"],
                    "payload": {"action": "media.play_pause"},
                })
                self.assertEqual(device_ws.receive_json()["payload"]["action"], "media.play_pause")
                self.assertEqual(desktop_ws.receive_json()["type"], "ack")

    def test_device_message_requires_desktop_recipient_scope(self):
        self.registry.revoke(self.desktop["principal_id"], self.channel)
        self.desktop = self.registry.provision(
            channel_id=self.channel, role="desktop", scopes=[],
            principal_id="desktop-limited",
        )
        desktop_path = f"/v1/connect/{self.channel}/{self.desktop['principal_id']}"
        device_path = f"/v1/connect/{self.channel}/{self.device['principal_id']}"
        with self.client.websocket_connect(
            desktop_path, headers={"Authorization": "Bearer " + self.desktop["token"]}
        ):
            with self.client.websocket_connect(
                device_path, headers={"Authorization": "Bearer " + self.device["token"]}
            ) as device_ws:
                device_ws.send_json({
                    "type": "command", "target_device_id": None,
                    "payload": {"action": "assistant.ping"},
                })
                self.assertEqual(device_ws.receive_json()["error"], "recipient_scope_denied")

    def test_desktop_message_requires_device_recipient_scope(self):
        self.registry.revoke(self.device["principal_id"], self.channel)
        self.device = self.registry.provision(
            channel_id=self.channel, role="device", scopes=[],
            principal_id="device-limited",
        )
        desktop_path = f"/v1/connect/{self.channel}/{self.desktop['principal_id']}"
        device_path = f"/v1/connect/{self.channel}/{self.device['principal_id']}"
        with self.client.websocket_connect(
            desktop_path, headers={"Authorization": "Bearer " + self.desktop["token"]}
        ) as desktop_ws:
            with self.client.websocket_connect(
                device_path, headers={"Authorization": "Bearer " + self.device["token"]}
            ):
                desktop_ws.send_json({
                    "type": "media", "target_device_id": self.device["principal_id"],
                    "payload": {"action": "media.play_pause"},
                })
                self.assertEqual(desktop_ws.receive_json()["error"], "recipient_scope_denied")

    def test_device_cannot_select_another_recipient(self):
        path = f"/v1/connect/{self.channel}/{self.device['principal_id']}"
        with self.client.websocket_connect(
            path, headers={"Authorization": "Bearer " + self.device["token"]}
        ) as socket:
            socket.send_json({
                "type": "command", "target_device_id": "other-device",
                "payload": {"action": "assistant.ping"},
            })
            self.assertEqual(socket.receive_json()["error"], "device_cannot_select_recipient")

    def test_revoked_credentials_cannot_connect(self):
        self.registry.revoke(self.device["principal_id"], self.channel)
        path = f"/v1/connect/{self.channel}/{self.device['principal_id']}"
        with self.assertRaises(Exception):
            with self.client.websocket_connect(
                path, headers={"Authorization": "Bearer " + self.device["token"]}
            ):
                pass


if __name__ == "__main__":
    unittest.main()
