# Mark 56 Android Companion — Phase 6

## Delivered
The desktop core now provides transport-neutral feature handling in `core/device_features.py`:
- Incoming Android notifications, calls and message alerts, gated by `notification.receive`.
- Battery reports and per-device latest battery status, gated by `battery.read`.
- Allow-listed media commands (play, pause, play/pause, next, previous, stop), gated by `media.control`.
- Strict payload validation and a bounded 256-event in-memory queue. Notification content is not persisted.

Inbound events pass the Phase 5 HMAC, freshness, replay, device identity and scope verifier. The new scopes are opt-in and are not granted to existing enrolled devices automatically.

## Integration boundary
This phase adds desktop-side contracts and tests. It does not ship an Android APK, Android notification-listener service, call/message permission screens, MediaSession integration, battery polling, TLS-pinned HTTP client or desktop HTTPS listener. Media commands are prepared as validated objects; an enabled authenticated transport must deliver them. No Android data is collected until those platform components are built and the user grants Android permissions.

## Privacy requirements
The future Android client must request notification access only after explanation, keep call/message content opt-in, use Android MediaSession APIs for playback controls, and provide per-feature toggles plus immediate disconnect/revoke. Do not log notification contents or credentials. These features do not require contacts, SMS, microphone, camera, location or health permissions.
