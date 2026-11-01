# Phase 3 — application verification report

## Verification branch

- Branch: `integration/mark56-consolidated-dev`
- Pull request: #44 (draft): https://github.com/ibarakumo2000-stack/Mark-56/pull/44
- Phase 3 workflow: `.github/workflows/phase3-application-verification.yml`

## Automated checks added

1. Python 3.12 and 3.13 matrix.
2. Dependency installation from `requirements.txt` plus packaging/runtime extras used by the app.
3. `compileall` over the desktop app, core, actions, plugins, dashboard, memory, and tests.
4. Full `unittest discover -s tests -v` suite.
5. Import smoke checks for desktop entry points and critical offline, plugin, screen, and updater modules.
6. Installer staging, secret scan, and static package smoke test via `scripts/build.py --stage-only` and `installer/smoke_test.py --static`.
7. Android companion Gradle debug APK build and artifact upload.
8. Linux/macOS portable-release workflow moved to Ubuntu 24.04 for its Linux runner to match the current t64 audio-library package names used by that job.

## What is and is not verified

The workflow and checks are committed, but this report does not claim they passed. At the time of this report, the GitHub connector returned no workflow-run records for the head commit and the only reported commit status was a failing Vercel check. The execution environment here cannot resolve github.com for a local clone, so the test suite and native builds could not be run directly in this session.

Headless CI also cannot prove:
- interactive desktop behavior on a real Windows/macOS/Linux desktop;
- GNOME Wayland ScreenCast portal permissions and sustained capture on a logged-in Ubuntu session;
- native Windows installer execution and macOS DMG launch/signing;
- real phone-to-desktop QR pairing, LAN connectivity, or battery sync.

These need runner/device evidence. Do not merge this PR or call Phase 3 passed until the three GitHub Actions jobs are green and the listed manual platform checks are recorded. Fix any CI failures on this branch and rerun the workflow.
