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



def _portal_capture_wayland(timeout: float = 35.0) -> tuple[bytes, int, int]:
    """Capture through xdg-desktop-portal without parsing its introspection XML.

    Some GNOME portal versions expose a hyphenated property in introspection
    XML (for example, power-saver-enabled), which dbus-next 0.2.x rejects
    while parsing the entire interface. Use the stable D-Bus method signatures
    directly instead. The desktop may show a permission/selection prompt.
    """
    import asyncio
    from urllib.parse import unquote, urlparse

    from dbus_next import BusType, Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    async def request_capture() -> tuple[bytes, int, int]:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        match_rule = None
        response_handler = None
        try:
            loop = asyncio.get_running_loop()
            response_future = loop.create_future()

            reply = await bus.call(Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface="org.freedesktop.portal.Screenshot",
                member="Screenshot",
                signature="sa{sv}",
                body=["", {"interactive": Variant("b", True)}],
            ))
            if reply.message_type == MessageType.ERROR:
                detail = reply.body[0] if reply.body else "unknown D-Bus error"
                raise RuntimeError(f"Screenshot portal D-Bus error {reply.error_name}: {detail}")
            if not reply.body or not isinstance(reply.body[0], str):
                raise RuntimeError("Screenshot portal returned no request handle.")
            handle = reply.body[0]

            def on_message(message):
                if (
                    message.message_type == MessageType.SIGNAL
                    and message.path == handle
                    and message.interface == "org.freedesktop.portal.Request"
                    and message.member == "Response"
                    and message.signature == "ua{sv}"
                ):
                    if not response_future.done():
                        response_future.set_result((message.body[0], message.body[1]))
                return False

            response_handler = on_message
            bus.add_message_handler(response_handler)
            match_rule = (
                "type='signal',"
                "sender='org.freedesktop.portal.Desktop',"
                f"path='{handle}',"
                "interface='org.freedesktop.portal.Request',"
                "member='Response'"
            )
            match_reply = await bus.call(Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[match_rule],
            ))
            if match_reply.message_type == MessageType.ERROR:
                detail = match_reply.body[0] if match_reply.body else "unknown D-Bus error"
                raise RuntimeError(f"Could not subscribe to screenshot response: {detail}")

            try:
                code, results = await asyncio.wait_for(response_future, timeout=timeout)
            finally:
                await bus.call(Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="RemoveMatch",
                    signature="s",
                    body=[match_rule],
                ))
                match_rule = None

            if code != 0:
                if code == 1:
                    raise RuntimeError("Screenshot was cancelled in the desktop permission dialog.")
                raise RuntimeError(f"Desktop screenshot portal returned response code {code}.")
            uri = results.get("uri")
            if not uri:
                raise RuntimeError("Screenshot portal succeeded but returned no image URI.")
            parsed = urlparse(uri)
            if parsed.scheme != "file":
                raise RuntimeError(f"Screenshot portal returned an unsupported URI scheme: {parsed.scheme!r}.")
            path = Path(unquote(parsed.path))
            if not path.is_file():
                raise RuntimeError("Screenshot portal image path does not exist.")
            return _decode_png(path.read_bytes())
        finally:
            if match_rule:
                try:
                    await bus.call(Message(
                        destination="org.freedesktop.DBus",
                        path="/org/freedesktop/DBus",
                        interface="org.freedesktop.DBus",
                        member="RemoveMatch",
                        signature="s",
                        body=[match_rule],
                    ))
                except Exception:
                    pass
            if response_handler is not None:
                bus.remove_message_handler(response_handler)
            bus.disconnect()

    try:
        return asyncio.run(request_capture())
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"xdg-desktop-portal screenshot request failed ({type(exc).__name__}: {exc}). "
            "Check that xdg-desktop-portal and the GNOME portal backend are installed and running, "
            "and launch Jarvis inside your logged-in graphical session."
        ) from exc


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

    # GNOME Wayland: use the desktop portal first. This is the supported
    # permission-aware API; gnome-screenshot can crash on broken portal setups.
    if wayland and is_gnome:
        try:
            return _portal_capture_wayland()
        except Exception as exc:
            failures.append(f"xdg-desktop-portal: {type(exc).__name__}: {exc}")

    # grim is appropriate for wlroots compositors, not GNOME Shell.
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


# Mark-56 plugin-template entry point. Kept alongside the helper API for the screen agent.
PLUGIN = {
    "name": "desktop_capture",
    "description": "Capture the current desktop for screen-reading requests. Use when the user asks what is on their screen. Returns capture dimensions and a diagnostic; does not upload or store the screenshot.",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        _png, width, height = capture_png()
        return f"Desktop capture succeeded: {width}x{height} pixels. The screenshot is ready for the screen-analysis workflow."
    except Exception as exc:
        return f"Sir, desktop capture failed: {type(exc).__name__}: {exc}"
