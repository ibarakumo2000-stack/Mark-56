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
        self.assertIn(("/api/devices/pairing-offers", ("POST",)), routes)
        self.assertIn(("/api/devices/enroll", ("POST",)), routes)
        self.assertIn(("/api/devices", ("GET",)), routes)
        self.assertIn(("/api/devices/{device_id}", ("DELETE",)), routes)
        self.assertIn(("/api/device/me", ("GET",)), routes)


if __name__ == "__main__":
    unittest.main()
