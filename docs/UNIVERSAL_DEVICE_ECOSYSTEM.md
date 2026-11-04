# Universal JARVIS Device Ecosystem

## Goal

Keep one JARVIS identity and capability model across the Mark 56 desktop,
Android phones, smartwatches, and smart glasses. Manufacturer-specific SDKs
must remain behind adapters so the core does not depend on a particular brand.

"Universal" means a common enrollment and command protocol with optional
capabilities. It does not mean every device exposes the same hardware APIs:
Android versions, watch operating systems, and glasses vendors restrict access
differently. A capability is advertised only when a compatible adapter and the
device's own permissions support it.

## Architecture

1. **JARVIS core** — AI provider routing, local memory, identity, task policy,
   and user permissions.
2. **Device gateway** — enrollment, device identity, authorization scopes,
   revocation, presence, and message routing.
3. **Companion application** — Android-first app that provides pairing,
   notifications, microphone/camera permission prompts, and a bridge for
   supported watches and glasses.
4. **Adapters** — Android companion transport, Wear OS, watchOS companion
   bridge, Bluetooth LE, and manufacturer-specific glasses SDKs.
5. **Transport** — local Wi-Fi/Bluetooth when nearby; authenticated TLS
   connections through a relay when remote.

The first implementation lives in `core/device_gateway.py`. It contains a
SQLite device registry, short-lived one-use pairing codes, hashed device-token
storage, permission scopes, per-device revocation, and a transport adapter
registry. It intentionally has no vendor SDK imports.

## Pairing flow

1. On the trusted JARVIS desktop, the owner opens **Settings → Devices → Pair
   new device** and chooses the permissions to grant.
2. The desktop creates a short-lived pairing code and QR representation.
3. The user opens the JARVIS Android app and scans the QR code or enters the
   code in **Devices → Add device**.
4. The phone presents its device type, platform, and requested permissions.
5. The desktop owner selects the requested scopes before creating the QR. The
   one-time pairing offer is constrained to those approved scopes.
6. The gateway redeems the code once, issues a random device token, stores only
   its SHA-256 hash, and returns the token to the companion once.
7. The owner can inspect or revoke each paired device.

Never put API keys, cloud provider credentials, or the raw device token in a QR
code. Pairing codes must expire, be single-use, and be rate-limited by the
network-facing API. The QR code should contain a short-lived enrollment URL or
code, not a permanent bearer credential.

## Permission scopes

Scopes are granted independently of hardware capabilities. Example scopes:

- `command.send` — send a user command to JARVIS.
- `notification.receive` — receive JARVIS notifications.
- `voice.capture` — send microphone audio after explicit OS permission.
- `camera.capture` — send camera frames after explicit OS permission.
- `display.render` — render JARVIS cards or prompts on a supported display.
- `haptics.send` — request supported vibration/haptic feedback.
- `health.read` — read only explicitly consented health summaries.
- `desktop.control` — request a desktop action; JARVIS still applies its own
  confirmation and action policy.

Do not create an unrestricted `admin` or wildcard scope. A device's advertised
capabilities describe what it can technically do; granted scopes describe what
the owner permits it to do.

## Compatibility strategy

| Device class | Common integration | Important limitation |
| --- | --- | --- |
| Android phone | Android companion app; HTTPS/WebSocket; optional BLE | Android permissions and background-execution rules vary by version and vendor |
| Wear OS watch | Wear OS companion module, phone relay, notifications and tiles | Full AI inference belongs on the phone/server, not the watch |
| Apple Watch | iPhone companion bridge and watchOS app | Requires Apple platform tooling and iPhone-side relay; not a direct Android watch target |
| Other watches | BLE GATT or vendor SDK when documented | Generic Bluetooth does not expose arbitrary app controls |
| Smart glasses | Companion phone app plus vendor SDK | Camera, microphone, display and streaming access vary by model |
| Desktop | Existing Mark 56 desktop client | Local device operations require the desktop to be online |

The Android app is the first mobile target. Wear OS is the first watch adapter
target. Other watch brands can be added where they expose a supported companion
or BLE interface. Glasses are integrated through a capability adapter for each
supported SDK; unsupported hardware features remain unavailable rather than
being simulated.

## Remote connectivity and offline behavior

- Nearby devices may use Bluetooth LE or the same trusted local network.
- Remote devices connect outward to an authenticated relay over TLS. Do not
  expose the desktop's control port directly to the public internet.
- The relay routes only authenticated, scope-authorized messages.
- If the internet is unavailable but devices share a LAN, local communication
  may continue when the local gateway is running.
- If the desktop is asleep or offline, desktop-only actions cannot execute.
- Local AI and local device communication are separate capabilities: local
  pairing does not make cloud-only AI or web search available offline.

## Security requirements before production

- Replace the legacy dashboard's shared six-character session-key model with
  named per-device identities and scoped tokens.
- Use TLS for every network transport; reject remote pairing over plaintext
  HTTP. A self-signed certificate must be pinned or enrolled safely, not
  bypassed silently.
- Use authenticated encryption (for example TLS plus authenticated application
  tokens); do not rely on custom AES-CBC as the security boundary.
- Store only token hashes on the desktop/server; rotate and revoke tokens.
- Rate-limit pairing attempts and avoid logging codes, tokens, audio, images, or
  private command contents.
- Require explicit confirmation for high-impact desktop actions even when the
  command comes from a paired device.
- Keep camera, microphone, location, and health access separately permissioned.
- Provide a visible connection indicator, per-device permission editor, and
  one-action revoke control.

## Build stages

- [x] Add a platform-neutral device registry and adapter contract.
- [x] Add tests for one-time pairing, permission scopes, token hashing,
      authentication, revocation, and adapter resolution.
- [ ] Run tests in the user's local Mark 56 development environment.
- [x] Mount the registry in the existing dashboard using a private per-user
      SQLite database, without replacing legacy remote-control routes.
- [x] Add TLS-gated pairing offers, one-time enrollment, authenticated device
      listing, per-device revocation, and device identity endpoints.
- [x] Add owner-only per-device permission editing and authenticated Android companion routes.
- [x] Add a desktop Devices panel with QR and manual pairing code, bridge lifecycle, status, media queue controls, and revocation.\n- [x] Make same-Wi-Fi QR pairing the primary, no-VPS path; label remote relay as optional and required only for out-of-network access.
- [x] Upgrade the phone companion UI with a branded splash screen, Material 3 feature cards, edge-to-edge layout, explicit permission recovery, and safe disconnect cleanup.
- [x] Add a separate Wear OS app, reachable-phone discovery, strict action allowlist, phone Data Layer bridge, and rate-limited desktop forwarding.
- [x] Add a vendor-neutral smart-glasses contract, revocation-aware session cleanup, and a reference BLE display adapter for the documented JARVIS GATT profile.
- [x] Add an ephemeral TLS WebSocket relay, hashed credential registry, two-sided scope checks, provisioning CLI, Docker/Caddy deployment, desktop runtime, keyring-backed dashboard configuration, and Android client transport.
- [x] Add a tag-based signed phone/watch release workflow with secret validation, APK signature verification, shared-certificate check, and SHA-256 checksums.
- [ ] Configure owner-managed Android signing secrets and publish a signed release.
- [ ] Deploy relay to an owner-controlled host and complete cross-network end-to-end security tests.
- [x] Deliver authenticated relay event metadata to the desktop-owned notification UI; private payloads are excluded and remote command events require local owner review.
- [ ] Add vendor-specific glasses SDKs after the target models and SDK access are selected; validate on physical glasses.
