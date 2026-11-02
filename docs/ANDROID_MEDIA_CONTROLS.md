# Android Companion Media Controls — Phase 7E

## Delivered in the Android client

- Optional media.control pairing scope requested only after the owner explicitly selects **Request Media Control Scope**.
- Separate **Enable Media Controls** runtime toggle; it is off by default and is not implied by pairing.
- Signed, certificate-pinned HTTPS polling of the desktop's existing POST /v1/media/next queue.
- Allow-listed Android MediaSession actions: play, pause, play/pause, next, previous and stop.
- A five-second polling cadence while the NotificationListenerService is connected. Polling performs no network request unless both the local toggle and desktop scope are enabled.
- The app uses Android's active media sessions and executes a command only when exactly one eligible active/paused session is found. It deliberately does nothing when multiple sessions are active rather than guessing which app the user intended.
- Unit tests cover the command allow-list, play/pause resolution and polling interval.

## Permission and safety model

The desktop pairing offer must approve media.control; the Android user must request that scope during QR pairing; and the user must separately enable media controls. Android Notification Access is also required to enumerate active MediaSessions. The app directs the user to Android's Notification Access settings when needed.

The bridge cannot launch apps, type text, navigate URLs, alter volume, or execute arbitrary shell/device commands. The server queue accepts only the existing six media actions and authenticates each poll with the enrolled device token, HMAC signature, timestamp/nonce protections and TLS certificate pinning.

## Desktop integration boundary

The HTTPS server already exposes a desktop-only enqueue callback as app.state.queue_media_command(device_id, token, action). The desktop UI/voice-command layer must call that callback only after the desktop owner has explicitly requested the media action. It should present the target paired device and action, and handle AuthorizationError, DeviceFeatureError and a full queue without silently retrying. No public phone-to-phone command route is introduced.

## Validation still required

CI can compile the Android app and test the pure command policy, but cannot prove that a specific phone, Android build, or media app exposes a controllable active session. Test on a physical Android device with Notification Access enabled and one active media app; then verify no command is executed when two sessions are active, the scope is missing, the local toggle is off, or the device is disconnected. The published APK remains a debug/testing build unless a production signing key and release process are configured.
