"""Optional OpenAI Responses API provider for Mark 56 one-shot tasks.

The live voice session remains on Gemini Live. This adapter is used only when
config/api_keys.json sets "text_provider": "openai". Secrets are read locally
and are never logged.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _settings() -> dict:
    try:
        return json.loads((_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _system_instruction(config) -> str:
    if config is None:
        return ""
    if isinstance(config, dict):
        value = config.get("system_instruction", "")
    else:
        value = getattr(config, "system_instruction", "")
    return value if isinstance(value, str) else str(value or "")


def _content_parts(contents) -> list[dict]:
    """Convert the text and inline-image shapes used by existing Gemini call sites."""
    items = contents if isinstance(contents, (list, tuple)) else [contents]
    parts: list[dict] = []
    for item in items:
        if isinstance(item, str):
            if item:
                parts.append({"type": "input_text", "text": item})
            continue

        blob = getattr(item, "inline_data", None)
        if blob is not None:
            data = getattr(blob, "data", None)
            mime = getattr(blob, "mime_type", None) or "application/octet-stream"
            if isinstance(data, str):
                encoded = data
            elif isinstance(data, bytes):
                encoded = base64.b64encode(data).decode("ascii")
            else:
                continue
            parts.append({
                "type": "input_image",
                "image_url": f"data:{mime};base64,{encoded}",
                "detail": "auto",
            })
            continue

        text = getattr(item, "text", None)
        if isinstance(text, str) and text:
            parts.append({"type": "input_text", "text": text})
            continue

        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append({"type": "input_text", "text": text})

    return parts


def generate(contents, config=None, timeout_ms: int = 30_000) -> str:
    """Return output text or raise a clear, secret-free error to the caller."""
    settings = _settings()
    api_key = str(settings.get("openai_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("OpenAI provider selected, but openai_api_key is not configured")

    model = str(settings.get("openai_model") or "gpt-4.1-mini").strip()
    if not model:
        model = "gpt-4.1-mini"

    parts = _content_parts(contents)
    if not parts:
        raise RuntimeError("OpenAI provider received no supported text or image content")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=max(1.0, float(timeout_ms) / 1000.0))
    response = client.responses.create(
        model=model,
        instructions=_system_instruction(config) or None,
        input=[{"role": "user", "content": parts}],
    )
    result = getattr(response, "output_text", None)
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("OpenAI returned an empty text response")
    return result.strip()
