import json
import unittest
from unittest.mock import patch

from relay.postgres_registry import PostgresRelayRegistry


class _Cursor:
    def __init__(self, *, row=None, rows=None, rowcount=1):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, *, count=0, rows=None, update_count=1):
        self.calls = []
        self.count = count
        self.rows = rows or []
        self.update_count = update_count

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "SELECT COUNT(*) AS count" in sql:
            return _Cursor(row={"count": self.count})
        if "RETURNING message.message_id" in sql:
            return _Cursor(rows=self.rows)
        return _Cursor(rowcount=self.update_count)


class PostgresRelayQueueTests(unittest.TestCase):
    def setUp(self):
        self.registry = PostgresRelayRegistry("postgresql://example.invalid/relay")

    def test_enqueue_bounds_ttl_and_serializes_payload(self):
        connection = _Connection()
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            message_id = self.registry.enqueue_message(
                channel_id="channel",
                sender_principal_id="sender",
                recipient_principal_id="recipient",
                payload={"type": "command", "payload": {"text": "hello"}},
                ttl_seconds=999,
            )
        self.assertTrue(message_id)
        self.assertEqual(len(connection.calls), 3)
        self.assertIn("DELETE FROM relay_messages", connection.calls[0][0])
        sql, params = connection.calls[2]
        self.assertIn("INSERT INTO relay_messages", sql)
        self.assertEqual(json.loads(params[4]), {
            "type": "command", "payload": {"text": "hello"}
        })
        self.assertEqual(params[6] - params[5], 20)

    def test_enqueue_rejects_queue_when_recipient_limit_reached(self):
        connection = _Connection(count=PostgresRelayRegistry.MAX_PENDING_PER_RECIPIENT)
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            with self.assertRaisesRegex(ValueError, "queue is full"):
                self.registry.enqueue_message(
                    channel_id="channel",
                    sender_principal_id="sender",
                    recipient_principal_id="recipient",
                    payload={"type": "command"},
                )
        self.assertEqual(len(connection.calls), 2)
        self.assertIn("DELETE FROM relay_messages", connection.calls[0][0])

    def test_claim_returns_decoded_payload_and_claim_token(self):
        connection = _Connection(rows=[{
            "message_id": "message-1",
            "payload_json": '{"type":"command","payload":{"text":"hello"}}',
        }])
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            claims = self.registry.claim_messages("channel", "recipient", limit=100)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["message_id"], "message-1")
        self.assertEqual(claims[0]["payload"]["payload"]["text"], "hello")
        self.assertTrue(claims[0]["claim_token"])
        self.assertIn("SKIP LOCKED", connection.calls[0][0])
        self.assertEqual(connection.calls[0][1][4], 25)

    def test_acknowledge_and_release_are_claim_scoped(self):
        connection = _Connection()
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            self.assertTrue(self.registry.ack_message("message-1", "claim-1"))
            self.assertTrue(self.registry.release_message("message-2", "claim-2"))
        self.assertIn("DELETE FROM relay_messages", connection.calls[0][0])
        self.assertIn("claim_token=NULL", connection.calls[1][0])

    def test_revocation_also_purges_pending_messages(self):
        connection = _Connection(update_count=1)
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            self.assertTrue(self.registry.revoke("device-1", "channel-1"))
        self.assertEqual(len(connection.calls), 2)
        self.assertIn("UPDATE principals SET revoked_at", connection.calls[0][0])
        self.assertIn("DELETE FROM relay_messages", connection.calls[1][0])


if __name__ == "__main__":
    unittest.main()
