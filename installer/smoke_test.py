"""Packaging smoke test — run with the BUNDLED interpreter against the staged app.

    runtime\\python.exe installer\\smoke_test.py <app_dir>       (full)

    python installer/smoke_test.py <app_dir> --static            (any machine)

Checks, in order:

  1. every application .py file compiles
  2. shipped resources exist (prompt, face mesh, icon, dashboard pages)
  3. no secrets / personal data were staged
  4. (full only) every required third-party module can be imported
     by the bundled interpreter
  5. application-source imports are checked for missing providers

The bundled runtime itself is deliberately excluded from source scanning.
Its job is to provide the Python interpreter and installed dependencies;
its site-packages contain tests, examples, compatibility modules, and
platform-specific files that are not MARK LV application source.

Exit code 0 = pass, 1 = at least one hard failure.
"""

import ast
import importlib
import importlib.util
import os
import sys
from pathlib import Path


# Qt must not need a display just to be imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Must import, or the app is broken at launch / in a core feature.
REQUIRED = [
    "PyQt6.QtWidgets",
    "PyQt6.QtMultimedia",
    "sounddevice",
    "numpy",
    "google.genai",
    "requests",
    "bs4",
    "playwright",
    "yt_dlp",
    "pyautogui",
    "pyperclip",
    "PIL",
    "cv2",
    "mss",
    "psutil",
    "send2trash",
    "pptx",
    "fastapi",
    "uvicorn",
    "cryptography",
    "multipart",
    "qrcode",
    "openpyxl",
    "edge_tts",
    "faster_whisper",
    "soundfile",
    "miniaudio",
    "ddgs",
    "pdfplumber",
    "PyPDF2",
    "docx",
    "pynvml",
    "pygetwindow",
    "googleapiclient",
    "google_auth_oauthlib",
    "msal",
    "youtube_transcript_api",
    "tinytuya",
    "paho.mqtt.client",
]

REQUIRED_WINDOWS = [
    "comtypes",
    "pycaw",
    "win10toast",
    "win32com.client",
    "wmi",
    "pywinauto",
]


# Imported by the code but deliberately NOT bundled
# (heavy / opt-in / self-installing).
OPTIONAL = {
    "torch",
    "kokoro",
    "vosk",
    "openwakeword",
    "pandas",
    "pydub",
    "pytesseract",
    "duckduckgo_search",
    "providers",
}


RESOURCES = [
    "main.py",
    "ui.py",
    "launcher.pyw",
    "VERSION",
    "LICENSE",
    "core/prompt.txt",
    "core/face_model.obj",
    "plugins/game_autoplay.py",
    "plugins/game_updater.py",
    "plugins/wayland_screencast.py",
    "plugins/website_studio_setup.py",
    "config/jarvis.ico",
    "dashboard/static/app.html",
    "dashboard/static/login.html",
]


FORBIDDEN = [
    "config/api_keys.json",
    "config/certs",
    "config/whatsapp_web",
    "memory/long_term.json",
    ".git",
    ".vscode",
]


# Directories that are part of the bundled environment rather than
# MARK LV application source. These must not be treated as application
# source during the static source scan.
EXCLUDED_SOURCE_DIRS = {
    "runtime",
    "__pycache__",
}


failures = []
warnings = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        failures.append(f"FAIL {msg}")
        print(f"FAIL {msg}")


def is_excluded_path(path, root):
    """Return True when a path belongs to a non-application directory."""
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return False

    return any(part in EXCLUDED_SOURCE_DIRS for part in relative_parts)


def py_files(root):
    """Return only MARK LV application Python source files.

    The bundled runtime is intentionally excluded because it contains
    third-party site-packages, tests, examples, and platform-specific
    compatibility modules that are not part of MARK LV.
    """
    result = []

    for p in root.rglob("*.py*"):
        if p.suffix not in (".py", ".pyw"):
            continue

        if is_excluded_path(p, root):
            continue

        result.append(p)

    return result


def application_directories(root):
    """Return application directories, excluding the bundled runtime."""
    result = set()

    for d in root.iterdir():
        if d.is_dir() and d.name not in EXCLUDED_SOURCE_DIRS:
            result.add(d.name)

    return result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    static = "--static" in sys.argv

    if not args:
        sys.exit(__doc__)

    app = Path(args[0]).resolve()

    print(
        f"Smoke test: {app} "
        f"({'static' if static else 'full'}) "
        f"Python {sys.version.split()[0]}"
    )

    print("\n[1] compile every application source file")

    files = py_files(app)
    bad = 0

    for p in files:
        try:
            compile(
                p.read_bytes(),
                str(p),
                "exec",
            )
        except SyntaxError as e:
            bad += 1
            failures.append(
                f"syntax error in {p.relative_to(app)}: {e}"
            )

    check(
        bad == 0,
        f"{len(files)} application files compile",
    )

    print("\n[2] shipped resources")

    for r in RESOURCES:
        check(
            (app / r).exists(),
            r,
        )

    face = app / "core" / "face_model.obj"

    check(
        face.exists() and face.stat().st_size > 4096,
        "face_model.obj is complete (>4 KB)",
    )

    print("\n[3] nothing private was staged")

    for f in FORBIDDEN:
        check(
            not (app / f).exists(),
            f"absent: {f}",
        )

    if static:
        return finish()

    print("\n[4] bundled interpreter can import every required module")

    mods = REQUIRED + (
        REQUIRED_WINDOWS if os.name == "nt" else []
    )

    for m in mods:
        try:
            importlib.import_module(m)
            print(f"  ok   {m}")

        except Exception as e:  # noqa: BLE001
            failures.append(
                f"cannot import {m}: "
                f"{type(e).__name__}: {e}"
            )

            print(
                f"FAIL {m}: "
                f"{type(e).__name__}: {e}"
            )

    print("\n[5] application imports that nothing provides")

    std = set(sys.stdlib_module_names)

    # Only application directories count as local modules.
    # The bundled runtime is deliberately excluded.
    local = (
        {p.stem for p in files}
        | application_directories(app)
    )

    seen = {}

    for p in files:
        try:
            tree = ast.parse(
                p.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

        except SyntaxError:
            continue

        for n in ast.walk(tree):
            names = []

            if isinstance(n, ast.Import):
                names = [
                    a.name.split(".")[0]
                    for a in n.names
                ]

            elif (
                isinstance(n, ast.ImportFrom)
                and n.level == 0
                and n.module
            ):
                names = [
                    n.module.split(".")[0]
                ]

            for m in names:
                if m not in std and m not in local:
                    seen.setdefault(
                        m,
                        p.name,
                    )

    unknown = []

    for m, where in sorted(seen.items()):
        try:
            found = (
                importlib.util.find_spec(m)
                is not None
            )
        except Exception:
            found = False

        # These imports are used only by the Linux Wayland screen-capture
        # backend. They are intentionally absent from the Windows runtime and
        # must not make a Windows installer fail its source-import audit.
        windows_only_missing_ok = (
            os.name == "nt"
            and m in {"dbus_next", "gi"}
        )

        if (
            not found
            and m not in OPTIONAL
            and not windows_only_missing_ok
            and not (
                m == "win32com"
                and os.name != "nt"
            )
        ):
            unknown.append(
                f"{m} (first seen in {where})"
            )

        elif not found:
            warnings.append(
                f"optional, not bundled: {m}"
            )

    check(
        not unknown,
        (
            "no unaccounted-for imports"
            if not unknown
            else
            "NOT PROVIDED: " + ", ".join(unknown)
        ),
    )

    return finish()


def finish():
    print()

    for w in warnings:
        print("  note", w)

    if failures:
        print(
            f"\nSMOKE TEST FAILED ({len(failures)}):"
        )

        for f in failures:
            print(f"  - {f}")

        return 1

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())