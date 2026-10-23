"""
android_control.py — JARVIS plugin

"Jarvis, lock my phone" / "put my phone to sleep" / "restart my phone" —
controls an Android phone connected via ADB (USB debugging, or wireless
debugging on Android 11+). No root required.

iPhone is NOT supported: iOS does not expose lock/sleep/reboot to any
third-party tool short of enterprise MDM enrollment, which is out of scope
for a personal voice-controlled action.

Setup (one-time, on the phone):
  1. Settings -> About phone -> tap "Build number" 7 times to unlock
     Developer Options.
  2. Settings -> Developer Options -> enable "USB debugging"
     (or "Wireless debugging" for Android 11+).
  3. Connect via USB and accept the "Allow USB debugging?" prompt on the
     phone — OR pair wirelessly with `adb pair <ip>:<port>` once, then
     `adb connect <ip>:<port>`.
  4. `adb` must be installed and on PATH on the machine running JARVIS
     (part of Android Platform Tools).

Drop this file into /plugins/ — no other file needs to change.
"""

import shutil
import subprocess

try:
    from core import confirm
except ImportError:
    confirm = None  # standalone/test environment — restart falls back to direct execution

PLUGIN = {
    "name": "control_android_phone",
    "description": (
        "Locks/sleeps the screen or restarts an ANDROID phone connected via ADB "
        "(USB or wireless debugging). Use for 'lock my phone', 'put my phone to "
        "sleep', 'restart my phone', 'reboot my phone'. Android has no separate "
        "lock vs sleep state, so 'lock' and 'sleep' do the same thing: turn the "
        "screen off. Restart requires the user to confirm on the JARVIS HUD "
        "first. NOT for iPhone/iOS — there is no supported way to control an "
        "iPhone this way; say so if asked about an iPhone instead of attempting it."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["lock", "sleep", "restart", "status"],
                "description": "lock/sleep = turn the phone's screen off. "
                                "restart = reboot the phone (needs on-screen "
                                "confirmation). status = report whether a phone "
                                "is connected and ready.",
            },
            "device_id": {
                "type": "STRING",
                "description": "Optional. ADB device serial, only needed if "
                                "more than one Android device is connected at once.",
            },
        },
        "required": ["action"],
    },
}


def _adb():
    return shutil.which("adb")


def _run(adb, *args, timeout=10):
    return subprocess.run([adb] + list(args), capture_output=True, text=True, timeout=timeout)


def _list_devices(adb):
    """Returns list of (serial, state) — state is 'device' (ready), 'unauthorized', or 'offline'."""
    out = _run(adb, "devices").stdout
    devices = []
    for line in out.strip().splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


def _pick_device(adb, device_id: str):
    """Returns (serial, error_message). error_message is '' on success."""
    devices = _list_devices(adb)
    ready = [d for d, state in devices if state == "device"]
    unauthorized = [d for d, state in devices if state == "unauthorized"]

    if device_id:
        for d, state in devices:
            if d == device_id:
                if state == "device":
                    return d, ""
                return "", f"Sir, '{device_id}' is connected but shows as '{state}' — check the phone screen for a debugging prompt."
        return "", f"Sir, I don't see a device '{device_id}' connected."

    if not devices:
        return "", ("Sir, no Android phone is connected. Plug it in via USB with USB "
                     "debugging enabled (or connect via wireless debugging), and accept "
                     "the prompt on the phone.")
    if unauthorized and not ready:
        return "", ("Sir, your phone is connected but hasn't authorized this computer yet — "
                     "check the phone screen for an 'Allow USB debugging?' prompt.")
    if len(ready) > 1:
        return "", (f"Sir, {len(ready)} phones are connected ({', '.join(ready)}) — "
                     "tell me which device_id to use.")
    if not ready:
        return "", "Sir, no authorized Android phone is ready right now."

    return ready[0], ""


def _is_awake(adb, serial) -> bool:
    try:
        out = _run(adb, "-s", serial, "shell", "dumpsys", "power").stdout
        for line in out.splitlines():
            if "mWakefulness=" in line:
                return "Awake" in line
    except Exception:
        pass
    return True  # unknown -> assume awake so lock/sleep still fires


def _screen_off(adb, serial) -> str:
    if not _is_awake(adb, serial):
        return "Sir, the phone's screen is already off."
    _run(adb, "-s", serial, "shell", "input", "keyevent", "26")
    return "Phone screen locked, sir."


def _do_reboot(adb, serial) -> str:
    _run(adb, "-s", serial, "reboot", timeout=15)
    return "Phone is restarting, sir."


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    device_id = (parameters.get("device_id") or "").strip()

    if action not in ("lock", "sleep", "restart", "status"):
        return "Sir, tell me lock, sleep, restart, or status for the phone."

    adb = _adb()
    if adb is None:
        return ("Sir, ADB isn't installed on this machine — install Android "
                "Platform Tools and make sure 'adb' is on PATH.")

    try:
        if action == "status":
            devices = _list_devices(adb)
            if not devices:
                return "Sir, no Android phone is currently connected."
            parts = [f"{d} ({state})" for d, state in devices]
            return f"Connected: {', '.join(parts)}."

        serial, err = _pick_device(adb, device_id)
        if err:
            return err

        if action in ("lock", "sleep"):
            result_text = _screen_off(adb, serial)

        elif action == "restart":
            if confirm is None:
                # No HUD bound (e.g. running standalone/tests) — do it directly.
                result_text = _do_reboot(adb, serial)
            else:
                if confirm.pending_title():
                    return ("There is already a confirmation waiting on screen. "
                            "Ask the user to answer that one first.")
                return confirm.request(
                    key="restart_phone",
                    title="Restart your phone",
                    detail="Any unsaved work in open apps on the phone may be lost. "
                           "The phone will reboot.",
                    run=lambda a=adb, s=serial: _do_reboot(a, s),
                )

    except subprocess.TimeoutExpired:
        return "Sir, the phone didn't respond in time — check the connection."
    except Exception as e:
        return f"Sir, control_android_phone failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
