"""Cross-platform process lock preventing multiple JARVIS desktop instances.

The lock is held by the operating system, so it is released automatically if
JARVIS exits or crashes. The lock file itself may safely remain on disk.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO


def acquire_single_instance_lock(
    lock_path: str | os.PathLike[str] | None = None,
) -> IO[str] | None:
    """Return a held lock-file handle, or None when another instance owns it."""
    path = Path(lock_path) if lock_path is not None else (
        Path.home() / ".jarvis" / "mark56-instance.lock"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")

    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write(" ")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        return handle
    except (OSError, BlockingIOError):
        handle.close()
        return None
