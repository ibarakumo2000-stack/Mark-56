# Phase 9 — Smart-glasses adapter framework

The glasses integration uses a vendor-neutral, permission-enforcing adapter
contract in `core/glasses_adapters.py`. Manufacturer SDKs stay in optional
transport modules; the JARVIS core does not import or assume a specific brand.

## Capability model

Adapters report only observed hardware support. Every operation is checked
against the enrolled glasses identity, its approved permission scope, the
adapter's declared hardware capability, and a revocable session-consent grant.
Camera frames are bounded to 2 MB; audio capture is limited to 15 seconds.
Captured media is not persisted by the adapter registry.

Revoking an enrolled glasses identity is reconciled with active adapter
sessions. The registry attempts to disconnect the physical adapter before
rejecting subsequent operations.

## Generic BLE reference profile

`core/transports/glasses_ble.py` implements the JARVIS BLE display profile:

- Service UUID: `a7e10000-56a1-4a56-9a56-000000000001`
- Display-card write characteristic: `a7e10000-56a1-4a56-9a56-000000000002`
- Display-card payload: UTF-8 JSON, maximum 4 KB.
- The adapter advertises only `display` capability when the service and write
  characteristic are observed.
- It deliberately does not claim camera or microphone support.

This profile is for glasses firmware or a bridge that implements the documented
JARVIS GATT service. It does not make arbitrary retail glasses compatible by
magic, and BLE is not a suitable general-purpose high-bandwidth video/audio
transport.

## Adding a manufacturer adapter

Create an optional module under `core/transports/glasses/` or a separately
packaged plugin. Implement `SmartGlassesAdapter`, report exact model/platform
support, and expose only capabilities the SDK and connected hardware actually
provide. Request camera and microphone session consent separately.

## Hardware support status

The generic BLE display profile and adapter authorization tests are included.
No Meta, XREAL, Vuzix, Ray-Ban or other manufacturer SDK is bundled. A real
vendor adapter requires the exact target model, developer SDK access/licensing,
and a physical device for display/camera/audio acceptance testing. Unsupported
features are reported as unavailable rather than simulated.
