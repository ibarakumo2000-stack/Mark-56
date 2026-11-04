#!/usr/bin/env python3
"""Fail closed unless a desktop draft release contains all same-commit packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

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


def download_asset_sha256(url: str) -> tuple[str, int]:
    """Stream a public GitHub release asset and return its SHA-256 and byte size."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        fail("release asset download URL must use HTTPS")
    request = urllib.request.Request(url, headers={
        "User-Agent": "JARVIS-Release-Preflight",
        "Accept": "application/octet-stream",
    })
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"could not download release package for checksum verification: {exc}")
    if size <= 0:
        fail("release package download was empty")
    return digest.hexdigest(), size


def read_public_asset(url: str, *, maximum: int = 1_000_000) -> str:
    """Read a small public release asset, such as a platform checksum manifest."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        fail("release asset download URL must use HTTPS")
    request = urllib.request.Request(url, headers={
        "User-Agent": "JARVIS-Release-Preflight",
        "Accept": "application/octet-stream",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(maximum + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"could not download checksum manifest: {exc}")
    if len(data) > maximum:
        fail("checksum manifest is unexpectedly large")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        fail("checksum manifest is not valid UTF-8")


def verify_metadata(
    metadata: dict, *, version: str, target: str, source_commit: str,
    actual_sha256: str, actual_size: int,
) -> None:
    if metadata.get("version") != version:
        fail(f"build metadata version is {metadata.get('version')!r}, expected {version!r}")
    if metadata.get("target") != target:
        fail(f"build metadata target is {metadata.get('target')!r}, expected {target!r}")
    if metadata.get("source_commit") != source_commit:
        fail(
            f"build metadata was built from {metadata.get('source_commit')!r}; "
            f"the release tag points to {source_commit!r}"
        )
    metadata_digest = str(metadata.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", metadata_digest):
        fail("build metadata does not contain a valid SHA-256 digest")
    if metadata_digest != actual_sha256.lower():
        fail("build metadata SHA-256 does not match the downloaded package")
    try:
        metadata_size = int(metadata.get("size"))
    except (TypeError, ValueError):
        fail("build metadata does not contain a valid package size")
    if metadata_size != actual_size:
        fail(
            f"build metadata size is {metadata_size}, but the downloaded package is "
            f"{actual_size} bytes"
        )


def verify_checksum_manifest(text: str, *, package_name: str, actual_sha256: str) -> None:
    """Require exactly one correctly-named sha256sum entry for this platform package."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        fail("platform checksum manifest must contain exactly one package entry")
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", lines[0])
    if not match:
        fail("platform checksum manifest has an invalid sha256sum entry")
    manifest_digest, manifest_name = match.groups()
    if manifest_name != package_name:
        fail(
            f"checksum manifest names {manifest_name!r}, expected {package_name!r}"
        )
    if manifest_digest.lower() != actual_sha256.lower():
        fail("checksum manifest SHA-256 does not match the downloaded package")


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
        package_url = assets[package_name].get("browser_download_url")
        if not package_url:
            fail(f"package asset has no download URL: {package_name}")
        actual_digest, actual_size = download_asset_sha256(package_url)

        published_size = assets[package_name].get("size")
        if published_size is not None and int(published_size) != actual_size:
            fail(f"GitHub asset size does not match downloaded package: {package_name}")

        # Newer GitHub release assets expose a server-computed digest. Validate
        # it when present, while retaining compatibility with older asset APIs.
        github_digest = assets[package_name].get("digest")
        if github_digest:
            expected_github_digest = "sha256:" + actual_digest
            if str(github_digest).lower() != expected_github_digest:
                fail(f"GitHub's asset digest does not match downloaded package: {package_name}")

        verify_metadata(
            metadata,
            version=version,
            target=target,
            source_commit=source_commit,
            actual_sha256=actual_digest,
            actual_size=actual_size,
        )

        checksum_url = assets[checksum_name].get("browser_download_url")
        if not checksum_url:
            fail(f"checksum manifest has no download URL: {checksum_name}")
        checksum_text = read_public_asset(checksum_url)
        verify_checksum_manifest(
            checksum_text,
            package_name=package_name,
            actual_sha256=actual_digest,
        )
        print(
            f"PASS {target}: downloaded package SHA-256, size, manifest, "
            "metadata, and source commit verified"
        )

    print(f"PASS {args.tag}: all four desktop targets use source commit {source_commit}")
    print("The release is ready for a human to review and publish.")


if __name__ == "__main__":
    main()
