# Phase 9 — Smart-glasses adapter framework

The glasses integration is implemented as a vendor-neutral capability adapter
contract in `core/glasses_adapters.py`. No manufacturer SDK is imported into
the JARVIS core.

## Capability model

Adapters declare actual hardware support for display, camera, microphone,
touch, IMU, battery and audio output. The registry will not invent capabilities.
Every operation is checked against:

1. The enrolled identity being a glasses device.
2. The device's approved permission scope (`display.render`,
   `camera.capture`, `voice.capture`, and so on).
3. The installed adapter's hardware capability declaration.
4. A separate, revocable per-session consent grant for camera, microphone,
   display, or other sensitive operations.

Frame/audio payloads are bounded. Audio capture duration is limited to 15
seconds per call. The core does not persist captured audio or camera frames.

## Adding a manufacturer adapter

Create an optional module under `core/transports/glasses/` or a separately
packaged plugin. Implement `SmartGlassesAdapter` and register it at runtime.
Keep vendor SDK calls behind that module, report exact model/platform support,
and expose only features available on the connected hardware.

## Hardware support status

The framework and authorization tests are in place. No specific Meta, XREAL,
Vuzix, Ray-Ban or other vendor SDK is bundled in this change. A real adapter
requires the target model, developer SDK access/licensing, and a physical
device for camera/display/audio acceptance testing. Unsupported hardware is
reported as unavailable rather than simulated.
