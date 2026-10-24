# Mark 56 offline mode and verified updates

## Offline AI

Mark 56's local model adapter calls Ollama through loopback only. Download Ollama and the model(s) while online, then local inference can run without internet. Example:

```bash
ollama pull qwen2.5:7b
ollama pull llava:7b
ollama list
python -m unittest tests.test_local_model -v
```

Configure `config/local_model.json` with `local_model_enabled: true`, `local_model_base_url: http://127.0.0.1:11434`, and the exact installed model names. Do not put cloud URLs in this config. Model downloads require internet initially. Choose model sizes based on available RAM/VRAM.

Offline mode is not yet the same as every feature working offline. The primary Gemini Live voice session, cloud provider integrations, and web-search/research actions still need internet. Wake-word detection can be local after its runtime/model has been installed. Offline STT/TTS availability depends on the selected engines and their models being installed and cached first. The UI should report these limitations honestly rather than silently switching to a cloud provider.

## Update checks and staging

- `plugins/update_manager.py` checks official stable GitHub Releases and does not modify the app.
- The `prepare` operation is for a user who has already chosen to download an offered update. It selects the package for the current OS/architecture, downloads the official `SHA256SUMS.txt`, downloads the package, and verifies the SHA-256 before reporting it as prepared.
- Prepared packages are staged in a temporary directory. The module does **not** launch an installer, overwrite the running app, or claim installation succeeded.
- A UI integration must display current version, offered version, release notes/link, and **Install** / **Later** choices. Only the Install choice should initiate platform-specific installation. Never auto-run an installer just because a check found an update.
- Offline or GitHub failures should be reported as “update check unavailable”; they must not prevent Mark 56 from starting.
- Windows packages may need a code signature; macOS packages may be unsigned/notarized. Checksums detect corruption but are not a substitute for code signing or a signed release manifest.

Supported staged packages:
- Windows x64: `MARK-LV-Setup-{version}.exe`
- Linux x64: `MARK-LV-Linux-x86_64.tar.gz`
- macOS Apple silicon: `MARK-LV-macOS-arm64.dmg`
- macOS Intel: `MARK-LV-macOS-x86_64.dmg`

## Tests

```bash
python -m unittest tests.test_local_model tests.test_update_manager tests.test_update_installer -v
python -m compileall -q core plugins tests
```

Do not weaken the existing desktop-action allowlist or confirmation gates to make offline AI work. Model output and text visible on screen are untrusted input.
