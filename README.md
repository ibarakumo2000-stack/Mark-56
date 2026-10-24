# Mark 56

Mark 56 is the next development version of the existing Mark LV (55) desktop AI assistant. The goal is to evolve the current Python/PyQt6 application in place—preserving its voice, HUD, memory, actions, plugin system, and dashboard architecture—rather than rebuilding it from scratch.

## Repository policy

- Mark 55 remains the untouched reference project.
- All Mark 56 changes belong in this repository.
- Do not copy runtime credentials, TLS private keys, linked messaging sessions, personal memory, local databases, logs, or generated cache data.
- Do not commit API keys or tokens. Use ignored local configuration or environment variables.
- Keep high-impact computer actions behind visible permissions and confirmation.

## Baseline structure

The intended baseline is copied from Mark 55 with sensitive/runtime files excluded:

- `main.py`, `ui.py`, `setup.py`, `requirements*.txt`
- `actions/`, `core/`, `memory/`, `plugins/`, `dashboard/`, `installer/`, `config/`

A clean example configuration belongs in `config/api_keys.example.json`; actual local credentials belong in ignored `config/api_keys.json`.

## Development status

See [MARK56_UPGRADE_PLAN.md](MARK56_UPGRADE_PLAN.md) for the staged roadmap and acceptance criteria. Features are only marked complete after implementation and testing.
## Mark 56 changes currently in the repository

- Optional OpenAI Responses API adapter for one-shot AI tasks in `core/openai_provider.py`.
- `core/gemini.py` can route one-shot calls to OpenAI when local config sets `text_provider` to `openai`; Gemini remains the default.
- The main Gemini Live voice conversation is unchanged and remains on Gemini Live.
- Example settings are documented in `config/api_keys.example.json`.
- Unit tests are in `tests/test_openai_provider.py`; run them from the project root with `python -m unittest discover -s tests`.

### Enable OpenAI for one-shot tasks (optional)

1. Copy `config/api_keys.example.json` to `config/api_keys.json` if you do not already have a local config. Do not overwrite an existing local config.
2. In the local `config/api_keys.json`, set `"text_provider": "openai"`, add your own `"openai_api_key": "..."`, and optionally set `"openai_model": "gpt-4.1-mini"`.
3. Install the updated dependencies with `python -m pip install -r requirements.txt`.
4. Run the unit tests, then launch with `python main.py`.

The real `config/api_keys.json` must remain local and ignored by Git. Never paste API keys into issues, chat logs, or commits. OpenAI usage may incur API charges. Switching this setting affects one-shot side tasks only; it does not switch the live voice conversation.
### Guarded screen agent

Mark 56 includes `plugins/screen_agent.py`. Its modes are `observe`, `read_text`, `analyze`, `propose`, and `execute`. Proposals never run automatically; `execute` requires `confirmed=true` and supports only a small allowlist of reversible actions. To test:

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py ui.py core actions plugins dashboard memory tests
```

Local OCR is optional and requires the Tesseract system package plus Python packages `pytesseract` and `Pillow`. Screen capture needs a logged-in graphical desktop session; it may not work in a headless terminal or restricted Wayland environment.


### Coding workspace and automated checks

The `coding_workspace` plugin is discovered by the existing plugin loader. Set `MARK56_WORKSPACE` to the project directory you want Mark 56 to inspect; otherwise it uses the application's current working directory. It can list/read bounded files, produce a unified diff without writing, apply a reviewed edit only with `confirmed=true` and a matching SHA-256, and run only the fixed unittest/pytest/compile suites. It does not accept arbitrary shell commands.

See [Build, test and release workflow](docs/BUILD_TEST_RELEASE.md). GitHub Actions runs unit tests and syntax compilation on Python 3.12 and 3.13. CI success does not establish that real desktop capture works in a Wayland session; that still requires a local GUI test.


### Closed-loop desktop task agent

The `desktop_task_agent` plugin now exposes `start`, `confirm`, `step`, `status`, `pause`, `resume`, `stop`, and `completed` operations. Each `step` obtains a fresh screenshot, asks the configured Gemini vision route for one small next action, performs only an allowlisted action, and requires another screenshot on the next step. Task memory records the goal, recent actions, current app estimate, and remaining work. The default limits are 180 seconds and 12 actions.

- Approved application launches use a fixed list; arbitrary shell commands are not accepted.
- Mouse clicks and bounded drawing drags are coordinate-checked; text and key input are limited.
- Goals containing common consequential terms enter `awaiting_confirmation`; the caller must obtain user approval and then call `confirm` with `confirmed=true`.
- `request_stop()` provides a thread-safe stop signal for a voice/UI stop-command integration. The caller must wire the spoken stop intent to this function; the current plugin does not by itself guarantee recognition of a stop phrase during a model request.
- A model's `completed` decision is based on its screenshot interpretation, not a formal pixel-level or application-document proof. Treat completion as vision-verified, not infallible.

#### Desktop capture on Linux

`plugins/desktop_capture.py` tries native capture backends with timeouts, validates that the output is a decodable image, and reports backend failures instead of pretending an empty screen was captured. It tries `grim` on Wayland (where supported), then installed desktop screenshot tools such as `gnome-screenshot` / `spectacle`, then Python capture fallbacks. `screen_agent` uses this adapter for observation, OCR, and vision analysis.

This is a fallback adapter, **not proof that the existing GNOME Wayland portal crash is fixed**. On the target Ubuntu GNOME session, verify capture with `screen_agent` and confirm that the screenshot contains the whole desktop. A backend may fail or capture only an XWayland surface; the task agent stops safely if no backend succeeds. Desktop input is still subject to Wayland/PyAutoGUI restrictions and needs a separate manual check.

Example workflow:
1. `start` with a low-risk task such as `Open Krita and draw a penguin`.
2. Call `step` one time, inspect its status/history, and repeat only while status is `running`.
3. Use `pause` / `resume` to suspend and continue; use `stop` to abort.
4. Only use `completed` to inspect the final state after the controller reports completion.

Run `python -m unittest discover -s tests -v` and `python -m compileall -q main.py ui.py core actions plugins dashboard memory tests`. Automated tests cannot verify capture quality or real mouse/keyboard control; those require a logged-in desktop session.

### Preferred response language

The **Customise Assistant** panel includes a **Preferred Response Language** selector. Its value is saved in `config/api_keys.json` as `preferred_response_language` and applied to the next Gemini Live session. The selected language is the default for both spoken and text-formulated replies, independent of the language used for incoming speech. A language-specific one-off request (such as a translation) does not change the saved preference. Available choices include English, Yoruba, Igbo, Hausa, French, Spanish, Portuguese, German, Italian, Arabic, Hindi, Mandarin Chinese, Japanese, Korean, Russian, Turkish, Swahili, Dutch, Bengali, and Indonesian. Voice fluency and pronunciation depend on model support for the selected language.


### Offline project scaffolding

The local_project_builder plugin can create starter portfolios, static web apps, browser games, and Python CLI projects without calling an AI provider. It previews the file list first, creates only a new folder under MARK56_WORKSPACE (or the current working directory), requires confirmation, and never overwrites an existing destination. These templates are foundations, not complete production systems; generated code still needs review and testing.

### Update channel

The Controls drawer includes an automatic background release check at startup and every six hours, plus a manual check button. The checker reads stable release metadata from the official Mark 56 GitHub Releases channel over HTTPS and never executes downloaded code. A newer release is surfaced for review. Automatic installation and restart are not enabled yet: a signed platform-specific package, hash/signature verification, staged replacement, rollback handling, and a restart-time installer must be implemented and tested before the app can safely apply updates unattended.

### Linux network audit boundaries

The linux_network_audit plugin is enabled only on Linux. It can perform explicitly confirmed host discovery or TCP port/service enumeration against bounded private/loopback networks using Nmap. Public targets and large ranges are rejected. It does not exploit devices, brute-force credentials, or use another person's device as an attack target. For lab practice, use an isolated virtual network and deliberately vulnerable training machines that you own or are authorized to test. Windows returns an unavailable message without attempting to install security tools.

### Coding workspace expectations

The coding workspace can review local files, propose a diff, apply a reviewed change with a matching SHA-256 confirmation, and run supported test suites. The offline scaffolder removes the AI-provider dependency for initial project creation. Complex problem solving and reliably correct production code still require iterative tests, dependency checks, runtime verification, and often a capable model; no code generator can guarantee correctness from generation alone.


### Reactor HUD refinement

The existing HUD layout is preserved. The reactor core has a restrained mechanical iris treatment with nested precision rings and subtle state/audio-reactive detail, using the existing palette rather than adding new colours.


### Project builder (no external AI provider required)

The `project_builder` plugin can list, preview, and create built-in starter templates for a portfolio website, a small browser web app, and a simple browser game. It writes only inside `MARK56_WORKSPACE` (or the current working directory), requires `confirmed=true` after preview, and refuses to overwrite an existing directory. These are useful deterministic starting points, not a substitute for a reasoning model when requirements are novel or complex.

### Defensive network inventory on Linux

The `network_audit` plugin supports bounded host discovery and common TCP port/service inventory with Nmap. It requires explicit confirmation, limits targets to private/loopback/link-local IPv4 CIDRs with at most 256 addresses, and runs no exploit scripts, brute force, or stealth operations. It is unavailable for scan operations on Windows. Service banners alone do not prove a vulnerability; use a deliberately vulnerable lab for exploit training.

### Automatic update checks

The Controls drawer now has a persistent `AUTO UPDATE: ON/OFF` switch and a separate `CHECK FOR UPDATES NOW` action. Enabled background checks run every six hours and once shortly after startup. The current release manager checks GitHub Releases metadata only. **Automatic installation and restart prompting are not yet enabled**: a signed, platform-specific installer, artifact verification, safe staging/rollback, and a tested restart handoff are still required. Do not treat a version being available as permission to execute downloaded code.


### Provider-independent static website builder

Mark 56 now includes `plugins/static_site_builder.py`, a local generator for responsive portfolio, business, landing, and church websites. It assembles HTML/CSS/JavaScript without an AI provider, previews before writing, escapes supplied text, confines output to `MARK56_WORKSPACE`, and refuses to overwrite existing destinations. See [Local static site builder](docs/LOCAL_STATIC_SITE_BUILDER.md) and run `python -m unittest tests.test_static_site_builder` (or the full test discovery suite).
