import unittest
from unittest.mock import patch

from dashboard.server import DashboardServer


class DashboardOwnerSessionTests(unittest.TestCase):
    def test_native_owner_session_is_issued_by_live_dashboard_instance(self):
        # Avoid constructing the persistent device registry or opening a listener.
        server = object.__new__(DashboardServer)
        server._tokens = set()
        server._token_keys = {}
        server._aes_cache = {}

        token = server.create_owner_session()

        self.assertTrue(token)
        self.assertIn(token, server._tokens)
        self.assertIn(token, server._token_keys)
        self.assertTrue(server._token_keys[token])
        self.assertIn(server._token_keys[token], server._aes_cache)

    def test_local_dashboard_url_uses_loopback_and_active_transport(self):
        server = object.__new__(DashboardServer)
        with patch.object(DashboardServer, "_ssl_enabled", return_value=False):
            self.assertEqual(server.get_local_url(), "http://127.0.0.1:8000")

    def test_device_page_clears_expired_browser_owner_session(self):
        from pathlib import Path
        page = Path("dashboard/static/devices.html").read_text(encoding="utf-8")
        self.assertIn('if(response.status===401)', page)
        self.assertIn('sessionStorage.removeItem("jarvis_token")', page)
        self.assertIn('location.replace("/login")', page)


if __name__ == "__main__":
    unittest.main()
