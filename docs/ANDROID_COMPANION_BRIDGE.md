# Mark 56 Android Companion Bridge — Phase 5

## What this phase delivers

The desktop core now has transport-neutral message authentication and pairing
payload primitives in `core/device_companion.py`. An Android companion can use
these rules to authenticate requests to a desktop bridge without sending device
credentials as a bearer token on every request.

This phase does **not** ship a Play Store-ready Android application or start a
desktop network listener. The desktop application must explicitly own listener
startup, TLS certificate lifecycle, firewall prompts, and shutdown.

## Pairing flow

1. The desktop creates a short-lived, single-use pairing offer through
   `DeviceRegistry.create_pairing_offer()`.
2. The UI displays every requested permission scope and obtains explicit owner
   approval before generating the offer.
3. The desktop creates a QR payload with `build_pairing_payload()`. It contains
   an HTTPS endpoint, the one-time code, expiry, and SHA-256 certificate
   fingerprint. Never generate a QR payload for plain HTTP.
4. The Android user scans the QR and confirms the desktop certificate
   fingerprint. The phone redeems the one-time code through the future
   enrollment endpoint. The returned device token is shown only once and is
   stored in Android Keystore-backed encrypted storage.
5. The desktop records the phone as an `android` device with only the scopes
   approved by the owner. The pairing code expires and cannot be reused.

## Authenticated request format

The client and server sign the same canonical UTF-8 JSON object, serialized
with sorted keys, compact separators, no NaN/Infinity values, and unescaped
Unicode:

- `version`: integer `1`
- `device_id`: enrolled device UUID
- `method`: uppercase HTTP method (GET, POST, PUT, DELETE)
- `path`: absolute path beginning with one slash; no query or fragment
- `timestamp`: Unix seconds
- `nonce`: unique URL-safe random value (20–96 characters)
- `body`: JSON value, maximum 16 KiB

The HMAC key is SHA-256 of UTF-8 `mark56-companion-v1:` followed by the
device token. The signature is lowercase hexadecimal HMAC-SHA256 over the
canonical object. The signature itself is not included in the signed object.

The desktop verifies the enrolled device and requested permission scope,
checks the signature with constant-time comparison, enforces a 60-second
clock-skew window, and rejects nonce reuse. The verifier has a bounded in-memory
replay cache; a production multi-process bridge must use a shared atomic replay
store.

## Security requirements before enabling the network bridge

- Bind only to an explicitly selected private LAN interface; never expose the
  bridge to the public internet by default.
- Require TLS and certificate pinning using the fingerprint in the QR payload.
- Do not disable hostname/certificate validation as a fallback.
- Do not log pairing codes, device tokens, message bodies, or signatures.
- Require explicit scope approval and provide immediate device revocation.
- Keep camera, microphone, location, health, and desktop-control permissions
  separate; none are implied by Android enrollment.
- Rate-limit pairing attempts and reject expired or reused codes.
- Do not automatically retry non-idempotent commands.
- Provide a visible connected indicator and a one-click disconnect/revoke action.
- Keep phone-to-desktop notifications and media controls opt-in.

## Current implementation boundary

Implemented: canonical request signing, strict route/body validation, HMAC
verification, device-token and scope checks, timestamp freshness, nonce replay
protection, and HTTPS QR-payload validation.

Still required for a complete end-to-end Android release: the Android app UI,
Keystore storage implementation, TLS-pinned HTTP client, desktop HTTPS listener
and enrollment routes, Android runtime permission UX, background-service
lifecycle, and physical-device integration tests. These are intentionally not
faked by this core module.
