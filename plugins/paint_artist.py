"""
paint_artist.py — JARVIS plugin (Windows only, no AI — fully local)

"Jarvis, draw a rocket in Paint" / "open this photo in Paint" / "mix a deep
red and use it" / "add text saying HELLO in a bold font" / "save it as
rocket.png" — opens classic mspaint.exe and drives it with real mouse/
keyboard automation: selects tools, drags shapes, mixes custom RGB colors,
places text. Never saves or closes on its own — it stays open with
unsaved work until you explicitly say to save.

HONESTY NOTE, READ BEFORE RELYING ON THIS: coordinate-based UI automation
is inherently fragile — it depends on your exact Windows/Paint version,
screen resolution, and window state. The coordinates below are reasonable
defaults for a MAXIMIZED classic mspaint.exe ribbon at 1920x1080. Run the
'calibrate' action once on your real machine (it walks you through clicking
each tool so it can record your actual coordinates) rather than trusting
the defaults blind. This file's drawing MATH and logic are fully testable
and were tested; the on-screen click accuracy could not be verified in the
environment this was built in (no Windows display available there).

No AI/Gemini involved anywhere in this file — shapes are hand-authored
geometric recipes, not AI-planned strokes. "Replicating" an existing photo
means opening it directly in Paint for you to work with, not tracing it
stroke by stroke (that would need AI vision to plan strokes, which was
explicitly ruled out).

Drop this file into /plugins/ — no other file needs to change.
"""

import json
import time
import subprocess
from pathlib import Path

PLUGIN = {
    "name": "draw_in_paint",
    "description": (
        "Opens Microsoft Paint (Windows only) and draws with its real tools: "
        "a built-in shape ('rocket', 'house', 'star', 'sun', 'smiley') via "
        "actual mouse-drag drawing, mixes/applies a custom RGB color, adds "
        "text in a chosen font, opens an existing image file into Paint (for "
        "'replicating'/editing an existing picture — this loads the real "
        "file, it does not AI-trace it), or saves. NEVER saves or closes on "
        "its own outside the explicit 'save' action — leaves work open and "
        "unsaved until told to save. Fully local, no AI model involved. "
        "Run action='calibrate' once per machine before relying on drawing "
        "accuracy — coordinates are approximate until calibrated."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["draw_shape", "open_image", "mix_color", "add_text",
                          "save", "calibrate"],
                "description": "What to do.",
            },
            "shape_name": {
                "type": "STRING",
                "enum": ["rocket", "house", "star", "sun", "smiley"],
                "description": "Built-in shape to draw (for action=draw_shape).",
            },
            "color": {
                "type": "STRING",
                "description": "Hex color like '#3355FF', for draw_shape "
                                "(overrides the shape's default color) or "
                                "mix_color.",
            },
            "image_path": {
                "type": "STRING",
                "description": "Path to an existing image (for action=open_image).",
            },
            "text": {
                "type": "STRING",
                "description": "Text to add (for action=add_text).",
            },
            "font_size": {
                "type": "INTEGER",
                "description": "Approximate font size for add_text (default 24).",
            },
            "save_path": {
                "type": "STRING",
                "description": "Where to save (for action=save). If omitted, "
                                "does a plain Ctrl+S (saves in place if the "
                                "file already has a name).",
            },
        },
        "required": ["action"],
    },
}

BASE_DIR = Path(__file__).resolve().parent.parent
CALIBRATION_PATH = BASE_DIR / "config" / "paint_calibration.json"

# ── Default layout: classic mspaint.exe ribbon, MAXIMIZED window, 1920x1080.
# Run action='calibrate' to overwrite these with your real coordinates.
DEFAULT_LAYOUT = {
    "canvas_box": [280, 160, 1900, 980],   # [x0, y0, x1, y1] drawable canvas area
    "tools": {
        "pencil":       [30, 130],
        "line":         [95, 150],
        "rectangle":    [95, 175],
        "ellipse":      [95, 200],
        "fill":         [30, 175],
        "text":         [95, 225],
        "edit_colors":  [330, 130],
        "color1_swatch":[430, 120],   # primary (left-click) color swatch
    },
}

_SHAPE_DEFAULT_COLOR = {
    "rocket": "#C0C0C0", "house": "#A0522D", "star": "#FFD700",
    "sun": "#FFA500", "smiley": "#FFD700",
}

# Hand-authored geometric recipes, normalized to a 0..1 unit square
# (x: left→right, y: top→bottom — matches screen coordinate convention).
# Each step: ("line", x1,y1,x2,y2) | ("rect", x1,y1,x2,y2) | ("ellipse", x1,y1,x2,y2)
_SHAPE_RECIPES = {
    "rocket": [
        ("line", 0.50, 0.05, 0.40, 0.30), ("line", 0.40, 0.30, 0.60, 0.30),
        ("line", 0.60, 0.30, 0.50, 0.05),                              # nose cone
        ("rect", 0.40, 0.30, 0.60, 0.70),                              # body
        ("ellipse", 0.46, 0.40, 0.54, 0.48),                           # window
        ("line", 0.40, 0.55, 0.28, 0.75), ("line", 0.28, 0.75, 0.40, 0.70),  # left fin
        ("line", 0.60, 0.55, 0.72, 0.75), ("line", 0.72, 0.75, 0.60, 0.70),  # right fin
        ("line", 0.44, 0.70, 0.50, 0.90), ("line", 0.50, 0.90, 0.56, 0.70),  # flame
    ],
    "house": [
        ("rect", 0.30, 0.45, 0.70, 0.85),                              # base
        ("line", 0.25, 0.45, 0.50, 0.20), ("line", 0.50, 0.20, 0.75, 0.45),  # roof
        ("line", 0.25, 0.45, 0.75, 0.45),
        ("rect", 0.46, 0.65, 0.54, 0.85),                              # door
        ("rect", 0.36, 0.52, 0.44, 0.60),                              # window L
        ("rect", 0.56, 0.52, 0.64, 0.60),                              # window R
    ],
    "star": [
        ("line", 0.50, 0.10, 0.61, 0.40), ("line", 0.61, 0.40, 0.93, 0.42),
        ("line", 0.93, 0.42, 0.67, 0.60), ("line", 0.67, 0.60, 0.78, 0.90),
        ("line", 0.78, 0.90, 0.50, 0.70), ("line", 0.50, 0.70, 0.22, 0.90),
        ("line", 0.22, 0.90, 0.33, 0.60), ("line", 0.33, 0.60, 0.07, 0.42),
        ("line", 0.07, 0.42, 0.39, 0.40), ("line", 0.39, 0.40, 0.50, 0.10),
    ],
    "sun": [
        ("ellipse", 0.35, 0.35, 0.65, 0.65),                           # core
        ("line", 0.50, 0.05, 0.50, 0.20), ("line", 0.50, 0.80, 0.50, 0.95),
        ("line", 0.05, 0.50, 0.20, 0.50), ("line", 0.80, 0.50, 0.95, 0.50),
        ("line", 0.18, 0.18, 0.29, 0.29), ("line", 0.71, 0.71, 0.82, 0.82),
        ("line", 0.82, 0.18, 0.71, 0.29), ("line", 0.29, 0.71, 0.18, 0.82),
    ],
    "smiley": [
        ("ellipse", 0.20, 0.20, 0.80, 0.80),                           # face
        ("ellipse", 0.36, 0.38, 0.42, 0.46), ("ellipse", 0.58, 0.38, 0.64, 0.46),  # eyes
        ("line", 0.35, 0.62, 0.42, 0.68), ("line", 0.42, 0.68, 0.58, 0.68),
        ("line", 0.58, 0.68, 0.65, 0.62),                              # smile
    ],
}


# ─────────────────────────── setup / calibration ─────────────────────────

def _require_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        return pyautogui
    except ImportError:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _load_layout() -> dict:
    if CALIBRATION_PATH.is_file():
        try:
            return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_LAYOUT


def _save_layout(layout: dict):
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(layout, indent=2), encoding="utf-8")


def _ensure_paint_open():
    import platform
    if platform.system() != "Windows":
        raise RuntimeError("Paint automation only works on Windows.")

    import pygetwindow as gw
    for w in gw.getAllWindows():
        if "paint" in w.title.lower() and w.visible:
            try:
                w.activate()
                w.maximize()
            except Exception:
                pass
            time.sleep(0.5)
            return

    subprocess.Popen(["mspaint.exe"])
    time.sleep(1.5)
    for w in gw.getAllWindows():
        if "paint" in w.title.lower() and w.visible:
            try:
                w.maximize()
            except Exception:
                pass
            break
    time.sleep(0.5)


def _calibrate() -> str:
    pg = _require_pyautogui()
    _ensure_paint_open()

    steps = [
        ("canvas top-left corner", "canvas_tl"),
        ("canvas bottom-right corner", "canvas_br"),
        ("the Pencil tool", "pencil"),
        ("the Line tool", "line"),
        ("the Rectangle tool", "rectangle"),
        ("the Ellipse (Oval) tool", "ellipse"),
        ("the Fill (paint bucket) tool", "fill"),
        ("the Text (A) tool", "text"),
        ("the 'Edit colors' button", "edit_colors"),
        ("the primary color swatch (top-left of the color box)", "color1_swatch"),
    ]
    layout = {"canvas_box": [0, 0, 0, 0], "tools": {}}
    for label, key in steps:
        print(f"[Paint calibration] Hover your mouse over {label} — capturing in 4 seconds...")
        time.sleep(4)
        x, y = pg.position()
        if key == "canvas_tl":
            layout["canvas_box"][0], layout["canvas_box"][1] = x, y
        elif key == "canvas_br":
            layout["canvas_box"][2], layout["canvas_box"][3] = x, y
        else:
            layout["tools"][key] = [x, y]

    _save_layout(layout)
    return f"Calibration saved to {CALIBRATION_PATH}. Future drawing actions will use these coordinates."


# ─────────────────────────── drawing primitives ──────────────────────────

def _scale(layout: dict, nx: float, ny: float):
    x0, y0, x1, y1 = layout["canvas_box"]
    return x0 + nx * (x1 - x0), y0 + ny * (y1 - y0)


def _select_tool(pg, layout: dict, tool: str):
    coords = layout["tools"].get(tool)
    if not coords:
        raise RuntimeError(f"No calibrated/default coordinate for tool '{tool}'.")
    pg.click(coords[0], coords[1])
    time.sleep(0.15)


def _hex_to_rgb(hex_color: str):
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"'{hex_color}' isn't a valid hex color (expected like '#3355FF').")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _apply_color(pg, layout: dict, rgb: tuple):
    """Opens Edit Colors, types the RGB values, applies as the active color.
    UI FLOW NOTE: classic mspaint's custom-color dialog layout has shifted
    across Windows versions — this assumes numeric R/G/B fields reachable
    via Tab from the dialog's default focus. Tune via calibration/manual
    testing on the real target machine if the dialog doesn't match."""
    _select_tool(pg, layout, "edit_colors")
    time.sleep(0.4)
    pg.press("tab")
    pg.typewrite(str(rgb[0]), interval=0.02)
    pg.press("tab")
    pg.typewrite(str(rgb[1]), interval=0.02)
    pg.press("tab")
    pg.typewrite(str(rgb[2]), interval=0.02)
    pg.press("enter")
    time.sleep(0.3)


def _draw_shape_recipe(pg, layout: dict, shape_name: str, color_hex: str):
    recipe = _SHAPE_RECIPES.get(shape_name)
    if not recipe:
        raise ValueError(f"No built-in recipe for '{shape_name}'.")

    rgb = _hex_to_rgb(color_hex or _SHAPE_DEFAULT_COLOR.get(shape_name, "#000000"))
    _apply_color(pg, layout, rgb)

    for step in recipe:
        kind = step[0]
        nx1, ny1, nx2, ny2 = step[1:]
        x1, y1 = _scale(layout, nx1, ny1)
        x2, y2 = _scale(layout, nx2, ny2)

        if kind == "line":
            _select_tool(pg, layout, "line")
        elif kind == "rect":
            _select_tool(pg, layout, "rectangle")
        elif kind == "ellipse":
            _select_tool(pg, layout, "ellipse")
        else:
            continue

        pg.moveTo(x1, y1, duration=0.1)
        pg.dragTo(x2, y2, duration=0.25, button="left")
        time.sleep(0.05)


def _open_image_in_paint(image_path: str):
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"'{image_path}' does not exist.")
    subprocess.Popen(["mspaint.exe", str(path)])
    time.sleep(1.5)


def _add_text(pg, layout: dict, text: str, font_size: int):
    _select_tool(pg, layout, "text")
    x0, y0 = _scale(layout, 0.15, 0.15)
    x1, y1 = _scale(layout, 0.75, 0.30)
    pg.moveTo(x0, y0, duration=0.1)
    pg.dragTo(x1, y1, duration=0.3, button="left")
    time.sleep(0.3)
    pg.typewrite(text, interval=0.03)
    # font-size adjustment via the ribbon font-size box is highly
    # version-dependent; left as a documented gap rather than a guess.
    pg.click(50, 50)  # click off the text box to commit it (approx, calibrate if needed)


def _save(pg, save_path: str):
    if save_path:
        pg.hotkey("ctrl", "shift", "s")
        time.sleep(0.5)
        pg.typewrite(str(Path(save_path).expanduser()), interval=0.02)
        pg.press("enter")
    else:
        pg.hotkey("ctrl", "s")
    time.sleep(0.5)


# ─────────────────────────── main entry point ────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    shape_name = (parameters.get("shape_name") or "").strip().lower()
    color = (parameters.get("color") or "").strip()
    image_path = (parameters.get("image_path") or "").strip()
    text = (parameters.get("text") or "").strip()
    font_size = int(parameters.get("font_size") or 24)
    save_path = (parameters.get("save_path") or "").strip()

    if action not in ("draw_shape", "open_image", "mix_color", "add_text", "save", "calibrate"):
        return "Sir, tell me draw_shape, open_image, mix_color, add_text, save, or calibrate."

    try:
        if action == "calibrate":
            result_text = _calibrate()
            return result_text  # no player.write_log needed mid-calibration prints

        pg = _require_pyautogui()
        layout = _load_layout()

        if action == "draw_shape":
            if shape_name not in _SHAPE_RECIPES:
                return f"Sir, I don't have a recipe for '{shape_name}' — I can draw: {', '.join(_SHAPE_RECIPES)}."
            _ensure_paint_open()
            _draw_shape_recipe(pg, layout, shape_name, color)
            result_text = f"Drew a {shape_name} in Paint — leaving it open and unsaved until you tell me to save."

        elif action == "open_image":
            if not image_path:
                return "Sir, I need the path to the image."
            _open_image_in_paint(image_path)
            result_text = f"Opened {image_path} in Paint for you to work with."

        elif action == "mix_color":
            if not color:
                return "Sir, give me a hex color to mix, e.g. '#3355FF'."
            _ensure_paint_open()
            rgb = _hex_to_rgb(color)
            _apply_color(pg, layout, rgb)
            result_text = f"Mixed and applied {color} as the active color."

        elif action == "add_text":
            if not text:
                return "Sir, what should the text say?"
            _ensure_paint_open()
            _add_text(pg, layout, text, font_size)
            result_text = f"Added the text — leaving it open and unsaved until you tell me to save."

        elif action == "save":
            _ensure_paint_open()
            _save(pg, save_path)
            result_text = f"Saved{' to ' + save_path if save_path else ''}."

    except Exception as e:
        return f"Sir, draw_in_paint failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
