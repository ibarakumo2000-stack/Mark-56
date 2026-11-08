# Phase 7F — Desktop Device Management

## Delivered

- Responsive owner-authenticated Devices dashboard for paired phones, watches and supported glasses.
- Per-device identity, platform, granted scopes, online/offline state, last-seen timestamp and readable last-seen age.
- Latest battery percentage, charging state and report time for devices granted `battery.read`.
- Latest Now Playing snapshot for devices granted `media.control`.
- Owner actions to rename a device, edit its approved scopes, send allow-listed media controls, and immediately revoke a device.
- Recent Android notification inbox with source-device attribution; notification content is available only to the authenticated desktop owner.
- Secure bridge start/stop, one-time pairing offers and private-LAN TLS enrollment remain owner-authorized.

## Security behavior

- All owner management endpoints require the existing dashboard bearer session.
- Enrollment and credential endpoints require HTTPS except loopback-only development calls.
- Companion devices authenticate with individual credentials and explicitly approved scopes.
- Scope changes take effect on the next authenticated request; revocation invalidates the device immediately.
- Notification history and media snapshots are returned only from owner-authenticated dashboard routes and only for devices with the corresponding approved scope.
- Device telemetry and notification history are bounded in memory; no long-lived device token is shown in the dashboard.
- The companion listener binds to an explicit private LAN address, not a wildcard or public interface.

## Operator flow

1. Open the authenticated dashboard and select **Devices**.
2. Start the secure companion bridge and pair the phone using a one-time QR.
3. Approve only the scopes the phone actually needs.
4. Rename devices so the dashboard identifies them clearly.
5. Review last-seen and battery information; review Now Playing only when media.control is approved.
6. Enable notification relay on the phone only if desired, and exclude sensitive apps in the Android companion.
7. Edit scopes or revoke a lost device immediately.

## Validation boundaries

CI verifies route registration, scope enforcement, registry updates, payload validation and syntax. Physical Android testing is still required for notification access, app filters, MediaSession discovery and actual media commands. LAN firewall behavior and certificate pinning also require an on-network device test.
