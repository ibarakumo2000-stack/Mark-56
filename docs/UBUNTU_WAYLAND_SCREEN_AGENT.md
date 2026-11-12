# Ubuntu GNOME Wayland Screen Agent acceptance

This acceptance test must be run on the actual Ubuntu desktop session. CI can
check imports and mocked portal behavior, but a GitHub runner cannot grant the
user's GNOME screen-sharing permission or prove that the local PipeWire stream
contains the visible desktop.

## Prerequisites

Install the portal, PipeWire, GStreamer, and Python bindings required by the
Mark 56 Wayland adapter. Run the test from the logged-in GNOME desktop session,
not from SSH or a headless terminal.

Check the session:

```bash
echo "$XDG_SESSION_TYPE"
echo "$XDG_CURRENT_DESKTOP"
```

The first value must be `wayland`; the desktop should identify GNOME.

## Verify a real screen frame

From the repository root with the Mark 56 virtual environment active:

```bash
source .venv/bin/activate
python3 scripts/verify_wayland_capture.py
```

GNOME will display its normal monitor-sharing permission prompt. Approve the
screen/monitor. A successful run must report a fresh PipeWire frame, valid PNG
decoding, and non-trivial dimensions. The script does not save or upload the
screenshot and always closes its temporary ScreenCast session.

## Verify observe-act-verify

The continuous desktop task agent requires an enabled local image-capable model;
it deliberately does not send screenshots to a cloud model as a fallback. First
confirm that the configured vision model accepts image input. Then ask JARVIS to
perform a harmless reversible task such as opening the Settings window. Confirm
that the task status advances through observation/action and only reports
completion after a fresh screenshot verifies the visible result. Test Pause,
Resume, and Stop, and confirm that capture/model errors stop the task without a
success claim.

## Acceptance evidence

Record the Ubuntu version, GNOME version, session type, portal permission
result, captured frame dimensions, vision model identifier, and task outcome.
Do not include screenshots, tokens, or personal desktop contents in CI logs.
