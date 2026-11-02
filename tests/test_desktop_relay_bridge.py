import unittest
import uuid
from relay.desktop_bridge import relay_websocket_url


class DesktopRelayBridgeTests(unittest.TestCase):
    def test_https_origin_maps_to_wss_endpoint(self):
        channel = str(uuid.uuid4())
        self.assertEqual(
            relay_websocket_url("https://relay.example.com", channel, "desktop"),
            f"wss://relay.example.com/v1/connect/{channel}/desktop",
        )

    def test_plaintext_and_embedded_credentials_are_rejected(self):
        channel = str(uuid.uuid4())
        for url in ("http://relay.example.com", "https://user:pass@relay.example.com",
                    "https://relay.example.com/path"):
            with self.assertRaises(ValueError):
                relay_websocket_url(url, channel, "desktop")
        with self.assertRaises(ValueError):
            relay_websocket_url("https://relay.example.com", "not-a-uuid", "desktop")


if __name__ == "__main__":
    unittest.main()
