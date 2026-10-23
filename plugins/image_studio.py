"""
image_studio.py — JARVIS plugin

"Jarvis, create an image of a luxury car with this person standing in front
of it" (optionally passing a reference photo) / "remove the background from
this image" / "make this image look more elegant" — generates new images or
edits existing ones using Gemini's native image model (gemini-3.1-flash-image,
aka Nano Banana).

This necessarily depends on an AI model — unlike code generation, there's no
deterministic/template equivalent for photorealistic image synthesis or
photo-realistic editing. Uses the same Gemini API key already configured
for the rest of the project (config/api_keys.json).

Defaults to an elegant, modern aesthetic unless the prompt/style clearly
asks for something else (matches the user's stated design preference).

HONESTY NOTE on "remove the background": this routes through the generative
edit model, which redraws the whole image per instruction — good for
creative edits ("remove the background and put me on a beach") but it is
NOT pixel-perfect alpha-channel matting the way a dedicated background-
removal tool (e.g. rembg) would be for something like clean product photos.
Said plainly in the result if that specific request is detected.

Drop this file into /plugins/ — no other file needs to change.
"""

import io
import json
import platform
import subprocess
from pathlib import Path
from datetime import datetime

PLUGIN = {
    "name": "create_or_edit_image",
    "description": (
        "Creates a new image from a text description, optionally compositing "
        "one or more uploaded reference photos (e.g. a photo of a specific "
        "person) into the generated scene — or edits an existing image "
        "(remove/change background, restyle, add/remove elements) based on "
        "an instruction. Use for 'create an image of X', 'make a picture "
        "with this person in it', 'edit this image to...', 'remove the "
        "background from this photo'. Defaults to a modern, elegant look "
        "unless a different style is requested. Uses Gemini's image model — "
        "this is an inherently AI-based capability, there's no local/"
        "template equivalent for photorealistic image generation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {
                "type": "STRING",
                "enum": ["generate", "edit"],
                "description": "'generate' = create a new image (optionally "
                                "with reference photo(s) composited in). "
                                "'edit' = modify an existing image per an "
                                "instruction (background removal, restyling, "
                                "adding/removing elements, etc.).",
            },
            "prompt": {
                "type": "STRING",
                "description": "What to create, or the edit instruction. "
                                "Be descriptive — e.g. 'a matte-black luxury "
                                "sedan on a city street at dusk' rather than "
                                "just 'a car'.",
            },
            "reference_image_paths": {
                "type": "ARRAY",
                "description": "Local image path(s). For 'generate': photo(s) "
                                "of a person/subject to include in the new "
                                "scene (optional). For 'edit': the image being "
                                "edited (required, usually just one).",
                "items": {"type": "STRING"},
            },
            "style": {
                "type": "STRING",
                "description": "Optional style override. If omitted, an "
                                "elegant/modern look is applied by default "
                                "unless the prompt itself already names a "
                                "different style (e.g. 'cartoon', 'vintage').",
            },
            "output_path": {
                "type": "STRING",
                "description": "Optional save path. Defaults to "
                                "~/Desktop/JarvisImages/<name>_<timestamp>.png",
            },
        },
        "required": ["mode", "prompt"],
    },
}

_IMAGE_MODEL = "gemini-3.1-flash-image"
_OUTPUT_DIR = Path.home() / "Desktop" / "JarvisImages"
_EXPLICIT_STYLE_HINTS = [
    "cartoon", "anime", "sketch", "watercolor", "pixel art", "vintage",
    "retro", "black and white", "grayscale", "oil painting", "comic book",
    "minimalist", "line art", "3d render", "claymation", "noir",
]
_BACKGROUND_REMOVAL_HINTS = ["remove the background", "remove background",
                              "transparent background", "delete the background"]


def _api_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(_api_config_path(), "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_reference_images(paths):
    """Loads and validates every path up front. Raises with a clear message
    on the FIRST bad path rather than silently dropping a requested photo —
    if the user asked for a specific person in the shot, failing loudly is
    safer than quietly generating something without them."""
    from PIL import Image
    images = []
    for p in paths:
        path = Path(p).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"'{p}' does not exist.")
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            raise ValueError(f"'{p}' isn't a readable image file ({e}).")
        images.append(img)
    return images


def _augment_prompt(prompt: str, style: str) -> str:
    if style:
        return f"{prompt}\n\nStyle: {style}."
    text = prompt.lower()
    if any(hint in text for hint in _EXPLICIT_STYLE_HINTS):
        return prompt  # user already specified a style — don't override it
    return (f"{prompt}\n\nStyle: elegant, modern, high-quality, "
            f"photorealistic, clean composition, professional lighting.")


def _slugify(text: str) -> str:
    keep = [c if c.isalnum() else "_" for c in text.strip().lower()]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:40] or "image"


def _default_output_path(prompt: str) -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _OUTPUT_DIR / f"{_slugify(prompt)}_{stamp}.png"


def _resolve_output_path(output_path: str, prompt: str) -> Path:
    if output_path:
        p = Path(output_path).expanduser()
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            p = p.with_suffix(".png")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return _default_output_path(prompt)


def _extract_image_and_text(response):
    """Handles both known response shapes across google-genai SDK versions:
    response.parts (newer) or response.candidates[0].content.parts (older)."""
    from PIL import Image

    parts = getattr(response, "parts", None)
    if not parts:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(candidates[0].content, "parts", [])
    parts = parts or []

    image = None
    text_notes = []
    for part in parts:
        if getattr(part, "text", None):
            text_notes.append(part.text)
        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None and image is None:
            if hasattr(part, "as_image"):
                try:
                    image = part.as_image()
                    continue
                except Exception:
                    pass
            image = Image.open(io.BytesIO(inline_data.data))

    return image, " ".join(text_notes).strip()


def _open_file(path: Path):
    system = platform.system()
    try:
        if system == "Windows":
            import os
            os.startfile(str(path))
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass  # non-fatal — the file is saved either way


def run(parameters: dict, player=None, session_memory=None) -> str:
    mode = (parameters.get("mode") or "").strip().lower()
    prompt = (parameters.get("prompt") or "").strip()
    reference_paths = parameters.get("reference_image_paths") or []
    style = (parameters.get("style") or "").strip()
    output_path = (parameters.get("output_path") or "").strip()

    if mode not in ("generate", "edit"):
        return "Sir, tell me whether to generate a new image or edit an existing one."
    if not prompt:
        return "Sir, I need a description of what to create or how to edit it."
    if mode == "edit" and not reference_paths:
        return "Sir, editing needs the path to the image you want edited."

    try:
        api_key = _get_api_key()
    except Exception as e:
        return f"Sir, I couldn't read the Gemini API key from config: {e}"

    try:
        ref_images = _load_reference_images(reference_paths) if reference_paths else []
    except Exception as e:
        return f"Sir, {e}"

    background_note = ""
    if mode == "edit" and any(h in prompt.lower() for h in _BACKGROUND_REMOVAL_HINTS):
        background_note = (" Note: this is a generative edit, not pixel-precise alpha "
                            "matting — great for creative background swaps, but for a "
                            "perfectly clean cutout (e.g. product photos) a dedicated "
                            "background-removal tool would do better.")

    final_prompt = _augment_prompt(prompt, style)
    contents = [final_prompt] + ref_images

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=_IMAGE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            )
        except TypeError:
            # older/newer SDK mismatch on the config kwarg shape — retry plain
            response = client.models.generate_content(model=_IMAGE_MODEL, contents=contents)

        image, notes = _extract_image_and_text(response)

        if image is None:
            reason = f" The model said: \"{notes}\"" if notes else ""
            return f"Sir, no image came back — it may have been blocked by safety filters.{reason}"

        save_path = _resolve_output_path(output_path, prompt)
        image.save(save_path)
        _open_file(save_path)

        verb = "Created" if mode == "generate" else "Edited"
        result_text = f"{verb} the image and saved it to {save_path}.{background_note}"

    except FileNotFoundError as e:
        return f"Sir, {e}"
    except Exception as e:
        return f"Sir, create_or_edit_image failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass

    return result_text
