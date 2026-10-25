"""Secure, Website Studio-specific OpenAI credential management.

Credentials are stored only in the OS keyring. This module deliberately does not
read or modify config/api_keys.json, so Website Studio cannot change the global
Gemini/OpenAI provider configuration.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SERVICE = "Mark56-WebsiteStudio"
_ACCOUNT = "openai-api-key"
_MODELS_URL = "https://api.openai.com/v1/models"
_TIMEOUT_SECONDS = 12


class CredentialError(RuntimeError):
    """A safe, user-facing credential setup error."""


def _keyring_module():
    try:
        import keyring
    except ImportError as exc:
        raise CredentialError(
            "Secure credential storage is unavailable. Install the keyring package "
            "and enable your operating system's credential service, then try again."
        ) from exc

    backend = keyring.get_keyring()
    # Never silently accept plaintext/fail backends. Linux requires Secret Service
    # (GNOME Keyring/KWallet); Windows/macOS use their native credential stores.
    module = type(backend).__module__.lower()
    name = type(backend).__name__.lower()
    priority = getattr(backend, "priority", 0)
    if priority <= 0 or any(token in module + "." + name for token in ("fail", "null", "plaintext", "filekeyring")):
        raise CredentialError(
            "No secure operating-system credential store is available. "
            "Unlock or configure your desktop keyring, then try again."
        )
    return keyring


def is_configured() -> bool:
    """Return whether a Website Studio key is present; never expose the key."""
    try:
        key = _keyring_module().get_password(_SERVICE, _ACCOUNT)
        return bool(isinstance(key, str) and key.strip())
    except CredentialError:
        return False
    except Exception:
        return False


def validate_api_key(api_key: str) -> None:
    """Validate the supplied key using a small authenticated GET request."""
    key = str(api_key or "").strip()
    if not key or len(key) > 512 or any(ch.isspace() for ch in key):
        raise CredentialError("Enter a valid-looking OpenAI API key.")

    request = Request(
        _MODELS_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise CredentialError("OpenAI could not validate this key. Check it and try again.")
            # Consume only a small bounded response portion; no model list is needed.
            response.read(1024)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise CredentialError("OpenAI rejected this API key. Check the key and try again.") from None
        if exc.code == 429:
            raise CredentialError("OpenAI rate-limited the validation request. Wait a moment and retry.") from None
        raise CredentialError(f"OpenAI validation failed with HTTP {exc.code}. Try again later.") from None
    except URLError:
        raise CredentialError("Could not reach OpenAI. Check your internet connection and try again.") from None
    except TimeoutError:
        raise CredentialError("OpenAI validation timed out. Try again.") from None
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("OpenAI validation failed. Check your connection and try again.") from None


def save_api_key(api_key: str) -> None:
    """Validate first, then persist the key in the OS keyring."""
    key = str(api_key or "").strip()
    validate_api_key(key)
    keyring = _keyring_module()
    try:
        keyring.set_password(_SERVICE, _ACCOUNT, key)
    except Exception:
        raise CredentialError(
            "The key was validated but could not be saved to the secure credential store. "
            "No plain-text fallback was used."
        ) from None


def delete_api_key() -> None:
    """Remove only the Website Studio credential."""
    keyring = _keyring_module()
    try:
        keyring.delete_password(_SERVICE, _ACCOUNT)
    except Exception as exc:
        # A missing entry is already the desired state.
        if type(exc).__name__ not in {"PasswordDeleteError", "CredentialNotFoundException"}:
            raise CredentialError("Could not remove the Website Studio key from secure storage.") from None


def status() -> dict:
    """Safe status payload for UI; never returns the credential."""
    try:
        configured = is_configured()
        return {"ok": True, "configured": configured, "storage": "operating-system credential store"}
    except Exception:
        return {"ok": False, "configured": False, "message": "Secure credential storage is unavailable."}
