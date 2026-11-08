import unittest
import socket
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from core.device_companion_server import CompanionServer
from dataclasses import asdict
from fastapi.testclient import TestClient
from core.device_companion import sign_companion_message

from core.device_gateway import DeviceRegistry, AuthorizationError
from core.device_companion_server import create_companion_app


class CompanionServerTests(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self.app = create_companion_app(self.registry)

    def tearDown(self):
        self.registry.close()

    def test_app_is_created_without_opening_a_listener(self):
        self.assertTrue(any(getattr(route, "path", None) == "/v1/pair"
                            for route in self.app.routes))
        self.assertIsNone(getattr(self.app.state, "server", None))

    def test_pairing_route_exists_and_media_is_not_an_http_enqueue_route(self):
        paths = {route.path for route in self.app.routes}
        self.assertIn("/v1/notifications", paths)
        self.assertIn("/v1/battery", paths)
        self.assertIn("/v1/media/next", paths)
        self.assertIn("/v1/wearable/action", paths)
        self.assertNotIn("/v1/devices/{device_id}/media", paths)

    def test_media_queue_requires_device_scope_and_identity(self):
        scopes = ("media.control",)
        offer = self.registry.create_pairing_offer(scopes)
        enrolled = self.registry.redeem_pairing_code(
            offer.code, device_name="Android", device_type="android",
            platform="android", capabilities=("media",), requested_scopes=scopes,
        )
        queue = self.app.state.queue_media_command
        result = queue(enrolled.device_id, enrolled.token, "pause")
        self.assertEqual(result, {"queued": True, "action": "pause"})
        with self.assertRaises(AuthorizationError):
            queue("different-device", enrolled.token, "pause")


    def test_wearable_queue_is_bounded_and_exposes_drain_callback(self):
        offer = self.registry.create_pairing_offer(("command.send",))
        device = self.registry.redeem_pairing_code(
            offer.code, device_name="Phone", device_type="android",
            platform="android", capabilities=("wear_bridge",),
            requested_scopes=("command.send",),
        )
        self.assertEqual(self.app.state.wearable_commands.maxlen, 32)
        self.assertEqual(self.app.state.drain_wearable_commands(), [])
        with self.assertRaises(ValueError):
            self.app.state.drain_wearable_commands(0)


    def test_wearable_action_is_authenticated_scoped_and_queued(self):
        offer = self.registry.create_pairing_offer(("command.send",))
        device = self.registry.redeem_pairing_code(
            offer.code, device_name="Phone", device_type="android",
            platform="android", capabilities=("wear_bridge",),
            requested_scopes=("command.send",),
        )
        signed = sign_companion_message(
            device.token, device_id=device.device_id, method="POST",
            path="/v1/wearable/action",
            body={"action": "assistant.ping", "source": "wear_os"},
        )
        response = TestClient(self.app).post(
            "/v1/wearable/action", json=asdict(signed),
            headers={"Authorization": "Bearer " + device.token},
        )
        self.assertEqual(response.status_code, 200)
        queued = self.app.state.drain_wearable_commands()
        self.assertEqual(queued[0]["action"], "assistant.ping")
        self.assertEqual(queued[0]["source"], "wear_os")

    def test_wearable_action_rejects_unapproved_scope(self):
        offer = self.registry.create_pairing_offer(("battery.read",))
        device = self.registry.redeem_pairing_code(
            offer.code, device_name="Phone", device_type="android",
            platform="android", capabilities=(),
            requested_scopes=("battery.read",),
        )
        signed = sign_companion_message(
            device.token, device_id=device.device_id, method="POST",
            path="/v1/wearable/action",
            body={"action": "assistant.ping", "source": "wear_os"},
        )
        response = TestClient(self.app).post(
            "/v1/wearable/action", json=asdict(signed),
            headers={"Authorization": "Bearer " + device.token},
        )
        self.assertEqual(response.status_code, 403)



    def test_chat_send_is_authenticated_scoped_and_drained_by_desktop(self):
        offer = self.registry.create_pairing_offer(("command.send",))
        device = self.registry.redeem_pairing_code(offer.code, device_name="Phone", device_type="android", platform="android", capabilities=("chat",), requested_scopes=("command.send",))
        signed = sign_companion_message(device.token, device_id=device.device_id, method="POST", path="/v1/chat/send", body={"message_id": "chat-msg-123456", "message": "Hello JARVIS"})
        response = TestClient(self.app).post("/v1/chat/send", json=asdict(signed), headers={"Authorization": "Bearer " + device.token})
        self.assertEqual(response.status_code, 200)
        queued = self.app.state.drain_chat_messages()
        self.assertEqual(queued[0]["device_id"], device.device_id)
        self.assertEqual(queued[0]["message"], "Hello JARVIS")

    def test_chat_rejects_device_without_command_scope(self):
        offer = self.registry.create_pairing_offer(("battery.read",))
        device = self.registry.redeem_pairing_code(offer.code, device_name="Phone", device_type="android", platform="android", capabilities=(), requested_scopes=("battery.read",))
        signed = sign_companion_message(device.token, device_id=device.device_id, method="POST", path="/v1/chat/send", body={"message_id": "chat-msg-123456", "message": "Hi"})
        response = TestClient(self.app).post("/v1/chat/send", json=asdict(signed), headers={"Authorization": "Bearer " + device.token})
        self.assertEqual(response.status_code, 403)

    def test_desktop_can_queue_reply_for_authenticated_phone_poll(self):
        offer = self.registry.create_pairing_offer(("command.send",))
        device = self.registry.redeem_pairing_code(offer.code, device_name="Phone", device_type="android", platform="android", capabilities=("chat",), requested_scopes=("command.send",))
        self.app.state.queue_chat_reply(device.device_id, "chat-msg-123456", "Hello from JARVIS")
        signed = sign_companion_message(device.token, device_id=device.device_id, method="POST", path="/v1/chat/poll", body={})
        response = TestClient(self.app).post("/v1/chat/poll", json=asdict(signed), headers={"Authorization": "Bearer " + device.token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"]["reply"], "Hello from JARVIS")

    def test_start_waits_until_https_listener_is_ready(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
        ])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory() as directory:
            cert_path = Path(directory) / "server.crt"
            key_path = Path(directory) / "server.key"
            cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = CompanionServer(
                self.app, host="127.0.0.1", port=port,
                certificate=cert_path, private_key=key_path,
            )
            try:
                server.start(timeout=5)
                context = ssl._create_unverified_context()
                with urlopen(f"https://127.0.0.1:{port}/health", context=context, timeout=3) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.stop()

    def test_pairing_code_is_one_time(self):
        offer = self.registry.create_pairing_offer(("battery.read",))
        enrolled = self.registry.redeem_pairing_code(
            offer.code, device_name="Phone", device_type="android",
            platform="android", capabilities=(), requested_scopes=("battery.read",),
        )
        self.assertEqual(enrolled.scopes, ("battery.read",))
        with self.assertRaises(Exception):
            self.registry.redeem_pairing_code(
                offer.code, device_name="Phone 2", device_type="android",
                platform="android", capabilities=(), requested_scopes=("battery.read",),
            )


if __name__ == "__main__":
    unittest.main()
