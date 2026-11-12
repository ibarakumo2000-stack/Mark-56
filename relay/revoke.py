"""Revoke a relay principal credential by channel and principal ID."""
from __future__ import annotations
import argparse
from relay.registry_factory import build_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--principal-id", required=True)
    args = parser.parse_args()
    registry = build_registry()
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
