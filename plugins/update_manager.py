"""Release-channel checks for Mark 56.

Checks the project's GitHub Releases endpoint over HTTPS. It never executes
downloaded code or replaces the running application. Automatic installation
requires a signed, platform-specific package and a restart-time installer.
"""
from __future__ import annotations
import json, re, urllib.error, urllib.request
from dataclasses import dataclass
from typing import Optional

RELEASE_API = "https://api.github.com/repos/ibarakumo2000-stack/Mark-56/releases/latest"
RELEASES_PAGE = "https://github.com/ibarakumo2000-stack/Mark-56/releases"
CURRENT_VERSION = "56.0.0"
_TIMEOUT = 5.0

@dataclass(frozen=True)
class UpdateStatus:
    current_version: str
    latest_version: Optional[str]
    update_available: bool
    release_url: str
    message: str

def _version(value: str):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return tuple(map(int, match.groups())) if match else None

def check_for_update(current_version: str = CURRENT_VERSION) -> UpdateStatus:
    current = _version(current_version)
    if current is None:
        return UpdateStatus(current_version, None, False, RELEASES_PAGE, "Current version is not valid semantic versioning.")
    request = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Mark56-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.status != 200:
                raise RuntimeError(f"Release service returned HTTP {response.status}.")
            payload = json.loads(response.read(256_000).decode("utf-8"))
        if payload.get("draft") or payload.get("prerelease"):
            return UpdateStatus(current_version, None, False, RELEASES_PAGE, "No stable release is currently available.")
        tag = str(payload.get("tag_name") or "")
        latest = _version(tag)
        if latest is None:
            return UpdateStatus(current_version, None, False, RELEASES_PAGE, "Latest release has no valid vMAJOR.MINOR.PATCH tag.")
        url = payload.get("html_url")
        if not isinstance(url, str) or not url.startswith("https://github.com/ibarakumo2000-stack/Mark-56/releases/"):
            url = RELEASES_PAGE
        newer = latest > current
        msg = (f"Version {tag} is available; a verified platform installer is required before it can be applied."
               if newer else "Mark 56 is up to date.")
        return UpdateStatus(current_version, tag.lstrip("v"), newer, url, msg)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, RuntimeError) as exc:
        return UpdateStatus(current_version, None, False, RELEASES_PAGE,
                            f"Update check unavailable ({type(exc).__name__}); existing installation was not changed.")

def as_dict(status: UpdateStatus) -> dict:
    return {"current_version": status.current_version, "latest_version": status.latest_version,
            "update_available": status.update_available, "release_url": status.release_url,
            "message": status.message, "auto_install_ready": False}

PLUGIN = {
    "name": "update_manager",
    "description": "Check the official Mark 56 GitHub Releases channel over HTTPS. Checks metadata only; does not download or execute updates.",
    "parameters": {"type": "OBJECT", "properties": {"operation": {"type": "STRING", "description": "check"}}, "required": ["operation"]},
}
def run(parameters: dict, **_context) -> str:
    if str((parameters or {}).get("operation") or "check").lower() != "check":
        return json.dumps({"ok": False, "message": "Only check is supported."})
    return json.dumps(as_dict(check_for_update()), ensure_ascii=False)
