# Universal Wearables & Android Companion

## Design goal
Mark 56 is protocol-first and capability-driven, not vendor-first. The optional BLE/GATT adapter uses the cross-platform Bleak library for discovery, connect, service enumeration, reads, writes, and notification activation. The core permission gateway remains responsible for authorization. The adapter itself does not grant permissions or start a listener.

## BLE adapter setup

Install `bleak` into the Mark 56 environment (`python -m pip install bleak`) and register `BleakTransport` with `ProtocolRegistry` when Bluetooth is enabled by the owner. The adapter is optional, so import/startup remain possible without Bluetooth libraries. Bluetooth permissions and platform support vary across Linux, Windows, and macOS. BLE-only products may expose limited generic characteristics; vendor-specific features need optional adapters using public SDKs.

## Android companion security and release

The Android companion remains paired to the desktop through one-time QR offers, TLS certificate pinning, and Android Keystore-backed credential storage. Permissions are opt-in and scoped; battery sync remains off by default. Android builds run in CI and produce APK artifacts. Publishing a signed APK to the website requires a configured signing key and release credentials; never commit signing secrets.

## Hardware-free validation

`tests/test_bleak_transport.py` verifies optional-dependency handling and payload validation without touching hardware. DeviceSimulator remains the deterministic integration fixture for capability, scope, and connection workflows. Real BLE scans require an enabled adapter and explicit user initiation.

## Compatibility limits

BLE GATT support is not a universal access mechanism for proprietary watch/glasses features. Wi-Fi/LAN bridges, Android companion relay, and manufacturer SDK adapters can be registered independently under the same protocol manager. No claim of universal hardware support is made without device/protocol validation.
