"""Verified, user-consented update staging for Mark 56.

This module only downloads official release assets into a temporary staging
folder and verifies SHA-256 against the official release's checksum manifest.
It never launches an installer or replaces the running application. The UI must
show the release details and obtain explicit consent before calling prepare_update.
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
from dataclasses import dataclass
from pathlib import Path

from plugins import update_manager

_REPO = "ibarakumo2000-stack/Mark-56"
_API_RELEASE = f"https://api.github.com/repos/{_REPO}/releases/latest"
_ALLOWED_HOSTS = {"github.com", "api.github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
_MAX_MANIFEST = 512_000
_MAX_ASSET = 2_000_000_000
_TIMEOUT = 20


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    asset_name: str
    file_path: str
    sha256: str
    release_url: str


def _request(url: str, *, max_bytes: int):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("Update URL is not an approved HTTPS GitHub release host.")
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Mark56-Updater",
    })
    response = urllib.request.urlopen(request, timeout=_TIMEOUT)
    if response.status != 200:
        response.close()
        raise RuntimeError(f"GitHub returned HTTP {response.status}.")
    data = response.read(max_bytes + 1)
    response.close()
    if len(data) > max_bytes:
        raise RuntimeError("Update response exceeded the allowed size.")
    return data


def platform_asset_names(system: str | None = None, machine: str | None = None) -> tuple[str, ...]:
    """Return supported asset names in preferred order for the current OS."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        return ("MARK-LV-Setup-{version}.exe",)
    if system == "linux":
        return ("MARK-LV-Linux-x86_64.tar.gz",) if machine in {"x86_64", "amd64"} else ()
    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return ("MARK-LV-macOS-arm64.dmg",)
        if machine in {"x86_64", "amd64"}:
            return ("MARK-LV-macOS-x86_64.dmg",)
    return ()


def _safe_release_url(value: object) -> str:
    if isinstance(value, str) and value.startswith(f"https://github.com/{_REPO}/releases/"):
        return value
    return update_manager.RELEASES_PAGE


def prepare_update(*, current_version: str | None = None, staging_dir: str | Path | None = None) -> PreparedUpdate:
    """Download and checksum-verify a newer stable release; does not install it."""
    status = update_manager.check_for_update(current_version)
    if status.status != "update_available" or not status.latest_version:
        raise RuntimeError(status.message)

    payload = json.loads(_request(_API_RELEASE, max_bytes=_MAX_MANIFEST).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("Latest release is not a verified stable release.")
    tag = str(payload.get("tag_name") or "")
    version_match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", tag)
    if not version_match or version_match.group(1) != status.latest_version:
        raise RuntimeError("Release version changed during update preparation.")

    candidates = platform_asset_names()
    if not candidates:
        raise RuntimeError(f"No Mark 56 installer is published for {platform.system()} {platform.machine()}.")

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("Release assets are missing.")
    names = [candidate.format(version=status.latest_version) for candidate in candidates]
    selected = next((a for name in names for a in assets if isinstance(a, dict) and a.get("name") == name), None)
    sums = next((a for a in assets if isinstance(a, dict) and a.get("name") == "SHA256SUMS.txt"), None)
    if not selected or not sums:
        raise RuntimeError("The release is missing this platform's installer or SHA256SUMS.txt.")

    asset_url = selected.get("browser_download_url")
    sums_url = sums.get("browser_download_url")
    if not isinstance(asset_url, str) or not isinstance(sums_url, str):
        raise RuntimeError("Release asset URLs are invalid.")

    manifest = _request(sums_url, max_bytes=256_000).decode("utf-8", errors="strict")
    expected = None
    asset_name = str(selected.get("name"))
    for line in manifest.splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?(.+)", line.strip())
        if match and match.group(2) == asset_name:
            expected = match.group(1).lower()
            break
    if not expected:
        raise RuntimeError("The official checksum manifest has no valid hash for this installer.")

    download_url = urllib.parse.urlparse(asset_url)
    if download_url.scheme != "https" or download_url.hostname not in _ALLOWED_HOSTS:
        raise RuntimeError("Installer URL is not an approved HTTPS GitHub release host.")
    request = urllib.request.Request(asset_url, headers={"User-Agent": "Mark56-Updater"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"Installer download failed with HTTP {response.status}.")
        length = response.headers.get("Content-Length")
        if length and (not length.isdigit() or int(length) > _MAX_ASSET):
            raise RuntimeError("Installer size is invalid or exceeds the safety limit.")
        directory = Path(staging_dir) if staging_dir else Path(tempfile.mkdtemp(prefix="mark56-update-"))
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / asset_name
        digest = hashlib.sha256()
        total = 0
        try:
            with destination.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_ASSET:
                        raise RuntimeError("Installer download exceeded the safety limit.")
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            actual = digest.hexdigest()
            if actual != expected:
                raise RuntimeError("Installer SHA-256 verification failed; the file was discarded.")
            return PreparedUpdate(
                version=status.latest_version,
                asset_name=asset_name,
                file_path=str(destination),
                sha256=actual,
                release_url=_safe_release_url(payload.get("html_url")),
            )
        except Exception:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise


# Mark-56 plugin-template entry point: stage and verify an official release, never install it.
PLUGIN = {
    "name": "update_installer",
    "description": "Prepare a verified Mark 56 release installer in a staging folder. This only downloads an official release asset and checks its checksum; it never runs or installs the file.",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        prepared = prepare_update()
        return (f"Verified update installer staged for version {prepared.version}: {prepared.asset_name}. "
                f"SHA-256 verification succeeded. Review the release details and use the explicit update confirmation UI to install.")
    except Exception as exc:
        return f"Sir, update staging failed safely: {type(exc).__name__}: {exc}"
