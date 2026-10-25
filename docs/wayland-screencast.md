# Persistent screen monitoring on Ubuntu GNOME Wayland

Mark 56 uses the GNOME ScreenCast portal for a single permissioned monitor
session and PipeWire/GStreamer frames while that session is active. The desktop
portal remains the authority: the user chooses the monitor and can deny access.
Mark 56 does not attempt to bypass that prompt.

## System packages

On Ubuntu, install the system-side PipeWire/GStreamer integration:

```bash
sudo apt update
sudo apt install gdbus python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-tools gstreamer1.0-pipewire
```

Use the same Python interpreter/virtual environment that runs Mark 56. The
`gi` module is an Ubuntu system package rather than a normal pip dependency;
a virtual environment that hides system site-packages may not see it. In that
case, use a compatible system Python environment for this integration rather
than installing arbitrary unofficial PyGObject wheels.

## Manual smoke test

From the repository root, inside the logged-in GNOME Wayland desktop session:

```bash
python - <<'PY'
from plugins import wayland_screencast

try:
    print(wayland_screencast.start_monitoring())
    for number in range(3):
        png, width, height = wayland_screencast.capture_monitor_frame()
        print(f"frame {number + 1}: {width}x{height}, {len(png)} PNG bytes")
finally:
    print(wayland_screencast.stop_monitoring())
PY
```

Approve the GNOME monitor-sharing prompt. Each line should report a real frame
with non-zero PNG bytes. Deny the prompt once as a negative test: the call must
report cancellation/denial, not claim that the screen is visible. Then run the
test again and choose the intended monitor.

## In-app checks

- Ask JARVIS what is on screen. It should call `screen_agent` in `analyze`
  mode and describe visible content from the captured frame.
- Call `screen_agent` with `mode=monitor_start`, then `monitor_status`,
  and finally `monitor_stop` to test manual session control.
- Ask for a bounded desktop task using `desktop_task_agent` with
  `operation=run`. It should request screen-sharing permission once, re-use
  fresh PipeWire frames between actions, and close the portal session on
  completion, timeout, error, or stop.
- While a task is running, issue `operation=pause`, `resume`, and `stop`.
  A stop should halt the task and close the portal session.

The streaming path requires a vision-capable model. In local/offline mode,
configure a local model that accepts images; do not silently route desktop
images to a cloud provider. The task controller has a bounded action budget and
stops on capture/model errors rather than claiming success.

## Current limitations

GNOME/portal and GStreamer plugin versions differ. This feature is not considered
verified until the smoke test above succeeds on the target desktop. A permission
grant is managed by GNOME and can be revoked by the user at any time. Closing
the ScreenCast session ends Mark 56's active stream; it does not change GNOME's
global privacy settings.
