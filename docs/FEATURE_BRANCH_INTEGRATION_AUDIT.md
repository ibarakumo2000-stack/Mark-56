# Mark 56 Feature-Branch Integration Audit

**Audit baseline:** `main` at `c591030dc87fce7a30cdd173a8c8764a68cbe262`  
**Audit date:** 2026-11-02

## Decision

Keep one canonical product repository and one release source: `ibarakumo2000-stack/Mark-56`, with `main` as the only release-integrated branch. Keep platform code in its existing modules (`core/`, `dashboard/`, `plugins/`, `android-companion/`, `relay/`, `installer/`, `scripts/`, `tests/`); do not flatten platform-specific code into one directory.

Do not merge old feature branches wholesale. Several are hundreds of commits behind `main`, have large divergent histories, or repeat changes that have already landed. Port only a clearly missing, isolated change onto a fresh branch from current `main`, then test it.

## Confirmed integrated work

| Area | Current main evidence | Decision |
|---|---|---|
| Wear OS, smart-glasses adapters, secure relay, signed Android release | PR #57 merged; Android and relay modules, release workflow and tests are present | Integrated; continue physical-device acceptance |
| Desktop QR pairing entry point | PR #59 merged at the audit baseline; dashboard header links to `/devices#pair-device` | Integrated |
| Device gateway API and dashboard | `dashboard/device_api.py`, `dashboard/server.py`, `tests/test_device_api.py` are present on main | The old draft PR #30 is not a missing feature to merge wholesale; compare only any genuinely new behavior |
| Desktop installers | Windows and Linux/macOS release workflows and platform build scripts are present | Pipeline exists; release completeness/provenance needs a stronger gate |
| Android companion distribution | Signed Android workflow and phone/watch APK/AAB outputs are present | Integrated; physical installation and pairing remain acceptance work |

## Open pull requests at audit time

| PR | Head | State / risk | Disposition |
|---|---|---|---|
| #1 Build automation, coding workspace, updater controls and safe network tools | `mark56-build-automation` | Draft; 167 commits, 63 files; very large and stale relative to current main | Do not merge. Inventory individual capabilities and port only missing pieces |
| #2 Installer release job fix | `fix-installer-release-publish` | One-file fix, but base is PR #1's feature branch rather than main | Do not merge as-is. Re-evaluate its one-file change against the current release workflow |
| #21 Continuous screen vision | `feature/continuous-screen-vision` | 184 commits, 67 files; heavily divergent and touches core app, UI, plugins, workflows and installers | Do not merge wholesale. Extract screen-agent changes as a focused follow-up after current screen-capture baseline is tested |
| #30 Device gateway dashboard API | `fix/device-gateway-dashboard-integration` | Draft; four files; gateway API, server wiring, docs and tests already exist on main | Treat as superseded/overlapping. Review only unique hunks before closing |

## Branch comparison findings

Comparisons below are against the audit baseline `main`. “Behind” means the branch lacks later main commits; “ahead” means it contains commits not in main. A branch being ahead is not proof that its implementation is correct or safe to merge.

| Branch | Ahead | Behind | Files in comparison | Finding |
|---|---:|---:|---:|---|
| `integration/mark56-feature-consolidation` | 0 | 266 | none | Superseded; do not merge |
| `integration/mark56-consolidated-dev` | 0 | 258 | none | Superseded; do not merge |
| `feature/unified-device-pairing-entrypoint` | 0 | 1 | none | Already merged through PR #59 |
| `feature/phases-8-11-wear-glasses-relay-android-polish` | 106 | 6 | Android, relay, glasses, workflows and tests | Merged through PR #57; branch is now historical |
| `feature/continuous-screen-vision` | 184 | 392 | 67 files | Highly divergent; extract only missing screen-agent work |
| `feat/verified-in-app-update-download` | 3 | 376 | 3 files | Candidate for focused comparison; main already has `core/update_checker.py` and related tests, so verify behavior before porting |
| `fix/device-gateway-dashboard-integration` | 4 | 364 | 4 files | Overlaps code and tests already on main |
| `fix/plugin-discovery-installer-manager` | 31 | 390 | 23 files | Stale, overlapping plugin/installer work; do not merge wholesale |
| `fix/three-plugin-discovery` | 182 | 392 | 67 files | Superseded snapshot; compare individual plugin-discovery fixes only |
| `fix-game-autoplay-updater-discovery` | 131 | 392 | 57 files | Superseded snapshot; compare individual plugin-discovery fixes only |
| `fix-plugin-discovery-and-mail-imports` | 123 | 392 | 54 files | Superseded snapshot; compare individual import fixes only |
| `fix-six-plugin-discovery-template` | 128 | 392 | 57 files | Superseded snapshot; compare individual plugin-template fixes only |
| `fix/gnome-wayland-screen-capture` | 117 | 392 | 55 files | Stale platform snapshot; retest and port narrowly |
| `fix/wayland-portal-dbus-introspection` | 149 | 392 | 58 files | Stale platform snapshot; retest and port narrowly |
| `fix/windows-installer-upgrade-safety` | 0 | 371 | none | No unique commits relative to current main |
| `feature/android-apk-release-publishing` | 0 | 300 | none | No unique commits relative to current main |
| `feature/universal-device-gateway` | 0 | 360 | none | No unique commits relative to current main |

Other historical phase branches (Android phases 2–7, wearable adapters, website-studio experiments, local-model CI, and earlier installer fixes) remain in the repository. They must be compared by file/feature against current main before any cherry-pick; branch names alone are not evidence of missing functionality.

## Dependency-ordered integration plan

1. **Canonical baseline and inventory** — use current main; record each branch's unique commits and changed paths; exclude merged, ancestor-only, and superseded branches.
2. **Core contracts and shared services** — integrate only missing device gateway, permission/scope, transport and plugin-loader changes. Add/retain unit tests before UI wiring.
3. **Desktop and companion UX** — wire the dashboard to the stable gateway API; then integrate phone, Wear OS and glasses adapters. Preserve explicit pairing, user-granted scopes, revocation and secure transport.
4. **Screen agent and coding/plugin features** — port isolated improvements after the current interfaces are stable; do not overwrite current UI/core files with a large historical snapshot.
5. **Updater and recovery** — converge on one authoritative update-check/download/install flow; verify official release host, platform/architecture asset selection, SHA-256, explicit user consent, and rollback.
6. **Release provenance and packaging** — every platform package for a desktop version must be built from the same tagged commit and version. Require Windows, Linux x86_64, macOS arm64 and macOS x86_64 assets plus build metadata/checksums before a draft release is promoted to stable.
7. **Acceptance and promotion** — run the full Python suite, compile checks, Android unit tests, installer smoke/recovery tests and platform-specific release checks. Then perform real-device acceptance for phone, watch, desktop pairing and relay before claiming hardware acceptance.

## Release consistency gaps to close

- Windows, Linux and macOS workflows are separate jobs that attach assets to a common version tag. The current Windows workflow intentionally creates a draft; Linux/macOS attach their packages to that draft. This is a useful staging pattern, but the repository still needs a single explicit pre-promotion check that refuses promotion unless all expected platform assets are present.
- Windows `build-info.json` currently records version, Python version, hash, size and signing state; portable metadata records version, target, Python version, hash, size and signing state. Neither records the source commit. Add the tag's exact commit SHA to every platform's build metadata.
- Keep desktop releases (`vX.Y.Z`) separate from Android companion releases (`companion-vX.Y.Z`); their package IDs, versioning and release assets differ.
- The in-app checker must point only to a published stable desktop release, choose the matching OS/architecture asset, verify the GitHub-published SHA-256 digest, and never silently execute an installer.
- Do not mark a desktop release latest until all four desktop targets are attached and verified. A release draft is not discoverable through the public latest-release endpoint.

## Acceptance status — not inferred from CI

Automated workflows can prove build/test steps passed on their runners. They cannot prove the user's physical Android phone can scan and pair with the desktop, that a real Wear OS watch reconnects, or that a smart-glasses adapter works with a specific vendor device. Keep these as explicit manual acceptance checks and report them separately from CI status.
