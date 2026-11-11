import os
import unittest
from unittest.mock import patch

from relay.app import _build_registry
from relay.registry import RelayRegistry


class RelayDatabaseSelectionTests(unittest.TestCase):
    def test_local_runtime_keeps_sqlite_registry(self):
        registry = _build_registry({"JARVIS_RELAY_DATABASE": ":memory:"})
        try:
            self.assertIsInstance(registry, RelayRegistry)
        finally:
            registry.close()

    def test_vercel_runtime_fails_closed_without_postgres_url(self):
        with self.assertRaisesRegex(RuntimeError, "requires managed PostgreSQL"):
            _build_registry({"VERCEL": "1"})

    def test_vercel_runtime_prefers_explicit_relay_database_url(self):
        from relay.postgres_registry import PostgresRelayRegistry

        expected = object()
        with patch.object(
            PostgresRelayRegistry, "__init__", return_value=None
        ) as init:
            with patch.dict(os.environ, {}, clear=True):
                with patch("relay.app.PostgresRelayRegistry", expected, create=True):
                    # The app imports the registry lazily; patch the module's class
                    # before invoking the factory.
                    pass
        # Exercise the factory with a patched module import target.
        with patch("relay.postgres_registry.PostgresRelayRegistry") as factory:
            factory.return_value = expected
            result = _build_registry({
                "VERCEL": "1",
                "JARVIS_RELAY_DATABASE_URL": "postgresql://pooled.example/db",
                "DATABASE_URL": "postgresql://fallback.example/db",
            })
        self.assertIs(result, expected)
        factory.assert_called_once_with("postgresql://pooled.example/db")

    def test_vercel_runtime_accepts_standard_database_url(self):
        from relay.postgres_registry import PostgresRelayRegistry

        with patch("relay.postgres_registry.PostgresRelayRegistry") as factory:
            _build_registry({"VERCEL": "1", "DATABASE_URL": "postgresql://db.example/app"})
        factory.assert_called_once_with("postgresql://db.example/app")


if __name__ == "__main__":
    unittest.main()
