import unittest
from relay.desktop_bridge import relay_websocket_url


class DesktopRelayBridgeTests(unittest.TestCase):
    def test_https_origin_maps_to_wss_endpoint(self):
        self.assertEqual(
            relay_websocket_url("https://relay.example.com", "channel", "desktop"),
            "wss://relay.example.com/v1/connect/channel/desktop",
        )

    def test_plaintext_and_embedded_credentials_are_rejected(self):
        for url in ("http://relay.example.com", "https://user:pass@relay.example.com",
                    "https://relay.example.com/path"):
            with self.assertRaises(ValueError):
                relay_websocket_url(url, "channel", "desktop")


if __name__ == "__main__":
    unittest.main()
