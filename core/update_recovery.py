"""Crash-safe local backup and rollback primitives for Mark 56 updates.

This module deliberately does not download, execute, or install packages. A
platform installer must call prepare_update() before replacing files, call
mark_installing()/mark_awaiting_health_check() around its install operation,
and call confirm_update() only after the new application has passed startup
health checks. A recovery-capable launcher/installer can call
recover_if_interrupted() before launching the application.

Backups and state remain on the user's machine. No backup contents are sent
to GitHub or any remote service.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_TX_ID = re.compile(r"^[0-9a-f]{32}$")
_PENDING_STATES = {"prepared", "installing", "awaiting_health_check"}


def default_recovery_dir() -> Path:
    """Return a per-user recovery location outside the application directory."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        return base / "MARK-LV" / "update-recovery"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "MARK-LV" / "update-recovery"
    base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return base / "mark56" / "update-recovery"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    with temp.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _load_state(recovery_dir: Path, transaction_id: str) -> tuple[Path, dict[str, Any]]:
    if not _TX_ID.fullmatch(str(transaction_id)):
        raise ValueError("Invalid update recovery transaction ID.")
    root = recovery_dir.expanduser().resolve()
    tx_dir = (root / transaction_id).resolve()
    if not _is_within(tx_dir, root) or tx_dir == root:
        raise ValueError("Recovery transaction path is outside the recovery directory.")
    state_path = tx_dir / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise FileNotFoundError("Update recovery state was not found.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Unsupported or invalid update recovery state.")
    return tx_dir, state


def _save_state(tx_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _write_json_atomic(tx_dir / "state.json", state)


def _assert_safe_install_root(install_dir: str | Path, recovery_dir: Path) -> Path:
    raw = Path(install_dir).expanduser()
    if raw.is_symlink():
        raise ValueError("The installation directory must not be a symbolic link.")
    root = raw.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Installation directory does not exist: {root}")
    recovery = recovery_dir.expanduser().resolve()
    if _is_within(recovery, root) or _is_within(root, recovery):
        raise ValueError("The recovery directory and installation directory must be separate.")
    return root


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Refusing to back up a symbolic link: {path.relative_to(root)}")


def _manifest(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries[path.relative_to(root).as_posix()] = _sha256(path)
    return entries


def prepare_update(
    install_dir: str | Path,
    *,
    recovery_dir: str | Path | None = None,
) -> dict[str, str]:
    """Create and verify a complete local snapshot before an installer changes files."""
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    root = _assert_safe_install_root(install_dir, recovery)
    _reject_symlinks(root)

    recovery = recovery.resolve()
    recovery.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    tx_dir = recovery / transaction_id
    tx_dir.mkdir(mode=0o700)
    backup = tx_dir / "backup"
    partial = tx_dir / "backup.partial"

    state: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "install_dir": str(root),
        "backup_dir": str(backup),
        "status": "preparing",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "startup_attempts": 0,
        "manifest": {},
    }
    _save_state(tx_dir, state)
    try:
        shutil.copytree(root, partial, copy_function=shutil.copy2)
        manifest = _manifest(partial)
        if not manifest:
            raise RuntimeError("The installation snapshot is empty; refusing to continue.")
        os.replace(partial, backup)
        state["manifest"] = manifest
        state["status"] = "prepared"
        _save_state(tx_dir, state)
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        shutil.rmtree(tx_dir, ignore_errors=True)
        raise

    _write_json_atomic(recovery / "latest.json", {"transaction_id": transaction_id, "install_dir": str(root), "updated_at": _utc_now()})
    latest_temp = recovery / "latest.txt.tmp"
    latest_temp.write_text(transaction_id + "\\n", encoding="ascii")
    os.replace(latest_temp, recovery / "latest.txt")
    return {
        "transaction_id": transaction_id,
        "status": "prepared",
        "install_dir": str(root),
        "backup_dir": str(backup),
        "file_count": str(len(state["manifest"])),
    }


def _transition(
    transaction_id: str,
    *,
    recovery_dir: str | Path | None,
    allowed: set[str],
    target: str,
) -> dict[str, Any]:
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    tx_dir, state = _load_state(recovery, transaction_id)
    if state.get("status") not in allowed:
        raise RuntimeError(f"Cannot change update state from {state.get('status')!r} to {target!r}.")
    state["status"] = target
    _save_state(tx_dir, state)
    return state


def mark_installing(transaction_id: str, *, recovery_dir: str | Path | None = None) -> dict[str, str]:
    state = _transition(transaction_id, recovery_dir=recovery_dir, allowed={"prepared"}, target="installing")
    return {"transaction_id": transaction_id, "status": state["status"]}


def mark_awaiting_health_check(
    transaction_id: str, *, recovery_dir: str | Path | None = None
) -> dict[str, str]:
    state = _transition(
        transaction_id,
        recovery_dir=recovery_dir,
        allowed={"installing"},
        target="awaiting_health_check",
    )
    return {"transaction_id": transaction_id, "status": state["status"]}


def confirm_update(transaction_id: str, *, recovery_dir: str | Path | None = None) -> dict[str, str]:
    """Commit a transaction after the new application passes its startup health check."""
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    tx_dir, state = _load_state(recovery, transaction_id)
    if state.get("status") == "confirmed":
        return {"transaction_id": transaction_id, "status": "confirmed"}
    if state.get("status") not in {"installing", "awaiting_health_check"}:
        raise RuntimeError(f"Cannot confirm an update in state {state.get('status')!r}.")
    state["status"] = "confirmed"
    state["confirmed_at"] = _utc_now()
    _save_state(tx_dir, state)
    shutil.rmtree(Path(state["backup_dir"]), ignore_errors=True)
    return {"transaction_id": transaction_id, "status": "confirmed"}


def _verify_backup(backup: Path, manifest: dict[str, str]) -> None:
    if not backup.is_dir() or backup.is_symlink():
        raise RuntimeError("The update backup is missing or unsafe; automatic rollback was not attempted.")
    actual = _manifest(backup)
    if actual != manifest:
        raise RuntimeError("The update backup failed its integrity check; original files were left untouched.")


def rollback_update(
    transaction_id: str,
    *,
    recovery_dir: str | Path | None = None,
) -> dict[str, str]:
    """Restore the verified snapshot using same-volume directory renames.

    Call this from a recovery process outside the installation directory. The
    application being replaced must be fully closed, especially on Windows.
    """
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    tx_dir, state = _load_state(recovery, transaction_id)
    if state.get("status") == "rolled_back":
        return {"transaction_id": transaction_id, "status": "rolled_back"}
    if state.get("status") not in (_PENDING_STATES | {"rollback_started"}):
        raise RuntimeError(f"Cannot roll back an update in state {state.get('status')!r}.")

    install_root = Path(state["install_dir"]).expanduser()
    if install_root.is_symlink():
        raise RuntimeError("The installation directory is unsafe; rollback stopped.")
    install_root = install_root.resolve()
    parent = install_root.parent
    restore = parent / f".{install_root.name}.restore-{transaction_id}"
    failed = parent / f".{install_root.name}.failed-{transaction_id}"
    if not install_root.is_dir() and not failed.is_dir():
        raise RuntimeError("The installation directory is missing and no interrupted rollback backup was found.")
    backup = Path(state["backup_dir"]).resolve()
    if not _is_within(backup, tx_dir.resolve()):
        raise RuntimeError("The recorded backup path is outside its transaction directory.")
    manifest = state.get("manifest") or {}
    _verify_backup(backup, manifest)

    state["status"] = "rollback_started"
    _save_state(tx_dir, state)
    try:
        # If a previous rollback completed the swap but crashed before
        # updating its journal, recognize the restored tree.
        if install_root.is_dir() and _manifest(install_root) == manifest:
            shutil.rmtree(failed, ignore_errors=True)
            shutil.rmtree(restore, ignore_errors=True)
        else:
            # A previous attempt may have stopped between either rename.
            # The verified backup is authoritative; restore from a fresh copy.
            if restore.exists():
                shutil.rmtree(restore, ignore_errors=True)
            shutil.copytree(backup, restore, copy_function=shutil.copy2)
            if install_root.exists():
                if failed.exists():
                    shutil.rmtree(install_root, ignore_errors=True)
                else:
                    os.replace(install_root, failed)
            os.replace(restore, install_root)
            shutil.rmtree(failed, ignore_errors=True)

        state["status"] = "rolled_back"
        state["rolled_back_at"] = _utc_now()
        _save_state(tx_dir, state)
        return {"transaction_id": transaction_id, "status": "rolled_back", "install_dir": str(install_root)}
    except Exception:
        # Keep rollback_started so a later recovery pass can retry.
        shutil.rmtree(restore, ignore_errors=True)
        raise


def recover_if_interrupted(
    *,
    recovery_dir: str | Path | None = None,
) -> list[dict[str, str]]:
    """Roll back all transactions left in a pending state by an interrupted installer.

    A platform-specific recovery launcher should invoke this before starting
    the application, while the application directory is not in use.
    """
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    if not recovery.exists():
        return []
    results: list[dict[str, str]] = []
    for state_file in sorted(recovery.glob("*/state.json")):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("schema_version") != _SCHEMA_VERSION:
                continue
            if state.get("status") == "preparing":
                shutil.rmtree(state_file.parent, ignore_errors=True)
                results.append({
                    "transaction_id": state_file.parent.name,
                    "status": "discarded_incomplete_backup",
                })
            elif state.get("status") in (_PENDING_STATES | {"rollback_started"}):
                results.append(rollback_update(
                    str(state.get("transaction_id") or ""),
                    recovery_dir=recovery,
                ))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            results.append({
                "transaction_id": state_file.parent.name,
                "status": "recovery_required",
                "message": str(exc),
            })
    return results


def get_update_recovery_status(
    transaction_id: str,
    *,
    recovery_dir: str | Path | None = None,
) -> dict[str, Any]:
    recovery = Path(recovery_dir).expanduser() if recovery_dir else default_recovery_dir()
    _tx_dir, state = _load_state(recovery, transaction_id)
    return {
        "transaction_id": transaction_id,
        "status": state.get("status"),
        "install_dir": state.get("install_dir"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "startup_attempts": state.get("startup_attempts", 0),
        "file_count": len(state.get("manifest") or {}),
    }
