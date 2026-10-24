"""Explicit-consent handoff for a checksum-verified Mark 56 update."""
from __future__ import annotations
import hashlib
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from plugins.update_installer import PreparedUpdate

@dataclass(frozen=True)
class InstallHandoff:
    status: str
    message: str
    path: str
    requires_user_action: bool = True

def _verify_staged_file(update: PreparedUpdate) -> Path:
    """Re-check staged bytes immediately before opening or launching the package."""
    path = Path(update.file_path).resolve()
    if not path.is_file() or path.name != update.asset_name:
        raise ValueError("The staged installer is missing or its filename does not match the verified update.")
    expected = str(update.sha256 or "").lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("The staged update has no valid SHA-256 digest.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("The staged update changed after verification; it will not be opened.")
    return path

def handoff_to_installer(update: PreparedUpdate, *, user_confirmed: bool) -> InstallHandoff:
    """Hand off a verified package only after an explicit UI confirmation."""
    if user_confirmed is not True:
        return InstallHandoff("cancelled", "Installation was not started because confirmation was not provided.", str(update.file_path))
    path = _verify_staged_file(update)
    system = platform.system()
    if system == "Windows":
        if path.name != f"MARK-LV-Setup-{update.version}.exe":
            raise ValueError("Windows installer version does not match the verified release.")
        subprocess.Popen([str(path)], shell=False)
        return InstallHandoff("installer_started", f"Windows setup launched for Mark 56 {update.version}. Follow its prompts. This app cannot confirm installation succeeded until setup finishes and Mark 56 is relaunched.", str(path))
    if system == "Linux":
        if platform.machine().lower() not in {"x86_64", "amd64"}:
            raise RuntimeError("The published Linux package supports x86_64 only.")
        if path.name != "MARK-LV-Linux-x86_64.tar.gz":
            raise ValueError("Linux archive does not match the supported package name.")
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("xdg-open is unavailable. The verified archive remains saved for manual installation.")
        subprocess.Popen([opener, str(path)], shell=False)
        return InstallHandoff("manual_install_required", "The verified Linux archive was opened for manual installation. Mark 56 has not replaced its current files.", str(path))
    if system == "Darwin":
        if path.name not in {"MARK-LV-macOS-arm64.dmg", "MARK-LV-macOS-x86_64.dmg"}:
            raise ValueError("macOS disk image name is not supported.")
        machine = platform.machine().lower()
        expected_arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
        if path.name != f"MARK-LV-macOS-{expected_arch}.dmg":
            raise RuntimeError("The staged macOS package does not match this machine's architecture.")
        subprocess.Popen(["open", str(path)], shell=False)
        return InstallHandoff("manual_install_required", "The verified disk image was opened. Follow its installation instructions. Mark 56 has not confirmed installation or restart.", str(path))
    raise RuntimeError(f"Installer handoff is not supported on {system}.")
