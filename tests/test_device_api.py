import unittest
from types import SimpleNamespace

from core.device_gateway import DeviceRegistry
from dashboard.device_api import _is_secure_or_loopback, build_device_router


def request(*, scheme="http", client="127.0.0.1"):
    return SimpleNamespace(
        url=SimpleNamespace(scheme=scheme),
        client=SimpleNamespace(host=client),
    )


class DeviceApiTests(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()

    def tearDown(self):
        self.registry.close()

    def test_loopback_http_is_allowed_for_local_development(self):
        self.assertTrue(_is_secure_or_loopback(request()))

    def test_remote_http_is_rejected(self):
        self.assertFalse(_is_secure_or_loopback(request(client="192.168.1.20")))

    def test_remote_https_is_allowed(self):
        self.assertTrue(_is_secure_or_loopback(
            request(scheme="https", client="192.168.1.20")
        ))

    def test_router_exposes_scoped_device_management_routes(self):
        router = build_device_router(
            self.registry, owner_auth=lambda req: True
        )
        routes = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
        expected = {
            ("/devices", ("GET",)),
            ("/api/devices/companion", ("GET",)),
            ("/api/devices/companion/start", ("POST",)),
            ("/api/devices/companion/stop", ("POST",)),
            ("/api/devices/pairing-offers", ("POST",)),
            ("/api/devices/enroll", ("POST",)),
            ("/api/devices", ("GET",)),
            ("/api/devices/{device_id}/scopes", ("PUT",)),
            ("/api/devices/{device_id}", ("DELETE",)),
            ("/api/devices/{device_id}/media", ("POST",)),
            ("/api/device/me", ("GET",)),
        }
        self.assertTrue(expected.issubset(routes))

    def test_pairing_offer_scopes_remain_allowlisted(self):
        with self.assertRaises(ValueError):
            self.registry.create_pairing_offer(("admin",))

    def test_revoked_device_is_removed_from_active_listing(self):
        offer = self.registry.create_pairing_offer(("media.control",))
        device = self.registry.redeem_pairing_code(
            offer.code, device_name="Test phone", device_type="android",
            platform="android", capabilities=("media",),
            requested_scopes=("media.control",),
        )
        self.assertEqual(len(self.registry.list_devices()), 1)
        self.assertTrue(self.registry.revoke_device(device.device_id))
        self.assertEqual(self.registry.list_devices(), [])


if __name__ == "__main__":
    unittest.main()
