# Phase 7D — Android Notification Forwarding

## User flow

1. The desktop owner grants the paired phone the `notification.receive` scope during one-time QR enrollment.
2. The phone user enables Notification Relay in JARVIS Companion.
3. Android asks the user to grant Notification Access to the JARVIS listener.
4. The user can exclude individual installed apps from forwarding in the companion app.
5. Supported notification title/text previews are sent to the paired desktop over certificate-pinned HTTPS with the device HMAC signature.
6. The authenticated desktop Devices page shows a recent notification inbox, labeled with the sending device.

## Privacy and security

- Forwarding is off by default and requires both owner-approved scope and the phone-side toggle.
- Android Notification Access is a separate operating-system permission.
- App exclusions are stored locally on the phone and checked before any network request.
- The desktop notification inbox is owner-authenticated; the companion bridge requires the enrolled device token, notification.receive scope, timestamp/nonce validation, HMAC and TLS pinning.
- The listener never logs notification text or titles.
- Disconnecting the phone clears the local pairing and turns notification forwarding off.
- The desktop keeps a bounded in-memory recent-event buffer; notification content is not written to persistent logs by this feature.

## Validation boundary

CI covers payload validation, permission checks and the event API. A physical Android device is required to validate Notification Access behavior, app exclusions and delivery under Doze/background restrictions.
