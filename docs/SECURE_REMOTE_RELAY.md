# Phase 10 — Secure remote relay

## Architecture

The relay is an optional, stateless message broker in `relay/`. Both desktop
and mobile clients make outbound WebSocket connections over TLS. The desktop
does not open a public inbound control port. Deploy the service behind Caddy
(or another correctly configured TLS reverse proxy).

The relay forwards validated, bounded JSON envelopes only between a desktop
principal and device principals that share a channel. It does not interpret
commands, persist messages, store raw credentials, or log message bodies.

## Deploy

Requirements: a Linux host with Docker Compose, a public DNS name, and inbound
ports 80/443 available for certificate issuance.

```bash
export JARVIS_RELAY_DOMAIN=relay.example.com
docker compose -f relay/compose.yml up -d --build
```

Check `https://relay.example.com/health` before provisioning.

## Provision one channel

Run the provisioning CLI in the relay container. The channel ID is a UUID
shared by the desktop and its enrolled devices. Store each token securely;
the CLI prints it only once.

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
principal ID and token and instantiate `relay.desktop_bridge.DesktopRelayBridge`
with an application-owned callback. The desktop connector reconnects with
bounded exponential backoff and sends only to a target device in its channel.

## Security operations

- Use `https://` / `wss://` only; the Compose deployment does not publish the
  relay's internal port.
- Keep the relay database volume private and back it up with host-level access
  controls.
- Provision separate, least-privilege credentials for every device.
- Revoke lost credentials with the trusted CLI: `docker compose -f relay/compose.yml exec relay python -m relay.revoke --channel "$CHANNEL" --principal-id "$PRINCIPAL_ID"`.
- Never place relay tokens in QR codes, URLs, app logs or source control.
- Messages are ephemeral; disconnected peers receive no stored backlog.
- Add monitoring, firewall restrictions, backups and an operator-controlled
  credential revocation process before production use.

This stage supplies the relay server, credential registry, provisioning CLI,
Docker/Caddy deployment, desktop connector and Android WebSocket client. It
still requires deployment to a host controlled by the project owner and
end-to-end testing across separate networks before it should be considered
production-ready.
