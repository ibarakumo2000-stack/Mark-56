import unittest

from relay.desktop_runtime import DesktopRelayRuntime


class DesktopRelayRuntimeTests(unittest.TestCase):
    def test_event_queue_keeps_only_safe_metadata(self):
        runtime = DesktopRelayRuntime(event_limit=2)
        runtime._record_message({
            "type": "notification", "device_id": "phone-1",
            "payload": {"title": "private notification body"},
        })
        events = runtime.drain_events()
        self.assertEqual(events[0]["type"], "notification")
        self.assertEqual(events[0]["device_id"], "phone-1")
        self.assertNotIn("payload", events[0])

    def test_event_queue_is_bounded(self):
        runtime = DesktopRelayRuntime(event_limit=2)
        for index in range(4):
            runtime._record_message({"type": "command", "device_id": f"device-{index}"})
        events = runtime.drain_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["device_id"], "device-2")

    def test_invalid_configuration_fails_closed_without_network(self):
        runtime = DesktopRelayRuntime()
        self.assertEqual(runtime.start(
            base_url="http://relay.invalid",
            channel_id="not-a-uuid",
            principal_id="desktop",
            token="invalid",
        ), "error")
        self.assertEqual(runtime.stop(), "stopped")


if __name__ == "__main__":
    unittest.main()
