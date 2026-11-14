# Mark 56 — remaining implementation stages

Updated: 2026-11-14

This tracker separates code already present from work that still needs implementation or real-device evidence. A module existing in the repository is not the same as a completed release acceptance test.

## Recently completed: hologram and full-interface switching

- [x] Minimize the full JARVIS window by hiding it and showing the floating hologram without quitting the assistant.
- [x] Restore the existing full interface from the hologram, clear the minimized state, raise and activate the window.
- [x] Request always-on-top for the full interface.
- [x] Add regression checks for minimize, restore, and always-on-top configuration.

Merged through PRs #126, #127, and #128. The always-on-top request remains subject to GNOME/Wayland compositor policy; real desktop verification is still required.

## Stage 1 — Core stability, credentials and security hygiene

**Present:** local-only config conventions, build-time secret scanning, redacted logging and permission-gated actions.

**Remaining:**
- [ ] Audit all tracked files and repository history for previously committed credentials.
- [ ] Rotate any exposed credentials at their issuing services; history cleanup alone does not revoke a key.
- [ ] Review dependency advisories and pin/upgrade vulnerable packages.
- [ ] Run clean-install and upgrade tests without carrying user secrets or runtime data.

**External action required:** credential rotation must happen in the provider dashboards by the account owner. Do not put replacement secrets in GitHub.

## Stage 2 — AI provider abstraction and offline mode

**Present:** Gemini Live remains the live voice provider; OpenAI Responses API is available for one-shot tasks; the Ollama adapter supports local text and image calls and explicitly avoids cloud fallback when local mode is enabled.

**Remaining:**
- [ ] Add/verify a first-class Settings UI for enabling local mode, selecting installed text/vision models, and testing the local endpoint.
- [ ] Show the active provider clearly in the HUD and command centre before private content is sent.
- [ ] Test model-unavailable, Ollama-stopped, model-not-installed, timeout, and low-memory cases on supported hardware.
- [ ] Decide and document the supported local-model profile for low-power CPUs versus GPU-capable machines.

## Stage 3 — Voice and language

**Present:** Gemini Live voice, selectable voice configuration, wake-word support, mute controls, and text-input fallback.

**Remaining:**
- [ ] Complete microphone permission, wake-word, interruption/barge-in, and reconnect tests on real Ubuntu, Windows, and macOS desktops.
- [ ] Verify voice selection and audio-device changes do not interrupt active background tasks.
- [ ] Confirm visible microphone state and privacy indicators remain accurate during hologram-only operation.

## Stage 4 — Screen and task agent

**Present:** guarded screen observation/OCR, local vision analysis, Wayland ScreenCast integration, and a bounded observe–act–verify task controller with pause/stop, action budgets, and consequential-action approval.

**Remaining:**
- [ ] Complete sustained PipeWire/Wayland capture and harmless input tests in a logged-in GNOME Wayland session.
- [ ] Verify permission denial, monitor changes, lock screen, display sleep, disconnect, and portal restart fail safely.
- [ ] Validate pause/stop responsiveness while a task is running and ensure no action occurs after stop.
- [ ] Keep the agent restricted to approved applications and reversible actions; do not expand to unrestricted autonomous desktop control.

## Stage 5 — Coding agent

**Present:** a dedicated workspace root, protected-path and symlink checks, diff-first proposals, SHA-256 review binding, explicit confirmation, and a fixed test-command allowlist.

**Remaining:**
- [ ] Add enforced OS-level sandboxing for project test execution; the current subprocess boundary is not a security sandbox.
- [ ] Deny network access by default during generated-code tests where the host supports isolation.
- [ ] Add resource limits and per-run output caps for CPU, memory, process count, and filesystem writes.
- [ ] Add recovery/undo support for reviewed edits and test failure reporting.

## Stage 6 — HUD and performance

**Present:** floating hologram, live HUD/avatar animation, telemetry, network sparkline, quiet-hours/routine controls, and reduced-footprint background operation.

**Remaining:**
- [ ] Profile CPU, memory, audio latency, and animation smoothness on low-power hardware.
- [ ] Verify the hologram remains responsive while the main window is hidden and tasks continue.
- [ ] Test always-on-top and focus behaviour on GNOME Wayland, X11, Windows, and macOS; document compositor limitations.
- [ ] Verify reduced-motion/low-power settings and graceful fallback when optional graphics are unavailable.

## Stage 7 — Safe updater

**Present:** stable-release checks, official GitHub asset selection, SHA-256 manifest verification, explicit-consent handoff, local snapshots, installer integration, and rollback/recovery paths.

**Remaining:**
- [ ] Finish a seamless user-confirmed update path for Linux/macOS instead of opening an archive or disk image for manual installation.
- [ ] Verify the complete download → hash check → consent → install → first-start health check → commit/rollback flow on clean machines.
- [ ] Confirm version metadata, release assets, and checksums are generated consistently for every supported architecture.
- [ ] Keep all update execution behind explicit user confirmation; never silently install.

## Stage 8 — Phone, desktop and Wear OS

**Present:** secure device gateway, expiring/revocable pairing, least-privilege scopes, authenticated relay, Android companion, Wear OS action allowlist, and connection diagnostics.

**Remaining:**
- [ ] Complete physical Android phone ↔ Ubuntu desktop QR pairing and device revocation tests.
- [ ] Complete physical Wear OS watch tests for pairing after reboot, Bluetooth/Wi-Fi handoff, phone process death, battery optimization, scope denial/revocation, and offline desktop behaviour.
- [ ] Verify no queued watch action executes after reconnect or after desktop revocation.
- [ ] Verify TLS pinning, credential rotation/revocation, and audit events in a production-like relay deployment.

## Stage 9 — Authorized security workflows

**Present:** Linux-only defensive assessment plugin with exact target validation, explicit authorization, bounded host discovery, service inventory, and non-exploitative safe checks.

**Remaining:**
- [ ] Audit every scan and system-change entry point for exact scope and explicit confirmation enforcement.
- [ ] Add tests for CIDR boundary, hostname validation, shell-injection attempts, concurrent scans, timeout, and cancellation.
- [ ] Verify reports redact secrets and clearly distinguish observations from recommendations.
- [ ] Keep exploit execution, credential theft, stealth, persistence, and out-of-scope targeting excluded.

## Release acceptance — must pass before declaring Mark 56 complete

- [ ] Full Python test suite and import/startup smoke tests on supported Python versions.
- [ ] Native Windows x64, Ubuntu x64, macOS Apple Silicon, and macOS Intel installer/recovery CI.
- [ ] Real-device manual checks for Ubuntu Wayland capture, audio/wake word, hologram switching, and background operation.
- [ ] Real-device Android phone and Wear OS pairing/revocation matrix.
- [ ] Clean-machine install, upgrade, user-data preservation, failed-upgrade rollback, and post-update launch.
- [ ] Confirm no credentials, private keys, personal memory, local databases, or linked-session data are included in release artifacts.
- [ ] README/release notes distinguish implemented, CI-tested, and manually verified capabilities.

## Execution order

1. Finish Stage 2 Settings and provider visibility so offline mode is usable without editing JSON by hand.
2. Complete Stage 4 Ubuntu Wayland and hologram/background acceptance.
3. Add real sandboxing to Stage 5 coding tests.
4. Complete Stage 7 user-confirmed Linux/macOS update handoff.
5. Run Stage 8 phone/watch device acceptance and Stage 9 security-scope tests.
6. Close Stage 1 credential audit and run the complete release acceptance matrix.

A stage is only marked complete when its code, automated tests, and applicable real-device acceptance evidence are all present.
