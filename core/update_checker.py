"""Lightweight, non-invasive GitHub release update checks for JARVIS.

The checker only reads public GitHub release metadata. It never downloads or
executes an installer itself: the user explicitly chooses Download, which opens
the release's platform-specific asset in the system browser.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
import urllib.error
import urllib.parse
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



def download_release_asset(
    download_url: str,
    asset_name: str,
    expected_digest: str,
    *,
    download_dir: str | Path | None = None,
    timeout: float = 20.0,
    max_bytes: int = 2_000_000_000,
) -> Path:
    """Download a GitHub release asset to disk and verify its published SHA-256.

    This function never launches the downloaded file. A digest from GitHub's
    release asset metadata is mandatory; absent or malformed digests fail closed.
    """
    parsed = urllib.parse.urlparse(str(download_url or ""))
    if parsed.scheme != "https" or parsed.hostname not in {
        "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    }:
        raise RuntimeError("Refusing update download from an untrusted host.")

    filename = Path(str(asset_name or "")).name
    if not filename or filename in {".", ".."} or filename != str(asset_name):
        raise RuntimeError("The release asset has an invalid filename.")
    digest_match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", str(expected_digest or "").strip())
    if not digest_match:
        raise RuntimeError("GitHub did not publish a valid SHA-256 digest for this asset; use the release page instead.")
    expected = digest_match.group(1).lower()

    destination_dir = Path(download_dir).expanduser() if download_dir else Path.home() / "Downloads"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    if destination.exists():
        raise RuntimeError(f"A file named {filename} already exists in {destination_dir}; move or rename it before downloading.")

    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/octet-stream"},
        method="GET",
    )
    temp_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            final_url = urllib.parse.urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in {
                "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
            }:
                raise RuntimeError("The update download redirected to an untrusted host.")
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".jarvis-update-", suffix=".part",
                dir=str(destination_dir), delete=False,
            ) as output:
                temp_path = Path(output.name)
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("The update package exceeded the permitted download size.")
                    digest.update(chunk)
                    output.write(chunk)
        if total == 0:
            raise RuntimeError("GitHub returned an empty update package.")
        if digest.hexdigest().lower() != expected:
            raise RuntimeError("The downloaded update failed SHA-256 verification; the file was discarded.")
        # The temporary file is in the same directory, so replacement is atomic.
        os.replace(temp_path, destination)
        temp_path = None
        return destination
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not download the update: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
