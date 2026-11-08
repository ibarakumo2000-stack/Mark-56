# Android Companion Media Controls — Phase 7E

## Delivered in the Android client

- Optional `media.control` pairing scope and a separate phone-side enable toggle.
- Signed, certificate-pinned HTTPS polling of the desktop's owner-authorized media command queue.
- Allow-listed Android MediaSession actions: play, pause, play/pause, next, previous and stop.
- A five-second polling cadence while the NotificationListenerService is connected and the feature is enabled.
- Current MediaSession app, title, artist, album, playback state, position and duration are sent to the desktop using the same device identity and scope.
- The authenticated desktop Devices page displays the latest unambiguous Now Playing snapshot and offers play/pause, previous, next and stop actions.
- The app acts only when exactly one eligible active/paused session exists. It clears stale Now Playing state rather than guessing when there are zero or multiple sessions.
- Unit tests cover the command allow-list, play/pause resolution, polling interval and server-side media-state validation.

## Permission and safety model

The desktop owner must approve `media.control`; the phone must have that scope and the user must separately enable media controls. Android Notification Access is required to enumerate active MediaSessions. No command is run if the local toggle is off, the scope is missing, Notification Access is unavailable, or multiple sessions make the target ambiguous.

The bridge accepts only the six media actions. It cannot launch apps, type text, navigate URLs, alter system volume, or execute arbitrary device commands. Commands are queued only by the authenticated desktop owner; the Android app polls with its enrolled device token, HMAC signature, timestamp/nonce protections and TLS certificate pinning.

## Validation still required

CI can compile the Android app and test pure policy and server validation. A physical Android device with Notification Access and one active media app is required to verify actual MediaSession metadata and transport controls. Test at least one app that publishes a standard Android MediaSession; some apps do not expose all metadata or skip actions.
