#!/usr/bin/env python3
"""Interactive smoke test for permission-based GNOME Wayland screen capture.

Run from the Mark 56 repository root inside the logged-in GNOME Wayland session.
The GNOME portal will ask the user to approve monitor capture. No screenshot is
uploaded or saved by this script.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if session != "wayland":
        print(f"FAIL: expected XDG_SESSION_TYPE=wayland, got {session or 'unset'}.")
        return 2
    if "gnome" not in desktop.lower():
        print(f"WARNING: expected GNOME; detected {desktop or 'unknown desktop'}.")
    try:
        from plugins import wayland_screencast
        from plugins.desktop_capture import _decode_png
        print("Requesting GNOME ScreenCast permission. Approve the monitor prompt.")
        print(wayland_screencast.start_monitoring())
        frame = wayland_screencast.capture_monitor_frame()
        if frame is None:
            raise RuntimeError("ScreenCast session started but no frame was returned.")
        png, width, height = frame
        _decode_png(png)
        if width < 64 or height < 64 or not png.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
            raise RuntimeError("Captured frame failed PNG/dimension validation.")
        print(f"PASS: fresh PipeWire frame captured and decoded ({width}x{height}).")
        print("PASS: capture used the permission-approved GNOME portal stream.")
        return 0
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    finally:
        try:
            print(wayland_screencast.stop_monitoring())
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
