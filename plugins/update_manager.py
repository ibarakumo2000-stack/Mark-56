"""Release-channel checks for Mark 56.

Checks official GitHub Releases metadata over HTTPS. It never executes
downloaded code or replaces the running application. Installing an update
requires a verified, platform-specific installer and a restart-time rollback path.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
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
    status: str = "unavailable"


def _version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return tuple(map(int, match.groups())) if match else None


def _unavailable(current_version: str, message: str) -> UpdateStatus:
    return UpdateStatus(
        current_version,
        None,
        False,
        RELEASES_PAGE,
        message,
        "unavailable",
    )


def check_for_update(current_version: str = CURRENT_VERSION) -> UpdateStatus:
    """Check for a newer stable release without changing the installed app."""
    current = _version(current_version)
    if current is None:
        return UpdateStatus(
            current_version,
            None,
            False,
            RELEASES_PAGE,
            "The installed version could not be verified. Check the app version configuration.",
            "invalid_version",
        )

    request = urllib.request.Request(
        RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Mark56-Updater",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.status != 200:
                return _unavailable(
                    current_version,
                    "GitHub did not return release information. Please try again later.",
                )
            payload = json.loads(response.read(256_000).decode("utf-8"))

    except urllib.error.HTTPError as exc:
        # GitHub returns 404 for /releases/latest when this public repository
        # has no published stable release yet. That is a normal first-release
        # state—not an application error and not evidence of a newer version.
        if exc.code == 404:
            return UpdateStatus(
                current_version,
                None,
                False,
                RELEASES_PAGE,
                "No stable release has been published yet. Mark 56 is up to date.",
                "up_to_date",
            )
        if exc.code == 403:
            return _unavailable(
                current_version,
                "The release service temporarily limited update checks. Please try again later.",
            )
        return _unavailable(
            current_version,
            f"Could not check for updates (HTTP {exc.code}). Please try again later.",
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return _unavailable(
            current_version,
            "Could not reach the release service. Check your internet connection and try again.",
        )
    except (ValueError, TypeError):
        return _unavailable(
            current_version,
            "The release service returned invalid data. Please try again later.",
        )

    if not isinstance(payload, dict):
        return _unavailable(
            current_version,
            "The release service returned invalid data. Please try again later.",
        )

    if payload.get("draft") or payload.get("prerelease"):
        return UpdateStatus(
            current_version,
            None,
            False,
            RELEASES_PAGE,
            "No stable release is available yet. Mark 56 is up to date.",
            "up_to_date",
        )

    tag = str(payload.get("tag_name") or "")
    latest = _version(tag)
    if latest is None:
        return _unavailable(
            current_version,
            "The latest release has no valid version tag, so it could not be verified.",
        )

    url = payload.get("html_url")
    if not isinstance(url, str) or not url.startswith(
        "https://github.com/ibarakumo2000-stack/Mark-56/releases/"
    ):
        url = RELEASES_PAGE

    newer = latest > current
    if newer:
        message = (
            f"Version {tag} is available. Review the official release; "
            "this installation will not be changed automatically."
        )
        status = "update_available"
    else:
        message = "Mark 56 is up to date."
        status = "up_to_date"

    return UpdateStatus(
        current_version,
        tag.lstrip("v"),
        newer,
        url,
        message,
        status,
    )


def as_dict(status: UpdateStatus) -> dict:
    return {
        "current_version": status.current_version,
        "latest_version": status.latest_version,
        "update_available": status.update_available,
        "release_url": status.release_url,
        "message": status.message,
        "status": status.status,
        "auto_install_ready": False,
    }


PLUGIN = {
    "name": "update_manager",
    "description": (
        "Check official Mark 56 GitHub Releases metadata over HTTPS. "
        "Reports up-to-date when there is no newer stable release; "
        "does not download or execute updates."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {"type": "STRING", "description": "check"}
        },
        "required": ["operation"],
    },
}


def run(parameters: dict, **_context) -> str:
    if str((parameters or {}).get("operation") or "check").lower() != "check":
        return json.dumps(
            {"ok": False, "status": "unsupported", "message": "Only check is supported."}
        )
    return json.dumps(as_dict(check_for_update()), ensure_ascii=False)
