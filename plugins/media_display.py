#media_display.py
"""
media_display — JARVIS plugin.

Puts images and video onto JARVIS's own display instead of a random OS window.

It talks to the interface that ui.py actually has:

    player.show_video(source, title, muted, audio_source)   plays in the HUD
    player.stop_video()                                     closes it
    player.set_video_muted(bool)                            sound off / on
    player.show_image(...) / player.hide_media()            OPTIONAL — only if
                                                            an image viewer
                                                            exists in the UI

No ui.py patch is required for video. ui.py plays a local file or a DIRECT
media URL (QMediaPlayer), and YouTube page links are not that, so this plugin
resolves the video with yt-dlp into the real stream URLs first. YouTube serves
picture and sound as two separate streams, which is exactly what the
`audio_source` argument of show_video() is for.

What it does
------------
  - "play a video of X"          -> finds X on YouTube, resolves the streams and
                                    plays it in the HUD (muted to begin with,
                                    because ui.py opens the sound only when
                                    asked — see `unmute`). Without yt-dlp it
                                    opens the video in your browser instead
                                    and says so.
  - "show me a picture of X"     -> looks X up (Wikipedia, then image search).
                                    Shown in the app if the UI has an image
                                    viewer, otherwise opened in the system's
                                    default image viewer.
  - "show me the earth"          -> real NASA satellite imagery (keyless
                                    Worldview Snapshots) in a few views.
  - "hide the display" / "stop"  -> closes the video (and any image panel).
  - "unmute" / "mute"            -> sound on / off for the playing video.

Requirements
------------
`requests` and `pillow` for images, `ddgs` for the image-search fallback,
`yt-dlp` (pip install yt-dlp) for in-app video. Qt's multimedia module must be
present for ui.py to play video at all.
"""

import io
import os
import re
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, quote

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


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_EARTH_WORDS = {"earth", "the earth", "planet earth", "globe", "the globe", "world", "the world"}

# NASA GIBS/Worldview Snapshots — public, keyless, documented at
# https://wvs.earthdata.nasa.gov/. One flat full-globe JPEG per request, no
# WMTS tiling math needed. VIIRS layers are date-stamped; Blue Marble is a
# fixed composite and ignores TIME.
_WVS_URL = "https://wvs.earthdata.nasa.gov/api/v1/snapshot"
_EARTH_LAYERS = [
    ("Daily true-colour (satellite)", "VIIRS_SNPP_CorrectedReflectance_TrueColor", True),
    ("Blue Marble (classic)", "BlueMarble_ShadedRelief_Bathymetry", False),
    ("Night lights", "VIIRS_Black_Marble", False),
]


# --------------------------------------------------------------------------
# PLUGIN declaration
# --------------------------------------------------------------------------

PLUGIN = {
    "name": "media_display",
    "description": (
        "Shows an image or plays a video on JARVIS's OWN on-screen display panel — "
        "use this whenever the user wants something put ON THE SCREEN/DISPLAY itself, "
        "e.g. 'show me a picture of X on the display', 'put the earth on screen', "
        "'show a satellite view of earth', 'play a video of X on the display'. For "
        "Earth specifically this shows real switchable satellite views with pan/zoom/"
        "rotate/turn controls. Do NOT use this for a plain 'search YouTube and open it' "
        "request with no mention of the display/screen — that is 'youtube_video'. Use "
        "action 'hide' when the user says to dismiss/clear/close/stop the display or "
        "the video, and 'unmute' / 'mute' for the sound of a video that is playing."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "show_image | show_video | hide | mute | unmute (default: show_image)",
            },
            "query": {
                "type": "STRING",
                "description": "What to show or play, e.g. 'the earth', 'a golden retriever', 'the eiffel tower', 'lofi hip hop beats'.",
            },
            "layer": {
                "type": "STRING",
                "description": (
                    "For an Earth image only: which view to start on — "
                    "'true color' (default) | 'blue marble' | 'night lights'."
                ),
            },
        },
        "required": [],
    },
    "behavior": "NON_BLOCKING",   # a few HTTP round-trips
    "scheduling": "WHEN_IDLE",
}


# --------------------------------------------------------------------------
# Image fetch helpers
# --------------------------------------------------------------------------

def _validate_image(data: bytes) -> bool:
    """Confirms `data` actually decodes as an image (catches HTML error pages
    served with a 200 status, which is a common silent-failure mode)."""
    if not data or len(data) < 512:
        return False
    if not _PIL_OK:
        return True  # can't validate without Pillow — trust it, Qt will reject junk anyway
    try:
        PIL.Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def _fetch_bytes(url: str, timeout: int = 15) -> bytes | None:
    if not _REQUESTS_OK:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.content
        return data if _validate_image(data) else None
    except Exception as e:
        print(f"[MediaDisplay] ⚠️ fetch failed for {url}: {e}")
        return None


def _wikipedia_image(query: str) -> bytes | None:
    if not _REQUESTS_OK:
        return None
    title = quote(query.strip().replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        info = r.json() or {}
        img_url = (info.get("originalimage") or {}).get("source") or (info.get("thumbnail") or {}).get("source")
        if not img_url:
            return None
        return _fetch_bytes(img_url)
    except Exception as e:
        print(f"[MediaDisplay] ⚠️ Wikipedia lookup failed: {e}")
        return None


def _get_ddgs():
    """Same lazy-import fallback actions/web_search.py uses — the package was
    renamed duckduckgo-search -> ddgs."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        pass
    from duckduckgo_search import DDGS
    return DDGS


def _ddgs_image(query: str) -> bytes | None:
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=5):
                data = _fetch_bytes(r.get("image", ""))
                if data:
                    return data
    except Exception as e:
        print(f"[MediaDisplay] ⚠️ Image search failed: {e}")
    return None


def _fetch_generic_image(query: str) -> bytes | None:
    return _wikipedia_image(query) or _ddgs_image(query)


def _fetch_earth_layers(preferred_label: str | None) -> tuple[dict, str, bool]:
    """Returns ({label: temp_file_path}, default_label, any_from_nasa)."""
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    layers: dict[str, str] = {}

    for label, layer_id, dated in _EARTH_LAYERS:
        params = (
            f"REQUEST=GetSnapshot&LAYERS={layer_id}&CRS=EPSG:4326"
            f"&BBOX=-90,-180,90,180&FORMAT=image/jpeg&WIDTH=2048&HEIGHT=1024&WRAP=DAY"
        )
        if dated:
            params += f"&TIME={yesterday}"
        data = _fetch_bytes(f"{_WVS_URL}?{params}", timeout=20)
        if data:
            f = tempfile.NamedTemporaryFile(prefix="jarvis_earth_", suffix=".jpg", delete=False)
            f.write(data)
            f.close()
            layers[label] = f.name

    if layers:
        default = preferred_label if preferred_label in layers else next(iter(layers))
        return layers, default, True

    # NASA unreachable — fall back to a plain Wikipedia photo so the request
    # never dead-ends, just without switchable satellite views.
    data = _wikipedia_image("Earth")
    if data:
        f = tempfile.NamedTemporaryFile(prefix="jarvis_earth_", suffix=".jpg", delete=False)
        f.write(data)
        f.close()
        return {"Earth (photo)": f.name}, "Earth (photo)", False

    return {}, "", False


_LAYER_ALIASES = {
    "true color": "Daily true-colour (satellite)", "true colour": "Daily true-colour (satellite)",
    "satellite": "Daily true-colour (satellite)", "default": "Daily true-colour (satellite)",
    "blue marble": "Blue Marble (classic)", "classic": "Blue Marble (classic)",
    "night lights": "Night lights", "night": "Night lights", "black marble": "Night lights",
}


# --------------------------------------------------------------------------
# YouTube -> playable streams
#
# ui.py hands its source straight to QMediaPlayer, which plays files and direct
# media URLs. A youtube.com/watch or /embed link is a web page and would just
# fail, so the page is resolved to the actual stream URLs here.
# --------------------------------------------------------------------------

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"


def _search_youtube(query: str) -> str | None:
    """Scrape fallback used only when yt-dlp's own search is unavailable."""
    if not _REQUESTS_OK:
        return None
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        seen = set()
        for vid in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text):
            if vid in seen:
                continue
            seen.add(vid)
            if f"/shorts/{vid}" in r.text:
                continue
            return vid
    except Exception as e:
        print(f"[MediaDisplay] ⚠️ YouTube search failed: {e}")
    return None


def _has(f: dict, key: str) -> bool:
    return (f.get(key) or "none") != "none"


def _pick_streams(formats: list[dict]) -> tuple[str, str]:
    """(video_url, audio_url) from yt-dlp's format list. audio_url is '' when
    the chosen video already carries its sound.

    Only plain HTTP(S) streams are considered — HLS/DASH manifests are not
    something QMediaPlayer can be handed as a bare URL. H.264 / AAC is
    preferred because it is what every Qt multimedia backend can decode; VP9
    and AV1 depend on codec packs the user may not have."""
    web = [f for f in formats
           if f.get("url") and str(f.get("protocol") or "").startswith("http")]

    def height(f): return f.get("height") or 0
    def avc(f): return str(f.get("vcodec") or "").startswith("avc1")

    combined = [f for f in web if _has(f, "vcodec") and _has(f, "acodec") and height(f) <= 720]
    if combined:
        best = max(combined, key=lambda f: (avc(f), height(f)))
        return best["url"], ""

    video = [f for f in web if _has(f, "vcodec") and not _has(f, "acodec") and height(f) <= 720]
    audio = [f for f in web if _has(f, "acodec") and not _has(f, "vcodec")]
    if not video or not audio:
        return "", ""
    v = max(video, key=lambda f: (avc(f), height(f), f.get("tbr") or 0))
    a = max(audio, key=lambda f: (str(f.get("ext")) == "m4a", f.get("abr") or 0))
    return v["url"], a["url"]


def _resolve_video(query: str) -> dict | None:
    """{title, channel, page_url, video_url, audio_url}, or None.

    None with 'page_url' set means the video was FOUND but not playable
    in-app; the caller then opens it in the browser."""
    try:
        import yt_dlp
    except ImportError:
        vid = _search_youtube(query)
        return {"page_url": f"https://www.youtube.com/watch?v={vid}",
                "title": query.title(), "channel": "", "video_url": "",
                "audio_url": "", "no_ytdlp": True} if vid else None

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and info.get("entries"):
                info = info["entries"][0]
            if not info:
                return None
            video_url, audio_url = _pick_streams(info.get("formats") or [])
            return {
                "page_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
                "title": info.get("title") or query.title(),
                "channel": info.get("uploader") or info.get("channel") or "",
                "video_url": video_url,
                "audio_url": audio_url,
            }
    except Exception as e:
        print(f"[MediaDisplay] ⚠️ yt-dlp failed: {e}")
        vid = _search_youtube(query)
        return {"page_url": f"https://www.youtube.com/watch?v={vid}",
                "title": query.title(), "channel": "", "video_url": "",
                "audio_url": ""} if vid else None


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def _has_video_hooks(player) -> bool:
    return bool(player) and callable(getattr(player, "show_video", None))


def _open_in_system_viewer(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)                       # noqa: S606 — user-initiated
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _save_temp_image(data: bytes) -> str:
    f = tempfile.NamedTemporaryFile(prefix="jarvis_img_", suffix=".jpg", delete=False)
    f.write(data)
    f.close()
    return f.name


def _action_show_image(query: str, layer: str, player) -> str:
    if not query:
        return "What should I show, sir?"

    in_app = callable(getattr(player, "show_image", None))

    is_earth = query.strip().lower() in _EARTH_WORDS
    if is_earth:
        preferred = _LAYER_ALIASES.get((layer or "").strip().lower())
        layers, default_label, from_nasa = _fetch_earth_layers(preferred)
        if not layers:
            return "I couldn't reach a live image of Earth right now, sir — try again in a moment."
        note = "" if from_nasa else " (NASA's imagery service wasn't reachable, so this is a static photo instead)"
        if in_app:
            player.show_image(
                image_path=layers[default_label], title=f"Earth — {default_label}",
                layers=layers, layer=default_label, tile_horizontally=from_nasa,
            )
            return f"Earth is on the display, sir{note}. Use the layer menu to switch views, and TURN to pan around it."
        _open_in_system_viewer(layers[default_label])
        return f"Earth ({default_label}) is open in your image viewer, sir{note}."

    data = _fetch_generic_image(query)
    if not data:
        return f"I couldn't find an image for '{query}', sir."
    if in_app:
        player.show_image(image_bytes=data, title=query.title())
        return f"'{query}' is on the display now, sir."
    _open_in_system_viewer(_save_temp_image(data))
    return f"'{query}' is open in your image viewer, sir — the display itself only plays video."


def _action_show_video(query: str, player) -> str:
    if not query:
        return "What video should I play, sir?"
    if not _has_video_hooks(player):
        return "The display can't play video right now, sir."

    found = _resolve_video(query)
    if not found:
        return f"I couldn't find a video for '{query}', sir."

    title, channel = found["title"], found["channel"]
    by = f" by {channel}" if channel else ""

    if not found["video_url"]:
        # Found, but not something the display can be handed. The browser
        # always works, so the request still ends with a video playing.
        webbrowser.open(found["page_url"])
        why = ("yt-dlp isn't installed (pip install yt-dlp)"
               if found.get("no_ytdlp") else "I couldn't get a playable stream for it")
        return f"{why}, so I opened '{title}'{by} in your browser instead, sir."

    # muted=True is ui.py's own default and a deliberate one: while a video
    # makes sound the microphone is closed, so it starts silent and the sound
    # is switched on on request.
    player.show_video(source=found["video_url"], title=title, muted=True,
                      audio_source=found["audio_url"])
    return (f"Playing '{title}'{by} on the display, sir. It starts muted — "
            f"say 'unmute' or press SOUND ON for the sound.")


def _action_hide(player) -> str:
    did = False
    if callable(getattr(player, "stop_video", None)):
        player.stop_video()
        did = True
    if callable(getattr(player, "hide_media", None)):
        player.hide_media()
        did = True
    return "Display cleared, sir." if did else "There's nothing on the display to clear, sir."


def _action_mute(player, muted: bool) -> str:
    setter = getattr(player, "set_video_muted", None)
    if not callable(setter):
        return "I can't change the sound from here, sir."
    playing = getattr(player, "video_is_playing", None)
    if callable(playing) and not playing():
        return "No video is playing, sir."
    setter(muted)
    return "Muted, sir." if muted else "Sound on, sir. I've closed the microphone while it plays."


# --------------------------------------------------------------------------
# Plugin entry point
# --------------------------------------------------------------------------

def run(parameters: dict, player=None, session_memory=None, **_ignored) -> str:
    params = parameters or {}
    action = (params.get("action") or "show_image").strip().lower()
    query = (params.get("query") or "").strip()

    if not player:
        return "The display isn't available right now, sir."

    try:
        if action in ("hide", "stop", "close", "clear"):
            result = _action_hide(player)
        elif action == "mute":
            result = _action_mute(player, True)
        elif action == "unmute":
            result = _action_mute(player, False)
        elif action in ("show_video", "play", "play_video"):
            result = _action_show_video(query, player)
        else:
            result = _action_show_image(query, params.get("layer", ""), player)
    except Exception as e:
        print(f"[MediaDisplay] ❌ {e}")
        result = f"Media display failed, sir: {e}"

    try:
        player.write_log(f"[MediaDisplay] {result}")
    except Exception:
        pass
    return result
