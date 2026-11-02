import asyncio
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


class FakeBridge:
    def __init__(self):
        self.sent = []

    async def send_to_device(self, device_id, message_type, payload):
        self.sent.append((device_id, message_type, payload))


class DesktopRelayPingResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_assistant_ping_gets_a_fixed_pong_response(self):
        runtime = DesktopRelayRuntime()
        bridge = FakeBridge()
        runtime._bridge = bridge

        runtime._record_message({
            "type": "command", "device_id": "phone-1",
            "payload": {"action": "assistant.ping"},
        })
        await asyncio.sleep(0)
        self.assertEqual(bridge.sent, [
            ("phone-1", "command", {"action": "assistant.pong"})
        ])

    async def test_other_remote_commands_are_not_executed_or_auto_replied(self):
        runtime = DesktopRelayRuntime()
        bridge = FakeBridge()
        runtime._bridge = bridge
        runtime._record_message({
            "type": "command", "device_id": "phone-1",
            "payload": {"action": "shell.exec", "command": "whoami"},
        })
        await asyncio.sleep(0)
        self.assertEqual(bridge.sent, [])


if __name__ == "__main__":
    unittest.main()
