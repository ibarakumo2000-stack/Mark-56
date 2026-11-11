"""Authenticated WebSocket relay with SQLite-local and PostgreSQL-shared routing.

The PostgreSQL backend stores credentials durably and keeps short-lived,
bounded delivery envelopes so WebSocket peers connected to different Vercel
instances can still exchange messages. Local/self-hosted SQLite mode remains
in-memory routed and never persists message bodies.
"""
from __future__ import annotations

import asyncio
import jsonimport time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from relay.registry import RelayAuthError
from relay.registry_factory import build_registry

MAX_MESSAGE_BYTES = 32_768
MAX_RATE = 60
RATE_WINDOW = 60
QUEUE_TTL_SECONDS = 20
QUEUE_POLL_SECONDS = 0.5
SCOPE_BY_TYPE = {
    "command": "command.send",
    "notification": "notification.receive",
    "media": "media.control",
    "battery": "battery.read",
    "display": "display.render",
    "voice": "voice.capture",
    "camera": "camera.capture",
}


def _build_registry(environ: dict[str, str] | None = None):
    return build_registry(environ)


def create_relay_app(registry: RelayRegistry | None = None) -> FastAPI:
    db = registry or _build_registry()
    app = FastAPI(title="JARVIS Secure Relay", docs_url=None, redoc_url=None, openapi_url=None)
    peers: dict[tuple[str, str], WebSocket] = {}
    desktop_peers: dict[str, WebSocket] = {}
    desktop_peer_tokens: dict[str, str] = {}
    peer_tokens: dict[tuple[str, str], str] = {}
    rate: dict[tuple[str, str], deque[float]] = defaultdict(deque)
    shared_queue = all(
        callable(getattr(db, name, None))
        for name in ("lookup_principal", "find_active_principal", "enqueue_message",
                     "claim_messages", "ack_message", "release_message")
    )

    @app.get("/health")
    async def health():
        try:
            ready = db.healthcheck()
        except Exception:
            ready = False
        if not ready:
            raise HTTPException(status_code=503, detail="Relay database unavailable")
        return {
            "service": "jarvis-relay",
            "status": "ready",
            "database": "ready",
            "cross_instance_delivery": shared_queue,
            "version": 2,
        }

    @app.websocket("/v1/connect/{channel_id}/{principal_id}")
    async def connect(websocket: WebSocket, channel_id: str, principal_id: str):
        auth = websocket.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            await websocket.close(code=4401, reason="Authentication required")
            return
        token = auth[7:]
        try:
            identity = db.authenticate(token)
        except RelayAuthError:
            await websocket.close(code=4401, reason="Invalid relay credential")
            return
        if identity["channel_id"] != channel_id or identity["principal_id"] != principal_id:
            await websocket.close(code=4403, reason="Relay identity mismatch")
            return
        if websocket.url.scheme != "wss" and websocket.client and websocket.client.host not in {
            "127.0.0.1", "::1", "localhost", "testclient"
        }:
            await websocket.close(code=4403, reason="TLS is required")
            return

        await websocket.accept()
        key = (channel_id, principal_id)
        old = desktop_peers.get(channel_id) if identity["role"] == "desktop" else peers.get(key)
        if old is not None:
            try:
                await old.close(code=4001, reason="Replaced by a newer connection")
            except Exception:
                pass
        peers[key] = websocket
        peer_tokens[key] = token
        if identity["role"] == "desktop":
            desktop_peers[channel_id] = websocket
            desktop_peer_tokens[channel_id] = token

        async def deliver_queued():
            """Poll the shared short-lived queue for messages addressed here."""
            last_cleanup = 0.0
            while True:
                try:
                    db.authenticate(token)
                except RelayAuthError:
                    try:
                        await websocket.close(code=4403, reason="Relay credential revoked")
                    except Exception:
                        pass
                    return
                except Exception:
                    # Database connectivity may flap during a serverless
                    # instance's lifetime; retry without dropping the socket.
                    await asyncio.sleep(1.0)
                    continue
                try:
                    claims = db.claim_messages(channel_id, principal_id, limit=10)
                    for claim in claims:
                        try:
                            await websocket.send_json(claim["payload"])
                        except Exception:
                            db.release_message(claim["message_id"], claim["claim_token"])
                            return
                        db.ack_message(claim["message_id"], claim["claim_token"])
                    now = time.monotonic()
                    cleanup = getattr(db, "cleanup_expired_messages", None)
                    if cleanup and now - last_cleanup >= 10:
                        cleanup()
                        last_cleanup = now
                except Exception:
                    # A transient database interruption must not kill the
                    # authenticated socket; the claim lease makes retries safe.
                    await asyncio.sleep(1.0)
                    continue
                await asyncio.sleep(QUEUE_POLL_SECONDS)

        queue_task = asyncio.create_task(deliver_queued()) if shared_queue else None
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                except asyncio.TimeoutError:
                    try:
                        db.authenticate(token)
                    except RelayAuthError:
                        await websocket.close(code=4403, reason="Relay credential revoked")
                        break
                    continue
                try:
                    identity = db.authenticate(token)
                except RelayAuthError:
                    await websocket.close(code=4403, reason="Relay credential revoked")
                    break
                if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    await websocket.close(code=4409, reason="Message too large")
                    break
                now = time.monotonic()
                bucket = rate[(channel_id, principal_id)]
                while bucket and bucket[0] <= now - RATE_WINDOW:
                    bucket.popleft()
                if len(bucket) >= MAX_RATE:
                    await websocket.close(code=4429, reason="Rate limit exceeded")
                    break
                bucket.append(now)
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "error": "invalid_json"})
                    continue
                if not isinstance(envelope, dict) or set(envelope) != {
                    "type", "target_device_id", "payload"
                }:
                    await websocket.send_json({"type": "error", "error": "invalid_envelope"})
                    continue
                message_type = envelope["type"]
                if message_type not in SCOPE_BY_TYPE:
                    await websocket.send_json({"type": "error", "error": "unsupported_message_type"})
                    continue
                required_scope = SCOPE_BY_TYPE[message_type]
                if required_scope not in identity["scopes"]:
                    await websocket.send_json({"type": "error", "error": "scope_denied"})
                    continue
                if not isinstance(envelope["payload"], dict):
                    await websocket.send_json({"type": "error", "error": "invalid_payload"})
                    continue

                if identity["role"] == "device":
                    if envelope["target_device_id"] is not None:
                        await websocket.send_json({
                            "type": "error", "error": "device_cannot_select_recipient"
                        })
                        continue
                    recipient = desktop_peers.get(channel_id)
                    recipient_token = desktop_peer_tokens.get(channel_id)
                    try:
                        recipient_identity = db.authenticate(recipient_token) if recipient_token else None
                    except RelayAuthError:
                        recipient_identity = None
                    if recipient_identity is None and shared_queue:
                        recipient_identity = db.find_active_principal(channel_id, "desktop")
                    outbound = {
                        "type": message_type,
                        "device_id": principal_id,
                        "payload": envelope["payload"],
                    }
                else:
                    target = envelope["target_device_id"]
                    if not isinstance(target, str) or not target or len(target) > 80:
                        await websocket.send_json({
                            "type": "error", "error": "target_device_required"
                        })
                        continue
                    recipient_key = (channel_id, target)
                    recipient = peers.get(recipient_key)
                    recipient_token = peer_tokens.get(recipient_key)
                    try:
                        recipient_identity = db.authenticate(recipient_token) if recipient_token else None
                    except RelayAuthError:
                        recipient_identity = None
                    if recipient_identity is None and shared_queue:
                        recipient_identity = db.lookup_principal(channel_id, target)
                    outbound = {"type": message_type, "payload": envelope["payload"]}

                if recipient_identity is None:
                    await websocket.send_json({"type": "error", "error": "peer_offline"})
                    continue
                expected_role = "desktop" if identity["role"] == "device" else "device"
                if recipient_identity["role"] != expected_role:
                    await websocket.send_json({"type": "error", "error": "invalid_recipient_role"})
                    continue
                if required_scope not in recipient_identity["scopes"]:
                    await websocket.send_json({"type": "error", "error": "recipient_scope_denied"})
                    continue

                if recipient is None and shared_queue:
                    try:
                        db.enqueue_message(
                            channel_id=channel_id,
                            sender_principal_id=principal_id,
                            recipient_principal_id=recipient_identity["principal_id"],
                            payload=outbound,
                            ttl_seconds=QUEUE_TTL_SECONDS,
                        )
                        await websocket.send_json({
                            "type": "ack", "accepted": True, "queued": True
                        })
                    except Exception:
                        await websocket.send_json({
                            "type": "error", "error": "delivery_unavailable"
                        })
                    continue
                if recipient is None:
                    await websocket.send_json({"type": "error", "error": "peer_offline"})
                    continue
                try:
                    await recipient.send_json(outbound)
                    await websocket.send_json({"type": "ack", "delivered": True})
                except Exception:
                    if shared_queue:
                        try:
                            db.enqueue_message(
                                channel_id=channel_id,
                                sender_principal_id=principal_id,
                                recipient_principal_id=recipient_identity["principal_id"],
                                payload=outbound,
                                ttl_seconds=QUEUE_TTL_SECONDS,
                            )
                            await websocket.send_json({
                                "type": "ack", "accepted": True, "queued": True
                            })
                        except Exception:
                            await websocket.send_json({
                                "type": "error", "error": "delivery_failed"
                            })
                    else:
                        await websocket.send_json({
                            "type": "error", "error": "delivery_failed"
                        })
        except WebSocketDisconnect:
            pass
        finally:
            if queue_task is not None:
                queue_task.cancel()
                try:
                    await queue_task
                except asyncio.CancelledError:
                    pass
            if peers.get(key) is websocket:
                peers.pop(key, None)
                peer_tokens.pop(key, None)
            if identity["role"] == "desktop" and desktop_peers.get(channel_id) is websocket:
                desktop_peers.pop(channel_id, None)
                desktop_peer_tokens.pop(channel_id, None)

    app.state.relay_registry = db
    app.state.relay_peers = peers
    app.state.relay_desktop_peers = desktop_peers
    app.state.relay_shared_queue = shared_queue
    return app


app = create_relay_app()
