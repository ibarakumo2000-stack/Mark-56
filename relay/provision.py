"""Provision a relay desktop or device identity; prints the secret only once."""
from __future__ import annotations
import argparse
import json
import os
from relay.registry import RelayRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="UUID shared by the desktop and its paired devices")
    parser.add_argument("--role", choices=("desktop", "device"), required=True)
    parser.add_argument("--principal-id", help="Stable device ID; defaults to a generated UUID")
    parser.add_argument("--scopes", default="", help="Comma-separated least-privilege scopes")
    args = parser.parse_args()
    registry = RelayRegistry(os.environ.get("JARVIS_RELAY_DATABASE", "relay-data/relay.sqlite3"))
    try:
        result = registry.provision(
            channel_id=args.channel, role=args.role,
            principal_id=args.principal_id,
            scopes=[s.strip() for s in args.scopes.split(",") if s.strip()],
        )
        print(json.dumps(result, indent=2))
        print("\nStore this token securely. It cannot be retrieved again.")
        return 0
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
