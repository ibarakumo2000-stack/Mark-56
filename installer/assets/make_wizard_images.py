"""Regenerate the installer's wizard images from the app icon.

    python installer/assets/make_wizard_images.py [path/to/jarvis.ico]

Writes (next to this script):
    wizard-large.bmp / wizard-large@2x.bmp   left panel on Welcome + Finish
    wizard-small.bmp / wizard-small@2x.bmp   top-right logo on inner pages
Needs Pillow. Edit BG_TOP / BG_BOTTOM / ACCENT / TITLE / TAGLINE to rebrand.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ICON = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent.parent / "config" / "jarvis.ico"

BG_TOP, BG_BOTTOM = (0, 6, 10), (0, 30, 44)
ACCENT = (0, 212, 255)
TITLE, TAGLINE = "MARK LV", "Personal AI assistant"


def font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "segoeuib.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def icon_image(px):
    im = Image.open(ICON)
    try:  # pick the largest frame the .ico offers
        im.size = max(im.info.get("sizes", {im.size}))
    except Exception:
        pass
    return im.convert("RGBA").resize((px, px), Image.LANCZOS)


def large(scale):
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # vertical gradient
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    d.rectangle([w - 2 * scale, 0, w, h], fill=ACCENT)           # accent edge
    ic = 112 * scale
    logo = icon_image(ic)
    img.paste(logo, ((w - ic) // 2, 54 * scale), logo)
    for text, f, y, col in ((TITLE, font(20 * scale, True), 190 * scale, (235, 250, 255)),
                            (TAGLINE, font(9 * scale), 222 * scale, ACCENT)):
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y), text, font=f, fill=col)
    return img


def small(scale):
    px = 55 * scale
    img = Image.new("RGB", (px, px), BG_TOP)
    ic = 47 * scale
    logo = icon_image(ic)
    img.paste(logo, ((px - ic) // 2, (px - ic) // 2), logo)
    return img


if __name__ == "__main__":
    for scale, suffix in ((1, ""), (2, "@2x")):
        large(scale).save(HERE / f"wizard-large{suffix}.bmp")
        small(scale).save(HERE / f"wizard-small{suffix}.bmp")
    print("wizard images written to", HERE)
