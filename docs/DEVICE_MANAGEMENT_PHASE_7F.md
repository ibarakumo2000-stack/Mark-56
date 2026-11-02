# Phase 7F — Desktop Device Management

## Delivered in this phase

- Adds a responsive **Devices** panel to the authenticated JARVIS dashboard.
- Shows enrolled device identity, platform, granted scopes, last-seen timestamp, and a best-effort online indicator.
- Starts and stops the companion HTTPS listener only after an authenticated owner action.
- Binds the companion listener to the private numeric LAN IP used to open the HTTPS dashboard. Wildcard and public addresses are rejected.
- Reuses the dashboard's locally generated TLS certificate and requires the Android client to pin its SHA-256 fingerprint.
- Creates five-minute, single-use pairing offers with explicit owner-selected scopes. The QR payload contains only the HTTPS endpoint, one-time code, expiry, and certificate fingerprint; it never contains a long-lived device token.
- Generates a QR image locally using the already-declared qrcode dependency. The page also exposes a copyable payload/manual code fallback.
- Allows the owner to edit a device's approved scopes or revoke the device immediately. Scope changes take effect on the next authenticated request.
- Adds owner-authorized media queue controls for devices that were explicitly granted media.control. The command allowlist remains play, pause, play/pause, next, previous, and stop.

## Security behavior

- All owner management endpoints require the existing dashboard bearer session.
- Enrollment and credential endpoints require HTTPS except loopback-only development calls.
- The companion listener is separate from the legacy remote dashboard listener and uses the same private device registry.
- The companion listener does not start on import or desktop application startup.
- No public internet bind, wildcard bind, raw token display, broad admin scope, arbitrary phone control, or arbitrary desktop command is introduced.
- Media queue commands are checked against the active device's currently granted media.control scope before enqueue.
- Stopping the bridge clears the in-memory companion application and prevents new media queue submissions.

## Operator flow

1. Open the dashboard over HTTPS using the computer's private LAN IP (not localhost).
2. Open **Devices** in the dashboard header.
3. Select **Start secure bridge**.
4. Select only the scopes the phone/watch/glasses actually need.
5. Create a pairing QR and scan it with the Android companion, or use the displayed code/payload where manual enrollment is supported.
6. Confirm the new device appears with the expected scopes.
7. Use media buttons only for a device that has media.control.
8. Revoke a lost device immediately; stop the bridge when device connectivity is not needed.

## Validation boundaries

Automated CI verifies route registration, scope allowlisting, registry revocation, syntax, and the existing companion policy tests. It does not prove the LAN firewall, Android certificate pinning, Android background execution, or real media-session behavior on physical hardware. Those remain manual acceptance checks. The dashboard and companion listener must both be reachable on the selected LAN; port 8765 must be allowed only on the trusted private network.
