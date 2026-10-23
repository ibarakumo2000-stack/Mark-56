"""
precision_toolkit — JARVIS plugin.

IMPORTANT — read this before wiring it in:
Mark-LII already ships native core tools that cover most of what this
plugin was requested to do:

    - "web search"      -> the core `web_search` tool (already works, not
                            touched here — nothing to add).
    - "YouTube control"  -> the core `youtube_video` tool (play/summarize/
                            get_info/trending).
    - "Desktop control"  -> the core `computer_control` / `desktop_control`
                            tools (typing, clicking by x/y, hotkeys, etc.
                            are already exact — they never guess).
    - "Code helper"      -> the core `code_helper` / `dev_agent` tools
                            (write/edit/explain/run/build on a file you name).

This plugin does NOT re-implement any of that (giving it the same name as
a core tool gets it silently rejected at load — plugin_loader.py enforces
that). Instead it fills three specific, genuine gaps:

  1. `screen` feature — finds and clicks on-screen TEXT using local OCR
     (pytesseract), with NO call to Gemini or any other vision model.
     The existing `computer_control` tool's `screen_find`/`screen_click`
     actions ask Gemini to *guess* a pixel location from a description —
     that is exactly the guessing behaviour you said you don't want for
     precision work. This plugin's `locate`/`click` actions instead run
     real OCR over a real screenshot and only ever act on a location that
     was actually measured. If your target text is not found, or more than
     one match exists, it says so and gives you the coordinates of every
     candidate — it will never pick one for you.
     A `read`/`analyze` action dumps every piece of text currently
     recognized on screen (grouped by line, size-capped) so JARVIS can
     answer "what's on my screen" using only local OCR.
     (`move`/`type`/`press`/`hotkey` here are thin, exact pass-throughs to
     pyautogui — same idea as `computer_control`, included so the whole
     "find it, then act on it" flow lives in one call chain. Key names
     also accept common spoken phrasing — "space bar", "left arrow",
     "control" — normalized to the exact pyautogui key name, never
     guessed at.)

  2. `youtube` feature — the core youtube_video tool has no "open this
     channel" or "list search results without auto-playing" action, and no
     video-posting reminder. This adds `search` (lists results, doesn't
     play anything), `open_channel` (resolves a name/@handle to a real
     channel URL and opens it, optionally to a specific tab), and
     `remind_post` (schedules a reminder through the same reminder system
     JARVIS already uses — it does not reinvent scheduling).

  3. `code` feature — code_helper needs you to name a file. This adds
     `analyze_active_file`, which detects the file currently open in the
     focused VS Code window, runs a real local syntax check for Python
     (py_compile — an actual error line number, not a guess), and *then*
     asks Gemini to review it and continue it toward a goal you describe.
     It will refuse to guess which file you mean if more than one file
     with that name exists, and it will not silently overwrite a file that
     VS Code shows has unsaved edits.

Honesty about limits:
  - OCR only finds TEXT. It cannot locate an icon or image with no visible
    label — that is a real limitation of avoiding a vision model, not a bug.
  - `analyze_active_file`'s local, no-AI check is Python-only (py_compile).
    Other languages still get a real Gemini review, just without a local
    pre-check backing it up.
  - Window-focus / active-window detection shells out to OS-native tools
    (same approach the rest of this codebase already uses in
    computer_control.py's `_focus_window`) and can fail on unusual window
    managers — it will tell you plainly when it can't determine something,
    rather than assume.

Dependencies (add whichever you don't already have):
    pip install pyautogui pytesseract pillow mss requests
    # plus the Tesseract-OCR *binary* itself (pytesseract is only a wrapper):
    #   Windows : https://github.com/UB-Mannheim/tesseract/wiki
    #   macOS   : brew install tesseract
    #   Linux   : sudo apt install tesseract-ocr
`google-genai`, `requests`, `pyautogui`, `pillow`, and `mss` are already in
this project's requirements.txt. Only `pytesseract` + the Tesseract binary
are new.
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus

# --------------------------------------------------------------------------- #
# Optional dependencies — every one of these degrades to a clear error        #
# message instead of crashing the plugin (or the whole app) if missing.       #
# --------------------------------------------------------------------------- #
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    _PYAUTOGUI = True
except Exception:
    _PYAUTOGUI = False

try:
    import pytesseract
    _TESSERACT = True
except Exception:
    _TESSERACT = False

try:
    from PIL import Image
    _PIL = True
except Exception:
    _PIL = False

try:
    import mss
    _MSS = True
except Exception:
    _MSS = False

try:
    import requests
    _REQUESTS = True
except Exception:
    _REQUESTS = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
GEMINI_MODEL    = "gemini-flash-latest"

_OS = platform.system()
_IS_WIN   = _OS == "Windows"
_IS_MAC   = _OS == "Darwin"
_IS_LINUX = _OS == "Linux"

_CNW = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WIN else {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# =========================================================================== #
# Shared helpers                                                              #
# =========================================================================== #

def _get_api_key() -> str:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("gemini_api_key", "")
    except Exception:
        return ""


def _get_gemini(model: str = GEMINI_MODEL):
    from google import genai
    client = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return client.models.generate_content(model=model, contents=contents)

    return _W()


def _open_url(url: str) -> None:
    try:
        if _IS_MAC:
            subprocess.Popen(["open", url])
        elif _IS_LINUX:
            subprocess.Popen(["xdg-open", url])
        else:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    except Exception as e:
        print(f"[PrecisionToolkit] ⚠️ open_url failed: {e}")


# =========================================================================== #
# 1) screen — local OCR-based, zero-vision-model screen locating              #
# =========================================================================== #

def _grab_screenshot():
    """Full virtual screen -> PIL.Image, plus the (left, top) offset of monitor 0."""
    if not _MSS or not _PIL:
        return None, (0, 0)
    with mss.mss() as sct:
        mon = sct.monitors[0]  # the union of all monitors
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, (mon["left"], mon["top"])


def _ocr_matches(query: str) -> list[dict]:
    """
    Returns every on-screen text box whose text contains `query`
    (case-insensitive), each as:
        {"text": ..., "x": center_x, "y": center_y,
         "left": ..., "top": ..., "width": ..., "height": ..., "confidence": ...}
    Coordinates are absolute screen pixels. Empty list means "not found" —
    never invented.
    """
    img, (off_x, off_y) = _grab_screenshot()
    if img is None:
        return []

    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    query_l = query.strip().lower()
    matches = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text or query_l not in text.lower():
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 0:  # tesseract marks non-text regions with conf -1
            continue
        left, top = data["left"][i], data["top"][i]
        w, h = data["width"][i], data["height"][i]
        matches.append({
            "text": text,
            "x": off_x + left + w // 2,
            "y": off_y + top + h // 2,
            "left": off_x + left, "top": off_y + top,
            "width": w, "height": h,
            "confidence": round(conf, 1),
        })
    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches


def _resolve_one(query: str, match_index: int | None) -> tuple[dict | None, str | None]:
    """
    Returns (match, error_message). Never guesses:
    - 0 matches  -> (None, "not found" message)
    - >1 matches and no match_index -> (None, message listing every candidate)
    - match_index out of range -> (None, error)
    - otherwise -> (the exact match, None)
    """
    matches = _ocr_matches(query)
    if not matches:
        return None, f"I don't see '{query}' anywhere on screen, sir — nothing to act on."
    if len(matches) == 1 or match_index is not None:
        idx = match_index if match_index is not None else 0
        if idx < 0 or idx >= len(matches):
            return None, (
                f"There's no candidate #{idx} for '{query}', sir — only "
                f"{len(matches)} found (0 to {len(matches) - 1})."
            )
        return matches[idx], None
    listing = "\n".join(
        f"  [{i}] \"{m['text']}\" at ({m['x']}, {m['y']}) — confidence {m['confidence']}"
        for i, m in enumerate(matches)
    )
    return None, (
        f"I found {len(matches)} places matching '{query}', sir — I won't guess which one:\n"
        f"{listing}\nTell me the index (match_index) to act on."
    )


# Natural-language key phrases -> the exact pyautogui key name.
# This is *not* a guess about which key you mean — "space bar" and "space"
# are the same key; this just normalizes wording so it isn't rejected for
# phrasing reasons alone. Anything not listed here still needs to already
# be a literal name in pyautogui.KEYBOARD_KEYS.
_KEY_ALIASES = {
    "space bar": "space", "spacebar": "space",
    "enter key": "enter", "return key": "enter", "return": "enter",
    "escape key": "esc", "escape": "esc",
    "left arrow": "left", "right arrow": "right",
    "up arrow": "up", "down arrow": "down",
    "arrow left": "left", "arrow right": "right",
    "arrow up": "up", "arrow down": "down",
    "delete key": "delete", "del": "delete",
    "backspace key": "backspace",
    "tab key": "tab",
    "control": "ctrl", "control key": "ctrl", "ctrl key": "ctrl",
    "command": "command" if _IS_MAC else "win",
    "cmd": "command" if _IS_MAC else "win",
    "windows key": "win", "windows": "win", "win key": "win",
    "option": "alt" if not _IS_MAC else "option", "option key": "alt" if not _IS_MAC else "option",
    "alt key": "alt",
    "shift key": "shift",
    "page up": "pageup", "page down": "pagedown",
    "caps lock": "capslock",
}


def _sanitize_key(key: str) -> str | None:
    if not _PYAUTOGUI:
        return None
    key = (key or "").strip().lower()
    key = _KEY_ALIASES.get(key, key)
    return key if key in pyautogui.KEYBOARD_KEYS else None


_SCREEN_READ_ACTIONS = {"locate", "read", "analyze"}
_SCREEN_CONTROL_ACTIONS = {"click", "move", "type", "press", "hotkey"}


def _handle_screen(params: dict) -> str:
    action = (params.get("action") or "locate").strip().lower()

    # OCR deps are needed for anything that looks at the screen (read/locate/click).
    needs_ocr = action in _SCREEN_READ_ACTIONS or action == "click"
    if needs_ocr and not (_TESSERACT and _MSS and _PIL):
        missing = []
        if not _TESSERACT:
            missing.append("pytesseract (+ the Tesseract-OCR binary)")
        if not _MSS:
            missing.append("mss")
        if not _PIL:
            missing.append("pillow")
        return f"Can't read the screen — missing: {', '.join(missing)}."

    # pyautogui is only needed for actions that actually move the mouse or
    # send keystrokes — a pure screen-read/locate shouldn't be blocked by it.
    needs_control = action in _SCREEN_CONTROL_ACTIONS
    if needs_control and not _PYAUTOGUI:
        return "Can't do that — pyautogui isn't installed. Run: pip install pyautogui"
    text = params.get("text", "")
    match_index = params.get("match_index")
    if isinstance(match_index, str) and match_index.strip():
        try:
            match_index = int(match_index)
        except ValueError:
            match_index = None
    elif match_index == "":
        match_index = None

    if action == "locate":
        if not text:
            return "What text should I look for on screen, sir?"
        match, err = _resolve_one(text, match_index)
        if err:
            return err
        return (
            f"Found '{match['text']}' at ({match['x']}, {match['y']}), "
            f"sir — confidence {match['confidence']}."
        )

    if action in ("read", "analyze"):
        img, (off_x, off_y) = _grab_screenshot()
        if img is None:
            return "Couldn't capture the screen, sir."
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        lines: dict[tuple[int, int], list[str]] = {}
        n = len(data.get("text", []))
        for i in range(n):
            word = (data["text"][i] or "").strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            if conf < 0:
                continue
            key = (data["block_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
        if not lines:
            return "I don't see any readable text on screen right now, sir."
        text_dump = "\n".join(" ".join(words) for words in lines.values())
        # Cap what gets handed back so a busy screen doesn't flood the response —
        # this is a measured transcript of the screen, not a summary or a guess.
        if len(text_dump) > 4000:
            text_dump = text_dump[:4000] + "\n… (truncated — screen has more text than shown here)"
        return (
            f"Here's every piece of text I can read on screen right now, sir "
            f"(via local OCR, no vision model):\n\n{text_dump}"
        )

    if action == "click":
        if not text:
            return "What text should I click, sir?"
        match, err = _resolve_one(text, match_index)
        if err:
            return err
        try:
            pyautogui.click(match["x"], match["y"])
        except Exception as e:
            return f"Found it but couldn't click: {e}"
        return f"Clicked '{match['text']}' at ({match['x']}, {match['y']}), sir."

    if action == "move":
        # Exact pass-through if x/y given; otherwise resolve text first — never a guess either way.
        x, y = params.get("x"), params.get("y")
        if x is not None and y is not None:
            try:
                pyautogui.moveTo(int(x), int(y))
            except Exception as e:
                return f"Couldn't move the mouse: {e}"
            return f"Mouse moved to ({x}, {y}), sir."
        if text:
            match, err = _resolve_one(text, match_index)
            if err:
                return err
            pyautogui.moveTo(match["x"], match["y"])
            return f"Mouse moved to '{match['text']}' at ({match['x']}, {match['y']}), sir."
        return "Give me either x/y coordinates or text to find, sir."

    if action == "type":
        if not text:
            return "What should I type, sir?"
        try:
            pyautogui.typewrite(text, interval=0.02)
        except Exception as e:
            return f"Couldn't type that: {e}"
        return f"Typed: {text!r}"

    if action == "press":
        raw_keys = params.get("keys")
        if raw_keys is None:
            raw_keys = [text] if text else []
        elif isinstance(raw_keys, str):
            raw_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if not raw_keys:
            return "Which key should I press, sir?"
        pressed, bad = [], []
        for k in raw_keys:
            good = _sanitize_key(k)
            if good:
                pyautogui.press(good)
                pressed.append(good)
            else:
                bad.append(k)
        msg = f"Pressed: {', '.join(pressed)}." if pressed else "Nothing valid to press."
        if bad:
            msg += f" (Unrecognized key name(s), skipped: {', '.join(bad)})"
        return msg

    if action == "hotkey":
        raw_keys = params.get("keys", "")
        keys = [k.strip() for k in raw_keys.split(",")] if isinstance(raw_keys, str) else list(raw_keys or [])
        keys = [k for k in keys if k]
        good_keys = [k for k in keys if _sanitize_key(k)]
        if len(good_keys) != len(keys):
            bad = set(keys) - set(good_keys)
            return f"Unrecognized key name(s) in that combo: {', '.join(bad)}"
        if not good_keys:
            return "Give me at least one key for the combo, sir."
        pyautogui.hotkey(*good_keys)
        return f"Sent hotkey: {'+'.join(good_keys)}"

    return f"Unknown screen action '{action}', sir. Use read | locate | click | move | type | press | hotkey."


# =========================================================================== #
# 2) youtube — channel navigation, search listing, post reminder             #
# =========================================================================== #

def _yt_search_raw(query: str, filter_param: str | None, max_results: int) -> list[dict]:
    if not _REQUESTS:
        return []
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    if filter_param:
        url += f"&sp={filter_param}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        html = r.text
        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"longBylineText":\{"runs":\[\{"text":"([^"]+)"', html)
        results, seen = [], set()
        for i, vid in enumerate(video_ids):
            if vid in seen:
                continue
            seen.add(vid)
            title = titles[i] if i < len(titles) else "(untitled)"
            channel = channels[i] if i < len(channels) else "Unknown channel"
            results.append({
                "title": title, "channel": channel,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[PrecisionToolkit] ⚠️ YouTube search scrape failed: {e}")
        return []


def _yt_find_channel_url(name: str) -> str | None:
    if name.startswith("@"):
        return f"https://www.youtube.com/{name}"
    if not _REQUESTS:
        return None
    # sp=EgIQAg%3D%3D filters YouTube search results to channels only.
    url = f"https://www.youtube.com/results?search_query={quote_plus(name)}&sp=EgIQAg%3D%3D"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        html = r.text
        m = re.search(r'"canonicalBaseUrl":"(/[^"]+)"', html)
        if m:
            return f"https://www.youtube.com{m.group(1)}"
    except Exception as e:
        print(f"[PrecisionToolkit] ⚠️ YouTube channel lookup failed: {e}")
    return None


def _handle_youtube(params: dict, player=None) -> str:
    action = (params.get("action") or "search").strip().lower()

    if action == "search":
        query = params.get("query", "")
        if not query:
            return "What should I search for on YouTube, sir?"
        if not _REQUESTS:
            return "Can't search YouTube — the `requests` package isn't installed."
        max_results = int(params.get("max_results") or 5)
        results = _yt_search_raw(query, filter_param=None, max_results=max_results)
        _open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        if not results:
            return f"Opened the YouTube search for '{query}', sir, but I couldn't parse any results to list."
        lines = [f"{i+1}. {r['title']} — {r['channel']}" for i, r in enumerate(results)]
        if player:
            player.write_log("JARVIS: " + " | ".join(lines))
        return "Here's what I found on YouTube, sir:\n" + "\n".join(lines)

    if action == "open_channel":
        name = params.get("channel_name", "")
        if not name:
            return "Which channel should I open, sir?"
        url = _yt_find_channel_url(name)
        if not url:
            return f"I couldn't find a channel matching '{name}', sir — I won't guess a URL."
        tab = (params.get("tab") or "").strip().lower()
        if tab in ("videos", "playlists", "community", "about", "featured"):
            url = url.rstrip("/") + f"/{tab}"
        _open_url(url)
        return f"Opened {name}'s channel{' (' + tab + ' tab)' if tab else ''}, sir."

    if action == "remind_post":
        date_str = params.get("date", "")
        time_str = params.get("time", "")
        message = params.get("message") or "🎬 Time to post your YouTube video!"
        if not date_str or not time_str:
            return "I need a date (YYYY-MM-DD) and time (HH:MM) to schedule that reminder, sir."
        try:
            from actions.reminder import reminder as _core_reminder
        except Exception as e:
            return f"Couldn't reach the reminder system: {e}"
        return _core_reminder(
            parameters={"date": date_str, "time": time_str, "message": message},
            player=player,
        )

    return f"Unknown youtube action '{action}', sir. Use search | open_channel | remind_post."


# =========================================================================== #
# 3) code — detect the active VS Code file, lint it locally, continue it     #
# =========================================================================== #

def _active_window_title() -> str | None:
    try:
        if _IS_WIN:
            import ctypes
            h = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(h, buf, length + 1)
            return buf.value or None
        if _IS_MAC:
            script = (
                'tell application "System Events" to get name of first application process '
                'whose frontmost is true'
            )
            app = subprocess.check_output(["osascript", "-e", script], **_CNW).decode().strip()
            script2 = f'tell application "{app}" to get name of front window'
            try:
                win = subprocess.check_output(["osascript", "-e", script2], **_CNW).decode().strip()
                return win or app
            except Exception:
                return app
        if _IS_LINUX:
            try:
                out = subprocess.check_output(
                    ["xdotool", "getactivewindow", "getwindowname"], **_CNW
                ).decode().strip()
                return out or None
            except Exception:
                out = subprocess.check_output(
                    ["wmctrl", "-l"], **_CNW
                ).decode()
                return out.splitlines()[-1] if out else None
    except Exception as e:
        print(f"[PrecisionToolkit] ⚠️ active window lookup failed: {e}")
    return None


_VSCODE_TITLE_RE = re.compile(r"^(\u25cf\s*)?([^-]+?)\s*-.*Visual Studio Code")


def _extract_vscode_hint(title: str) -> tuple[str, bool] | None:
    """(filename, has_unsaved_changes) from a VS Code window title, or None if not VS Code."""
    if "Visual Studio Code" not in title:
        return None
    m = _VSCODE_TITLE_RE.match(title)
    if not m:
        return None
    unsaved = bool(m.group(1))
    filename = m.group(2).strip()
    return filename, unsaved


def _find_candidate_files(filename: str, search_root: str | None) -> list[Path]:
    roots = []
    if search_root:
        roots.append(Path(search_root).expanduser())
    else:
        roots += [Path.cwd(), Path.home() / "Desktop", Path.home() / "Documents", Path.home()]
    seen, found = set(), []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob(filename):
                if p.is_file() and p.resolve() not in seen:
                    seen.add(p.resolve())
                    found.append(p)
                if len(found) >= 10:
                    break
        except Exception:
            continue
        if found:
            break  # stop widening the search once one root produced matches
    return found


def _local_lint(path: Path) -> str:
    if path.suffix != ".py":
        return "(No local linter for this file type — relying on AI review only.)"
    import py_compile
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(path), cfile=str(Path(tmp) / "out.pyc"), doraise=True)
        return "Local check (py_compile): no syntax errors."
    except py_compile.PyCompileError as e:
        return f"Local check (py_compile) found a syntax error:\n{e.msg}"
    except Exception as e:
        return f"Local check couldn't run: {e}"


def _handle_code(params: dict, player=None) -> str:
    goal = params.get("goal", "")
    if not goal:
        return "What are you trying to accomplish with this code, sir?"

    explicit_path = params.get("file_path")
    if explicit_path:
        target = Path(explicit_path).expanduser()
        if not target.is_file():
            return f"I can't find {target}, sir."
    else:
        title = _active_window_title()
        if not title:
            return "I couldn't tell which window is focused, sir — pass file_path directly instead."
        hint = _extract_vscode_hint(title)
        if not hint:
            return f"The focused window doesn't look like VS Code, sir (focused: \"{title}\")."
        filename, unsaved = hint
        candidates = _find_candidate_files(filename, params.get("search_root"))
        if not candidates:
            return f"VS Code has '{filename}' open, sir, but I couldn't locate it on disk. Pass file_path directly."
        if len(candidates) > 1:
            listing = "\n".join(f"  - {p}" for p in candidates)
            return (
                f"Found {len(candidates)} files named '{filename}', sir — I won't guess which one:\n"
                f"{listing}\nPass file_path to pick one."
            )
        target = candidates[0]
        if unsaved and not params.get("force"):
            return (
                f"{target.name} has unsaved changes in the editor, sir — what I'd read from disk "
                f"wouldn't match what you're looking at. Save the file first, or pass force=true "
                f"to proceed anyway."
            )

    try:
        code = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"Couldn't read {target}: {e}"

    lint_report = _local_lint(target)

    api_key = _get_api_key()
    if not api_key:
        return f"{lint_report}\n\n(No Gemini API key configured, so I can't go further than the local check.)"

    prompt = (
        "You are reviewing and continuing a piece of code for a developer.\n\n"
        f"Local static-analysis result:\n{lint_report}\n\n"
        f"File: {target.name}\n"
        f"Current content:\n```\n{code}\n```\n\n"
        f"What the developer is trying to accomplish:\n{goal}\n\n"
        "1. List any bugs or errors you find, with line numbers where you can.\n"
        "2. Then continue/complete the code from where it leaves off so it does what the "
        "developer described. Return the FULL updated file content in one code block, "
        "followed by a short explanation of what you changed."
    )
    try:
        model = _get_gemini()
        response = model.generate_content(prompt)
        answer = (response.text or "").strip()
    except Exception as e:
        return f"{lint_report}\n\n(Gemini review failed: {e})"

    if params.get("save"):
        code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", answer, re.DOTALL)
        if code_match:
            try:
                backup = target.with_suffix(target.suffix + ".bak")
                backup.write_text(code, encoding="utf-8")
                target.write_text(code_match.group(1), encoding="utf-8")
                answer += f"\n\n(Saved to {target}; original backed up to {backup.name}.)"
            except Exception as e:
                answer += f"\n\n(Could not save automatically: {e})"
        else:
            answer += "\n\n(save=true was set, but I couldn't find a clean code block to write.)"

    if player:
        player.write_log(f"JARVIS: reviewed {target.name} — see chat for details.")
    return answer


# =========================================================================== #
# Plugin contract                                                             #
# =========================================================================== #

PLUGIN = {
    "name": "precision_toolkit",
    "description": (
        "Fills gaps the built-in tools don't cover: (1) read/find/click exact on-screen TEXT using "
        "real local OCR — NEVER a vision-model guess — for when the user wants their screen "
        "analyzed, or the mouse moved or a key pressed exactly as instructed; (2) YouTube "
        "search-results listing, opening a specific channel, and scheduling a reminder to post a "
        "video; (3) detecting the file currently open in the focused VS Code window, checking it "
        "for real syntax errors, and asking Gemini to continue it toward a stated goal. Do NOT use "
        "this for things the built-in web_search, youtube_video, computer_control, or code_helper "
        "tools already handle — only for: reading/analyzing what's on screen or locating/clicking "
        "text on it without guessing, YouTube channel navigation or search listings, a 'remind me "
        "to post a video' request, or reviewing the code currently open in VS Code without being "
        "told its file path."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "feature": {
                "type": "STRING",
                "description": "Which capability to use: screen | youtube | code",
            },
            "action": {
                "type": "STRING",
                "description": (
                    "screen: read (dump all on-screen text, i.e. 'analyze my screen') | "
                "locate | click | move | type | press | hotkey. "
                    "youtube: search | open_channel | remind_post. "
                    "(code has no action — it always analyzes+continues.)"
                ),
            },
            "text": {
                "type": "STRING",
                "description": "screen: text to find/click/move-to, or text to type",
            },
            "match_index": {
                "type": "INTEGER",
                "description": "screen: which candidate to act on when locate/click found more than one match",
            },
            "x": {"type": "INTEGER", "description": "screen(move): exact x coordinate"},
            "y": {"type": "INTEGER", "description": "screen(move): exact y coordinate"},
            "keys": {
                "type": "STRING",
                "description": "screen(press/hotkey): comma-separated key names, e.g. 'left' or 'ctrl,s'",
            },
            "query": {"type": "STRING", "description": "youtube(search): search query"},
            "max_results": {"type": "INTEGER", "description": "youtube(search): how many results to list (default 5)"},
            "channel_name": {"type": "STRING", "description": "youtube(open_channel): channel name or @handle"},
            "tab": {"type": "STRING", "description": "youtube(open_channel): videos | playlists | community | about"},
            "date": {"type": "STRING", "description": "youtube(remind_post): YYYY-MM-DD"},
            "time": {"type": "STRING", "description": "youtube(remind_post): HH:MM (24h)"},
            "message": {"type": "STRING", "description": "youtube(remind_post): reminder text (optional)"},
            "goal": {"type": "STRING", "description": "code: what the developer is trying to accomplish"},
            "file_path": {"type": "STRING", "description": "code: explicit file path (skips VS Code auto-detection)"},
            "search_root": {"type": "STRING", "description": "code: folder to search for the active file's name"},
            "force": {"type": "BOOLEAN", "description": "code: proceed even if VS Code shows unsaved changes"},
            "save": {"type": "BOOLEAN", "description": "code: write Gemini's continuation back to the file (backs up the original first)"},
        },
        "required": ["feature"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    feature = (params.get("feature") or "").strip().lower()
    try:
        if feature == "screen":
            result = _handle_screen(params)
        elif feature == "youtube":
            result = _handle_youtube(params, player=player)
        elif feature == "code":
            result = _handle_code(params, player=player)
        else:
            result = "Which feature, sir — screen, youtube, or code?"
    except Exception as e:
        result = f"Sir, precision_toolkit ran into a problem: {e}"

    if player:
        player.write_log(f"JARVIS: {result}")
    return result
