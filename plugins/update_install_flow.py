"""Explicit-consent handoff for a previously checksum-verified Mark 56 update.

This module intentionally does not pretend that opening an installer is the
same as completing an installation. Windows setup can be launched after consent.
Linux archives and macOS disk images are opened for a user-driven install because
the current release artifacts do not define a signed, transactional installer
contract with a reliable rollback hook.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass

from plugins.update_installer import PreparedUpdate


@dataclass(frozen=True)
class InstallHandoff:
    status: str
    message: str
    path: str
    requires_user_action: bool = True


def handoff_to_installer(update: PreparedUpdate, *, user_confirmed: bool) -> InstallHandoff:
    """Hand off a verified package only after explicit user consent."""
    if user_confirmed is not True:
        return InstallHandoff(
            "cancelled",
            "Installation was not started because confirmation was not provided.",
            update.file_path,
        )

    path = Path(update.file_path).resolve()
    if not path.is_file() or path.name != update.asset_name:
        raise ValueError("The staged installer is missing or its filename does not match the verified update.")
    # Refuse unexpected extensions and OS/package mismatches.
    system = platform.system()
    suffixes = {
        "Windows": (".exe",),
        "Linux": (".gz",),
        "Darwin": (".dmg",),
    }.get(system, ())
    if not suffixes or path.suffix.lower() not in suffixes:
        raise RuntimeError(f"Unsupported installer package for {system}.")

    if system == "Windows":
        if path.name != f"MARK-LV-Setup-{update.version}.exe":
            raise ValueError("Windows installer version does not match the verified release.")
        # Launch only the exact verified path, without a shell. Installer may
        # request UAC through its own signed setup flow.
        process = subprocess.Popen([str(path)], shell=False)
        return InstallHandoff(
            "installer_started",
            f"Windows setup launched for Mark 56 {update.version}. Follow the setup prompts. The app cannot confirm success until setup finishes and the app is relaunched.",
            str(path),
            True,
        )

    if system == "Linux":
        if path.name != "MARK-LV-Linux-x86_64.tar.gz":
            raise ValueError("Linux archive does not match the supported package name.")
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("No desktop opener (xdg-open) is available. The verified archive is saved and can be installed manually.")
        subprocess.Popen([opener, str(path)], shell=False)
        return InstallHandoff(
            "manual_install_required",
            "The verified Linux archive has been opened for manual installation. No files were replaced, and rollback is not needed because this helper does not modify the existing installation.",
            str(path),
            True,
        )

    if system == "Darwin":
        if path.name not in {"MARK-LV-macOS-arm64.dmg", "MARK-LV-macOS-x86_64.dmg"}:
            raise ValueError("macOS disk image name is not supported.")
        expected_arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        if f"macOS-{expected_arch}.dmg" not in path.name:
            raise RuntimeError("The staged macOS package does not match this machine's architecture.")
        subprocess.Popen(["open", str(path)], shell=False)
        return InstallHandoff(
            "manual_install_required",
            "The verified disk image has been opened. Follow its installation instructions. JARVIS has not replaced the running app and cannot verify completion automatically.",
            str(path),
            True,
        )

    raise RuntimeError(f"Automatic installer handoff is not supported on {system}.")
