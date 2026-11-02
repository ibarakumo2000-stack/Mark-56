import unittest

from core.device_gateway import DeviceRegistry
from core.glasses_adapters import (
    GlassesAdapterError, GlassesAdapterRegistry, GlassesCapability, GlassesDescriptor,
)


class FakeGlasses:
    adapter_id = "test.glasses"

    def __init__(self):
        self.disconnected = False

    def discover(self, timeout=5.0):
        return []

    def connect(self, device_id):
        self.disconnected = False

    def disconnect(self, device_id):
        self.disconnected = True
        self.disconnected_device_id = device_id

    def render_card(self, device_id, card):
        self.last_card = card

    def capture_frame(self, device_id):
        return b"frame"

    def capture_audio(self, device_id, duration_ms):
        return b"audio"


class GlassesAdapterTests(unittest.TestCase):
    def setUp(self):
        self.devices = DeviceRegistry()
        offer = self.devices.create_pairing_offer(("display.render", "camera.capture", "voice.capture"))
        self.device = self.devices.redeem_pairing_code(
            offer.code, device_name="Test glasses", device_type="glasses",
            platform="test", capabilities=("display", "camera", "microphone"),
            requested_scopes=("display.render", "camera.capture", "voice.capture"),
        )
        self.registry = GlassesAdapterRegistry(self.devices)
        self.adapter = FakeGlasses()
        self.registry.register(self.adapter)
        self.descriptor = GlassesDescriptor(
            "Example", "Prototype", "test",
            frozenset({GlassesCapability.DISPLAY, GlassesCapability.CAMERA, GlassesCapability.MICROPHONE}),
        )
        self.registry.connect(self.device.token, "test.glasses", "physical-device", self.descriptor)

    def tearDown(self):
        self.devices.close()

    def test_camera_requires_scope_and_explicit_session_consent(self):
        with self.assertRaises(GlassesAdapterError):
            self.registry.capture_frame(self.device.token)
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.CAMERA})
        self.assertEqual(self.registry.capture_frame(self.device.token), b"frame")

    def test_camera_capture_uses_the_connected_physical_device(self):
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.CAMERA})
        self.assertEqual(self.registry.capture_frame(self.device.token), b"frame")

    def test_microphone_capture_uses_the_connected_physical_device(self):
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.MICROPHONE})
        self.assertEqual(self.registry.capture_audio(self.device.token, 5000), b"audio")

    def test_consent_cannot_invent_hardware_capability(self):
        with self.assertRaises(GlassesAdapterError):
            self.registry.grant_session_consent(self.device.token, {GlassesCapability.IMU})

    def test_consent_can_be_revoked_immediately(self):
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.DISPLAY})
        self.registry.render_card(self.device.token, {"title": "JARVIS"})
        self.registry.revoke_session_consent(self.device.token)
        with self.assertRaises(GlassesAdapterError):
            self.registry.render_card(self.device.token, {"title": "JARVIS"})

    def test_audio_duration_is_bounded(self):
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.MICROPHONE})
        with self.assertRaises(GlassesAdapterError):
            self.registry.capture_audio(self.device.token, 30000)

    def test_revoking_device_disconnects_physical_adapter_session(self):
        self.registry.grant_session_consent(self.device.token, {GlassesCapability.CAMERA})
        self.assertTrue(self.devices.revoke_device(self.device.device_id))
        with self.assertRaises(Exception):
            self.registry.capture_frame(self.device.token)
        self.assertTrue(self.adapter.disconnected)

    def test_disconnect_closes_adapter_session(self):
        self.assertTrue(self.registry.disconnect(self.device.token))
        self.assertTrue(self.adapter.disconnected)
        self.assertEqual(self.adapter.disconnected_device_id, "physical-device")


if __name__ == "__main__":
    unittest.main()
