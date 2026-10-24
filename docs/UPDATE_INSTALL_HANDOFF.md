# Update installation handoff — current phase

This phase adds a narrowly scoped handoff helper for a package already represented by a `PreparedUpdate` result from the checksum-verification stage.

## User-consent rule

Call `handoff_to_installer(update, user_confirmed=True)` only from a real UI action after the user chooses **Install**. A background update check, assistant suggestion, or successful download is not consent. **Later** must not call this function.

## Current platform behavior

- **Windows x64:** launches the exact version-matched `MARK-LV-Setup-{version}.exe` using an argument list and `shell=False`. This reports that setup started, not that setup succeeded.
- **Linux x64:** opens the checksum-verified `MARK-LV-Linux-x86_64.tar.gz` for manual installation. It does not overwrite application files.
- **macOS:** opens the architecture-matched DMG for user-driven installation. It does not overwrite the app bundle.
- Unsupported platforms, missing files, and mismatched package names are rejected.

## Important limitations

This is not yet a complete transactional auto-updater. Current release artifacts do not expose a common install API or post-install health-check contract. The Linux tarball and macOS DMG require documented manual steps; therefore no automatic rollback is claimed. Windows setup may run independently, and this helper does not claim to observe its completion. Do not add an automatic restart or delete the previous version until the packaged app has a stable install location, a health check, and an OS-specific recovery plan.

## Tests

```bash
python -m unittest tests.test_update_installer tests.test_update_install_flow tests.test_update_manager -v
python -m compileall -q core plugins tests
```
