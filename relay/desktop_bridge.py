"""Outbound-only desktop connector for the JARVIS relay.

The desktop opens a wss:// connection; it never exposes a public control port.
The application supplies an event callback and an explicit relay credential.
"""
from __future__ import annotations
import asyncio
import json
import random
from typing import Awaitable, Callable
from urllib.parse import urlparse

MessageHandler = Callable[[dict], Awaitable[None] | None]
StateHandler = Callable[[str], None]


def relay_websocket_url(base_url: str, channel_id: str, principal_id: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Relay URL must be an HTTPS origin without embedded credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Relay URL must be an origin only")
    import uuid
    try:
        channel_id = str(uuid.UUID(channel_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Channel ID must be a UUID") from exc
    if not principal_id or len(principal_id) > 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in principal_id):
        raise ValueError("Invalid relay identity")
    return f"wss://{parsed.netloc}/v1/connect/{channel_id}/{principal_id}"


class DesktopRelayBridge:
    def __init__(self, *, base_url: str, channel_id: str, token: str,
                 on_message: MessageHandler, principal_id: str | None = None,
                 on_state: StateHandler | None = None):
        import uuid
        try:
            channel_id = str(uuid.UUID(channel_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Channel ID must be a UUID") from exc
        principal_id = principal_id or f"desktop-{channel_id}"
        self.url = relay_websocket_url(base_url, channel_id, principal_id)
        if not token.startswith("rly_"):
            raise ValueError("Invalid relay token")
        self.token = token
        self.on_message = on_message
        self.on_state = on_state
        self._stop = asyncio.Event()
        self._socket = None

    def _notify_state(self, state: str) -> None:
        if self.on_state is not None:
            try:
                self.on_state(state)
            except Exception:
                pass

    async def run_forever(self) -> None:
        self._notify_state("connecting")
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to enable remote relay transport") from exc
        delay = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url, extra_headers={"Authorization": f"Bearer {self.token}"},
                    open_timeout=10, close_timeout=5, max_size=32768,
                    ping_interval=20, ping_timeout=20,
                ) as socket:
                    self._socket = socket
                    self._notify_state("connected")
                    delay = 1.0
                    async for raw in socket:
                        try:
                            message = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(message, dict) or message.get("type") in {"ack", "error"}:
                            continue
                        if message.get("type") not in {
                            "command", "notification", "media", "battery",
                            "display", "voice", "camera",
                        }:
                            continue
                        if not isinstance(message.get("device_id"), str) or not message["device_id"] or len(message["device_id"]) > 80:
                            continue
                        if not isinstance(message.get("payload"), dict):
                            continue
                        result = self.on_message(message)
                        if asyncio.iscoroutine(result):
                            await result
            except asyncio.CancelledError:
                raise
            except Exception:
                self._notify_state("reconnecting")
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=delay + random.uniform(0, delay * 0.15)
                    )
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 60.0)
            finally:
                self._socket = None
                if not self._stop.is_set():
                    self._notify_state("disconnected")

    async def send_to_device(self, device_id: str, message_type: str, payload: dict) -> None:
        if self._socket is None:
            raise ConnectionError("JARVIS relay is not connected")
        if message_type not in {"command", "notification", "media", "battery", "display", "voice", "camera"}:
            raise ValueError("Unsupported relay message type")
        if not isinstance(device_id, str) or not device_id or len(device_id) > 80:
            raise ValueError("Invalid target device identity")
        if not isinstance(payload, dict):
            raise ValueError("Relay payload must be an object")
        encoded = json.dumps({
            "type": message_type, "target_device_id": device_id, "payload": payload,
        }, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 32_768:
            raise ValueError("Relay message exceeds the 32 KB limit")
        await self._socket.send(encoded)

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            await self._socket.close()
        self._notify_state("stopped")
