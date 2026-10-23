# MARK LV — Windows installer: build guide

Produces `dist\MARK-LV-Setup-<version>.exe`: a normal Windows setup wizard that
installs MARK LV together with its own private Python and every library it
needs. End users never install Python, run pip or open VS Code.

> **Status — read this first.** The packaging system was written and checked on
> a Linux machine without Windows, Inno Setup or internet access. What *was*
> verified: file staging and exclusions, the secret scan (against your real
> project, positive and negative), the launcher's logging / secret redaction /
> crash handling, the smoke-test logic, and that all 83 source files compile on
> Python 3.12. What was **not** possible: building the runtime, compiling the
> `.exe`, and installing it. **Your first real build will be the first time
> those steps run** — follow "First build" below and send me any error.

## Why a bundled Python runtime and not PyInstaller

MARK LV is built around things a frozen single-EXE would fight:

| App behaviour | Effect with PyInstaller | With a bundled runtime |
|---|---|---|
| Drop-in `plugins/*.py`, loaded from disk at launch | needs hidden-import lists; new plugins can't use new libraries | works unchanged |
| `core/installer.py`, `dev_agent`, `code_architect`, Kokoro/wake-word run `sys.executable -m pip …` | `sys.executable` is the app itself → each call would launch another copy of MARK LV | real `python.exe`, works |
| Restart / auto-start / reminders / game-updater spawn `pythonw main.py` | break (no interpreter) | work unchanged |
| ~25 files compute `BASE_DIR` from `__file__` | each needs patching | no source changes at all |

So **no application source file is modified**. The installer ships CPython
3.12 (embeddable build) with all dependencies pre-installed in `runtime\`, and
shortcuts start `runtime\pythonw.exe launcher.pyw`.

## One-time setup on the build machine

1. Windows 10/11 x64 with internet access.
2. Python 3.9+ (only to run the build script).
3. [Inno Setup 6.3 or newer](https://jrsoftware.org/isdl.php).
4. Copy these into the project root (next to `main.py`), keeping the names:
   `installer\`, `scripts\`, `INSTALLER_BUILD.md`.

## Build

```bat
scripts\build_installer.bat
```

Output: `dist\MARK-LV-Setup-1.0.0.exe`, `dist\SHA256SUMS.txt`, `dist\build-info.json`.
The first build downloads Python and several hundred MB of wheels; the runtime is then
cached in `build\runtime` and later builds take about a minute.

Useful options: `--stage-only` (no Windows needed — stage + secret scan +
static checks), `--skip-installer`, `--rebuild-runtime`, `--version 1.1.0`,
`--python 3.12.10`, `--python-sha256 <hash>`, `--sign-command "<cmd>"`.

### First build — what to expect

1. Staging prints what was **left out** (secrets, personal data, dev files).
2. The secret scan must say `clean`. If it fails, the build stops — that is the point.
3. The runtime build is the long step. If a package fails to install, the pip
   error is shown; fix the pin in `installer\requirements-extra.txt` and re-run.
4. The smoke test imports every module the app needs **with the bundled
   interpreter**. A `FAIL <module>` here is exactly the "works on my PC, breaks
   on theirs" bug caught before shipping.
5. Inno compiles `installer\MarkLV.iss`. A compile error names the line.

## What the user sees

Welcome → license (must tick *I agree*) → install folder (Browse; disk space
shown) → shortcuts (Start Menu, Desktop, optional browser download) → progress
→ *Installation complete* with **Launch MARK LV**. First launch shows the app's
own setup screen asking for the Gemini API key.

## Where things live

| What | Location |
|---|---|
| Program + private Python | `%LOCALAPPDATA%\Programs\MARK-LV\` (per-user; **no admin prompt**) |
| Settings, API keys, memory, plugins, cache | inside the install folder: `config\`, `memory\`, `plugins\`, `cache\`, `uploads\` |
| Logs (secrets redacted) | `%LOCALAPPDATA%\MARK-LV\logs\mark-lv.log` |

**Deviation from the brief, deliberately:** user data is *not* moved to
`%APPDATA%`. The app reads `config/`, `memory/` etc. relative to its own code in
~25 places and installs plugin libraries on demand; per-user installation makes
all of that writable without touching the source. Upgrades never overwrite those
folders, and the uninstaller asks before deleting them. If you later want the
data in `%APPDATA%`, that is a source change to the `get_base_dir()` helpers —
say so and I'll do it.

## Secrets and what is deliberately not shipped

Never packaged (and the build fails if a key/token/private key is detected):
`config\api_keys.json` (Gemini key + Telegram bot token + plugin credentials),
`config\certs\` (the dashboard's TLS **private key** — each install generates
its own), `config\whatsapp_web\`, `memory\long_term.json` (what the assistant
knows about you), caches, `.git`, `.vscode`, `setup.py`, `requirements2.txt`,
`plugins\*.zip` (e.g. `Hostinger VPS.zip` is not a plugin).

**Action for you:** the project folder you uploaded contained a live-looking
Gemini key, a Telegram bot token, and — in
`plugins\mail_account_config.example.json` — what looks like a real Google
OAuth client secret (`GOCSPX-…`). The build blanks that value in the packaged
copy only. If that zip has been shared anywhere, **rotate those credentials**,
and remove the secret from the example file in your source.

## Dependencies

`installer\requirements-extra.txt` is appended to your `requirements.txt`. It adds
packages the code imports but `requirements.txt` omits (`edge-tts`,
`faster-whisper`, `soundfile`, `miniaudio`, `msal`, `setuptools<81` for
`win10toast`). Not bundled (opt-in or huge; the app installs them on demand,
which works because the runtime has a real pip): `torch`/`kokoro`, `vosk`,
`openwakeword`, `pandas`, `pydub`, `pytesseract` (also needs the Tesseract program).

Needs internet **after** install: Gemini and all online services; Whisper
speech models (downloaded on first use); Playwright's Chromium (optional
installer task, otherwise on first use).

## Releasing, versioning, branding

* **New version:** edit `installer\version.txt` (or `--version`), run the build.
  The number appears in the installer, Apps list, `VERSION` file and log.
* **Branding:** edit the `#define` block at the top of `installer\MarkLV.iss`
  (name, publisher, URL, GUID — never change the GUID between releases or
  upgrades stop replacing the old install); recolour/retitle the wizard art in
  `installer\assets\make_wizard_images.py` and run it. The icon is `config\jarvis.ico`.
* **Signing:** unsigned installers trigger Windows SmartScreen. With a
  certificate: `scripts\build_installer.bat --sign-command "signtool sign /f my.pfx /p PASSWORD /fd sha256 /tr http://timestamp.digicert.com /td sha256 $f"`.
  Nothing claims to be signed unless this is used.
* **Auto-update:** not implemented. The groundwork is in place — a `VERSION`
  file and a SHA-256 in `dist\build-info.json`. A safe design is: app fetches a
  small JSON from your server, compares versions, downloads the new setup `.exe`,
  verifies its SHA-256 (and signature), then runs it with `/SILENT`.

## Test it

Automated (on a fresh VM, e.g. Windows Sandbox):
`powershell -ExecutionPolicy Bypass -File scripts\test_installation.ps1 -Installer dist\MARK-LV-Setup-1.0.0.exe`

Manual clean-machine checklist (no Python, no VS Code, no pip, none of the libraries):

- [ ] Installer opens, all screens work, license must be accepted
- [ ] Install finishes with no admin prompt; Start Menu entry exists; Desktop shortcut if ticked
- [ ] **Launch MARK LV** opens the HUD; Gemini key screen appears on first run
- [ ] After entering a key: voice reply works; microphone and speakers selectable
- [ ] Webcam / screen-vision command works
- [ ] A plugin runs (e.g. weather, pomodoro); drop a new `.py` into `plugins\` → it loads after restart
- [ ] No-internet: app shows its connection message and does not crash
- [ ] Log exists at `%LOCALAPPDATA%\MARK-LV\logs\` and contains no key
- [ ] Settings → Apps lists MARK LV; Uninstall asks about personal data; shortcuts and folder removed
- [ ] Reinstall after "keep data" → previous API key and memory are still there

## Known limitations

* The taskbar/Task Manager process is `pythonw.exe` (the window title and icon are MARK LV's).
* Shortcuts and the Start Menu launch through `launcher.pyw` (logging + crash
  dialog). The app's own *restart*, *auto-start with Windows* and self-made
  desktop shortcut start `main.py` directly — they work, but without the log file.
* Installer size is large (expect several hundred MB; OpenCV, Qt, ONNX, ctranslate2).
* Windows 10/11 x64 only. macOS/Linux were out of scope.
* CC BY-NC 4.0 (see `LICENSE`, shown in the wizard): redistribution must be non-commercial and credit the author.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Inno Setup 6 not found` | install it, or set env var `ISCC` to `ISCC.exe` |
| Secret scan fails | a key/token reached the package; remove it from the source file named |
| `FAIL cannot import X` in the smoke test | wheel missing/incompatible for Python 3.12 — pin/replace in `requirements-extra.txt`, `--rebuild-runtime` |
| `NOT PROVIDED: foo` | code imports `foo`; add it to `requirements-extra.txt` (or `OPTIONAL` in `smoke_test.py` if truly optional) |
| Installer is only a few MB | runtime not staged — rebuild without `--stage-only` |
| App closes instantly after install | open `%LOCALAPPDATA%\MARK-LV\logs\mark-lv.log` |
| `win32com` / pywin32 import errors | run the build with `--rebuild-runtime`; check `runtime\Lib\site-packages\pywin32_system32` exists |
| SmartScreen warning | normal for unsigned installers — sign it |
