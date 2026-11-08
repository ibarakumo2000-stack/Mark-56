import unittest
from types import SimpleNamespace

from core.device_gateway import DeviceRegistry
from dashboard.device_api import (
    _discover_private_lan_ipv4, _is_secure_or_loopback,
    _usable_private_ipv4, build_device_router,
)


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


    def test_private_lan_address_validation_rejects_loopback_and_public(self):
        self.assertTrue(_usable_private_ipv4("192.168.1.20"))
        self.assertTrue(_usable_private_ipv4("10.0.0.8"))
        self.assertFalse(_usable_private_ipv4("127.0.0.1"))
        self.assertFalse(_usable_private_ipv4("169.254.1.2"))
        self.assertFalse(_usable_private_ipv4("8.8.8.8"))
        self.assertFalse(_usable_private_ipv4("not-an-ip"))

    def test_private_lan_discovery_returns_none_when_no_interface_exists(self):
        # The function is intentionally safe when the computer is offline.
        from unittest.mock import patch
        with patch("dashboard.device_api.socket.socket", side_effect=OSError("offline")):
            with patch("dashboard.device_api.socket.getaddrinfo", return_value=[]):
                self.assertIsNone(_discover_private_lan_ipv4())

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
            ("/api/devices/notifications", ("GET",)),
            ("/api/devices/{device_id}/name", ("PATCH",)),
            ("/api/devices/{device_id}/scopes", ("PUT",)),
            ("/api/devices/{device_id}", ("DELETE",)),
            ("/api/devices/{device_id}/media", ("POST",)),
            ("/api/devices/wearable-commands", ("GET",)),
            ("/api/devices/glasses", ("GET",)),
            ("/api/devices/glasses/discover", ("POST",)),
            ("/api/devices/glasses/pair", ("POST",)),
            ("/api/devices/glasses/{device_id}/connect", ("POST",)),
            ("/api/devices/glasses/{device_id}/disconnect", ("POST",)),
            ("/api/devices/glasses/{device_id}/display", ("POST",)),
            ("/api/devices/relay", ("GET",)),
            ("/api/devices/relay/configure", ("POST",)),
            ("/api/devices/relay/start", ("POST",)),
            ("/api/devices/relay/configuration", ("DELETE",)),
            ("/api/devices/relay/stop", ("POST",)),
            ("/api/devices/relay/events", ("GET",)),
            ("/api/devices/relay/ping", ("POST",)),
            ("/api/device/me", ("GET",)),
        }
        self.assertTrue(expected.issubset(routes))

    def test_device_registry_supports_safe_owner_rename(self):
        offer = self.registry.create_pairing_offer(("battery.read",))
        device = self.registry.redeem_pairing_code(
            offer.code, device_name="Old name", device_type="android",
            platform="android", capabilities=("battery",), requested_scopes=("battery.read",),
        )
        self.assertTrue(self.registry.rename_device(device.device_id, "Desk phone"))
        self.assertEqual(self.registry.list_devices()[0]["device_name"], "Desk phone")
        with self.assertRaises(ValueError):
            self.registry.rename_device(device.device_id, " " * 81)

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
