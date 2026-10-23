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

The `desktop_task_agent` plugin adds bounded task lifecycle management (`start`, `step`, `status`, `stop`). For each `step`, it captures a fresh screenshot, asks the configured Gemini vision provider for one structured next action, executes only allowlisted actions, and requires another fresh screenshot before continuing. It automatically stops on visible completion, capture/provider/input errors, a 180-second time limit, or 12 actions. Application launch is restricted to a fixed allowlist; arbitrary shell commands are never accepted.

Example: start a task with `operation=start, task="Open Krita and draw a penguin"`, then call `operation=step` until the plugin reports `completed` or `active=false`. The caller should surface each step result to the task orchestrator and honour `operation=stop` immediately. This implementation is a bounded control loop, not a background daemon. Screen capture and PyAutoGUI input must work in the logged-in graphical session; on Ubuntu Wayland the current machine has a confirmed GNOME portal crash, so this plugin will stop with a clear error until desktop capture is repaired. It will not claim the screen is blank or the drawing is complete after a capture error.
