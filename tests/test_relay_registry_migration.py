import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.postgres_registry import PostgresRelayRegistry
from relay.migrate_registry import migrate


CHANNEL = "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11"


class _Cursor:
    def __init__(self, row=None, rowcount=1):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "SELECT principal_id, token_hash" in sql:
            return _Cursor(row=self.existing)
        return _Cursor(rowcount=1)


class PostgresRegistryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = PostgresRelayRegistry("postgresql://example.invalid/relay")
        self.record = {
            "principal_id": "phone-1",
            "channel_id": CHANNEL,
            "role": "device",
            "token_hash": "a" * 64,
            "scopes_json": '["command.send","notification.receive"]',
            "created_at": 1700000000.0,
            "revoked_at": None,
        }

    def test_imports_hash_and_metadata_without_raw_token(self):
        connection = _Connection()
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            imported, skipped = self.registry.import_principals([self.record])
        self.assertEqual((imported, skipped), (1, 0))
        sql, params = connection.calls[1]
        self.assertIn("INSERT INTO principals", sql)
        self.assertEqual(params[3], "a" * 64)
        self.assertNotIn("rly_", repr(params))

    def test_matching_existing_principal_is_idempotently_skipped(self):
        connection = _Connection(existing={
            "principal_id": "phone-1", "token_hash": "a" * 64,
        })
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            result = self.registry.import_principals([self.record])
        self.assertEqual(result, (0, 1))
        self.assertEqual(len(connection.calls), 1)

    def test_conflicting_principal_or_token_hash_aborts_migration(self):
        connection = _Connection(existing={
            "principal_id": "phone-1", "token_hash": "b" * 64,
        })
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            with self.assertRaisesRegex(ValueError, "conflicts"):
                self.registry.import_principals([self.record])

    def test_invalid_hash_is_rejected(self):
        connection = _Connection()
        invalid = dict(self.record, token_hash="not-a-sha256")
        with patch.object(self.registry, "_ensure_schema"), patch.object(
            self.registry, "_connect", return_value=connection
        ):
            with self.assertRaisesRegex(ValueError, "invalid token hash"):
                self.registry.import_principals([invalid])

    def test_migration_reads_sqlite_registry_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "relay.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("""CREATE TABLE principals (
                    principal_id TEXT, channel_id TEXT, role TEXT,
                    token_hash TEXT, scopes_json TEXT, created_at REAL,
                    revoked_at REAL
                )""")
                connection.execute(
                    "INSERT INTO principals VALUES (?, ?, ?, ?, ?, ?, ?)",
                    tuple(self.record[key] for key in (
                        "principal_id", "channel_id", "role", "token_hash",
                        "scopes_json", "created_at", "revoked_at",
                    )),
                )
            fake_registry = unittest.mock.Mock()
            fake_registry.import_principals.return_value = (1, 0)
            fake_registry.close.return_value = None
            with patch("relay.migrate_registry.PostgresRelayRegistry", return_value=fake_registry):
                result = migrate(str(source), "postgresql://example.invalid/relay")
            self.assertEqual(result, {
                "source_principals": 1, "imported": 1, "already_present": 0,
            })
            fake_registry.import_principals.assert_called_once()
            self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main()
