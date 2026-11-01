# Mark 56 — Update Recovery and Installer Integration

## Purpose

Mark 56 uses a local, crash-aware recovery transaction before replacing an existing installation. The recovery engine lives in `core/update_recovery.py`; `core/update_recovery_cli.py` is the command-line adapter used by installers and launchers; `core/update_recovery_worker.py` restores a backup from a separate process after the failed application exits.

Backups and transaction journals remain on the user's device. They are not uploaded or sent to GitHub.

## Transaction lifecycle

1. **Prepare:** the platform installer runs the existing installation's recovery CLI with `--prepare INSTALL_DIR`. The engine snapshots the installation, preserves safe internal symbolic links, and records a SHA-256 manifest.
2. **Install:** the prepare command journals the transaction as `installing`. If the installer fails, the previous runtime in the backup can run the recovery CLI with `--rollback-id TRANSACTION_ID`.
3. **Health check:** after files have been replaced, the new runtime runs `--mark-awaiting`.
4. **Startup monitoring:** the packaged launcher records its PID and begins a 90-second stability window. A clean exit confirms the transaction. An exception schedules a detached recovery worker. If the process is killed, the next launch detects the stale startup attempt and schedules rollback.
5. **Commit:** confirmation marks the transaction `confirmed` and removes the backup. The small state journal remains for diagnostics.
6. **Recover:** rollback verifies the full backup manifest before swapping the previous installation back into place. A rollback interrupted during its own directory swap remains retryable.

The 90-second stability window is a launch-health heuristic, not a proof that every feature works. The application must still pass its normal smoke and regression tests.

## Platform integrations

### Windows — Inno Setup

- `installer/MarkLV.iss` invokes the currently installed Python runtime before an upgrade and refuses to continue if the backup cannot be created and verified.
- The backup is stored under `%LOCALAPPDATA%/MARK-LV/update-recovery`, outside the installation directory.
- The installer replaces the bundled runtime, then marks the transaction as awaiting startup health.
- If setup fails before commit, Inno Setup invokes the backup runtime to restore the previous application.
- The packaged launcher monitors the first startup and hands rollback to the detached worker if startup fails.

The Windows build pipeline also regenerates a compact multi-resolution ICO from `config/jarvis.png` before Inno Setup compilation. The source ICO is larger than Inno Setup's resource update limit, so the build host requires Pillow.

### Ubuntu / Linux

- The generated `install.sh` creates a verified snapshot before upgrading.
- It stages the new package separately, carries forward `config`, `memory`, `cache`, `uploads`, and `plugins`, then swaps the application directory.
- A shell error trap restores the backup runtime and previous installation.
- The new launcher monitors startup and can recover an interrupted first launch.

The Linux package is currently x86_64 only. The installer may optionally install Ubuntu/Debian desktop and audio libraries when the user explicitly enables that option.

### macOS — Apple Silicon and Intel

- Both DMG targets include an `Install.command` installer alongside `JARVIS.app`.
- The command snapshots the complete existing app bundle, stages the replacement with `ditto`, preserves user data, and swaps the app bundle.
- If the installation command fails, the backup runtime restores the previous bundle.
- The app's launcher uses the bundle-level transaction path and the matching backup runtime.
- The command installs into the current user's `~/Applications` directory. Manually dragging the app bundle bypasses the recovery-aware upgrade flow; use `Install.command` for upgrades.

The release workflow uses native Apple Silicon and Intel runners to build the corresponding DMGs.

## Native verification

`.github/workflows/phase6-native-recovery.yml` runs recovery tests on native Windows, Ubuntu, macOS Apple Silicon, and macOS Intel runners. It validates the Linux and macOS installer shell syntax and compiles the Windows Inno Setup script. It also exercises the Linux/macOS installer scripts with install → upgrade → preserve user data → rollback scenarios.

The Windows runner compiles the Inno Setup script and runs a native install/upgrade/rollback test using an isolated test installation.

These CI tests validate installer and recovery behavior in disposable environments. They do not replace a final manual acceptance test on the end user's own Windows, Ubuntu, Apple Silicon, or Intel computer, especially for desktop permissions, application launch, and hardware-specific dependencies.

## Safety properties

- Recovery state and backups are local to the user.
- The backup is verified by SHA-256 before restoration.
- Symbolic links are preserved only when their resolved targets remain inside the application tree; escaping or broken links block the backup.
- Recovery data must be outside the installation directory.
- User configuration and personal data folders are preserved during upgrades.
- Downloaded installers are still staged and hash-verified by the updater; recovery does not bypass explicit user consent.
- A confirmed update is not automatically rolled back.
- Rollback runs outside the application directory and waits for the failed launcher process to exit.

## Known limitations

- The health monitor begins only after the packaged Python launcher executes. If the operating system cannot start the new Python interpreter at all, automatic recovery may require a manual run of the backup recovery CLI.
- The macOS recovery-aware upgrade path targets `~/Applications/JARVIS.app`; an older system-wide copy in `/Applications` is not silently replaced by this per-user installer.
- The 90-second stability timer is a conservative first-start signal, not a full application feature test.
- Native CI tests do not prove successful operation on every end-user machine or desktop session.

Do not advertise seamless recovery as universally guaranteed. Describe it as an automatic backup and rollback path with documented platform and startup limitations.
