"""Command-line adapter used by platform installers and launchers."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core import update_recovery as recovery


def _latest(recovery_dir=None):
    root = Path(recovery_dir).expanduser() if recovery_dir else recovery.default_recovery_dir()
    pointer = root / "latest.json"
    if pointer.is_symlink() or not pointer.is_file():
        raise FileNotFoundError("No update transaction is available.")
    data = json.loads(pointer.read_text(encoding="utf-8"))
    txid = str(data.get("transaction_id") or "")
    tx_dir, state = recovery._load_state(root, txid)
    return root, txid, state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", metavar="INSTALL_DIR")
    parser.add_argument("--mark-installing", action="store_true")
    parser.add_argument("--mark-awaiting", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--rollback-latest", action="store_true")
    parser.add_argument("--rollback-id")
    parser.add_argument("--begin-startup", metavar="INSTALL_DIR")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--confirm-id")
    parser.add_argument("--recovery-dir")
    args = parser.parse_args()
    root = Path(args.recovery_dir).expanduser() if args.recovery_dir else recovery.default_recovery_dir()

    if args.prepare:
        result = recovery.prepare_update(args.prepare, recovery_dir=root)
        recovery.mark_installing(result["transaction_id"], recovery_dir=root)
        result["status"] = "installing"
    elif args.mark_installing:
        root, txid, state = _latest(root)
        recovery.mark_installing(txid, recovery_dir=root)
        result = {"transaction_id": txid, "status": "installing"}
    elif args.mark_awaiting:
        root, txid, state = _latest(root)
        recovery.mark_awaiting_health_check(txid, recovery_dir=root)
        result = {"transaction_id": txid, "status": "awaiting_health_check"}
    elif args.confirm_id:
        result = recovery.confirm_update(args.confirm_id, recovery_dir=root)
    elif args.confirm:
        root, txid, state = _latest(root)
        result = recovery.confirm_update(txid, recovery_dir=root)
    elif args.rollback_latest:
        root, txid, state = _latest(root)
        result = recovery.rollback_update(txid, recovery_dir=root)
    elif args.rollback_id:
        result = recovery.rollback_update(args.rollback_id, recovery_dir=root)
    elif args.begin_startup:
        pending = recovery.pending_transaction_for_install(args.begin_startup, recovery_dir=root)
        if not pending:
            result = {"status": "no_pending_update"}
        else:
            txid, state = pending
            pid = int(state.get("startup_pid") or 0)
            if pid:
                try:
                    os.kill(pid, 0)
                    result = {"status": "already_running", "transaction_id": txid}
                    print(json.dumps(result))
                    return 0
                except OSError:
                    pass
            attempts = int(state.get("startup_attempts") or 0)
            if attempts >= 1:
                result = {"status": "needs_rollback", "transaction_id": txid,
                          "backup_dir": state.get("backup_dir")}
            else:
                tx_dir, latest = recovery._load_state(root, txid)
                latest["startup_attempts"] = attempts + 1
                latest["startup_pid"] = args.pid or os.getpid()
                latest["startup_started_at"] = recovery._utc_now()
                recovery._save_state(tx_dir, latest)
                result = {"status": "health_check_started", "transaction_id": txid,
                          "backup_dir": state.get("backup_dir")}
    else:
        parser.error("select a recovery operation")
        return 2

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
