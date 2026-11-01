# Mark 56 consolidation — Phase 2 report

## Scope

This branch is the consolidated development baseline created from the current `main`:

- Branch: `integration/mark56-consolidated-dev`
- Phase 2 is a selective integration, not a wholesale merge of stale feature branches.
- The existing `main` implementations are retained wherever they are newer or already contain the feature.

## Changes integrated from feature branches

| File | Source | Integration |
|---|---|---|
| `plugins/game_autoplay.py` | `feature/continuous-screen-vision` | Adopted lazy PyAutoGUI initialization so plugin discovery does not import desktop-input dependencies prematurely. |
| `plugins/static_site_builder.py` | `feature/continuous-screen-vision` | Adopted visual style presets (editorial/minimal/studio), expanded accent choices, SEO/social metadata and Organization structured data. Retained the current main implementation as the baseline and used the newer generator implementation as the consolidated version. |

## Existing main implementations retained

The following modules were checked against `feature/continuous-screen-vision` and were byte-for-byte identical, so no duplicate copy was needed:

- `core/local_model.py`
- `core/website_studio_credentials.py`
- `plugins/coding_workspace.py`
- `plugins/desktop_capture.py`
- `plugins/desktop_task_agent.py`
- `plugins/ethical_security_assessment.py`
- `plugins/linux_network_audit.py`
- `plugins/local_project_builder.py`
- `plugins/network_audit.py`
- `plugins/project_builder.py`
- `plugins/static_site_workspace.py`
- `plugins/update_install_flow.py`
- `plugins/update_installer.py`
- `plugins/update_manager.py`
- `plugins/website_stack_advisor.py`
- `plugins/screen_agent.py`
- `plugins/wayland_screencast.py`
- `plugins/website_studio_setup.py`
- `plugins/game_updater.py`

The device-gateway dashboard branch was also checked: `dashboard/device_api.py`, `dashboard/server.py`, `tests/test_device_api.py`, and `docs/UNIVERSAL_DEVICE_ECOSYSTEM.md` already match `main`.

## Deliberately not copied

- `core/plugin_loader.py`: current `main` includes plugin removal/disabled-file handling that the older feature branch does not have. Preserve main.
- `main.py` and `ui.py`: the feature branch has large, divergent replacements. They were not copied because doing so could regress current UI, plugin manager, Android companion, or updater integration. Their changes require focused review during Phase 3 rather than a blind replacement.
- Android companion branches checked so far are behind `main` and contribute no unique commits.
- Older updater/build branches are heavily diverged from current `main`; their files were not merged wholesale. Release workflow changes will be reviewed independently during Phase 3/5.

## Verification boundary

Phase 2 establishes the consolidated branch and records the selective merge decisions. It does not claim that the full application or installers have passed tests. Phase 3 must run the complete test suite and platform-specific checks against this branch, then fix any integration defects before Phase 4 merges it into `main`.
