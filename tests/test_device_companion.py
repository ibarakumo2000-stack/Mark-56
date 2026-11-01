import unittest
import time

from core.device_gateway import AuthorizationError, DeviceRegistry
from core.device_companion import (
    CompanionMessageVerifier,
    InvalidCompanionMessage,
    build_pairing_payload,
    sign_companion_message,
)


class CompanionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.devices = DeviceRegistry()
        scopes = ("command.send", "notification.receive")
        offer = self.devices.create_pairing_offer(scopes)
        self.device = self.devices.redeem_pairing_code(
            offer.code, device_name="Android phone", device_type="android",
            platform="android", capabilities=("notification.receive",),
            requested_scopes=scopes,
        )
        self.verifier = CompanionMessageVerifier(self.devices)

    def tearDown(self):
        self.devices.close()

    def message(self, **kwargs):
        return sign_companion_message(
            self.device.token, device_id=self.device.device_id,
            method="POST", path="/v1/notifications", body={"title": "Hello"},
            timestamp=1000, nonce="abcdefghijklmnopqrstuvwx", **kwargs
        )

    def test_valid_signed_message_verifies(self):
        msg = self.message()
        identity = self.verifier.verify(
            self.device.token, msg, now=1000,
            required_scope="notification.receive",
        )
        self.assertEqual(identity["device_id"], self.device.device_id)

    def test_replay_is_rejected(self):
        msg = self.message()
        self.verifier.verify(self.device.token, msg, now=1000)
        with self.assertRaises(InvalidCompanionMessage):
            self.verifier.verify(self.device.token, msg, now=1000)

    def test_tampering_is_rejected(self):
        msg = self.message()
        altered = msg.__class__(
            msg.version, msg.device_id, msg.method, msg.path, msg.timestamp,
            msg.nonce, {"title": "Changed"}, msg.signature,
        )
        with self.assertRaises(InvalidCompanionMessage):
            self.verifier.verify(self.device.token, altered, now=1000)

    def test_expired_message_is_rejected(self):
        msg = self.message()
        with self.assertRaises(InvalidCompanionMessage):
            self.verifier.verify(self.device.token, msg, now=2000)

    def test_wrong_token_is_rejected(self):
        msg = self.message()
        with self.assertRaises(AuthorizationError):
            self.verifier.verify("x" * 48, msg, now=1000)

    def test_missing_scope_is_rejected(self):
        msg = self.message()
        with self.assertRaises(AuthorizationError):
            self.verifier.verify(
                self.device.token, msg, now=1000, required_scope="camera.capture"
            )

    def test_invalid_route_and_oversized_body_are_rejected(self):
        with self.assertRaises(ValueError):
            sign_companion_message(
                self.device.token, device_id=self.device.device_id,
                method="POST", path="//evil.example/path", body={},
            )
        with self.assertRaises(ValueError):
            sign_companion_message(
                self.device.token, device_id=self.device.device_id,
                method="POST", path="/v1/data", body={"data": "x" * 17000},
            )

    def test_pairing_qr_payload_requires_https_and_certificate_fingerprint(self):
        code = "ABCDEFGH"
        fingerprint = ":".join(["ab"] * 32)
        payload = build_pairing_payload(
            pairing_code=code, expires_at=time.time() + 120,
            desktop_endpoint="https://192.168.1.10:8765",
            desktop_fingerprint=fingerprint,
        )
        self.assertEqual(payload["protocol"], "mark56-companion")
        self.assertEqual(payload["certificate_sha256"], fingerprint)
        with self.assertRaises(ValueError):
            build_pairing_payload(
                pairing_code=code, expires_at=time.time() + 120,
                desktop_endpoint="http://192.168.1.10:8765",
                desktop_fingerprint=fingerprint,
            )


if __name__ == "__main__":
    unittest.main()
