"""
canva_designer.py — JARVIS plugin (no AI — fully local)

"Jarvis, create a modern and elegant business card in Canva" — launches
your installed Canva DESKTOP app (not a browser tab — tries the real local
app first: PATH lookup, common install folders, then asking Windows itself
via Get-StartApps for a Store-installed Canva app; falls back to opening
canva.com in your browser only if no desktop install can be found), and
hands you a concrete design brief (color palette, font pairing, layout
guidance, and a few real inspiration links from the web) picked from a
hand-built library of elegant/modern design themes — no AI model involved.

HONESTY NOTE, READ BEFORE RELYING ON THIS: this does NOT click around
inside Canva's editor (desktop or web) to build the design for you, and
that's still true now that it targets the desktop app specifically. The
desktop app is effectively the same constantly-changing, largely
canvas-rendered interface as the web version, just wrapped natively — if
anything it's LESS scriptable than the browser (no DOM-level tooling
available at all, only blind pixel coordinates). A plugin that pretended
to auto-replicate a design inside it would silently break on Canva's next
update and give a false sense that a design exists when it doesn't. What
this DOES reliably: launches the real app, and gives you a real, usable
design brief to apply yourself in a couple of minutes. For genuine
hands-off automated creation, Canva's own Connect API is the real path —
a separate developer registration + OAuth setup, not something a drop-in
plugin can do blind.

Drop this file into /plugins/ — no other file needs to change.
"""

import re
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime

PLUGIN = {
    "name": "design_in_canva",
    "description": (
        "Launches the installed Canva DESKTOP app (not a browser tab — tries "
        "the real local app first, falls back to canva.com only if no "
        "desktop install is found), finds ONE real reference image matching "
        "the request and extracts its actual dominant colors and layout "
        "structure via computer vision (k-means color clustering + region "
        "detection — deterministic, no AI model), and produces a design "
        "brief grounded in that real reference (its actual palette, plus a "
        "curated font pairing and layout guidance) — falling back to a "
        "built-in elegant/modern theme only if no usable reference image is "
        "found. Does NOT automatically build the design inside Canva's "
        "editor — not reliably scriptable, desktop or web — it launches the "
        "real app, saves the reference image next to the brief, and gives "
        "you what you need to recreate that look yourself. Use for 'create "
        "a business card/poster/flyer/logo in Canva', 'design something "
        "modern and elegant for X in Canva'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "design_type": {
                "type": "STRING",
                "enum": ["business_card", "poster", "flyer", "logo",
                          "presentation", "resume", "social_post", "invitation"],
                "description": "What kind of design to create.",
            },
            "description": {
                "type": "STRING",
                "description": "What it's for / any details, e.g. 'for a "
                                "coffee brand, warm and cozy' or 'tech "
                                "startup, futuristic'.",
            },
            "theme": {
                "type": "STRING",
                "enum": ["midnight_luxury", "minimal_mono", "warm_editorial",
                          "tech_futuristic", "soft_botanical"],
                "description": "Optional. Force a specific built-in theme "
                                "instead of auto-picking one from the "
                                "description.",
            },
        },
        "required": ["design_type"],
    },
}

REPORTS_DIR = Path.home() / "Desktop" / "JarvisDesigns"

_CANVA_CREATE_URLS = {
    "business_card": "https://www.canva.com/create/business-cards/",
    "poster": "https://www.canva.com/create/posters/",
    "flyer": "https://www.canva.com/create/flyers/",
    "logo": "https://www.canva.com/create/logos/",
    "presentation": "https://www.canva.com/create/presentations/",
    "resume": "https://www.canva.com/create/resumes/",
    "social_post": "https://www.canva.com/create/instagram-posts/",
    "invitation": "https://www.canva.com/create/invitations/",
}

# Hand-built palette + font library — no AI. Colors as hex, fonts as names
# Canva has natively (safe to type straight into Canva's font search box).
_THEMES = {
    "midnight_luxury": {
        "label": "Midnight Luxury",
        "palette": ["#0B0F19 (deep navy/near-black)", "#D4AF37 (gold)", "#F5F0E6 (cream)"],
        "fonts": {"heading": "Playfair Display", "body": "Lato"},
        "keywords": ["luxury", "elegant", "premium", "upscale", "gold", "classic"],
    },
    "minimal_mono": {
        "label": "Minimal Mono",
        "palette": ["#111111 (near-black)", "#FFFFFF (white)", "#9AA7B8 (cool grey)"],
        "fonts": {"heading": "Montserrat", "body": "Inter"},
        "keywords": ["minimal", "clean", "simple", "monochrome", "black and white"],
    },
    "warm_editorial": {
        "label": "Warm Editorial",
        "palette": ["#B5502F (terracotta)", "#F3E9DC (cream)", "#3A322C (charcoal)"],
        "fonts": {"heading": "Cormorant Garamond", "body": "Karla"},
        "keywords": ["warm", "cozy", "organic", "editorial", "earthy", "coffee", "artisan"],
    },
    "tech_futuristic": {
        "label": "Tech Futuristic",
        "palette": ["#0B0F19 (deep charcoal)", "#00E5FF (electric cyan)", "#FFFFFF (white)"],
        "fonts": {"heading": "Space Grotesk", "body": "Poppins"},
        "keywords": ["futuristic", "tech", "startup", "digital", "modern", "sleek", "innovation"],
    },
    "soft_botanical": {
        "label": "Soft Botanical",
        "palette": ["#5B6E58 (sage)", "#F4F1EA (off-white)", "#7A5C46 (walnut brown)"],
        "fonts": {"heading": "Libre Baskerville", "body": "Nunito"},
        "keywords": ["botanical", "natural", "wellness", "organic", "plant", "spa", "calm"],
    },
}

_LAYOUT_TIPS = {
    "business_card": [
        "Keep it to 3–4 elements max: logo/name, title, contact info, tagline.",
        "Leave generous margins — don't let text touch the edges.",
        "Pick one alignment (all-left or all-centered) and stay consistent.",
    ],
    "poster": [
        "One clear focal point — a headline or hero image, not several competing for attention.",
        "Establish a size hierarchy: headline, then subhead, then body — 3 sizes max.",
        "Leave breathing room; a poster that's too full reads as noise from a distance.",
    ],
    "flyer": [
        "Lead with the single most important fact (what/when/where) in the largest text.",
        "Use no more than 2 fonts total — one for headings, one for body.",
        "Keep contact info/CTA visually separated at the bottom.",
    ],
    "logo": [
        "Design it to work in a single color first — if it holds up in black, the color version will too.",
        "Avoid more than 2 typefaces; many strong logos use just one.",
        "Test it small — a logo that only works huge won't work on a favicon.",
    ],
    "presentation": [
        "One idea per slide — resist cramming multiple points onto one.",
        "Keep a consistent margin/grid across every slide.",
        "Use your accent color sparingly, for emphasis only — not on every slide element.",
    ],
    "resume": [
        "Prioritize scannability — clear section headings, consistent spacing.",
        "Stick to 1–2 fonts and let hierarchy come from size/weight, not extra typefaces.",
        "Leave real white space; a dense resume is harder to skim, not more impressive.",
    ],
    "social_post": [
        "Design for a small screen first — text should read clearly as a thumbnail.",
        "Keep critical text away from the edges (platforms crop/overlay UI there).",
        "One strong focal image beats several small competing ones.",
    ],
    "invitation": [
        "Hierarchy: event name first, then date/time, then location, then RSVP details.",
        "Leave generous white space — invitations read as more elegant when less crowded.",
        "Match the font pairing's formality to the event's tone.",
    ],
}


def _find_canva_desktop_windows():
    """Best-effort local-app detection on Windows. Tries, in order: a
    directly-invocable executable on PATH, common install directories, then
    asking Windows itself (via Get-StartApps) for an installed Store/PWA app
    named Canva and its AppID so it can be launched properly. Returns a
    ready-to-run subprocess arg list, or None if nothing was found."""
    which = shutil.which("Canva")
    if which:
        return [which]

    candidates = [
        Path.home() / "AppData/Local/Canva/Canva.exe",
        Path("C:/Program Files/Canva/Canva.exe"),
        Path("C:/Program Files (x86)/Canva/Canva.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return [str(c)]

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Where-Object {$_.Name -like '*Canva*'} | "
             "Select-Object -First 1 -ExpandProperty AppID"],
            capture_output=True, text=True, timeout=10,
        )
        app_id = result.stdout.strip()
        if app_id:
            return ["explorer.exe", f"shell:AppsFolder\\{app_id}"]
    except Exception:
        pass
    return None


def _open_canva_app(fallback_url: str) -> str:
    """Tries the installed desktop app first; falls back to the browser
    create-page if no desktop install can be found. Returns a short note
    on which path was actually taken, for an honest result message."""
    system = platform.system()

    try:
        if system == "Windows":
            cmd = _find_canva_desktop_windows()
            if cmd:
                subprocess.Popen(cmd)
                return "opened the Canva desktop app"
        elif system == "Darwin":
            if Path("/Applications/Canva.app").exists():
                subprocess.Popen(["open", "-a", "Canva"])
                return "opened the Canva desktop app"
    except Exception:
        pass  # fall through to browser fallback below

    try:
        webbrowser.open(fallback_url)
    except Exception:
        pass
    return ("couldn't find a Canva desktop app installed, so I opened "
            "canva.com in your browser instead")


def _fetch_reference_image_url(query: str):
    """Finds one usable reference image URL for the design query. None on failure."""
    try:
        DDGS = _get_ddgs()
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=8):
                url = r.get("image") or r.get("url") or ""
                if url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
                    return url, r.get("title", "")
    except Exception:
        pass
    return None, ""


def _download_reference_image(url: str, dest_dir: Path):
    """Downloads + validates + normalizes a reference image. None on failure."""
    try:
        import requests
        from PIL import Image
        import io

        resp = requests.get(url, timeout=10, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        if "svg" in resp.headers.get("Content-Type", ""):
            return None

        buf, size = io.BytesIO(), 0
        for chunk in resp.iter_content(8192):
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                return None
            buf.write(chunk)
        buf.seek(0)

        img = Image.open(buf)
        img.load()
        img = img.convert("RGB")

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"reference_{abs(hash(url)) % 10**8}.jpg"
        img.save(dest, "JPEG", quality=90)
        return dest
    except Exception:
        return None


def _extract_palette(image_path: Path, k: int = 4):
    """Real dominant-color extraction via k-means clustering — deterministic
    computer vision, no AI model. Returns a list of '#RRGGBB' hex strings,
    largest cluster first."""
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path))
    if img is None:
        return []
    img = cv2.resize(img, (150, 150))
    pixels = img.reshape(-1, 3).astype(np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 6, cv2.KMEANS_RANDOM_CENTERS)

    counts = np.bincount(labels.flatten())
    order = np.argsort(-counts)
    hexes = []
    for i in order:
        b, g, r = centers[i].astype(int)
        hexes.append(f"#{r:02X}{g:02X}{b:02X}")
    return hexes


def _describe_layout(image_path: Path) -> str:
    """Reuses the same structural (non-AI) region-detection approach as the
    wireframe builder — describes rough band structure, not exact content."""
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path))
    if img is None:
        return ""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    dilated = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] * b[3] > (w * h) * 0.02]
    if not boxes:
        return "Mostly open/uncluttered composition — no strong distinct regions detected."

    boxes.sort(key=lambda b: b[1])
    band_count = 1
    last_y = boxes[0][1]
    for b in boxes[1:]:
        if b[1] - last_y > h * 0.08:
            band_count += 1
            last_y = b[1]

    density = len(boxes) / max(band_count, 1)
    if density <= 1.5:
        style = "a clean, minimal layout with a small number of distinct elements"
    elif density <= 3:
        style = "a moderately structured layout with a few clear content blocks"
    else:
        style = "a denser, multi-element layout with several distinct regions"

    return f"Roughly {band_count} horizontal band(s) detected, {style}."


def _get_ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        return DDGS


def _find_inspiration(design_type: str, description: str) -> list:
    query = f"{description} {design_type.replace('_', ' ')} design inspiration".strip()
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append({"title": r.get("title", ""), "url": r.get("href", "")})
    except Exception:
        pass
    return results


def _pick_theme(design_type: str, description: str, forced_theme: str) -> str:
    if forced_theme and forced_theme in _THEMES:
        return forced_theme
    text = (description or "").lower()
    best, best_score = "midnight_luxury", 0  # default matches an elegant/modern baseline
    for key, theme in _THEMES.items():
        score = sum(1 for kw in theme["keywords"] if kw in text)
        if score > best_score:
            best, best_score = key, score
    return best


def _slugify(text: str) -> str:
    keep = [c if c.isalnum() else "_" for c in text.strip().lower()]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:50] or "design"


def run(parameters: dict, player=None, session_memory=None) -> str:
    design_type = (parameters.get("design_type") or "").strip().lower()
    description = (parameters.get("description") or "").strip()
    forced_theme = (parameters.get("theme") or "").strip().lower()

    if design_type not in _CANVA_CREATE_URLS:
        return (f"Sir, I can build a brief for: {', '.join(_CANVA_CREATE_URLS)}. "
                f"'{design_type}' isn't one I have a Canva page/layout guidance for.")

    try:
        theme_key = _pick_theme(design_type, description, forced_theme)
        theme = _THEMES[theme_key]
        tips = _LAYOUT_TIPS[design_type]
        inspiration = _find_inspiration(design_type, description)

        canva_url = _CANVA_CREATE_URLS[design_type]
        open_note = _open_canva_app(canva_url)

        # Try to ground the brief in ONE real reference image (actual
        # extracted palette + structure) rather than a generic theme bucket.
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        img_query = f"{description} {design_type.replace('_', ' ')} design".strip()
        ref_url, ref_title = _fetch_reference_image_url(img_query)
        ref_path = _download_reference_image(ref_url, REPORTS_DIR) if ref_url else None

        if ref_path:
            extracted_palette = _extract_palette(ref_path)
            layout_note = _describe_layout(ref_path)
            heading_block = f"Modeled after: {ref_title or ref_url}"
            palette_lines = [f"- {c} (extracted from the reference image)" for c in extracted_palette] \
                or [f"- {c}" for c in theme["palette"]]
            structure_note = f"\n**Reference structure:** {layout_note}\n" if layout_note else ""
            ref_line = f"\n**Reference image saved at:** {ref_path} — open it side-by-side while building.\n"
        else:
            extracted_palette = []
            heading_block = theme["label"]
            palette_lines = [f"- {c}" for c in theme["palette"]]
            structure_note = ""
            ref_line = "\n(No usable reference image found — using the built-in theme palette instead.)\n"

        lines = [
            f"# {heading_block} — {design_type.replace('_', ' ').title()}",
            "",
            f"Brief: {description}" if description else "",
            ref_line,
            "## Color Palette",
        ] + palette_lines + [
            "",
            "## Fonts (search these names directly in Canva's font picker)",
            f"- Heading: **{theme['fonts']['heading']}**",
            f"- Body: **{theme['fonts']['body']}**",
            structure_note,
            "## Layout Guidance",
        ] + [f"- {t}" for t in tips]

        if inspiration:
            lines += ["", "## Other Inspiration References"]
            lines += [f"- [{i['title']}]({i['url']})" for i in inspiration if i["url"]]

        content = "\n".join(l for l in lines if l is not None)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        brief_path = REPORTS_DIR / f"{_slugify(design_type + '_' + description)}_{stamp}.md"
        brief_path.write_text(content, encoding="utf-8")

        ref_note = " grounded in a real reference image's extracted palette and layout" if ref_path else " using a built-in elegant/modern theme"
        result_text = (f"For your {design_type.replace('_', ' ')}, I {open_note}, and put together "
                        f"a design brief{ref_note} — saved to {brief_path}.")

    except Exception as e:
        return f"Sir, design_in_canva failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
