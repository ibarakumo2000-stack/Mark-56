"""Revoke a relay principal credential by channel and principal ID."""
from __future__ import annotations
import argparse
import os
from relay.registry import RelayRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--principal-id", required=True)
    args = parser.parse_args()
    registry = RelayRegistry(os.environ.get("JARVIS_RELAY_DATABASE", "relay-data/relay.sqlite3"))
    try:
        revoked = registry.revoke(args.principal_id, args.channel)
        if not revoked:
            parser.error("Principal was not found or was already revoked")
        print("Relay credential revoked. Reconnect attempts will be rejected.")
        return 0
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
