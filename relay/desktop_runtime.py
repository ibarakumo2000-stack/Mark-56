"""Threaded lifecycle wrapper for the optional desktop relay connector.

The dashboard can start/stop this runtime without blocking its ASGI event loop.
Incoming event metadata is kept in a small in-memory queue; payloads are never
persisted or automatically executed by this wrapper.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any

from relay.desktop_bridge import DesktopRelayBridge


class DesktopRelayRuntime:
    def __init__(self, *, event_limit: int = 100, on_event=None):
        self._event_limit = max(1, min(int(event_limit), 500))
        self._events: deque[dict[str, Any]] = deque(maxlen=self._event_limit)
        self._events_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bridge: DesktopRelayBridge | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            self._state = state

    def _record_message(self, message: dict) -> None:
        event = {
            "received_at": int(time.time()),
            "type": message.get("type", "unknown"),
            "device_id": message.get("device_id", ""),
        }
        with self._events_lock:
            self._events.append(event)

        # Forward only the safe metadata projection to the application. The
        # remote payload (which may contain private text/media or commands) is
        # deliberately not passed to the UI callback or persisted here.
        callback = self._on_event
        if callback is not None:
            try:
                callback(dict(event))
            except Exception:
                # A UI/host callback must never terminate the relay receive loop.
                pass

        # The only automatic response is a harmless reachability pong. The
        # transport never executes remote actions or forwards arbitrary commands.
        payload = message.get("payload")
        if (
            message.get("type") == "command"
            and isinstance(payload, dict)
            and payload.get("action") == "assistant.ping"
        ):
            bridge = self._bridge
            device_id = message.get("device_id")
            if bridge is not None and isinstance(device_id, str) and device_id:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(bridge.send_to_device(
                        device_id, "command", {"action": "assistant.pong"}
                    ))
                except RuntimeError:
                    pass

    def _run(self, *, base_url: str, channel_id: str, principal_id: str, token: str) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            bridge = DesktopRelayBridge(
                base_url=base_url,
                channel_id=channel_id,
                principal_id=principal_id,
                token=token,
                on_message=self._record_message,
                on_state=self._set_state,
            )
            self._bridge = bridge
            self._set_state("connecting")
            async def run_bridge():
                # Signal only after the event loop is actively executing.
                self._ready.set()
                await bridge.run_forever()

            task = loop.create_task(run_bridge())
            loop.run_until_complete(task)
        except Exception:
            self._set_state("error")
            self._ready.set()
        finally:
            self._bridge = None
            self._loop = None
            self._set_state("stopped" if self._state != "error" else "error")
            loop.close()

    def start(self, *, base_url: str, channel_id: str, principal_id: str, token: str) -> str:
        if self._thread is not None and self._thread.is_alive():
            return self.status()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run,
            kwargs={
                "base_url": base_url, "channel_id": channel_id,
                "principal_id": principal_id, "token": token,
            },
            name="jarvis-desktop-relay",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(5):
            self._set_state("error")
            raise RuntimeError("Desktop relay did not initialize within five seconds")
        return self.status()

    def status(self) -> str:
        with self._state_lock:
            return self._state

    def stop(self, timeout: float = 5.0) -> str:
        bridge, loop, thread = self._bridge, self._loop, self._thread
        if bridge is not None and loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(bridge.stop(), loop)
            future.result(timeout=timeout)
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is not None and thread.is_alive():
            raise RuntimeError("Desktop relay did not stop cleanly")
        self._thread = None
        self._set_state("stopped")
        return self.status()

    def send_to_device(self, device_id: str, message_type: str, payload: dict[str, Any]) -> None:
        """Send one explicit owner-requested message over the active relay."""
        bridge, loop = self._bridge, self._loop
        if bridge is None or loop is None or not loop.is_running():
            raise ConnectionError("Desktop relay is not connected")
        future = asyncio.run_coroutine_threadsafe(
            bridge.send_to_device(device_id, message_type, payload), loop
        )
        future.result(timeout=10.0)

    def drain_events(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._events_lock:
            events = list(self._events)[-limit:]
            self._events.clear()
        return events
