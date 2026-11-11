"""Read-only desktop capability diagnostics for Mark 56.

The module reports what the current OS/session appears to support. It never
requests screen-sharing permission, changes OS security settings, or bypasses
desktop portals. Actual capture remains subject to the user's OS permission.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    status: str
    detail: str
    action: str = ""


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def get_platform_report() -> dict:
    system = platform.system()
    release = platform.release()
    machine = platform.machine()
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")
    checks: list[Capability] = []

    if system == "Linux":
        if not session:
            session = "wayland" if os.environ.get("WAYLAND_DISPLAY") else (
                "x11" if os.environ.get("DISPLAY") else "unknown"
            )
        if session == "wayland":
            portal = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) and _has_module("dbus_next")
            gst = _has_module("gi")
            checks.append(Capability(
                "Screen capture", "permission-required" if portal and gst else "limited",
                "Wayland screen capture must be approved through the desktop portal. "
                + ("Portal and GStreamer Python bindings appear available." if portal and gst
                   else "Install/enable the desktop portal, dbus-next and GStreamer bindings."),
                "Open the desktop screen-sharing prompt by starting a screen capture from Mark 56."
            ))
            checks.append(Capability(
                "Global hotkeys", "limited",
                "Wayland compositors restrict global keyboard hooks; in-window shortcuts remain available.",
                "Use the focused Mark 56 window or configure a compositor-supported shortcut."
            ))
        else:
            checks.append(Capability(
                "Screen capture", "available" if os.environ.get("DISPLAY") else "limited",
                "X11 display detected." if os.environ.get("DISPLAY") else "No X11 DISPLAY is available.",
                "Check the desktop session and screenshot utility permissions."
            ))
            checks.append(Capability(
                "Global hotkeys", "available" if any(shutil.which(x) for x in ("ydotool", "xdotool")) else "limited",
                "A desktop input utility is present." if any(shutil.which(x) for x in ("ydotool", "xdotool"))
                else "No supported desktop input utility was detected.",
                "Install and configure a supported input utility if global hotkeys are required."
            ))
    elif system == "Darwin":
        checks.extend([
            Capability("Screen capture", "permission-required",
                       "macOS Screen Recording permission is controlled by System Settings; this diagnostic cannot verify user approval.",
                       "Review Privacy & Security → Screen & System Audio Recording."),
            Capability("Global hotkeys", "limited",
                       "Global key monitoring may require Accessibility permission.",
                       "Review Privacy & Security → Accessibility.")
        ])
    elif system == "Windows":
        checks.extend([
            Capability("Screen capture", "permission-required",
                       "Capture depends on Windows graphics/session permissions and the active desktop.",
                       "Unlock the desktop and approve any Windows capture prompt."),
            Capability("Global hotkeys", "available",
                       "Windows supports registered application hotkeys; individual hooks may still be blocked by policy.")
        ])
    else:
        checks.append(Capability("Desktop integration", "unknown",
                                 "This operating system has no dedicated Mark 56 capability profile yet."))

    checks.append(Capability(
        "Audio devices", "available" if _has_module("sounddevice") or _has_module("pyaudio") else "check",
        "Audio backend package detected." if (_has_module("sounddevice") or _has_module("pyaudio"))
        else "Audio availability is determined by the active Qt/audio backend."
    ))
    return {
        "system": system, "release": release, "machine": machine,
        "session": session or "unknown", "desktop": desktop or "unknown",
        "capabilities": [asdict(x) for x in checks],
    }


def format_platform_report(report: dict | None = None) -> str:
    report = report or get_platform_report()
    lines = [
        "DESKTOP PLATFORM STATUS",
        f"OS: {report['system']} {report['release']} ({report['machine']})",
        f"Session: {report['session']}",
        f"Desktop: {report['desktop']}",
        "",
    ]
    for item in report["capabilities"]:
        lines.append(f"{item['name']}: {item['status'].replace('-', ' ').upper()}")
        lines.append(f"  {item['detail']}")
        if item.get("action"):
            lines.append(f"  Suggested action: {item['action']}")
        lines.append("")
    lines.append("These are diagnostic indicators, not proof that an OS permission has been granted.")
    return "\n".join(lines)
