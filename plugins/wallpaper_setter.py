"""
wallpaper_setter.py — JARVIS plugin

"JARVIS, find a car doing a drift and set it as my wallpaper" -> searches the
web for images matching the description, scores candidates by resolution
(and how well their aspect ratio matches your actual screen, so it fills
cleanly instead of being awkwardly cropped), downloads and validates the
best one, saves a permanent high-quality copy, and sets it as the desktop
wallpaper — Windows, macOS, or Linux (GNOME/Cinnamon/XFCE/KDE, or a
feh/nitrogen fallback).

Requires (all already in requirements.txt): requests, pillow, ddgs.
pyautogui (already in requirements.txt) is used, if present, to read your
actual screen resolution for aspect-ratio scoring — it's optional; without
it, scoring just falls back to resolution alone.

Drop this file into /plugins/ — no other file needs to change.
"""

import io
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


PLUGIN = {
    "name": "wallpaper_setter",
    "description": (
        "Searches the web for an image matching a description and sets it as the "
        "desktop wallpaper/background. Use this when the user asks to 'set my "
        "wallpaper/background to X', 'find a picture of X and make it my desktop "
        "background', or similar — it picks the best available image by resolution "
        "(not just the first result) and actually applies it as the wallpaper, it "
        "doesn't just show or save the image. For putting an image on JARVIS's own "
        "display panel instead of the desktop background, use 'media_display' "
        "instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "What the wallpaper should be a picture of, e.g. 'a car performing a drift', 'northern lights over mountains'.",
            },
            "min_width": {
                "type": "INTEGER",
                "description": "Optional minimum acceptable image width in pixels (default: 1600, auto-relaxed if nothing meets it).",
            },
        },
        "required": ["query"],
    },
    "behavior": "NON_BLOCKING",   # image search + multiple download attempts
    "scheduling": "WHEN_IDLE",
}

_WALLPAPER_DIR = Path.home() / "Pictures" / "JarvisWallpapers"
_MAX_IMAGE_BYTES = 15 * 1024 * 1024   # 15 MB safety cap per candidate
_FETCH_TIMEOUT = 12
_SEARCH_RESULTS = 25
_DOWNLOAD_ATTEMPTS = 6                # how many ranked candidates to actually try
_PREFERRED_MIN_WIDTH = 1600           # "good graphic quality" bar, auto-relaxed if nothing qualifies
_FALLBACK_MIN_WIDTH = 1000
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# --------------------------------------------------------------------------
# Screen resolution (for aspect-ratio scoring only — never a hard blocker)
# --------------------------------------------------------------------------

def _screen_aspect() -> float:
    try:
        import pyautogui
        w, h = pyautogui.size()
        if w and h:
            return w / h
    except Exception:
        pass
    return 16 / 9  # sane default


# --------------------------------------------------------------------------
# Search + candidate scoring
# --------------------------------------------------------------------------

def _get_ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        pass
    from duckduckgo_search import DDGS
    return DDGS


def _search_candidates(query: str) -> list[dict]:
    """Returns raw image-search hits (url/width/height/title), best-effort."""
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            # Biasing the query itself toward wallpaper-shaped results is cheap
            # and noticeably improves what comes back, on top of the scoring below.
            hits = list(ddgs.images(f"{query} wallpaper high resolution", max_results=_SEARCH_RESULTS))
            if len(hits) < 5:
                hits += list(ddgs.images(query, max_results=_SEARCH_RESULTS))
        return hits
    except Exception as e:
        print(f"[Wallpaper] ⚠️ Image search failed: {e}")
        return []


def _score(width: int, height: int, screen_aspect: float) -> float:
    if not width or not height:
        return 1.0  # unknown dimensions — rank below anything we can measure, but don't discard

    # Area is capped once an image is comfortably "big enough" for a wallpaper
    # (roughly 4K), so an oversized image can't out-rank a properly-sized one
    # purely by being bigger — past that point, how well it actually FITS the
    # screen (aspect ratio) is what decides quality, not raw pixel count. A
    # 4000x6000 portrait photo has more pixels than a 3840x2160 desktop shot,
    # but it'll look badly cropped/zoomed as a wallpaper — it should lose.
    area_cap = 3840 * 2160
    area = min(width * height, area_cap)

    img_aspect = width / height
    mismatch = abs(img_aspect - screen_aspect) / screen_aspect
    aspect_penalty = max(0.15, 1 - mismatch)

    return area * aspect_penalty


def _rank_candidates(hits: list[dict], screen_aspect: float) -> list[dict]:
    seen_urls = set()
    ranked = []
    for h in hits:
        url = (h.get("image") or h.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        seen_urls.add(url)
        w, hgt = int(h.get("width") or 0), int(h.get("height") or 0)
        ranked.append({"url": url, "width": w, "height": hgt,
                        "score": _score(w, hgt, screen_aspect)})
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


# --------------------------------------------------------------------------
# Download / validate
# --------------------------------------------------------------------------

def _download_and_validate(url: str) -> "PIL.Image.Image | None":
    if not (_REQUESTS_OK and _PIL_OK):
        return None
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT, stream=True, headers=_HEADERS)
        resp.raise_for_status()
        if "svg" in resp.headers.get("Content-Type", "").lower():
            return None

        buf = io.BytesIO()
        size = 0
        for chunk in resp.iter_content(8192):
            size += len(chunk)
            if size > _MAX_IMAGE_BYTES:
                return None
            buf.write(chunk)
        buf.seek(0)

        img = PIL.Image.open(buf)
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _pick_best_image(query: str, min_width: int) -> tuple:
    """Returns (PIL.Image, url, width, height) for the best candidate that
    actually downloads and decodes, or (None, None, 0, 0) if nothing worked."""
    hits = _search_candidates(query)
    if not hits:
        return None, None, 0, 0

    ranked = _rank_candidates(hits, _screen_aspect())
    if not ranked:
        return None, None, 0, 0

    # Two passes: first only candidates meeting the quality bar, then — if none
    # of those pan out — everything else, so a strict bar never means "nothing"
    # when there was in fact a usable (just under-labelled) image available.
    strict = [c for c in ranked if c["width"] >= min_width]
    relaxed = [c for c in ranked if c["width"] < min_width]

    for pool in (strict, relaxed):
        for cand in pool[:_DOWNLOAD_ATTEMPTS]:
            img = _download_and_validate(cand["url"])
            if img is not None:
                w, h = img.size
                return img, cand["url"], w, h

    return None, None, 0, 0


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug[:60] or "wallpaper"


def _save_wallpaper_file(img: "PIL.Image.Image", query: str) -> Path:
    _WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = _WALLPAPER_DIR / f"{_slugify(query)}_{stamp}.jpg"
    img.save(dest, "JPEG", quality=95)  # high quality, not the aggressively compressed default
    return dest


# --------------------------------------------------------------------------
# OS-specific wallpaper application
# --------------------------------------------------------------------------

def _set_wallpaper_windows(path: Path) -> tuple:
    try:
        import ctypes
        SPI_SETDESKWALLPAPER = 20
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDCHANGE = 0x02
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, str(path), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        if ok:
            return True, ""
        return False, "Windows reported the wallpaper change failed."
    except Exception as e:
        return False, str(e)


def _set_wallpaper_mac(path: Path) -> tuple:
    script = f'tell application "System Events" to tell every desktop to set picture to "{path}"'
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return (r.returncode == 0), (r.stderr.strip() if r.returncode != 0 else "")
    except Exception as e:
        return False, str(e)


def _set_wallpaper_linux(path: Path) -> tuple:
    uri = f"file://{path}"

    if shutil.which("gsettings"):
        try:
            for key in ("picture-uri", "picture-uri-dark"):
                subprocess.run(["gsettings", "set", "org.gnome.desktop.background", key, uri],
                                capture_output=True, timeout=8)
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                                capture_output=True, text=True, timeout=8)
            if uri.split("://")[-1] in (r.stdout or ""):
                return True, ""
        except Exception:
            pass

    if shutil.which("xfconf-query"):
        try:
            list_r = subprocess.run(
                ["xfconf-query", "-c", "xfce4-desktop", "-l"],
                capture_output=True, text=True, timeout=8,
            )
            props = [ln for ln in (list_r.stdout or "").splitlines() if ln.endswith("last-image")]
            for prop in props:
                subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", str(path)],
                                capture_output=True, timeout=8)
            if props:
                return True, ""
        except Exception:
            pass

    for tool, args in (("feh", ["feh", "--bg-fill", str(path)]),
                        ("nitrogen", ["nitrogen", "--set-zoom-fill", str(path), "--save"])):
        if shutil.which(tool):
            try:
                r = subprocess.run(args, capture_output=True, timeout=8)
                if r.returncode == 0:
                    return True, ""
            except Exception:
                continue

    return False, ("Couldn't set the wallpaper on this desktop environment — none of "
                    "gsettings (GNOME/Cinnamon), xfconf-query (XFCE), feh, or nitrogen "
                    "are available. Install one, or tell me your desktop environment.")


def _apply_wallpaper(path: Path) -> tuple:
    system = platform.system()
    if system == "Windows":
        return _set_wallpaper_windows(path)
    if system == "Darwin":
        return _set_wallpaper_mac(path)
    if system == "Linux":
        return _set_wallpaper_linux(path)
    return False, f"Unsupported OS '{system}'."


# --------------------------------------------------------------------------
# Plugin entry point
# --------------------------------------------------------------------------

def run(parameters: dict, player=None) -> str:
    params = parameters or {}
    query = (params.get("query") or "").strip()
    if not query:
        return "What should the wallpaper be a picture of, sir?"

    if not (_REQUESTS_OK and _PIL_OK):
        return "Sir, I need the 'requests' and 'pillow' packages installed to fetch wallpapers."

    try:
        min_width = int(params.get("min_width") or _PREFERRED_MIN_WIDTH)
    except (TypeError, ValueError):
        min_width = _PREFERRED_MIN_WIDTH
    min_width = max(_FALLBACK_MIN_WIDTH, min_width)

    if player:
        try:
            player.write_log(f"[Wallpaper] Searching for: {query}")
        except Exception:
            pass

    img, url, w, h = _pick_best_image(query, min_width)
    if img is None:
        result = f"I couldn't find a usable image for '{query}', sir — try rephrasing it."
    else:
        save_path = _save_wallpaper_file(img, query)
        ok, err = _apply_wallpaper(save_path)
        if ok:
            quality_note = f"{w}×{h}" if w and h else "resolution unknown"
            below_bar = w and w < min_width
            note = " (nothing met the preferred quality bar, so this is the best available)" if below_bar else ""
            result = (f"Wallpaper set, sir — '{query}', {quality_note}{note}. "
                       f"Saved to {save_path}.")
        else:
            result = (f"I found and saved an image for '{query}' ({save_path}), sir, but "
                       f"couldn't apply it as the wallpaper: {err}")

    if player:
        try:
            player.write_log(f"[Wallpaper] {result}")
        except Exception:
            pass
    return result
