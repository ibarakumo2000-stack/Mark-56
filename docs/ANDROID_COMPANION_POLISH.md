# Android Companion UX and quality pass

The phone companion has a branded JARVIS splash screen, Material 3 dark theme,
custom launcher artwork, edge-to-edge system-bar handling, grouped feature
cards, clear privacy copy, and accessible live connection status. Feature
controls are grouped by purpose rather than presented as one long flat button
list. Returning from Android system settings refreshes the visible permission
state.

Pairing requests remain explicit and scope-based. Notification access and media
session access require Android's own Notification Access grant as well as the
desktop-approved scope. Battery sync, notifications, media controls, Wear OS
forwarding and remote relay remain separately opt-in.

Disconnect now stops the remote relay, clears the encrypted desktop and relay
credentials, clears stale requested scopes, and disables scheduled battery
sync. The desktop owner must still revoke the server-side device identity to
invalidate it remotely.

Remote relay endpoint parsing rejects plaintext URLs, embedded credentials,
non-origin URLs, malformed UUIDs, and oversized messages. The UI presents a
manual reconnect action; it does not silently create an always-on background
connection.

## Release quality

The phone and watch modules have minified release variants. The signed release
workflow validates the owner-managed keystore, runs both modules' unit tests,
verifies both APK signatures, confirms they share the same certificate, and
publishes SHA-256 checksums. The rolling preview remains a debug build.

Before claiming a polished public release, run TalkBack, large font/display
scaling, contrast and touch-target checks; verify on at least one small and one
large Android screen; and test Android 13+ notification access, Android 15
edge-to-edge behavior, and battery-optimized background execution on physical
devices.
