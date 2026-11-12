"""Install the configured local Ollama vision model for the desktop task agent.

Run explicitly from the repository root:
    python3 scripts/setup_local_vision.py

The script never uploads screenshots and never configures a cloud fallback.
"""
from __future__ import annotations


def main() -> int:
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core import local_model

    settings = local_model._settings()
    model = str(settings.get("local_vision_model_name") or "").strip()
    if not model:
        print("ERROR: Set local_vision_model_name in config/local_model.json first.")
        return 2
    if settings.get("local_model_enabled") is not True:
        print("ERROR: Enable local_model_enabled in config/local_model.json first.")
        return 2
    state = local_model.status()
    if not state.get("ok"):
        print(state.get("message") or "Ollama is not reachable.")
        print("Start Ollama, then run this setup command again.")
        return 2
    if model in set(state.get("models") or []):
        print(f"Vision model already installed: {model}")
        print("The task agent will validate image input on its first real observation.")
        return 0

    ollama = shutil.which("ollama")
    if not ollama:
        print("ERROR: Ollama CLI was not found. Install Ollama before continuing.")
        return 2
    print(f"Downloading local vision model: {model}")
    print("This download is performed by Ollama. Screen captures remain local.")
    try:
        result = subprocess.run([ollama, "pull", model], check=False)
    except OSError as exc:
        print(f"ERROR: Could not start Ollama: {exc}")
        return 2
    if result.returncode != 0:
        print(f"ERROR: ollama pull failed with exit code {result.returncode}.")
        return result.returncode or 2
    final = local_model.vision_status()
    if not final.get("ready"):
        print(final.get("message") or "Model installation could not be verified.")
        return 2
    print(f"READY: {model} is installed for local image analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
