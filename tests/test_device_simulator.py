import unittest

from core.device_simulator import (
    DeviceSimulator,
    SimulatedCharacteristicError,
    SimulatedConnectionError,
    SimulatedDeviceNotFound,
    SimulatedPermissionError,
)


class DeviceSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.sim = DeviceSimulator.with_demo_devices()
        self.watch = "demo-watch-001"
        self.glasses = "demo-glasses-001"

    def test_discovers_watch_and_glasses_with_capabilities(self):
        devices = self.sim.discover()
        self.assertEqual({item["device_type"] for item in devices}, {"watch", "glasses"})
        watch = self.sim.discover(device_type="watch")[0]
        self.assertIn("health.read", watch["capabilities"])
        self.assertEqual(watch["device_id"], self.watch)

    def test_discovery_does_not_connect(self):
        self.sim.discover()
        self.assertFalse(self.sim.inspect(self.watch)["connected"])

    def test_non_advertised_device_is_not_discovered_or_connectable(self):
        hidden = self.sim.add_device(
            name="Hidden watch", device_type="watch", advertised=False
        )
        self.assertNotIn(hidden, {item["device_id"] for item in self.sim.discover()})
        with self.assertRaises(SimulatedDeviceNotFound):
            self.sim.connect(hidden)

    def test_connection_failure_is_reported(self):
        failing = self.sim.add_device(
            name="Faulty glasses", device_type="glasses",
            connection_error="Simulated radio timeout",
        )
        with self.assertRaisesRegex(SimulatedConnectionError, "radio timeout"):
            self.sim.connect(failing)

    def test_non_connectable_device_fails(self):
        offline = self.sim.add_device(
            name="Sleeping watch", device_type="watch", connectable=False
        )
        with self.assertRaises(SimulatedConnectionError):
            self.sim.connect(offline)

    def test_read_requires_connection_and_permission(self):
        with self.assertRaises(SimulatedConnectionError):
            self.sim.read(self.watch, "2A37")
        self.sim.connect(self.watch)
        with self.assertRaises(SimulatedPermissionError):
            self.sim.read(self.watch, "2A37")
        self.sim.grant_permissions(self.watch, ("health.read",))
        self.assertEqual(self.sim.read(self.watch, "2A37"), 72)

    def test_write_requires_scope_and_updates_value(self):
        self.sim.connect(self.watch)
        with self.assertRaises(SimulatedPermissionError):
            self.sim.write(self.watch, "FFF1", "vibrate")
        self.sim.grant_permissions(self.watch, ("haptics.send",))
        self.sim.write(self.watch, "FFF1", {"pattern": [100, 200]})
        self.assertEqual(self.sim.read(self.watch, "FFF1"), {"pattern": [100, 200]})

    def test_notification_exchange_and_permission(self):
        self.sim.connect(self.glasses)
        with self.assertRaises(SimulatedPermissionError):
            self.sim.notify(self.glasses, "FFF2", {"event": "button"})
        self.sim.grant_permissions(self.glasses, ("notification.receive",))
        self.sim.notify(self.glasses, "FFF2", {"event": "button"})
        self.sim.notify(self.glasses, "FFF2", {"event": "touch"})
        self.assertEqual(
            self.sim.drain_notifications(self.glasses, "FFF2"),
            [{"event": "button"}, {"event": "touch"}],
        )
        self.assertEqual(self.sim.drain_notifications(self.glasses, "FFF2"), [])

    def test_revoke_permission_blocks_future_exchange(self):
        self.sim.connect(self.watch)
        self.sim.grant_permissions(self.watch, ("health.read",))
        self.assertEqual(self.sim.read(self.watch, "2A37"), 72)
        self.sim.revoke_permissions(self.watch, ("health.read",))
        with self.assertRaises(SimulatedPermissionError):
            self.sim.read(self.watch, "2A37")

    def test_characteristic_properties_are_enforced(self):
        self.sim.connect(self.watch)
        with self.assertRaises(SimulatedCharacteristicError):
            self.sim.write(self.watch, "2A19", 10)

    def test_disconnect_blocks_data_exchange(self):
        self.sim.connect(self.watch)
        self.sim.disconnect(self.watch)
        with self.assertRaises(SimulatedConnectionError):
            self.sim.read(self.watch, "2A19")

    def test_unknown_device_and_characteristic_are_reported(self):
        with self.assertRaises(SimulatedDeviceNotFound):
            self.sim.connect("missing")
        self.sim.connect(self.watch)
        with self.assertRaises(SimulatedCharacteristicError):
            self.sim.read(self.watch, "2AFF")

    def test_inspection_returns_metadata_not_mutable_state(self):
        details = self.sim.inspect(self.watch)
        self.assertEqual(details["device_type"], "watch")
        self.assertTrue(details["services"])
        details["capabilities"].append("desktop.control")
        self.assertNotIn("desktop.control", self.sim.inspect(self.watch)["capabilities"])

    def test_unknown_permission_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            self.sim.grant_permissions(self.watch, ("root.access",))


if __name__ == "__main__":
    unittest.main()
