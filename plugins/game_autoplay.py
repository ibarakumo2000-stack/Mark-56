"""
game_autoplay — JARVIS plugin.

Drop this file straight into the `plugins/` folder of your Mark-LII (JARVIS)
install, alongside code_architect.py / screen_vision.py if you added those.
No other file needs to change; `core/plugin_loader.py` discovers it
automatically at startup.

What it does
------------
"JARVIS, take over [game]" -> it focuses the game window, then loops:
  screenshot -> Gemini vision decides the next move from the control scheme
  you gave it -> JARVIS presses those keys/clicks -> repeat -- until it
  detects a win/loss screen, gets stuck, hits the time limit, or you tell
  it to stop.

Read this before you use it
----------------------------
Be honest with yourself about what this can and can't do:

- It is NOT a guaranteed-win button. It's a general vision+reasoning loop,
  not a specialized bot for any particular game. It'll do reasonably well
  at slower-paced, simple, single-player games (puzzle games, turn-based
  games, basic platformers) and will struggle or fail outright at
  fast-twitch/reflex games, because every decision costs a real API round
  trip (well over a second), and at anything visually complex or with
  hidden state the screenshot doesn't show.
- Use it on single-player / offline games. Most online and competitive
  multiplayer games explicitly prohibit bots/automation in their terms of
  service and run anti-cheat that can ban your account for exactly this
  kind of input automation — this plugin doesn't know or care what a
  game's rules say, so that judgment call is on you.
- Safety: pyautogui's fail-safe stays ON — slam your mouse into a screen
  corner at any moment and all automated input stops immediately. You can
  also just say "JARVIS, stop playing" (action: stop). There's a hard
  max-duration cap so it can never run forever unattended, a small
  blacklist of dangerous key combos (alt+F4, alt+Tab, the Windows key,
  etc.) it will never send, and it releases any held key the moment it
  stops, errors out, or gets stuck.

Requirements
------------
Nothing new beyond what Mark-LII already needs: `pyautogui` (already in
requirements.txt) for input control, `mss` + `pillow` for screenshots, and
the same `config/api_keys.json` (`"gemini_api_key"`) every action reads.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import mss
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


# --------------------------------------------------------------------------
# Config — same convention as every other action/plugin in this project.
# --------------------------------------------------------------------------

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
MODEL_VISION    = "gemini-flash-latest"

DEFAULT_DECISION_INTERVAL = 1.5    # seconds between screenshot->decision->action cycles
MIN_DECISION_INTERVAL     = 0.8
MAX_DECISION_INTERVAL     = 5.0

DEFAULT_MAX_DURATION = 300     # 5 minutes
MIN_MAX_DURATION      = 15
HARD_MAX_DURATION     = 1800   # 30 minutes absolute ceiling

MAX_HOLD_MS       = 2000
STUCK_LIMIT        = 4          # consecutive "stuck" reports before giving up
HISTORY_LIMIT       = 6


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        key = json.load(f).get("gemini_api_key", "")
    if not key:
        raise RuntimeError("gemini_api_key not found in config/api_keys.json")
    return key


def _get_model(model_name: str):
    from google import genai
    _c = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model_name, contents=contents)

    return _W()


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


# --------------------------------------------------------------------------
# Window focus — same cross-platform approach actions/computer_control.py
# uses (kept self-contained here so this file stays drop-in on its own).
# --------------------------------------------------------------------------

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(platform.system(), "linux")


def _focus_window(title: str) -> tuple[bool, str]:
    os_name = _platform_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return True, f"Focused window: {title}"
        except Exception as e:
            return False, f"Could not focus '{title}' on Windows: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            time.sleep(0.3)
            return True, f"Focused window: {title}"
        except Exception as e:
            return False, f"Could not focus '{title}' on macOS: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(["wmctrl", "-a", title], capture_output=True, timeout=5)
            if result.returncode == 0:
                time.sleep(0.3)
                return True, f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            subprocess.run(["xdotool", "search", "--name", title, "windowactivate"],
                            capture_output=True, timeout=5)
            time.sleep(0.3)
            return True, f"Focused window: {title}"
        except FileNotFoundError:
            return False, "Focusing windows on Linux needs wmctrl or xdotool installed."
        except Exception as e:
            return False, f"Could not focus '{title}' on Linux: {e}"

    return False, f"Unknown OS '{os_name}'."


def _capture_screen_image(monitor_index: int | None = None) -> "PIL.Image.Image":
    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")
    if not _PIL:
        raise RuntimeError("Pillow is not installed. Run: pip install pillow")
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index and 1 <= monitor_index < len(monitors):
            target = monitors[monitor_index]
        else:
            target = monitors[1] if len(monitors) > 1 else monitors[0]
        shot = sct.grab(target)
        sw, sh = shot.size
        img = PIL.Image.frombytes("RGB", (sw, sh), shot.bgra, "raw", "BGRX")
    return img


# --------------------------------------------------------------------------
# Input safety — allowed keys and a hard blacklist of disruptive combos.
# --------------------------------------------------------------------------

_FALLBACK_KEYS = set(
    list("abcdefghijklmnopqrstuvwxyz0123456789")
    + ["left", "right", "up", "down", "space", "enter", "esc", "escape", "tab",
       "shift", "shiftleft", "shiftright", "ctrl", "ctrlleft", "ctrlright",
       "alt", "altleft", "altright", "backspace", "delete",
       "comma", "period", "minus", "equal", "quote", "semicolon",
       "f1", "f2", "f3", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]
)

_BLACKLIST_SINGLE = {"win", "winleft", "winright", "printscreen", "scrolllock",
                      "numlock", "capslock", "sleep"}
_BLACKLIST_COMBOS = [
    {"alt", "f4"}, {"altleft", "f4"}, {"altright", "f4"},
    {"alt", "tab"}, {"altleft", "tab"}, {"altright", "tab"},
    {"ctrl", "alt", "delete"}, {"ctrlleft", "altleft", "delete"},
    {"ctrl", "w"}, {"ctrlleft", "w"},
    {"ctrl", "q"}, {"ctrlleft", "q"},
]


def _allowed_keys() -> set[str]:
    if _PYAUTOGUI:
        try:
            return set(k.lower() for k in pyautogui.KEYBOARD_KEYS)
        except Exception:
            pass
    return _FALLBACK_KEYS


def _sanitize_keys(requested: list) -> list[str]:
    """Returns a cleaned key list, or [] if the request is unsafe/invalid.
    Blacklist checks run on the RAW requested keys first, so a dangerous key
    can never slip through just because it's missing from the allow-list."""
    if not requested:
        return []
    raw = [str(k).strip().lower() for k in requested if str(k).strip()]
    if not raw:
        return []

    raw_set = set(raw)
    if raw_set & _BLACKLIST_SINGLE:
        return []
    for combo in _BLACKLIST_COMBOS:
        if combo.issubset(raw_set):
            return []

    allowed = _allowed_keys()
    keys = [k for k in raw if k in allowed]
    return keys[:4]  # cap combo size, no reasonable game needs more than that


# --------------------------------------------------------------------------
# PLUGIN declaration
# --------------------------------------------------------------------------

PLUGIN = {
    "name": "game_autoplay",
    "description": (
        "Takes over keyboard/mouse control of a game and plays it autonomously: "
        "repeatedly looks at the screen, decides the next move using the control "
        "scheme given, and sends that input, until it wins, loses, gets stuck, or "
        "is told to stop. Use when the user says things like 'take over this game "
        "and play it', 'play this for me', 'win this level for me'. Works best on "
        "simple, single-player, non-time-critical games — it will NOT reliably win "
        "fast-paced or complex games, and should not be used on online/competitive "
        "multiplayer games (most prohibit bots in their terms of service). "
        "Requires the user to specify (or have already specified) the game's "
        "control scheme. Use action 'stop' immediately if the user says to stop, "
        "cancel, or take back control."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "start | stop | status (default: start)",
            },
            "game_name": {
                "type": "STRING",
                "description": "Name of the game, and of its window (used to focus it). Required for 'start'.",
            },
            "window_title": {
                "type": "STRING",
                "description": "Exact window title to focus, if different from game_name. Optional.",
            },
            "controls": {
                "type": "STRING",
                "description": (
                    "The control scheme, e.g. 'left/right arrows to move, up to jump, "
                    "z to shoot'. Required for 'start' — JARVIS cannot guess a game's "
                    "controls, ask the user if they haven't given them."
                ),
            },
            "goal": {
                "type": "STRING",
                "description": "What counts as winning/progressing, e.g. 'reach the flag', 'clear all rows', 'survive as long as possible'. Optional but recommended.",
            },
            "max_duration": {
                "type": "INTEGER",
                "description": "Safety auto-stop after this many seconds (default: 300, max: 1800).",
            },
            "decision_interval": {
                "type": "NUMBER",
                "description": "Seconds between each look-decide-act cycle (default: 1.5, min: 0.8).",
            },
        },
        "required": ["action"],
    },
}


# --------------------------------------------------------------------------
# Autoplay loop
# --------------------------------------------------------------------------

class _GameAutoplayer:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._held_keys: set[str] = set()
        self._held_lock = threading.Lock()

        self.game_name = ""
        self.status = "idle"     # idle | playing | won | lost | stuck | timeout | stopped | error
        self.cycles = 0
        self.start_time: float | None = None
        self.last_note = ""
        self.error = ""

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, game_name, window_title, controls, goal, max_duration, decision_interval) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return f"Already playing {self.game_name}, sir. Say stop first if you want to switch games."

            if not _PYAUTOGUI:
                return "Can't take over the game — pyautogui isn't installed. Run: pip install pyautogui"
            if not (_MSS and _PIL):
                return "Can't take over the game — mss/pillow aren't installed. Run: pip install mss pillow"

            target_title = window_title or game_name
            focused, msg = _focus_window(target_title)
            if not focused:
                return f"I couldn't find/focus '{target_title}', sir — make sure the game window is open and visible. ({msg})"

            self._stop_event.clear()
            self.game_name = game_name
            self.status = "playing"
            self.cycles = 0
            self.start_time = time.time()
            self.last_note = ""
            self.error = ""

            self._thread = threading.Thread(
                target=self._play_loop,
                args=(target_title, game_name, controls, goal, max_duration, decision_interval),
                daemon=True,
                name="GameAutoplayThread",
            )
            self._thread.start()

        return (
            f"Taking over {game_name}, sir. Playing now — say 'stop' or slam the mouse "
            f"into a screen corner any time to take back control."
        )

    def stop(self) -> str:
        with self._lock:
            thread = self._thread
            game_name = self.game_name

        if thread is None or not thread.is_alive():
            self._release_held_keys()
            return "I'm not playing anything right now, sir."

        self._stop_event.set()
        thread.join(timeout=10)
        self._release_held_keys()

        with self._lock:
            self._thread = None
            if self.status == "playing":
                self.status = "stopped"
            final_status = self.status
            cycles = self.cycles
            note = self.last_note

        verdict = {
            "won": f"I won {game_name} for you, sir.",
            "lost": f"Lost that run of {game_name}, sir.",
            "stuck": f"I got stuck in {game_name} and couldn't make further progress, sir.",
            "timeout": f"Hit the time limit playing {game_name}, sir.",
            "stopped": f"Stopped playing {game_name}, sir — control is back to you.",
            "error": f"Had to stop playing {game_name} due to an error, sir.",
        }.get(final_status, f"Stopped playing {game_name}, sir.")

        extra = f" ({cycles} moves made.{' Last note: ' + note if note else ''})" if cycles else ""
        return verdict + extra

    def status_report(self) -> str:
        if not self.is_running():
            return "I'm not playing anything right now, sir."
        elapsed = round(time.time() - (self.start_time or time.time()), 1)
        return (
            f"Playing {self.game_name}, sir — {elapsed}s in, {self.cycles} moves made. "
            f"{('Last note: ' + self.last_note) if self.last_note else ''}"
        ).strip()

    def _hold_key(self, key: str):
        pyautogui.keyDown(key)
        with self._held_lock:
            self._held_keys.add(key)

    def _release_key(self, key: str):
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass
        with self._held_lock:
            self._held_keys.discard(key)

    def _release_held_keys(self):
        if not _PYAUTOGUI:
            return
        with self._held_lock:
            keys = list(self._held_keys)
            self._held_keys.clear()
        for k in keys:
            try:
                pyautogui.keyUp(k)
            except Exception:
                pass

    def _execute_action(self, action_type: str, keys: list[str], hold_ms: int,
                         click_x, click_y, screen_w: int, screen_h: int):
        try:
            if action_type == "key" and keys:
                clean = _sanitize_keys(keys[:1])
                if clean:
                    pyautogui.press(clean[0])

            elif action_type == "keys" and keys:
                clean = _sanitize_keys(keys)
                if clean:
                    hold = max(0, min(int(hold_ms or 150), MAX_HOLD_MS)) / 1000.0
                    for k in clean:
                        self._hold_key(k)
                    if hold:
                        self._stop_event.wait(timeout=hold)
                    for k in reversed(clean):
                        self._release_key(k)

            elif action_type == "click" and click_x is not None and click_y is not None:
                x = max(0, min(int(click_x), screen_w - 1))
                y = max(0, min(int(click_y), screen_h - 1))
                pyautogui.click(x, y)

            # "none" -> intentionally do nothing this cycle
        except (pyautogui.FailSafeException if _PYAUTOGUI else Exception):
            raise
        except Exception:
            pass  # never let a bad action crash the play loop

    def _play_loop(self, window_title, game_name, controls, goal, max_duration, decision_interval):
        history: list[str] = []
        stuck_streak = 0
        deadline = time.time() + min(max_duration, HARD_MAX_DURATION)

        try:
            model = _get_model(MODEL_VISION)

            while not self._stop_event.is_set() and time.time() < deadline:
                cycle_start = time.time()

                _focus_window(window_title)  # best-effort refocus each cycle

                try:
                    img = _capture_screen_image()
                except Exception as e:
                    self.error = str(e)
                    self.status = "error"
                    break
                screen_w, screen_h = img.size

                prompt = f"""You are JARVIS, autonomously playing a video game for the user via
screenshots and simulated keyboard/mouse input.

Game: {game_name}
Goal: {goal or "make as much progress / survive as long as possible"}
Control scheme: {controls}

Recent moves (most recent last): {history[-HISTORY_LIMIT:] if history else "(none yet)"}

Look at the attached screenshot (the whole screen, {screen_w}x{screen_h}px) and decide
the single next input to send. Reply with ONLY this JSON, no markdown, no explanation:

{{
  "status": "playing" | "won" | "lost" | "stuck",
  "action_type": "key" | "keys" | "click" | "none",
  "keys": ["<pyautogui key name(s) from the control scheme, e.g. 'left', 'space'>"],
  "hold_ms": 150,
  "click_x": null,
  "click_y": null,
  "note": "<max 12 words on what you're doing/seeing>"
}}

Rules:
- "status": "won" only if you can clearly see a win/victory/level-complete screen.
  "lost" only if you can clearly see a game-over/defeat screen. "stuck" if the screen
  hasn't meaningfully changed across your recent moves and nothing in the control
  scheme seems to help. Otherwise "playing".
- "keys" must only use key names implied by the control scheme above.
- Use "click" with click_x/click_y (screen pixel coordinates) only if the control
  scheme is mouse-based.
- Keep hold_ms short (under 500) unless a sustained move is clearly needed.
- If status is "won" or "lost", set action_type to "none".

JSON:"""

                try:
                    response = model.generate_content([prompt, img])
                    raw = _strip_fences(response.text)
                    decision = json.loads(raw)
                except Exception as e:
                    decision = {"status": "playing", "action_type": "none", "note": f"(decision error: {e})"}

                status = str(decision.get("status", "playing")).lower()
                action_type = str(decision.get("action_type", "none")).lower()
                keys = decision.get("keys") or []
                hold_ms = decision.get("hold_ms", 150)
                click_x, click_y = decision.get("click_x"), decision.get("click_y")
                note = str(decision.get("note", ""))[:120]

                self.cycles += 1
                self.last_note = note
                history.append(f"{action_type}:{keys or ''} - {note}".strip())

                if status == "won":
                    self.status = "won"
                    break
                if status == "lost":
                    self.status = "lost"
                    break
                if status == "stuck":
                    stuck_streak += 1
                    if stuck_streak >= STUCK_LIMIT:
                        self.status = "stuck"
                        break
                else:
                    stuck_streak = 0

                if self._stop_event.is_set():
                    break

                self._execute_action(action_type, keys, hold_ms, click_x, click_y, screen_w, screen_h)

                elapsed = time.time() - cycle_start
                remaining = decision_interval - elapsed
                if remaining > 0:
                    self._stop_event.wait(timeout=remaining)

            else:
                # loop condition failed naturally -> either stopped or timed out
                if not self._stop_event.is_set() and self.status == "playing":
                    self.status = "timeout"

        except Exception as e:
            self.status = "error"
            self.error = str(e)
        finally:
            self._release_held_keys()


_autoplayer = _GameAutoplayer()


# --------------------------------------------------------------------------
# Plugin entry point
# --------------------------------------------------------------------------

def run(parameters: dict, player=None, session_memory=None) -> str:
    p = parameters or {}
    action = (p.get("action") or "start").strip().lower()

    try:
        if action == "start":
            game_name = (p.get("game_name") or "").strip()
            controls = (p.get("controls") or "").strip()
            if not game_name:
                result = "Which game should I take over, sir?"
            elif not controls:
                result = f"What are the controls for {game_name}, sir? I need those before I can play."
            else:
                max_duration = p.get("max_duration")
                try:
                    max_duration = max(MIN_MAX_DURATION, min(int(max_duration or DEFAULT_MAX_DURATION), HARD_MAX_DURATION))
                except (TypeError, ValueError):
                    max_duration = DEFAULT_MAX_DURATION

                decision_interval = p.get("decision_interval")
                try:
                    decision_interval = max(MIN_DECISION_INTERVAL, min(float(decision_interval or DEFAULT_DECISION_INTERVAL), MAX_DECISION_INTERVAL))
                except (TypeError, ValueError):
                    decision_interval = DEFAULT_DECISION_INTERVAL

                result = _autoplayer.start(
                    game_name=game_name,
                    window_title=(p.get("window_title") or "").strip(),
                    controls=controls,
                    goal=(p.get("goal") or "").strip(),
                    max_duration=max_duration,
                    decision_interval=decision_interval,
                )
        elif action == "stop":
            result = _autoplayer.stop()
        elif action == "status":
            result = _autoplayer.status_report()
        else:
            result = f"Unknown action '{action}', sir. Use start, stop, or status."
    except Exception as e:
        result = f"Sir, game_autoplay ran into a problem: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
    return result
