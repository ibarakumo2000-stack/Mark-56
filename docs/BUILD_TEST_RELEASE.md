# Mark 56 development and release workflow

## Local preflight

Run from the repository root with the project virtual environment active:

```bash
python -m unittest discover -s tests -v
python -m compileall -q main.py ui.py core actions plugins dashboard memory tests
python -c "import json,pathlib; json.loads(pathlib.Path('config/api_keys.example.json').read_text(encoding='utf-8')); print('Example config valid')"
```

The GitHub Actions workflow runs unit tests and syntax compilation on Python 3.12 and 3.13 for pushes and pull requests. It does not need real API credentials and must never receive them as CI secrets for unit tests.

## Coding workspace plugin

`plugins/coding_workspace.py` is loaded through the existing plugin discovery mechanism. Set `MARK56_WORKSPACE=/absolute/path/to/project` before launching Mark 56 to choose the directory it can inspect. If unset, the current working directory is used.

Supported operations:

- `list`: list workspace files, skipping common virtual environments, caches, build output and dependency folders.
- `read`: read a bounded UTF-8 file and return its SHA-256.
- `propose`: return a unified diff only; does not write the file.
- `apply`: writes a reviewed edit only when `confirmed=true` and `expected_sha256` still matches the current file.
- `test`: runs only the fixed unittest, pytest, or compileall command. No arbitrary shell command parameter is accepted. Tests execute project code, so only point this plugin at projects you trust.

The plugin deliberately does not install dependencies, commit files, push code, or deploy websites. Review the diff and test output before accepting a change.

## Screen agent known limitation

The screen agent is registered as a plugin and has confirmation-gate unit tests. On some Wayland/Xwayland sessions PyAutoGUI import fails with an X11 authorization error, and a screenshot utility may not be able to capture the desktop. CI cannot prove that a real desktop capture works. Treat live capture and OCR as unverified until tested in the target graphical session.

## Release checklist

- [ ] Unit tests pass locally and in GitHub Actions.
- [ ] Syntax compilation passes.
- [ ] Example config parses and contains no real credentials.
- [ ] Plugin manager shows `screen_agent` and `coding_workspace` as valid.
- [ ] Screen capture/OCR are tested in a real logged-in desktop session.
- [ ] Confirmation and stale-file-hash protections pass.
- [ ] Existing Gemini Live, memory, actions, HUD and dashboard receive manual regression testing.
- [ ] No API keys, certificates, messaging sessions, memory databases, or logs are committed.
- [ ] Review changes before merging the pull request.
