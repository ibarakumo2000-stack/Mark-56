# Phase 10 — Secure remote relay

## Architecture

The optional stateless broker lives in `relay/`. Desktop and mobile clients
open outbound WebSocket connections over TLS. The desktop does not expose a
public inbound control port. Deploy behind Caddy or another correctly
configured TLS reverse proxy.

The relay forwards bounded JSON envelopes only between desktop and device
principals in the same channel. Sender and recipient must both hold the
required scope for the message type. The self-hosted SQLite broker does not
persist message bodies, store raw credentials, or log message content.

The Vercel deployment uses the connected Neon PostgreSQL integration for
credential persistence and a bounded cross-instance delivery queue. When a
recipient is connected to a different Vercel function instance (or briefly
offline), a message can be buffered in PostgreSQL for up to 20 seconds. It is
deleted after socket delivery or expiry, and the queue is capped at 100 pending
messages per recipient. This is temporary cloud-side buffering, not message
history. Do not enable the Vercel relay if this short-lived server-side storage
is incompatible with your privacy requirements.

## Deploy

Requirements: a Linux host with Docker Compose, a public DNS name, and inbound
ports 80/443 available for certificate issuance.

```bash
export JARVIS_RELAY_DOMAIN=relay.example.com
docker compose -f relay/compose.yml up -d --build
```

Check `https://relay.example.com/health` before provisioning. The relay
container port is exposed only on the Compose network; Caddy owns public TLS.

## Provision one channel

Run the provisioning CLI in the relay container. The channel ID is a UUID
shared by the desktop and its enrolled devices. Store each token securely; the
CLI prints it only once.

```bash
CHANNEL="$(python -c 'import uuid; print(uuid.uuid4())')"
docker compose -f relay/compose.yml exec relay \
  python -m relay.provision --channel "$CHANNEL" --role desktop \
  --scopes command.send,notification.receive,media.control
docker compose -f relay/compose.yml exec relay \
  python -m relay.provision --channel "$CHANNEL" --role device \
  --scopes command.send,notification.receive,media.control
```

Use the returned channel ID, principal ID and token in the Android app's
**Secure Remote Relay** configuration. Configure the desktop with its own
principal ID and token and instantiate
`relay.desktop_bridge.DesktopRelayBridge` with an application-owned callback.
The desktop connector reconnects with bounded exponential backoff and can be
stopped explicitly.

## Security operations

- Use `https://` / `wss://` only; the Compose deployment does not publish the
  relay's internal port.
- The broker checks the sender scope and the receiving principal's scope for
  every forwarded message.
- Message envelopes are limited to 32 KB; the broker applies a per-principal
  rate limit and reauthenticates credentials during the connection.
- Keep the relay database volume private and back it up with host-level access
  controls.
- Provision separate least-privilege credentials for every device.
- Revoke lost credentials with the trusted CLI:
  `docker compose -f relay/compose.yml exec relay python -m relay.revoke --channel "$CHANNEL" --principal-id "$PRINCIPAL_ID"`.
- Never place relay tokens in QR codes, URLs, app logs or source control.
- Self-hosted SQLite mode does not persist message bodies. Vercel mode uses the
  separately documented 20-second bounded delivery queue for cross-instance
  handoff; queued payloads are deleted after delivery or expiry.

## Completion boundary

The relay service, credential registry, provisioning CLI, Docker/Caddy
deployment, desktop connector, and Android WebSocket client are implemented.
The Android client recognizes relay acknowledgements/errors and reconnects
with bounded exponential backoff after serverless function-duration closures;
credential rejection remains terminal until the owner refreshes credentials.
Authenticated incoming events now reach the desktop application's
metadata-only event callback and appear in the desktop event panel. The relay
runtime sends only event type, device ID, and receive timestamp to that
callback; payload contents, tokens, audio, and image data are not forwarded to
the desktop UI through this path.

Remote `command` events are surfaced as requests for owner review. They are
not translated into assistant prompts or executed automatically. The only
automatic command response remains the fixed `assistant.ping` → 
`assistant.pong` reachability check.

Deployment to an owner-controlled host and cross-network end-to-end testing
still require operator configuration and physical-device acceptance. Do not
call the relay production-live until those steps have been completed.
