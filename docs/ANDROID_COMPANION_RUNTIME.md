# Mark 56 Android Companion Runtime (Phase 7)

## What this phase adds

- An opt-in FastAPI HTTPS service factory in `core/device_companion_server.py`.
- One-time QR-pairing-code redemption at `POST /v1/pair`. The phone receives its bearer token exactly once; the desktop registry stores only its hash.
- Authenticated notification and battery ingestion using the existing HMAC-SHA256 message envelope, timestamp freshness checks, nonce replay protection, and per-device scopes.
- Authenticated `POST /v1/media/next` polling and a desktop-only in-process command enqueue function. There is deliberately no network endpoint that lets a phone submit a media command to itself.
- Bounded request bodies and bounded per-device media command queues.
- A stoppable Uvicorn server wrapper that requires TLS certificate/key files and an explicit IP bind address.

## Security and lifecycle

Importing the module or calling `create_companion_app` does **not** open a socket. The application must explicitly create a `CompanionServer` and call `start()` after the owner enables pairing. Use a certificate whose Subject Alternative Name contains the desktop LAN IP. The QR payload must carry the SHA-256 certificate fingerprint from `certificate_fingerprint(cert_path)`; the Android client must pin that exact certificate before sending the pairing code or token.

Do not bind to `0.0.0.0` or `::`; bind only to the specific LAN interface the owner selected. Keep the firewall limited to the chosen port and trusted local network. Stop the server when pairing/device connectivity is disabled. Never log pairing codes, bearer tokens, notification contents, or signed request bodies.

The desktop app should create the pairing offer only after the owner reviews and approves the requested scopes. Generate the QR data with `build_pairing_payload` from `core.device_companion`, and show the approved scopes separately in the UI. The phone must request a subset of those approved scopes.

## Minimal desktop integration

```python
from core.device_companion_server import (
    CompanionServer, certificate_fingerprint, create_companion_app,
)
from core.device_gateway import DeviceRegistry

registry = DeviceRegistry("~/.local/share/mark56/devices.sqlite3")
app = create_companion_app(registry)
server = CompanionServer(
    app,
    host="192.168.1.20",  # selected desktop LAN IP, not a wildcard
    port=8765,
    certificate="~/.local/share/mark56/companion-cert.pem",
    private_key="~/.local/share/mark56/companion-key.pem",
)
# Call server.start() only after the user enables the companion bridge.
# Call server.stop() when disabled or during application shutdown.
print(certificate_fingerprint("~/.local/share/mark56/companion-cert.pem"))
```

The example assumes the certificate and key have already been provisioned securely. Do not commit private keys or device database files.

## API contract

- `GET /health`: service readiness only; no device details.
- `POST /v1/pair`: JSON fields `pairing_code`, `device_name`, `platform`, `capabilities`, `requested_scopes`. HTTPS certificate pinning is mandatory on the client. Pairing code is one-use and expires according to the existing registry offer.
- `POST /v1/notifications`: signed message envelope in the JSON body, bearer token in Authorization header; requires `notification.receive`.
- `POST /v1/battery`: signed message envelope; requires `battery.read`.
- `POST /v1/media/next`: signed request envelope for this exact route; requires `media.control`; returns one queued command or null.

## Remaining work before calling the phone integration production-ready

This commit is the desktop HTTPS runtime and API contract, not a finished Android application. Still required: Android Kotlin app and QR scanner, Android Keystore token storage, certificate-pinned HTTP client, notification-listener permission onboarding, Android battery reporting, Android MediaSession command execution, UI lifecycle integration, real-device tests, certificate provisioning/rotation UX, and installer packaging. The desktop UI does not yet start/stop this service automatically. The feature must remain disabled until those pieces are connected and tested.
