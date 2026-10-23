"""
app_closer.py — JARVIS plugin

"Jarvis, close Spotify" / "quit Discord" / "exit that game" — finds the
running process(es) for the named app and closes them: graceful terminate
first, then force-kill any stragglers after a short grace period.

Refuses to touch core OS/system processes or JARVIS's own process, no
matter how it's asked — see _BLOCKLIST.

Drop this file into /plugins/ — no other file needs to change.
"""

import difflib
import os
import platform
import time

try:
    import psutil
except ImportError:
    psutil = None

PLUGIN = {
    "name": "close_app",
    "description": (
        "Closes/quits a running application by name. Use when the user says "
        "'close X', 'quit X', 'exit X', 'kill X', 'stop the X app'. Matches "
        "against currently RUNNING processes (fuzzy match on app name), and "
        "closes every process belonging to that app. Never closes core "
        "operating-system processes or JARVIS itself, even if asked."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "app_name": {
                "type": "STRING",
                "description": "Name of the app to close, as the user said it, "
                                "e.g. 'chrome', 'discord', 'notepad'.",
            },
            "force": {
                "type": "BOOLEAN",
                "description": "Optional. If true, force-kill immediately instead "
                                "of asking the app to close gracefully first. Use "
                                "when the user says the app is frozen/unresponsive "
                                "or explicitly says 'force close' / 'force quit'.",
            },
        },
        "required": ["app_name"],
    },
}

_OS = platform.system()
_GRACE_SECONDS = 3.0

# Processes that must NEVER be closed, regardless of match confidence — killing
# these can crash or destabilize the whole OS. Compared against psutil's
# proc.name() lowercase, without extension.
_BLOCKLIST = {
    # Windows
    "explorer", "winlogon", "wininit", "csrss", "smss", "services",
    "lsass", "svchost", "dwm", "system", "registry", "taskhostw", "fontdrvhost",
    # macOS
    "launchd", "kernel_task", "windowserver", "loginwindow", "finder",
    "coreaudiod", "syslogd", "hidd",
    # Linux
    "systemd", "init", "xorg", "x", "xwayland", "wayland", "dbus-daemon",
    "networkmanager", "gnome-shell", "plasmashell", "kwin_x11", "kwin_wayland",
    "pulseaudio", "pipewire",
}


def _score(query_norm: str, name: str) -> float:
    name_norm = name.lower().replace(".exe", "").replace("_", " ").replace("-", " ")
    if query_norm in name_norm or name_norm in query_norm:
        return 0.8
    return difflib.SequenceMatcher(None, query_norm, name_norm).ratio()


def _matching_processes(app_name: str):
    """
    Returns (matched_procs, matched_base_name, ambiguous_other_names).
    matched_procs: list of psutil.Process for the best-matching app family.
    ambiguous_other_names: distinct OTHER app names that scored almost as well,
    from a genuinely different process family (so we can ask for clarification
    instead of guessing).
    """
    query_norm = app_name.strip().lower().replace("_", " ").replace("-", " ")
    my_pid = os.getpid()

    scored = []  # (score, proc, base_name)
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
            if not name or pid == my_pid:
                continue
            base = name.lower().replace(".exe", "")
            if base in _BLOCKLIST:
                continue
            s = _score(query_norm, name)
            if s >= 0.55:
                scored.append((s, proc, base))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not scored:
        return [], None, []

    scored.sort(key=lambda t: t[0], reverse=True)
    top_score, _, top_base = scored[0]

    matched = [p for s, p, b in scored if b == top_base]
    other_families = {b for s, p, b in scored
                       if b != top_base and s >= top_score - 0.12}

    return matched, top_base, sorted(other_families)


def run(parameters: dict, player=None, session_memory=None) -> str:
    app_name = (parameters.get("app_name") or "").strip()
    force = bool(parameters.get("force", False))

    if not app_name:
        return "Sir, I need to know which app to close."

    if psutil is None:
        return "Sir, the psutil library isn't installed. Run 'pip install psutil' and try again."

    if app_name.strip().lower().replace(".exe", "") in _BLOCKLIST:
        return f"Sir, '{app_name}' is a core system process — I won't close that, it could destabilize the machine."

    try:
        matched, base_name, other_families = _matching_processes(app_name)

        if not matched:
            return f"Sir, I don't see '{app_name}' running right now."

        if other_families:
            return (f"Sir, '{app_name}' could mean more than one running app "
                     f"({base_name} or {', '.join(other_families)}) — which one did you mean?")

        closed, stuck = [], []

        if force:
            for proc in matched:
                try:
                    proc.kill()
                    closed.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:
            for proc in matched:
                try:
                    proc.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            gone, alive = psutil.wait_procs(matched, timeout=_GRACE_SECONDS)
            closed.extend(gone)

            for proc in alive:
                try:
                    proc.kill()
                    closed.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    stuck.append(proc)

        n = len(closed)
        if n == 0:
            result_text = f"Sir, I found '{base_name}' but couldn't close it — I may not have permission."
        else:
            plural = "process" if n == 1 else "processes"
            how = "force-closed" if force else "closed"
            result_text = f"{base_name.capitalize()} {how} ({n} {plural})."
            if stuck:
                result_text += f" {len(stuck)} process(es) wouldn't respond even to a force-kill."

    except Exception as e:
        return f"Sir, close_app failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
