# Mark 56 update UI integration

The desktop controls drawer now offers a consent-based update flow:

1. **Check for updates** reads stable GitHub release metadata only.
2. **Download verified update** appears only after a newer stable release is offered and requires a user click.
3. The updater downloads the platform asset and checks its SHA-256 against the release `SHA256SUMS.txt` manifest.
4. The UI then offers **Open installer** or **Later**. The staged package is re-hashed immediately before handoff.
5. Windows setup is launched with `shell=False`; Linux archives and macOS disk images are opened for manual installation.

The UI does not claim that opening an installer means installation succeeded. Linux/macOS manual installation, restart health checks, transactional replacement, and rollback are not implemented in this phase. A checksum is not a substitute for publisher code-signing or a signed release manifest.

## Local validation

From the project root with the virtual environment activated:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q core plugins tests ui.py
```
