"""Lightweight, non-invasive GitHub release update checks for JARVIS.

The checker only reads public GitHub release metadata. It never downloads or
executes an installer itself: the user explicitly chooses Download, which opens
the release's platform-specific asset in the system browser.
"""
from __future__ import annotations

import json
import platform
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "ibarakumo2000-stack/Mark-56"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
_USER_AGENT = "JARVIS-Mark56-UpdateChecker/1.0"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def version_tuple(value: str) -> tuple[int, int, int] | None:
    """Parse a stable semantic version; return None for development labels."""
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def read_current_version(base_dir: str | Path | None = None) -> str:
    """Read the version stamped into packaged builds, with a source-tree fallback."""
    root = Path(base_dir).resolve() if base_dir is not None else Path(__file__).resolve().parents[1]
    for candidate in (root / "VERSION", root / "installer" / "version.txt"):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if version_tuple(value):
            return value.lstrip("v")
    return "0.0.0"


def _normalise_arch(machine: str) -> str:
    value = (machine or "").lower().replace("-", "_")
    if value in {"amd64", "x64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return value


def select_release_asset(
    release: dict[str, Any],
    system: str | None = None,
    machine: str | None = None,
) -> dict[str, Any] | None:
    """Find the release asset for the active OS and CPU architecture."""
    system = (system or platform.system()).lower()
    arch = _normalise_arch(machine or platform.machine())
    assets = release.get("assets")
    if not isinstance(assets, list):
        assets = []

    if system == "windows":
        matches = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")
                   and "setup" in str(a.get("name", "")).lower()]
    elif system == "darwin":
        matches = [a for a in assets if str(a.get("name", "")).lower().endswith(".dmg")
                   and f"macos-{arch}" in str(a.get("name", "")).lower()]
    elif system == "linux":
        matches = [a for a in assets if str(a.get("name", "")).lower().endswith(".tar.gz")
                   and f"linux-{arch}" in str(a.get("name", "")).lower()]
    else:
        return None
    return matches[0] if matches else None


def fetch_latest_release(timeout: float = 6.0, api_url: str = LATEST_RELEASE_API) -> dict[str, Any]:
    """Fetch latest public stable release metadata from GitHub."""
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            payload = json.loads(response.read(1_500_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub could not be reached: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an unexpected release response.")
    if payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("GitHub's latest release is not a stable public release.")
    version = str(payload.get("tag_name") or "").strip().lstrip("v")
    if not version_tuple(version):
        raise RuntimeError("The latest GitHub release has no valid MAJOR.MINOR.PATCH version.")
    return payload


def check_for_update(
    current_version: str | None = None,
    *,
    timeout: float = 6.0,
    api_url: str = LATEST_RELEASE_API,
    system: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    """Return a UI-ready status dict without downloading or executing anything."""
    current = str(current_version or read_current_version()).strip().lstrip("v")
    current_parts = version_tuple(current)
    try:
        release = fetch_latest_release(timeout=timeout, api_url=api_url)
    except RuntimeError as exc:
        return {"status": "error", "current_version": current, "message": str(exc)}

    latest = str(release["tag_name"]).strip().lstrip("v")
    latest_parts = version_tuple(latest)
    if latest_parts is None:
        return {"status": "error", "current_version": current,
                "message": "The latest release version could not be understood."}
    if current_parts is not None and latest_parts <= current_parts:
        return {
            "status": "current",
            "current_version": current,
            "latest_version": latest,
            "release_url": release.get("html_url") or RELEASES_PAGE,
        }

    asset = select_release_asset(release, system=system, machine=machine)
    release_url = str(release.get("html_url") or RELEASES_PAGE)
    download_url = str((asset or {}).get("browser_download_url") or release_url)
    notes = str(release.get("body") or "").strip()
    if len(notes) > 1800:
        notes = notes[:1797].rstrip() + "..."
    return {
        "status": "available",
        "current_version": current,
        "latest_version": latest,
        "release_url": release_url,
        "download_url": download_url,
        "asset_name": (asset or {}).get("name"),
        "sha256": str((asset or {}).get("digest") or ""),
        "notes": notes,
    }
