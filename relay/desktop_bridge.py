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


def relay_websocket_url(base_url: str, channel_id: str, principal_id: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Relay URL must be an HTTPS origin without embedded credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Relay URL must be an origin only")
    if not channel_id or not principal_id or "/" in principal_id:
        raise ValueError("Invalid relay identity")
    return f"wss://{parsed.netloc}/v1/connect/{channel_id}/{principal_id}"


class DesktopRelayBridge:
    def __init__(self, *, base_url: str, channel_id: str, token: str,
                 on_message: MessageHandler, principal_id: str = "desktop"):
        self.url = relay_websocket_url(base_url, channel_id, principal_id)
        if not token.startswith("rly_"):
            raise ValueError("Invalid relay token")
        self.token = token
        self.on_message = on_message
        self._stop = asyncio.Event()
        self._socket = None

    async def run_forever(self) -> None:
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
                    delay = 1.0
                    async for raw in socket:
                        try:
                            message = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(message, dict) or message.get("type") in {"ack", "error"}:
                            continue
                        result = self.on_message(message)
                        if asyncio.iscoroutine(result):
                            await result
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay + random.uniform(0, delay * 0.15))
                delay = min(delay * 2, 60.0)
            finally:
                self._socket = None

    async def send_to_device(self, device_id: str, message_type: str, payload: dict) -> None:
        if self._socket is None:
            raise ConnectionError("JARVIS relay is not connected")
        if message_type not in {"command", "notification", "media", "battery", "display", "voice", "camera"}:
            raise ValueError("Unsupported relay message type")
        if not isinstance(payload, dict):
            raise ValueError("Relay payload must be an object")
        await self._socket.send(json.dumps({
            "type": message_type, "target_device_id": device_id, "payload": payload,
        }, separators=(",", ":")))

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            await self._socket.close()
