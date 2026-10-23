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
