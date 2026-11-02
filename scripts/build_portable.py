#!/usr/bin/env python3
"""Build self-contained Linux and macOS JARVIS installer packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as helpers  # noqa: E402

BUILD, STAGE, DIST, INSTALLER = helpers.BUILD, helpers.STAGE, helpers.DIST, helpers.INSTALLER
PYTHON_BUILD_RELEASE = "20261021"
PYTHON_BUILD_VERSION = "3.12.15"
RUNTIMES = {
    "linux-x86_64": {
        "file": "cpython-3.12.15+20261021-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
        "sha256": "6d7521138fd33afddc1ccd08abb007d9a2829e38117c2576f9efdc0ec73ce772",
        "output": "MARK-LV-Linux-x86_64.tar.gz",
    },
    "macos-arm64": {
        "file": "cpython-3.12.15+20261021-aarch64-apple-darwin-install_only_stripped.tar.gz",
        "sha256": "7b8d00b751db21cea87dc551a8f8165147c5fbc5251d5537d7e5497dde00a219",
        "output": "MARK-LV-macOS-arm64.dmg",
    },
    "macos-x86_64": {
        "file": "cpython-3.12.15+20261021-x86_64-apple-darwin-install_only_stripped.tar.gz",
        "sha256": "f12e0504397683d6be0745ffd4c39ef45a455cec169adf35c628840d06133773",
        "output": "MARK-LV-macOS-x86_64.dmg",
    },
}

LINUX_INSTALLER = r'''#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_ROOT="$HOME/.local/share/Programs/MARK-LV"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
STAGING="${INSTALL_ROOT}.new.$$"
TX_ID=""
RECOVERY_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mark56/update-recovery"

echo "JARVIS / MARK 56 — Linux installer"
echo "Install location: $INSTALL_ROOT"
OLD_PYTHON="$INSTALL_ROOT/runtime/bin/python3.12"
OLD_CLI="$INSTALL_ROOT/core/update_recovery_cli.py"
if [ ! -e "$INSTALL_ROOT" ] || [ ! -x "$OLD_PYTHON" ] || [ ! -f "$OLD_CLI" ] || ! "$OLD_PYTHON" --version >/dev/null 2>&1; then
  RECOVERY_TX_ID="$(cat "$RECOVERY_DIR/latest.txt" 2>/dev/null || true)"
  RECOVERY_BACKUP="$RECOVERY_DIR/$RECOVERY_TX_ID/backup"
  if [ -n "$RECOVERY_TX_ID" ] && [ -x "$RECOVERY_BACKUP/runtime/bin/python3.12" ]; then
    "$RECOVERY_BACKUP/runtime/bin/python3.12" "$RECOVERY_BACKUP/core/update_recovery_cli.py" --rollback-id "$RECOVERY_TX_ID"
  fi
fi
if [ -d "$INSTALL_ROOT" ] && [ -x "$INSTALL_ROOT/runtime/bin/python3.12" ] && [ -f "$INSTALL_ROOT/core/update_recovery_cli.py" ]; then
  PREPARE_JSON="$("$INSTALL_ROOT/runtime/bin/python3.12" "$INSTALL_ROOT/core/update_recovery_cli.py" --prepare "$INSTALL_ROOT")"
  TX_ID="$(printf '%s' "$PREPARE_JSON" | "$INSTALL_ROOT/runtime/bin/python3.12" -c 'import json,sys; print(json.load(sys.stdin)["transaction_id"])')"
  echo "Created and verified local recovery snapshot: $TX_ID"
elif [ -e "$INSTALL_ROOT" ]; then
  echo "Existing installation has no usable recovery runtime; refusing an unsafe in-place upgrade." >&2
  exit 1
fi

rollback_on_error() {
  status=$?
  trap - ERR
  if [ -n "$TX_ID" ]; then
    BACKUP="$RECOVERY_DIR/$TX_ID/backup"
    BACKUP_PYTHON="$BACKUP/runtime/bin/python3.12"
    if [ -x "$BACKUP_PYTHON" ]; then
      echo "Installation failed; restoring the previous Mark 56 version..."
      "$BACKUP_PYTHON" "$BACKUP/core/update_recovery_cli.py" --rollback-id "$TX_ID" || {
        echo "Automatic rollback could not finish. Recovery data remains at: $RECOVERY_DIR/$TX_ID" >&2
      }
    else
      echo "Recovery runtime missing. Backup retained at: $BACKUP" >&2
    fi
  fi
  rm -rf "$STAGING"
  exit "$status"
}
trap rollback_on_error ERR

mkdir -p "$STAGING" "$BIN_DIR" "$APP_DIR"
cp -a "$SOURCE_DIR/." "$STAGING/"
if [ -n "$TX_ID" ]; then
  if [ -d "$INSTALL_ROOT/config" ]; then
    mkdir -p "$STAGING/config"
    cp -a "$INSTALL_ROOT/config/." "$STAGING/config/"
  fi
  for data_dir in memory cache uploads; do
    if [ -e "$INSTALL_ROOT/$data_dir" ]; then
      rm -rf "$STAGING/$data_dir"
      cp -a "$INSTALL_ROOT/$data_dir" "$STAGING/$data_dir"
    fi
  done
  if [ -d "$INSTALL_ROOT/plugins" ]; then
    mkdir -p "$STAGING/plugins"
    BACKUP_ROOT="$RECOVERY_DIR/$TX_ID/backup"
    "$BACKUP_ROOT/runtime/bin/python3.12" - "$INSTALL_ROOT/plugins" "$STAGING/plugins" <<'PY'
import os, shutil, sys
source, destination = sys.argv[1:3]
for current, directories, files in os.walk(source, followlinks=False):
    relative = os.path.relpath(current, source)
    target_dir = destination if relative == "." else os.path.join(destination, relative)
    os.makedirs(target_dir, exist_ok=True)
    for name in list(directories):
        src = os.path.join(current, name)
        dst = os.path.join(target_dir, name)
        if os.path.islink(src):
            directories.remove(name)
            if not os.path.lexists(dst):
                os.symlink(os.readlink(src), dst)
        else:
            os.makedirs(dst, exist_ok=True)
    for name in files:
        src = os.path.join(current, name)
        dst = os.path.join(target_dir, name)
        if not os.path.lexists(dst):
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            else:
                shutil.copy2(src, dst)
PY
  fi
  FAILED="$(dirname "$INSTALL_ROOT")/.$(basename "$INSTALL_ROOT").failed-$TX_ID"
  mv "$INSTALL_ROOT" "$FAILED"
  mv "$STAGING" "$INSTALL_ROOT"
  NEW_PYTHON="$INSTALL_ROOT/runtime/bin/python3.12"
  "$NEW_PYTHON" "$INSTALL_ROOT/core/update_recovery_cli.py" --mark-awaiting
  rm -rf "$FAILED"
else
  mv "$STAGING" "$INSTALL_ROOT"
fi

chmod +x "$INSTALL_ROOT/launch.sh"
cat > "$BIN_DIR/mark56" <<LAUNCHER
#!/usr/bin/env bash
RECOVERY_DIR="$RECOVERY_DIR"
if [ ! -x "$INSTALL_ROOT/launch.sh" ] || [ ! -x "$INSTALL_ROOT/runtime/bin/python3.12" ] || ! "$INSTALL_ROOT/runtime/bin/python3.12" --version >/dev/null 2>&1; then
  TX_ID="\$(cat "\$RECOVERY_DIR/latest.txt" 2>/dev/null || true)"
  BACKUP="\$RECOVERY_DIR/\$TX_ID/backup"
  if [ -n "\$TX_ID" ] && [ -x "\$BACKUP/runtime/bin/python3.12" ]; then
    "\$BACKUP/runtime/bin/python3.12" "\$BACKUP/core/update_recovery_cli.py" --rollback-id "\$TX_ID" || exit 1
  else
    echo "Mark 56 cannot start and no usable recovery backup was found." >&2
    exit 1
  fi
fi
exec "$INSTALL_ROOT/launch.sh" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/mark56"
desktop_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/ /\\ /g; s/&/\\&/g'; }
EXEC_PATH="$(desktop_escape "$BIN_DIR/mark56")"
ICON_PATH="$(desktop_escape "$INSTALL_ROOT/config/jarvis.png")"
cat > "$APP_DIR/mark56.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=JARVIS (Mark 56)
Comment=Personal desktop AI assistant
Exec=$EXEC_PATH
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Development;
DESKTOP

if [ "${JARVIS_INSTALL_SYSTEM_LIBS:-0}" = "1" ] && command -v apt-get >/dev/null 2>&1; then
  packages="libasound2 libpulse0 libegl1 libgl1 libportaudio2 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-xkb1 libxkbcommon-x11-0"
  if [ "$(id -u)" -eq 0 ]; then apt-get update && apt-get install -y $packages
  elif command -v sudo >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y $packages
  else echo "sudo unavailable; install desktop/audio libraries with your package manager." >&2
  fi
fi

trap - ERR
echo "Installation complete. Launch from the applications menu or run: $BIN_DIR/mark56"
'''
LINUX_LAUNCHER = r'''#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$APP_DIR/runtime/bin/python3.12"
if [ ! -x "$PYTHON" ]; then echo "JARVIS runtime is missing: $PYTHON" >&2; exit 1; fi
exec "$PYTHON" "$APP_DIR/launcher.pyw" "$@"
'''
LINUX_README = """JARVIS / MARK 56 — Linux installer bundle

1. Extract this archive.
2. Open a terminal in the extracted MARK-LV-Linux-x86_64 folder.
3. Run: bash install.sh
4. Launch JARVIS from your applications menu or run: ~/.local/bin/mark56

The bundle includes Python and its Python dependencies. Online AI features need
internet access and your own provider API key. Some Linux audio/Qt features need
native system libraries. Ubuntu/Debian users can run:
  JARVIS_INSTALL_SYSTEM_LIBS=1 bash install.sh
This can call sudo to install system libraries.

Only install software downloaded from the official Mark-56 GitHub Release.
"""
MAC_README = """JARVIS / MARK 56 — macOS installer

1. Open this disk image.
2. Control-click Install.command and choose Open if Gatekeeper asks.
3. The installer places JARVIS.app in ~/Applications. On upgrades it creates
   and verifies a local backup, preserves user data, and swaps the app bundle.
4. Launch JARVIS from Applications and grant privacy permissions only for
   features you intend to use.

Use Install.command for upgrades; manually dragging the app bypasses the
automatic backup and rollback workflow.

This package is not signed or notarized with an Apple Developer ID. macOS may
show a security warning. Verify the DMG came from the official Mark-56 GitHub
Releases page before opening it. Apple silicon and Intel have separate builds.
Online AI features need internet access and your own provider key.
"""

MAC_INSTALLER = r'''#!/bin/bash
set -Eeuo pipefail
if [ "${JARVIS_INSTALLER_DEBUG:-0}" = "1" ]; then set -x; fi
SOURCE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_APP="$SOURCE_DIR/JARVIS.app"
APPLICATIONS="$HOME/Applications"
TARGET="$APPLICATIONS/JARVIS.app"
STAGING="$APPLICATIONS/.JARVIS.app.new.$$"
RECOVERY_DIR="$HOME/Library/Application Support/MARK-LV/update-recovery"
TX_ID=""

echo "JARVIS / MARK 56 — macOS installer"
mkdir -p "$APPLICATIONS"

rollback_on_error() {
  status=$?
  trap - ERR
  if [ -n "$TX_ID" ]; then
    BACKUP="$RECOVERY_DIR/$TX_ID/backup"
    BACKUP_ROOT="$BACKUP/Contents/Resources/MARK-LV"
    BACKUP_PYTHON="$BACKUP_ROOT/runtime/bin/python3.12"
    if [ -x "$BACKUP_PYTHON" ]; then
      echo "Installation failed; restoring the previous JARVIS application..."
      "$BACKUP_PYTHON" "$BACKUP_ROOT/core/update_recovery_cli.py" --rollback-id "$TX_ID" || {
        echo "Automatic rollback failed. Recovery backup retained at: $BACKUP" >&2
      }
    else
      echo "Recovery runtime missing. Backup retained at: $BACKUP" >&2
    fi
  fi
  rm -rf "$STAGING"
  exit "$status"
}
trap rollback_on_error ERR

if [ ! -d "$TARGET" ]; then
  RECOVERY_TX_ID="$(cat "$RECOVERY_DIR/latest.txt" 2>/dev/null || true)"
  RECOVERY_BACKUP="$RECOVERY_DIR/$RECOVERY_TX_ID/backup"
  RECOVERY_ROOT="$RECOVERY_BACKUP/Contents/Resources/MARK-LV"
  if [ -n "$RECOVERY_TX_ID" ] && [ -x "$RECOVERY_ROOT/runtime/bin/python3.12" ]; then
    "$RECOVERY_ROOT/runtime/bin/python3.12" "$RECOVERY_ROOT/core/update_recovery_cli.py" --rollback-id "$RECOVERY_TX_ID"
  fi
  if [ "${JARVIS_RECOVERY_ONLY:-0}" = "1" ]; then
    exit 0
  fi
fi

if [ -d "$TARGET" ]; then
  CURRENT_ROOT="$TARGET/Contents/Resources/MARK-LV"
  CURRENT_PYTHON="$CURRENT_ROOT/runtime/bin/python3.12"
  CURRENT_CLI="$CURRENT_ROOT/core/update_recovery_cli.py"
  if [ ! -x "$CURRENT_PYTHON" ] || [ ! -f "$CURRENT_CLI" ] || ! "$CURRENT_PYTHON" --version >/dev/null 2>&1; then
    RECOVERY_TX_ID="$(cat "$RECOVERY_DIR/latest.txt" 2>/dev/null || true)"
    RECOVERY_BACKUP="$RECOVERY_DIR/$RECOVERY_TX_ID/backup"
    RECOVERY_ROOT="$RECOVERY_BACKUP/Contents/Resources/MARK-LV"
    if [ -n "$RECOVERY_TX_ID" ] && [ -x "$RECOVERY_ROOT/runtime/bin/python3.12" ]; then
      "$RECOVERY_ROOT/runtime/bin/python3.12" "$RECOVERY_ROOT/core/update_recovery_cli.py" --rollback-id "$RECOVERY_TX_ID"
    else
      echo "The installed JARVIS runtime is damaged and no usable recovery backup was found." >&2
      exit 1
    fi
  fi
fi

if [ -d "$TARGET" ]; then
  OLD_ROOT="$TARGET/Contents/Resources/MARK-LV"
  OLD_PYTHON="$OLD_ROOT/runtime/bin/python3.12"
  OLD_CLI="$OLD_ROOT/core/update_recovery_cli.py"
  if [ ! -x "$OLD_PYTHON" ] || [ ! -f "$OLD_CLI" ]; then
    echo "Existing JARVIS installation has no usable recovery runtime. Refusing an unsafe upgrade." >&2
    exit 1
  fi
  PREPARE_JSON="$("$OLD_PYTHON" "$OLD_CLI" --prepare "$TARGET")"
  TX_ID="$(printf '%s' "$PREPARE_JSON" | "$OLD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["transaction_id"])')"
  echo "Created and verified local recovery snapshot: $TX_ID"
fi

ditto "$SOURCE_APP" "$STAGING"
if [ -n "$TX_ID" ]; then
  OLD_ROOT="$TARGET/Contents/Resources/MARK-LV"
  NEW_ROOT="$STAGING/Contents/Resources/MARK-LV"
  if [ -d "$OLD_ROOT/config" ]; then
    mkdir -p "$NEW_ROOT/config"
    cp -R "$OLD_ROOT/config/." "$NEW_ROOT/config/"
  fi
  for data_dir in memory cache uploads; do
    if [ -e "$OLD_ROOT/$data_dir" ]; then
      rm -rf "$NEW_ROOT/$data_dir"
      ditto "$OLD_ROOT/$data_dir" "$NEW_ROOT/$data_dir"
    fi
  done
  if [ -d "$OLD_ROOT/plugins" ]; then
    mkdir -p "$NEW_ROOT/plugins"
    BACKUP_ROOT="$RECOVERY_DIR/$TX_ID/backup/Contents/Resources/MARK-LV"
    "$BACKUP_ROOT/runtime/bin/python3.12" - "$OLD_ROOT/plugins" "$NEW_ROOT/plugins" <<'PY'
import os, shutil, sys
source, destination = sys.argv[1:3]
for current, directories, files in os.walk(source, followlinks=False):
    relative = os.path.relpath(current, source)
    target_dir = destination if relative == "." else os.path.join(destination, relative)
    os.makedirs(target_dir, exist_ok=True)
    for name in list(directories):
        src = os.path.join(current, name)
        dst = os.path.join(target_dir, name)
        if os.path.islink(src):
            directories.remove(name)
            if not os.path.lexists(dst):
                os.symlink(os.readlink(src), dst)
        else:
            os.makedirs(dst, exist_ok=True)
    for name in files:
        src = os.path.join(current, name)
        dst = os.path.join(target_dir, name)
        if not os.path.lexists(dst):
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            else:
                shutil.copy2(src, dst)
PY
  fi
  FAILED="$APPLICATIONS/.JARVIS.app.failed-$TX_ID"
  mv "$TARGET" "$FAILED"
  mv "$STAGING" "$TARGET"
  NEW_ROOT="$TARGET/Contents/Resources/MARK-LV"
  "$NEW_ROOT/runtime/bin/python3.12" "$NEW_ROOT/core/update_recovery_cli.py" --mark-awaiting
  rm -rf "$FAILED"
else
  mv "$STAGING" "$TARGET"
fi

trap - ERR
echo "JARVIS installed at: $TARGET"
if [ "${JARVIS_INSTALLER_NO_LAUNCH:-0}" != "1" ]; then
  open -a "$TARGET"
fi
'''


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_runtime(target: str) -> Path:
    cfg = RUNTIMES[target]
    url = (
        f"https://github.com/astral-sh/python-build-standalone/releases/download/"
        f"{PYTHON_BUILD_RELEASE}/{cfg['file'].replace('+', '%2B')}"
    )
    archive = BUILD / "cache" / cfg["file"]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file() or sha256(archive) != cfg["sha256"]:
        archive.unlink(missing_ok=True)
        temp = archive.with_suffix(archive.suffix + ".part")
        temp.unlink(missing_ok=True)
        print(f"  downloading Python runtime: {cfg['file']}")
        urllib.request.urlretrieve(url, temp)
        actual = sha256(temp)
        if actual.lower() != cfg["sha256"].lower():
            temp.unlink(missing_ok=True)
            helpers.die(f"Python runtime SHA-256 mismatch: expected {cfg['sha256']}, got {actual}")
        temp.replace(archive)

    extracted = BUILD / f"runtime-extract-{target}"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(extracted, filter="data")
    source = extracted / "python"
    if not (source / "bin" / "python3.12").is_file():
        helpers.die(f"unexpected runtime archive layout for {target}: python/bin/python3.12 is missing")
    runtime = STAGE / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(source, runtime)
    shutil.rmtree(extracted, ignore_errors=True)
    return runtime / "bin" / "python3.12"


def make_png_icon(python: Path) -> None:
    src, dest = STAGE / "config" / "jarvis.ico", STAGE / "config" / "jarvis.png"
    converter = r"""
import sys
from pathlib import Path
from PIL import Image
with Image.open(Path(sys.argv[1])) as original:
    image = original.convert("RGBA")
    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    image.save(Path(sys.argv[2]), format="PNG", optimize=True)
"""
    helpers.run([python, "-c", converter, src, dest])


def make_macos_app(python: Path, version: str, arch: str) -> Path:
    dmg_root = BUILD / f"macos-dmg-{arch}"
    if dmg_root.exists():
        shutil.rmtree(dmg_root)
    app = dmg_root / "JARVIS.app"
    contents, resources, macos = app / "Contents", app / "Contents" / "Resources", app / "Contents" / "MacOS"
    resources.mkdir(parents=True)
    macos.mkdir(parents=True)
    shutil.copytree(STAGE, resources / "MARK-LV")

    iconset = BUILD / f"Jarvis-{arch}.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    icon_script = r"""
import sys
from pathlib import Path
from PIL import Image
src, out = Path(sys.argv[1]), Path(sys.argv[2])
with Image.open(src) as original:
    image = original.convert("RGBA")
    for size in (16, 32, 128, 256, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(out / f"icon_{size}x{size}.png", optimize=True)
        if size < 512:
            image.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(out / f"icon_{size}x{size}@2x.png", optimize=True)
    image.resize((1024, 1024), Image.Resampling.LANCZOS).save(out / "icon_512x512@2x.png", optimize=True)
"""
    helpers.run([python, "-c", icon_script, STAGE / "config" / "jarvis.ico", iconset])
    helpers.run(["iconutil", "-c", "icns", "-o", resources / "Jarvis.icns", iconset])
    shutil.rmtree(iconset, ignore_errors=True)

    executable = macos / "JARVIS"
    executable.write_text(
        "#!/bin/sh\nset -eu\n"
        'APP_ROOT="$(cd "$(dirname "$0")/../Resources/MARK-LV" && pwd)"\n'
        'PYTHON="$APP_ROOT/runtime/bin/python3.12"\n'
        'LOG_DIR="$HOME/Library/Logs/MARK-LV"\n'
        'mkdir -p "$LOG_DIR"\n'
        'if [ ! -x "$PYTHON" ]; then echo "JARVIS Python runtime missing: $PYTHON" >&2; exit 1; fi\n'
        'exec "$PYTHON" "$APP_ROOT/launcher.pyw" "$@" >> "$LOG_DIR/launcher.log" 2>&1\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    info = {
        "CFBundleName": "JARVIS",
        "CFBundleDisplayName": "JARVIS",
        "CFBundleIdentifier": "com.mark56.jarvis",
        "CFBundleVersion": version,
        "CFBundleShortVersionString": version,
        "CFBundleExecutable": "JARVIS",
        "CFBundleIconFile": "Jarvis.icns",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "JARVIS uses the microphone when you choose voice interaction.",
        "NSCameraUsageDescription": "JARVIS uses the camera when you activate a vision feature.",
        "NSScreenCaptureUsageDescription": "JARVIS captures screen content only when you activate a screen-aware feature.",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    (dmg_root / "READ-ME-FIRST.txt").write_text(MAC_README, encoding="utf-8")
    installer_script = dmg_root / "Install.command"
    installer_script.write_text(MAC_INSTALLER, encoding="utf-8")
    installer_script.chmod(0o755)
    (dmg_root / "Applications").symlink_to("/Applications", target_is_directory=True)
    return dmg_root


def build(target: str, version: str) -> None:
    if target not in RUNTIMES:
        helpers.die(f"unsupported target: {target}")
    machine = platform.machine().lower()
    expected = "aarch64" if target == "macos-arm64" else "x86_64"
    aliases = {expected}
    if expected == "aarch64":
        aliases.add("arm64")
    if machine not in aliases:
        helpers.die(f"runner architecture mismatch for {target}: machine={machine}")
    if target == "linux-x86_64" and sys.platform != "linux":
        helpers.die("linux-x86_64 must be built on Linux")
    if target.startswith("macos-") and sys.platform != "darwin":
        helpers.die(f"{target} must be built on macOS")

    helpers.step(1, "stage clean application source")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    helpers.stage_source()
    (STAGE / "VERSION").write_text(version + "\n", encoding="utf-8")

    helpers.step(2, "scan staged source for secrets")
    hits = helpers.scan_for_secrets(STAGE)
    if hits:
        helpers.die("secrets found in staged files:\n    " + "\n    ".join(hits))
    print("  clean: no keys, tokens or private keys in the package")

    helpers.step(3, "install self-contained Python runtime")
    python = install_runtime(target)
    helpers.run([python, "--version"])
    helpers.run([python, "-m", "pip", "--version"])
    requirements = helpers.merged_requirements()
    helpers.run([
        python, "-m", "pip", "install", "--disable-pip-version-check",
        "--no-cache-dir", "--prefer-binary", "-r", requirements,
    ])

    helpers.step(4, "smoke-test bundled runtime")
    smoke_command = [python, INSTALLER / "smoke_test.py", STAGE]
    if target == "linux-x86_64":
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            helpers.die("xvfb-run is required for the headless Linux smoke test")
        smoke_command = [xvfb, "-a", *smoke_command]
    helpers.run(smoke_command)
    make_png_icon(python)

    if target == "linux-x86_64":
        helpers.step(5, "prepare Linux installer bundle")
        (STAGE / "launch.sh").write_text(LINUX_LAUNCHER, encoding="utf-8")
        (STAGE / "install.sh").write_text(LINUX_INSTALLER, encoding="utf-8")
        (STAGE / "README-INSTALL.txt").write_text(LINUX_README, encoding="utf-8")
        (STAGE / "launch.sh").chmod(0o755)
        (STAGE / "install.sh").chmod(0o755)
        if DIST.exists():
            shutil.rmtree(DIST)
        DIST.mkdir(parents=True)
        output = DIST / RUNTIMES[target]["output"]
        with tarfile.open(output, "w:gz") as archive:
            archive.add(STAGE, arcname="MARK-LV-Linux-x86_64")
    else:
        helpers.step(5, "prepare macOS app and disk image")
        dmg_root = make_macos_app(python, version, target.removeprefix("macos-"))
        if DIST.exists():
            shutil.rmtree(DIST)
        DIST.mkdir(parents=True)
        output = DIST / RUNTIMES[target]["output"]
        label = f"JARVIS {version} {target.removeprefix('macos-')}"
        helpers.run(["hdiutil", "create", "-volname", label, "-srcfolder", dmg_root, "-ov", "-format", "UDZO", output])

    if not output.is_file() or output.stat().st_size < 10_000_000:
        helpers.die(f"installer output missing or unexpectedly small: {output}")
    digest = sha256(output)
    info = {
        "version": version,
        "target": target,
        "source_commit": helpers.os.environ.get("GITHUB_SHA", ""),
        "python": PYTHON_BUILD_VERSION,
        "sha256": digest,
        "size": output.stat().st_size,
        "signed": False if target.startswith("macos-") else None,
    }
    (DIST / f"build-info-{target}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    (DIST / f"SHA256SUMS-{target}.txt").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"\nBUILD OK: {output} ({output.stat().st_size / 1_000_000:.1f} MB)")
    print(f"SHA-256: {digest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(RUNTIMES), required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    parts = args.version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        helpers.die("version must be MAJOR.MINOR.PATCH, e.g. 56.0.0")
    build(args.target, args.version)


if __name__ == "__main__":
    main()
