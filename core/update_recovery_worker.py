"""Detached recovery worker. Waits for the failed app/installer process to exit."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.update_recovery import process_is_alive, rollback_update


def wait_for_parent(pid: int, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_alive(pid):
            return
        time.sleep(0.5)
    raise TimeoutError("The application process did not exit; recovery was not allowed to replace live files.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transaction_id")
    parser.add_argument("parent_pid", type=int)
    parser.add_argument("--recovery-dir")
    args = parser.parse_args()
    wait_for_parent(args.parent_pid)
    result = rollback_update(args.transaction_id, recovery_dir=args.recovery_dir)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
