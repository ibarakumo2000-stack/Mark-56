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


### Plugin management

Open **Controls → Plugins** to enable/disable discovered plugins. You can also add a local `.py` plugin file or remove an existing plugin. The manager validates the plugin contract without executing its code during installation, backs up removed files under `.plugin-backups/`, and records removals in your local settings so an app update does not silently re-enable a removed built-in plugin. **Only install Python plugins from sources you trust:** once loaded, a plugin runs with the same file and network permissions as JARVIS. Restart JARVIS after adding or removing a plugin so its tool list is refreshed.

### Desktop update notifications

Packaged builds check GitHub Releases in the background and show a download prompt when a newer stable version is published. **Controls → Check for updates** also lets you check manually. Choosing Download opens the release asset in your browser; the app does not automatically install or execute an installer. The first update that adds this feature must be installed manually once by users on older builds, then future releases can notify them inside the app. See [INSTALLER_BUILD.md](INSTALLER_BUILD.md) for the release-publishing checklist.
