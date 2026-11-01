# Mark 56 Upgrade Plan

## Principles
1. Preserve the Mark 55 architecture and working features; avoid unnecessary rewrites.
2. Keep Mark 55 untouched. This repository is the only destination for Mark 56 work.
3. Exclude credentials, TLS private keys, personal memory, linked messaging sessions, local databases, logs, and generated caches from version control.
4. Make providers configurable and clearly show when information leaves the device.
5. Use scoped permissions, preview/confirmation for consequential actions, and a reliable stop/pause control.
6. Track implemented, tested, and planned work separately.

## Stage 0 — Safe baseline
- Copy the existing Mark 55 source tree into this repository without carrying its Git history or runtime secrets.
- Add a sanitized example config and verify ignored local config remains untracked.
- Preserve the existing main/UI/actions/core/memory/plugins/dashboard/installer organization.
- Run syntax checks and startup/import smoke tests before feature work.

## Stage 1 — Core stability and security
- Rotate credentials that were committed in Mark 55; remove them from the Mark 56 working tree.
- Review Git history cleanup for Mark 55 separately. Deleting a file in a new commit does not remove it from earlier commits.
- Improve error handling, logging redaction, permission transparency, and dependency checks.
- Preserve existing local settings and memory when updating the app.

## Stage 2 — AI provider abstraction
- Keep Gemini Live functioning as the baseline voice provider.
- Add optional OpenAI Responses API and configurable local/self-hosted inference behind a provider interface.
- Never silently switch provider or transmit screen/audio content without clear user-facing indication.
- Add timeouts, bounded retries, and actionable setup errors.

## Stage 3 — Voice and language
- Preserve selectable voices and local "Hey Jarvis" wake-word support.
- Keep wake-word detection local; make microphone state and permissions visible.
- Ask clarifying questions when speech is ambiguous, especially before consequential actions.
- Retain text input as a fallback.

## Stage 4 — Screen/task agent
- Add task-scoped observation, proposed-action previews, pause/stop, and post-action verification.
- Restrict automation to the selected task and permitted application scope.
- Require confirmation for sending messages, deleting files, installing software, changing accounts, or other high-impact actions.

## Stage 5 — Coding agent
- Work in a dedicated project workspace.
- Show diffs and test output before applying changes to user projects.
- Run generated code in a restricted workspace and do not execute arbitrary generated shell commands without review.

## Stage 6 — HUD and performance
- Evolve the reactor-core visual treatment without unnecessarily changing the existing layout.
- Keep model and file operations off the UI/audio threads.
- Add low-power/reduced-motion options and graceful fallback if optional graphics fail.

## Stage 7 — Safe updater
- Verify signed/versioned metadata and artifact hashes.
- Stage updates, back up settings, preserve memory, and support rollback.
- Never execute an update merely because an AI response or remote message requests it.

## Stage 8 — Phone-to-PC control
- Require explicit pairing, expiring/revocable credentials, TLS, least-privilege scopes, and an audit log.
- Keep remote control disabled until enabled by the user.
- Do not expose an unauthenticated control endpoint to the public internet.

## Stage 9 — Authorized security workflows
- Focus on defensive diagnostics and explicitly scoped labs/targets.
- Require confirmation before network scans or system changes.
- Do not implement stealth, credential theft, persistence, or actions against out-of-scope systems.

## Release acceptance
- [ ] Clean environment setup documented
- [ ] Python syntax/import and startup smoke tests pass
- [ ] Existing voice, wake word, memory, plugins, and HUD regression checks pass
- [ ] No secrets or user-specific runtime data are tracked
- [ ] Confirmation and permission gates tested
- [ ] Provider timeout/fallback tests pass
- [ ] Updater integrity/rollback tests pass before updater is called complete
- [ ] Linux and Windows smoke tests performed
- [ ] README clearly distinguishes implemented features from planned features

## Current implementation status (2026-10-25)

The repository is beyond the initial bootstrap, but this is **not yet a fully completed Mark 56 release**. Source code, automated tests, and OS-level acceptance are tracked separately.

### Implemented or present in the codebase
- Sanitized example configuration and local-only runtime configuration conventions.
- Optional OpenAI Responses API support for one-shot tasks; Gemini Live remains the baseline voice session.
- Selectable Gemini Live voices and local wake-word support.
- Plugin loader that validates `PLUGIN` metadata and a callable `run()`, tracks invalid plugins, and supports enable/disable settings.
- Guarded `screen_agent` modes for observe/read/analyze/propose/limited confirmed execute.
- A Website Studio setup plugin with a separate OS-keyring credential store, and a permission-based Wayland ScreenCast plugin. These require real desktop validation on each supported OS/session.
- In the current development branch: add/remove controls for local Python plugins, persistent removal state, installer checks for required plugin files, and background/manual GitHub-release update notifications.

### Still not complete or not yet verified
- Secret rotation and a complete history audit/removal of any old credentials from previous repository history.
- Local/self-hosted inference and a final GPU-server location.
- Proof that continuous screen observation works reliably through the user's Ubuntu Wayland session; the agent is still guarded and is not an unrestricted autonomous multi-step computer operator.
- A fully sandboxed coding agent with enforced workspace isolation, reviewable diffs, and restricted command execution for every generated project path.
- Full self-update: downloading artifacts inside the app, verifying artifact hashes/signatures before use, safe installation sequencing, settings/memory backup, and rollback. Current update notifications only open the platform download URL and never install silently.
- Phone-to-PC control with secure pairing, revocation, TLS, least privilege, and an audit log.
- A complete defensive security workflow with clear scope enforcement and confirmation gates across every scan/system-change path.
- Clean-machine install and regression tests on Windows, Linux, and macOS, plus manual testing of voice, wake word, screen capture, plugin add/remove, and upgrade preservation.

The release acceptance checklist remains unchecked until each item is run and recorded. A passing unit-test workflow is not evidence that OS permissions, screen capture, installers, and desktop hardware work correctly.

## Step 2 implementation: guarded screen agent

Implemented in `plugins/screen_agent.py` with a `screen_agent` tool entry point:

- `observe`: captures a local screenshot; optional PNG path must remain inside the user's home directory.
- `read_text`: optional local OCR (requires pytesseract, Pillow, and the system Tesseract binary).
- `analyze`: asks the configured Gemini text/vision route to describe the current screen; screenshot content is treated as untrusted input.
- `propose`: returns a proposal only and does not execute it.
- `execute`: requires `confirmed=true` and allows only click, bounded text typing, or a small navigation-key allowlist. Coordinates are checked against screen bounds; no shell, hotkey, deletion, submit, purchase, or credential-entry action is allowed.

Safety tests are in `tests/test_screen_agent.py`. Local test execution is still required; a GitHub commit is not evidence that desktop capture or plugin auto-discovery works on the target Ubuntu session. The agent is intentionally conservative and is not yet an autonomous multi-step computer-use system.


## Phase 6 — Update reliability and recovery (platform integration implemented; native CI verification running)

### Implemented
- `core/update_recovery.py`: local installation snapshots, SHA-256 manifests, atomic transaction journals, safe internal symlink preservation, verified rollback, and retryable interrupted rollback.
- `core/update_recovery_cli.py`: command adapter used by native installers and launchers.
- `core/update_recovery_worker.py`: detached recovery process that waits for the failed launcher to exit before replacing the application directory.
- Windows Inno Setup: pre-upgrade backup, failed-setup rollback, and post-install health-check state.
- Ubuntu installer: staged package replacement, preservation of user-data directories, and shell error-trap rollback.
- macOS DMG: recovery-aware `Install.command`, full app-bundle backup, user-data preservation, and separate Apple Silicon / Intel builds.
- Packaged launcher: 90-second startup stability check, confirmation cleanup, and rollback hand-off after an exception or a detected interrupted startup.
- Windows installer build now regenerates a compact multi-resolution ICO from `config/jarvis.png` to avoid Inno Setup's resource-size failure.
- Tests cover recovery engine behavior, platform CLI hand-offs, installer script upgrade/data-preservation/rollback scenarios, and native OS validation.

### Native verification
- Added `.github/workflows/phase6-native-recovery.yml` for Windows x64, Ubuntu x64, macOS Apple Silicon, and macOS Intel.
- Linux and macOS jobs run their actual generated installer scripts through install → upgrade → preserve user data → rollback scenarios.
- Windows job compiles the Inno Setup installer and runs an isolated native install/upgrade/rollback test.
- The workflow also validates shell syntax and compiles application/recovery sources.

### Remaining acceptance checks
- Wait for the latest native workflow run to pass on all four runners.
- Review the Inno Setup compile and real Windows install/upgrade/rollback results.
- Run a final manual acceptance test on a real Windows PC, Ubuntu desktop, Apple Silicon Mac, and Intel Mac where available.
- Confirm the app starts normally after a successful upgrade and that the backup is removed only after the health check.
- Confirm recovery behavior when the app is forcibly terminated during the first launch.

**Status:** platform integration is implemented. Phase 6 is not yet declared fully complete until the latest four-platform CI run passes and the remaining real-device acceptance checks are recorded. The 90-second startup window is a heuristic and does not guarantee every application feature is healthy.
