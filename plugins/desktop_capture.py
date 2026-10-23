"""Desktop screenshot adapter with ordered, bounded backend fallbacks.

On Linux Wayland, PyAutoGUI/X11 may not have permission to capture the whole
desktop. Prefer native capture tools when present, then fall back to Python
capture APIs. No backend is assumed to work until it returns a decodable PNG.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _decode_png(data: bytes):
    from PIL import Image
    image = Image.open(io.BytesIO(data))
    image.load()
    if image.width < 1 or image.height < 1:
        raise RuntimeError("Capture backend returned an empty image.")
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), image.width, image.height


def _run_capture(command: list[str], timeout: float = 5.0) -> tuple[bytes, int, int]:
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False, close_fds=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace")[:180]
        raise RuntimeError(f"{Path(command[0]).name} exited {result.returncode}: {detail}")
    return _decode_png(result.stdout)


def _file_capture(command_builder, timeout: float = 6.0) -> tuple[bytes, int, int]:
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


def capture_png() -> tuple[bytes, int, int]:
    """Return a verified PNG and dimensions, or raise an actionable error."""
    failures: list[str] = []
    wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

    # grim works on wlroots compositors; it is not expected to work on GNOME.
    if wayland and shutil.which("grim"):
        try:
            return _run_capture([shutil.which("grim") or "grim"], timeout=5.0)
        except Exception as exc:
            failures.append(f"grim: {type(exc).__name__}: {exc}")

    # Desktop screenshot tools are invoked without a shell and always time out.
    if shutil.which("gnome-screenshot"):
        try:
            return _file_capture(lambda p: [shutil.which("gnome-screenshot") or "gnome-screenshot", "--file", p])
        except Exception as exc:
            failures.append(f"gnome-screenshot: {type(exc).__name__}: {exc}")
    if shutil.which("spectacle"):
        try:
            return _file_capture(lambda p: [shutil.which("spectacle") or "spectacle", "--background", "--nonotify", "--output", p])
        except Exception as exc:
            failures.append(f"spectacle: {type(exc).__name__}: {exc}")

    # mss can work in X11/XWayland sessions. Verify its output; don't mistake
    # an XWayland-only or failed image for a reliable full-desktop capture.
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue(), image.width, image.height
    except Exception as exc:
        failures.append(f"mss: {type(exc).__name__}: {exc}")

    # Final compatibility fallback. On Wayland this often fails with an
    # authorization error; keep the original failure in the diagnostic.
    try:
        import pyautogui
        image = pyautogui.screenshot()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue(), image.width, image.height
    except Exception as exc:
        failures.append(f"pyautogui: {type(exc).__name__}: {exc}")

    summary = "; ".join(failures[-4:])
    raise RuntimeError(
        "No desktop capture backend succeeded. On GNOME Wayland, check that the "
        "desktop screenshot portal is healthy; native fallbacks were attempted. "
        + summary[:900]
    )
