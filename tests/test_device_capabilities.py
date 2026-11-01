import unittest

from core.device_capabilities import CapabilityDetector


class CapabilityDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = CapabilityDetector()

    def test_detects_verified_watch_capabilities_from_gatt_evidence(self):
        device = {
            "device_id": "watch-1",
            "name": "Test Watch",
            "capabilities": ["health.read", "haptics.send"],
            "services": [
                {"uuid": "180F", "characteristics": [
                    {"uuid": "2A19", "properties": ["read"]},
                ]},
                {"uuid": "180D", "characteristics": [
                    {"uuid": "2A37", "properties": ["read", "notify"]},
                ]},
                {"uuid": "180A", "characteristics": [
                    {"uuid": "2A29", "properties": ["read"]},
                ]},
            ],
        }
        result = self.detector.detect(device)
        self.assertEqual(
            result["detected_capabilities"],
            ["battery.read", "device_info.read", "heart_rate.read"],
        )
        self.assertEqual(result["unverified_capabilities"], ["haptics.send"])
        self.assertEqual(result["permission_scopes_required"], ["health.read"])
        self.assertFalse(result["permissions_granted"])

    def test_service_presence_without_characteristic_does_not_verify(self):
        result = self.detector.detect({
            "services": [{"uuid": "180F", "characteristics": []}],
            "capabilities": ["battery.read"],
        })
        self.assertEqual(result["detected_capabilities"], [])
        self.assertEqual(result["unverified_capabilities"], ["battery.read"])

    def test_wrong_characteristic_property_does_not_verify_capability(self):
        result = self.detector.detect({
            "services": [{"uuid": "180F", "characteristics": [
                {"uuid": "2A19", "properties": ["notify"]},
            ]}],
        })
        self.assertNotIn("battery.read", result["detected_capabilities"])

    def test_supports_short_and_canonical_uuids(self):
        result = self.detector.detect({
            "services": [{"uuid": "0000180f-0000-1000-8000-00805f9b34fb",
                          "characteristics": [
                              {"uuid": "00002a19-0000-1000-8000-00805f9b34fb",
                               "properties": ["read"]},
                          ]}],
        })
        self.assertEqual(result["detected_capabilities"], ["battery.read"])

    def test_discovery_record_without_gatt_metadata_is_conservative(self):
        result = self.detector.detect({
            "service_uuids": ["180F"],
            "capabilities": ["battery.read", "camera.capture"],
        })
        self.assertEqual(result["detected_capabilities"], [])
        self.assertEqual(
            result["unverified_capabilities"],
            ["battery.read", "camera.capture"],
        )

    def test_capability_detection_does_not_grant_permissions(self):
        result = self.detector.detect({
            "services": [{"uuid": "180D", "characteristics": [
                {"uuid": "2A37", "properties": ["read"]},
            ]}],
        })
        self.assertEqual(result["permission_scopes_required"], ["health.read"])
        self.assertFalse(result["permissions_granted"])

    def test_supports_dict_service_shape(self):
        result = self.detector.detect({
            "services": {
                "180F": {
                    "2A19": {"properties": ["read"]},
                },
            },
        })
        self.assertEqual(result["detected_capabilities"], ["battery.read"])

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(TypeError):
            self.detector.detect(None)


if __name__ == "__main__":
    unittest.main()
