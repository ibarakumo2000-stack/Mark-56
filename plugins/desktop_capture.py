"""Desktop screenshot adapter with ordered, bounded backend fallbacks.

On Linux Wayland, PyAutoGUI/X11 may not have permission to capture the whole
desktop. Prefer the desktop's native screenshot path, then fall back to Python
capture APIs. A backend is accepted only if it returns a decodable, non-empty
image with visible pixel variation; blank/black placeholder frames trigger the
next fallback instead of being passed to the vision model as a successful shot.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _decode_png(data: bytes) -> tuple[bytes, int, int]:
    from PIL import Image, ImageStat

    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.load()
    if image.width < 64 or image.height < 64:
        raise RuntimeError(f"Capture image is suspiciously small ({image.width}x{image.height}).")

    # Detect the common failure mode where an XWayland backend returns a
    # black/uniform placeholder while the real GNOME Wayland desktop is visible.
    sample = image.copy()
    sample.thumbnail((64, 64))
    stats = ImageStat.Stat(sample)
    spread = max(channel[1] - channel[0] for channel in stats.extrema)
    deviation = max(stats.stddev)
    if spread < 8 or deviation < 2.0:
        raise RuntimeError(
            "Capture returned an almost uniform/blank frame; refusing to send it "
            "to screen analysis. This often indicates a Wayland/XWayland capture limitation."
        )

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue(), image.width, image.height


def _run_capture(command: list[str], timeout: float = 5.0) -> tuple[bytes, int, int]:
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False, close_fds=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace")[:180]
        raise RuntimeError(f"{Path(command[0]).name} exited {result.returncode}: {detail}")
    return _decode_png(result.stdout)


def _file_capture(command_builder, timeout: float = 8.0) -> tuple[bytes, int, int]:
    fd, name = tempfile.mkstemp(prefix="mark56-screen-", suffix=".png")
    os.close(fd)
    path = Path(name)
    try:
        result = subprocess.run(command_builder(str(path)), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False, close_fds=True)
        if result.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
            detail = result.stderr.decode("utf-8", "replace")[:180]
            raise RuntimeError(f"Capture command failed ({result.returncode}): {detail}")
        return _decode_png(path.read_bytes())
    finally:
        path.unlink(missing_ok=True)


def _python_capture_mss() -> tuple[bytes, int, int]:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
    return _decode_png(buf.getvalue())


def _python_capture_pyautogui() -> tuple[bytes, int, int]:
    import pyautogui
    buf = io.BytesIO()
    pyautogui.screenshot().save(buf, format="PNG")
    return _decode_png(buf.getvalue())


def capture_png() -> tuple[bytes, int, int]:
    """Return a verified screenshot and dimensions, or raise actionable details."""
    failures: list[str] = []
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    is_gnome = "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

    # GNOME Wayland should try its own screenshot utility first. grim is for
    # wlroots compositors and generally cannot capture a GNOME Shell desktop.
    if wayland and is_gnome and shutil.which("gnome-screenshot"):
        try:
            exe = shutil.which("gnome-screenshot") or "gnome-screenshot"
            return _file_capture(lambda p: [exe, "--file", p])
        except Exception as exc:
            failures.append(f"gnome-screenshot: {type(exc).__name__}: {exc}")

    if wayland and not is_gnome and shutil.which("grim"):
        try:
            return _run_capture([shutil.which("grim") or "grim", "-"], timeout=5.0)
        except Exception as exc:
            failures.append(f"grim: {type(exc).__name__}: {exc}")

    if shutil.which("gnome-screenshot") and not (wayland and is_gnome):
        try:
            exe = shutil.which("gnome-screenshot") or "gnome-screenshot"
            return _file_capture(lambda p: [exe, "--file", p])
        except Exception as exc:
            failures.append(f"gnome-screenshot: {type(exc).__name__}: {exc}")
    if shutil.which("spectacle"):
        try:
            exe = shutil.which("spectacle") or "spectacle"
            return _file_capture(lambda p: [exe, "--background", "--nonotify", "--output", p])
        except Exception as exc:
            failures.append(f"spectacle: {type(exc).__name__}: {exc}")

    try:
        return _python_capture_mss()
    except Exception as exc:
        failures.append(f"mss: {type(exc).__name__}: {exc}")

    try:
        return _python_capture_pyautogui()
    except Exception as exc:
        failures.append(f"pyautogui: {type(exc).__name__}: {exc}")

    summary = "; ".join(failures[-5:])
    hint = (
        " On GNOME Wayland, ensure the GNOME screenshot/desktop portal services are "
        "installed and running; log out and back in after repairing portal packages."
        if wayland and is_gnome else
        " Check the active desktop session and install a supported screenshot backend."
    )
    raise RuntimeError(
        "No usable desktop screenshot was captured. Blank/black frames are rejected."
        + hint + " Backend diagnostics: " + summary[:1400]
    )
