"""Minimal, authenticated, non-persistent WebSocket relay.

Deploy behind a TLS reverse proxy and use wss://. The relay does not store
message bodies, expose a public desktop listener, or interpret user commands.
"""
from __future__ import annotations
import json
import os
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from relay.registry import RelayAuthError, RelayRegistry

MAX_MESSAGE_BYTES = 32_768
MAX_RATE = 60
RATE_WINDOW = 60
SCOPE_BY_TYPE = {
    "command": "command.send",
    "notification": "notification.receive",
    "media": "media.control",
    "battery": "battery.read",
    "display": "display.render",
    "voice": "voice.capture",
    "camera": "camera.capture",
}


def create_relay_app(registry: RelayRegistry | None = None) -> FastAPI:
    db = registry or RelayRegistry(os.environ.get("JARVIS_RELAY_DATABASE", "relay-data/relay.sqlite3"))
    app = FastAPI(title="JARVIS Secure Relay", docs_url=None, redoc_url=None, openapi_url=None)
    peers: dict[tuple[str, str], WebSocket] = {}
    rate: dict[str, deque[float]] = defaultdict(deque)

    @app.get("/health")
    async def health():
        return {"service": "jarvis-relay", "status": "ready", "version": 1}

    @app.websocket("/v1/connect/{channel_id}/{principal_id}")
    async def connect(websocket: WebSocket, channel_id: str, principal_id: str):
        auth = websocket.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            await websocket.close(code=4401, reason="Authentication required")
            return
        try:
            identity = db.authenticate(auth[7:])
        except RelayAuthError:
            await websocket.close(code=4401, reason="Invalid relay credential")
            return
        if identity["channel_id"] != channel_id or identity["principal_id"] != principal_id:
            await websocket.close(code=4403, reason="Relay identity mismatch")
            return
        if websocket.url.scheme != "wss" and websocket.client and websocket.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            await websocket.close(code=4403, reason="TLS is required")
            return
        await websocket.accept()
        key = (channel_id, principal_id)
        old = peers.get(key)
        if old is not None:
            try:
                await old.close(code=4001, reason="Replaced by a newer connection")
            except Exception:
                pass
        peers[key] = websocket
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                except asyncio.TimeoutError:
                    try:
                        identity = db.authenticate(auth[7:])
                    except RelayAuthError:
                        await websocket.close(code=4403, reason="Relay credential revoked")
                        break
                    continue
                try:
                    identity = db.authenticate(auth[7:])
                except RelayAuthError:
                    await websocket.close(code=4403, reason="Relay credential revoked")
                    break
                if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    await websocket.close(code=4409, reason="Message too large")
                    break
                now = time.monotonic()
                bucket = rate[principal_id]
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
                if not isinstance(envelope, dict) or set(envelope) != {"type", "target_device_id", "payload"}:
                    await websocket.send_json({"type": "error", "error": "invalid_envelope"})
                    continue
                message_type = envelope["type"]
                if message_type not in SCOPE_BY_TYPE:
                    await websocket.send_json({"type": "error", "error": "unsupported_message_type"})
                    continue
                if SCOPE_BY_TYPE[message_type] not in identity["scopes"]:
                    await websocket.send_json({"type": "error", "error": "scope_denied"})
                    continue
                if not isinstance(envelope["payload"], dict):
                    await websocket.send_json({"type": "error", "error": "invalid_payload"})
                    continue
                if identity["role"] == "device":
                    if envelope["target_device_id"] is not None:
                        await websocket.send_json({"type": "error", "error": "device_cannot_select_recipient"})
                        continue
                    recipient = peers.get((channel_id, "desktop"))
                    outbound = {"type": message_type, "device_id": principal_id, "payload": envelope["payload"]}
                else:
                    target = envelope["target_device_id"]
                    if not isinstance(target, str) or not target or len(target) > 80:
                        await websocket.send_json({"type": "error", "error": "target_device_required"})
                        continue
                    recipient = peers.get((channel_id, target))
                    outbound = {"type": message_type, "payload": envelope["payload"]}
                if recipient is None:
                    await websocket.send_json({"type": "error", "error": "peer_offline"})
                    continue
                try:
                    await recipient.send_json(outbound)
                    await websocket.send_json({"type": "ack", "delivered": True})
                except Exception:
                    await websocket.send_json({"type": "error", "error": "delivery_failed"})
        except WebSocketDisconnect:
            pass
        finally:
            if peers.get(key) is websocket:
                peers.pop(key, None)

    app.state.relay_registry = db
    app.state.relay_peers = peers
    return app


app = create_relay_app()
