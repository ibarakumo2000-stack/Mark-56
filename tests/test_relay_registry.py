import unittest
import uuid
from relay.registry import RelayAuthError, RelayRegistry


class RelayRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = RelayRegistry(":memory:")
        self.channel = str(uuid.uuid4())

    def tearDown(self):
        self.registry.close()

    def test_provision_and_authenticate_desktop_and_device(self):
        desktop = self.registry.provision(channel_id=self.channel, role="desktop", scopes=["command.send"])
        device = self.registry.provision(channel_id=self.channel, role="device", scopes=["media.control"])
        self.assertEqual(self.registry.authenticate(desktop["token"])["role"], "desktop")
        identity = self.registry.authenticate(device["token"])
        self.assertEqual(identity["channel_id"], self.channel)
        self.assertEqual(identity["scopes"], ["media.control"])
        self.assertNotIn("token", identity)

    def test_raw_tokens_are_not_stored(self):
        device = self.registry.provision(channel_id=self.channel, role="device", scopes=[])
        rows = self.registry._db.execute("SELECT token_hash FROM principals").fetchall()
        self.assertNotEqual(rows[0]["token_hash"], device["token"])

    def test_revocation_invalidates_token(self):
        device = self.registry.provision(channel_id=self.channel, role="device", scopes=[])
        self.assertTrue(self.registry.revoke(device["principal_id"], self.channel))
        with self.assertRaises(RelayAuthError):
            self.registry.authenticate(device["token"])

    def test_invalid_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.provision(channel_id=self.channel, role="device", scopes=["admin"])

    def test_desktop_identity_is_unique_per_channel(self):
        first = self.registry.provision(channel_id=self.channel, role="desktop", scopes=[])
        second_channel = str(uuid.uuid4())
        second = self.registry.provision(channel_id=second_channel, role="desktop", scopes=[])
        self.assertEqual(first["principal_id"], "desktop-" + self.channel)
        self.assertNotEqual(first["principal_id"], second["principal_id"])


if __name__ == "__main__":
    unittest.main()
