# Phase 8 — Wear OS companion

## Included

- Separate Wear OS APK module under `android-companion/wear-app`.
- A watch-sized JARVIS quick-action surface for play/pause, next, previous, and a JARVIS ping.
- Reachable-phone discovery through the Google Play Services Data Layer capability API. The watch targets a phone that advertises the installed JARVIS companion instead of sending to an arbitrary connected node.
- A strict watch-side action encoder and unit tests. Only four fixed actions can be serialized.
- A phone-side `WearableListenerService` that requires the local Wear OS bridge toggle and the desktop-approved `command.send` scope.
- A per-watch-source cooldown before forwarding to the desktop.
- The phone forwards accepted actions over the certificate-pinned, HMAC-authenticated desktop HTTPS connection.
- The desktop validates the signed event, checks the scope and allowlist, and places the event in a bounded queue. It does not execute watch actions automatically.
- Phone and watch debug APKs are built and tested by CI. The signed release workflow publishes both packages with the same owner-controlled signing key.

## Setup and pairing

1. Build/install the phone APK and Wear OS APK from the same CI run or signed release.
2. Pair the watch with the Android phone using Google's normal Wear OS pairing flow.
3. In JARVIS Companion, request the Wear OS bridge scope before desktop pairing.
4. Pair the phone to the desktop; the desktop owner must approve `command.send`.
5. Enable the Wear OS bridge in the phone app.
6. Open JARVIS on the phone and launch the watch app. The watch should show the reachable phone state.

## Security boundaries

- Watch actions are a fixed allowlist; arbitrary shell commands, text entry, camera capture and microphone capture are not accepted.
- The phone bridge is off by default.
- The desktop must approve `command.send`; the phone must separately enable the bridge.
- Watch messages are bounded and rate-limited before phone forwarding.
- The dashboard feed is an event queue, not an automatic desktop-action executor. The existing desktop confirmation policy remains the final authority.

## Acceptance tests still required

Install both APKs on a real Wear OS watch and Android phone. Test pairing after reboot, Bluetooth/Wi-Fi handoff, phone process death, battery optimization, denied scope, revoked scope, and offline desktop behavior. Emulator builds and CI do not prove hardware pairing or OEM background reliability.


## Phase 8 readiness diagnostics

The phone companion now includes a **Check Wear OS Connection** diagnostic in
the Phone & Wearable Features card. It reports the three independent gates:
desktop pairing, owner-approved `command.send`, and the phone-side Wear OS
bridge toggle. It also queries Google Play Services for currently connected
Wear OS Data Layer nodes when the screen opens, returns to the foreground, or
the user taps the diagnostic button.

The connected-node count is a transport diagnostic only: it does not claim
that the JARVIS watch app is installed or that an action reached the desktop.
The watch still reports its own reachable-phone state, and the desktop Devices
panel remains the authority for received events. If the node lookup fails, the
phone reports that separately instead of showing a false disconnected state.

### Real-device acceptance matrix

- [ ] Install the matching signed phone and watch APKs from the same release.
- [ ] Confirm the phone diagnostic detects the connected Wear OS node.
- [ ] Confirm the watch reports the phone companion reachable.
- [ ] Confirm bridge disabled: watch action does not reach desktop.
- [ ] Confirm bridge enabled but `command.send` denied: action is not forwarded.
- [ ] Enable the owner-approved scope and phone bridge; send JARVIS ping.
- [ ] Confirm the desktop Devices event feed receives the watch event.
- [ ] Confirm play/pause, next and previous remain allowlisted.
- [ ] Turn Bluetooth off/on and verify reconnection without re-pairing.
- [ ] Force-stop/reopen the phone app and verify system-managed listener behavior.
- [ ] Revoke the phone device on desktop and confirm further watch events are rejected.
- [ ] Disconnect the desktop and verify no action is executed or queued for later replay.

CI can validate compilation and unit policies, but these hardware checks must
be performed on a physical Wear OS watch and Android phone.
