# Phase 8 — Wear OS companion

## Included

- Adds a separate Wear OS APK module under `android-companion/wear-app`.
- Provides a watch-sized quick-action screen for play/pause, next, previous, and a JARVIS ping.
- Uses Google Play Services Data Layer messages to send actions to the paired Android phone.
- Adds a phone-side `WearableListenerService` which ignores all watch messages unless the user enabled the Wear OS bridge and the desktop granted `command.send`.
- The phone forwards only the four fixed actions over the existing certificate-pinned, HMAC-authenticated desktop HTTPS connection.
- The desktop verifies the signature and scope, validates the source and action allowlist, and places the event in a bounded queue.
- The authenticated desktop Devices page can inspect and drain queued watch actions. It does not execute them automatically.

## Setup and pairing

1. Build/install the phone APK and Wear OS APK from the same release.
2. Pair the watch with the Android phone using Google's normal Wear OS pairing flow.
3. In JARVIS Companion, request the Wear OS bridge scope before desktop pairing.
4. Pair the phone to the desktop; the desktop owner must approve `command.send`.
5. Enable the Wear OS bridge in the phone app.
6. Start the desktop companion bridge and check **Devices → Wear OS activity**.

## Security boundaries

- Watch actions are a fixed allowlist; arbitrary shell commands, text entry, camera capture and microphone capture are not accepted.
- The phone bridge is off by default.
- The desktop must approve `command.send`; the phone must separately enable the bridge.
- Queue size is bounded and the desktop dashboard requires owner authentication.
- The dashboard feed is an event queue, not an automatic desktop-action executor. The existing desktop confirmation policy remains the final authority.

## Acceptance tests still required

Install both APKs on a real Wear OS watch and Android phone, test pairing after reboot, Bluetooth/Wi-Fi handoff, phone process death, battery optimization, denied scope, revoked scope, and offline desktop behavior. The emulator build does not prove hardware pairing or OEM background reliability.
