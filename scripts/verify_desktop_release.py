#!/usr/bin/env python3
"""Fail closed unless a desktop draft release contains all same-commit packages."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPOSITORY = "ibarakumo2000-stack/Mark-56"
TARGETS = {
    "windows-x86_64": ("MARK-LV-Setup-{version}.exe", "build-info.json", "SHA256SUMS-windows-x86_64.txt"),
    "linux-x86_64": ("MARK-LV-Linux-x86_64.tar.gz", "build-info-linux-x86_64.json", "SHA256SUMS-linux-x86_64.txt"),
    "macos-arm64": ("MARK-LV-macOS-arm64.dmg", "build-info-macos-arm64.json", "SHA256SUMS-macos-arm64.txt"),
    "macos-x86_64": ("MARK-LV-macOS-x86_64.dmg", "build-info-macos-x86_64.json", "SHA256SUMS-macos-x86_64.txt"),
}


def fail(message: str) -> None:
    print(f"RELEASE PREFLIGHT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not args.tag.startswith("v") or len(args.tag.split(".")) != 3:
        fail("desktop release tag must be vMAJOR.MINOR.PATCH")
    version = args.tag[1:]
    if not all(part.isdigit() for part in version.split(".")):
        fail("desktop release tag must be vMAJOR.MINOR.PATCH")

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        fail("GITHUB_TOKEN is missing")
    try:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", f"{args.tag}^{{commit}}"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        fail(f"tag {args.tag} is not available in the checked-out repository")

    url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{args.tag}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JARVIS-Release-Preflight",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.loads(response.read(2_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        fail(f"could not read GitHub release metadata: {exc}")

    if not release.get("draft") or release.get("prerelease"):
        fail("expected an unpublished stable draft release; do not run preflight after promotion")
    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    required = []
    for target, (package_pattern, metadata_name, checksum_name) in TARGETS.items():
        package_name = package_pattern.format(version=version)
        required.extend((package_name, metadata_name, checksum_name))
        if package_name not in assets:
            fail(f"missing package for {target}: {package_name}")
        if metadata_name not in assets:
            fail(f"missing build metadata for {target}: {metadata_name}")
        if checksum_name not in assets:
            fail(f"missing checksum manifest for {target}: {checksum_name}")

        metadata_url = assets[metadata_name].get("url")
        if not metadata_url:
            fail(f"metadata asset has no API URL: {metadata_name}")
        metadata_request = urllib.request.Request(metadata_url, headers={
            "Accept": "application/octet-stream",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JARVIS-Release-Preflight",
        })
        try:
            with urllib.request.urlopen(metadata_request, timeout=20) as response:
                metadata = json.loads(response.read(100_000).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            fail(f"could not read {metadata_name}: {exc}")

        if metadata.get("version") != version:
            fail(f"{metadata_name} version is {metadata.get('version')!r}, expected {version!r}")
        if metadata.get("target") != target:
            fail(f"{metadata_name} target is {metadata.get('target')!r}, expected {target!r}")
        if metadata.get("source_commit") != source_commit:
            fail(
                f"{metadata_name} was built from {metadata.get('source_commit')!r}; "
                f"tag {args.tag} points to {source_commit!r}"
            )
        digest = str(metadata.get("sha256") or "")
        if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            fail(f"{metadata_name} does not contain a valid SHA-256 digest")
        print(f"PASS {target}: {package_name}, metadata and source commit verified")

    print(f"PASS {args.tag}: all four desktop targets use source commit {source_commit}")
    print("The release is ready for a human to review and publish.")


if __name__ == "__main__":
    main()
