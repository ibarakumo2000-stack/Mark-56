#!/usr/bin/env bash
# Complete Ubuntu bootstrap for the Mark 56 desktop application.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== JARVIS / Mark 56 Ubuntu setup =="
echo "Project: $ROOT"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer is for Ubuntu/Debian systems." >&2
  exit 1
fi

echo
echo "== Installing Ubuntu system libraries =="
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-dev build-essential \
  portaudio19-dev libportaudio2 libasound2-dev \
  libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-keysyms1 \
  libxcb-image0 libxcb-render-util0 libxcb-xkb1 libxkbcommon-x11-0 \
  libegl1 libgl1 ffmpeg tesseract-ocr xdg-utils \
  pulseaudio-utils brightnessctl bluez

if [[ ! -x ".venv/bin/python" ]]; then
  echo
  echo "== Creating project virtual environment =="
  python3 -m venv .venv
fi

PY="$ROOT/.venv/bin/python"

echo
echo "== Python version =="
"$PY" --version
"$PY" -m pip install --upgrade pip wheel

echo
echo "== Installing all declared Mark 56 application dependencies =="
"$PY" -m pip install -r requirements.txt

echo
echo "== Installing optional speech/runtime and packaged-app dependencies =="
"$PY" -m pip install -r installer/requirements-extra.txt

echo
echo "== Installing provider integrations and secure relay dependencies =="
"$PY" -m pip install -r requirements2.txt
"$PY" -m pip install -r relay/requirements.txt

echo
echo "== Installing Playwright browser engines =="
"$PY" -m playwright install chromium firefox

echo
echo "== Checking dependency consistency =="
"$PY" -m pip check

echo
echo "== Checking core runtime imports =="
"$PY" - <<'PY'
modules = (
    "PyQt6", "numpy", "sounddevice", "google.genai", "fastapi",
    "uvicorn", "cryptography", "qrcode", "bleak", "playwright",
    "faster_whisper", "msal",
)
failed = []
for name in modules:
    try:
        __import__(name)
        print(f"OK   {name}")
    except Exception as exc:
        failed.append((name, str(exc)))
        print(f"FAIL {name}: {exc}")
if failed:
    raise SystemExit(f"{len(failed)} required import checks failed")
PY

echo
echo "== Setup complete =="
echo "Launch JARVIS with:"
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  python3 main.py"
echo
echo "Note: speech recognition models and optional AI models may still download"
echo "the first time you enable/use those features; this script installs packages."
