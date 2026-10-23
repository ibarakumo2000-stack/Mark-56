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

## Current status
Planning and repository bootstrap only. The code baseline must be copied and validated before marking the application upgrade as started in implementation terms. Later stages are not yet implemented or tested.
