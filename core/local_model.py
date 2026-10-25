
"""Local language/vision model adapter for Mark 56.

Uses the Ollama HTTP API on localhost. No API key, cloud provider, or third-party
Python package is required. A vision-capable Ollama model is needed for images.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _base_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _settings() -> dict:
    """Read local model settings from config/local_model.json."""
    try:
        base = _base_dir() / "config"
        # The app's canonical settings file is api_keys.json. Older local-model
        # experiments used local_model.json, so retain it as a compatibility fallback.
        for config_path in (base / "api_keys.json", base / "local_model.json"):
            try:
                value = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    return value
            except (OSError, ValueError, TypeError):
                continue
        return {}
    except (OSError, ValueError, TypeError):
        return {}


def enabled() -> bool:
    """Whether local-model mode is explicitly enabled in local settings."""
    return _settings().get("local_model_enabled") is True


def _base_url(settings: dict | None = None) -> str:
    settings = settings if settings is not None else _settings()
    value = str(
        settings.get("local_model_base_url")
        or "http://127.0.0.1:11434"
    ).strip().rstrip("/")

    parsed = urlparse(value)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError(
            "Local model URL must point to loopback; "
            "remote model servers are not accepted."
        )

    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "Local model URL cannot contain credentials, a query, or a fragment."
        )

    return value


def status(timeout_seconds: float = 2.0) -> dict:
    """Report local Ollama reachability and installed model names."""
    settings = _settings()

    try:
        request = urllib.request.Request(
            _base_url(settings) + "/api/tags",
            method="GET",
        )

        with urllib.request.urlopen(
            request, timeout=max(0.2, timeout_seconds)
        ) as response:
            payload = json.loads(
                response.read(2_000_000).decode("utf-8")
            )

        models = [
            str(item.get("name"))
            for item in payload.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]

        return {
            "ok": True,
            "enabled": settings.get("local_model_enabled") is True,
            "models": models,
        }

    except Exception as exc:
        return {
            "ok": False,
            "enabled": settings.get("local_model_enabled") is True,
            "models": [],
            "message": (
                f"Local model unavailable ({type(exc).__name__}). "
                "Start Ollama and check its local URL."
            ),
        }


def generate(
    prompt: str,
    *,
    images: list[bytes] | None = None,
    model: str | None = None,
    timeout_ms: int = 30_000,
) -> str:
    """Generate text locally; optional PNG/JPEG bytes are passed to a vision model."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("A non-empty prompt is required.")

    settings = _settings()

    if settings.get("local_model_enabled") is not True:
        raise RuntimeError(
            "Local model mode is disabled in config/local_model.json."
        )

    model_setting = (
        "local_vision_model_name" if images else "local_model_name"
    )
    selected_model = str(
        model or settings.get(model_setting) or ""
    ).strip()

    if not selected_model:
        raise RuntimeError(
            "Set local_model_name (and local_vision_model_name "
            "for screenshots) in config/local_model.json."
        )

    message = {
        "role": "user",
        "content": prompt,
    }

    if images:
        message["images"] = [
            base64.b64encode(data).decode("ascii")
            for data in images
        ]

    payload = json.dumps(
        {
            "model": selected_model,
            "messages": [message],
            "stream": False,
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        _base_url(settings) + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    timeout = max(1.0, min(float(timeout_ms) / 1000.0, 120.0))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(
                response.read(4_000_000).decode("utf-8")
            )
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Local model request failed. Ensure Ollama is running "
            "and the model is installed."
        ) from exc

    response_text = result.get("message", {}).get("content", "")

    if not isinstance(response_text, str) or not response_text.strip():
        raise RuntimeError("Local model returned an empty response.")

    return response_text.strip()
