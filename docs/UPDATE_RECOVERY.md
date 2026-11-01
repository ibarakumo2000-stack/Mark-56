# Mark 56 — Update Recovery

## Purpose

core/update_recovery.py provides local, crash-aware backup and rollback primitives for platform installers. It does not download, launch, or install an update. That separation is intentional: only a trusted platform installer should mutate the installed application.

Backups stay on the user's device. They are not uploaded, attached to release requests, or transmitted to GitHub.

## Transaction lifecycle

1. **Prepare:** call prepare_update(install_dir) before touching the installation. It creates a private per-user transaction folder, copies the current installation, and records SHA-256 hashes for every backed-up file.
2. **Install:** call mark_installing(transaction_id) immediately before replacing files.
3. **Health check:** after the platform installer finishes, call mark_awaiting_health_check(transaction_id).
4. **Commit:** call confirm_update(transaction_id) only after the new application has completed its startup health checks. This marks the transaction confirmed and removes the backup.
5. **Recover:** if installation or startup fails, a recovery process outside the application directory calls recover_if_interrupted(). Pending transactions are restored from their verified snapshots.

The state journal is written atomically. Rollback verifies the complete backup manifest before changing the current installation and uses same-volume directory renames for the replacement. A rollback interrupted during the directory swap remains journaled as rollback_started and can be retried.

## Example installer integration

\`\`\`python
from core import update_recovery

transaction = update_recovery.prepare_update(APP_DIR)
transaction_id = transaction["transaction_id"]

try:
    update_recovery.mark_installing(transaction_id)
    replace_application_files()
    update_recovery.mark_awaiting_health_check(transaction_id)
    run_startup_smoke_checks()
    update_recovery.confirm_update(transaction_id)
except Exception:
    # Run recovery from a separate process after the application has exited.
    raise
\`\`\`

A platform-specific recovery launcher must invoke recover_if_interrupted() before launching the application after a failed or interrupted update. Do not call rollback from a process whose executable or working directory is inside the installation being replaced; close the application first. On Windows, locked files must be released before directory replacement.

## Safety properties

- Refuses symbolic links in the installation tree rather than following paths outside the app directory.
- Refuses to put recovery data inside the installation directory.
- Keeps backups local and creates the transaction directory with owner-only permissions where supported.
- Verifies the backup SHA-256 manifest before rollback.
- Does not run downloaded files or bypass the updater's explicit user-consent flow.
- Keeps confirmed updates out of automatic rollback.
- Leaves a retryable journal if the rollback swap itself is interrupted.

## Current integration boundary

The recovery engine and its unit tests are implemented. The existing Windows Inno Setup installer, Linux shell installer, and macOS drag-and-drop DMG flow still need platform-specific wiring to create the backup before replacing files and to run recovery before relaunch. Until those adapters are connected and tested on native operating systems, Mark 56 must **not** advertise seamless automatic rollback as available. The current updater continues to stage verified assets and hand off to the platform installer with explicit user consent.
