"""Persistent GNOME Wayland ScreenCast portal session backed by PipeWire/GStreamer.

This module is optional: it fails with an actionable error if the desktop portal,
PipeWire, or GStreamer Python bindings are unavailable. It never falls back to
cloud capture and never bypasses the desktop's own screen-sharing permission UI.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
import uuid
from typing import Any

_lock = threading.RLock()
_session: "WaylandScreenCast | None" = None


def _unwrap_variants(value):
    """Convert dbus-next Variant wrappers into ordinary Python values."""
    if hasattr(value, "signature") and hasattr(value, "value"):
        return _unwrap_variants(value.value)
    if isinstance(value, dict):
        return {key: _unwrap_variants(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_unwrap_variants(item) for item in value)
    return value


class WaylandScreenCast:
    def __init__(self) -> None:
        self._bus = None
        self._session_handle = None
        self._remote_fd = None
        self._pipeline = None
        self._sink = None
        self._Gst = None
        self._last_frame = None
        self._closed = False
        self._node_id = None

    @staticmethod
    def _portal_call(bus, interface: str, member: str, signature: str, body: list,
                     timeout: float = 35.0) -> tuple[Any, dict]:
        from dbus_next import Message, MessageType
        from dbus_next import Variant
        from dbus_next.aio import MessageBus

        async def call_request():
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            reply = await bus.call(Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface=interface, member=member,
                signature=signature, body=body,
            ))
            if reply.message_type == MessageType.ERROR:
                detail = reply.body[0] if reply.body else "unknown portal error"
                raise RuntimeError(f"{member} failed ({reply.error_name}): {detail}")
            if not reply.body or not isinstance(reply.body[0], str):
                raise RuntimeError(f"{member} did not return a request handle.")
            handle = reply.body[0]
            rule = ("type='signal',sender='org.freedesktop.portal.Desktop',"
                    f"path='{handle}',interface='org.freedesktop.portal.Request',member='Response'")

            def handler(message):
                if (message.message_type == MessageType.SIGNAL and message.path == handle
                    and message.interface == "org.freedesktop.portal.Request"
                    and message.member == "Response" and message.signature == "ua{sv}"):
                    if not future.done():
                        future.set_result((message.body[0], message.body[1]))
                return False

            bus.add_message_handler(handler)
            match = await bus.call(Message(
                destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus", member="AddMatch", signature="s", body=[rule]))
            if match.message_type == MessageType.ERROR:
                bus.remove_message_handler(handler)
                raise RuntimeError(f"Could not subscribe to portal response: {match.body}")
            try:
                code, results = await asyncio.wait_for(future, timeout=timeout)
            finally:
                await bus.call(Message(
                    destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="RemoveMatch", signature="s", body=[rule]))
                bus.remove_message_handler(handler)
            if code != 0:
                reason = "cancelled by user" if code == 1 else f"response code {code}"
                raise RuntimeError(f"ScreenCast permission/request was {reason}.")
            return _unwrap_variants(results), {}

        return asyncio.run(call_request())

    def start(self) -> None:
        from dbus_next import BusType, Message, MessageType, Variant
        from dbus_next.aio import MessageBus

        async def create_session():
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            token = "mark56_" + uuid.uuid4().hex[:16]
            options = {"handle_token": Variant("s", token),
                       "session_handle_token": Variant("s", token + "_session")}
            results, _ = await self._request(
                "org.freedesktop.portal.Session", "CreateSession", "a{sv}", [options])
            handle = results.get("session_handle")
            if not handle:
                raise RuntimeError("ScreenCast portal returned no session handle.")
            self._session_handle = handle
            source_options = {
                "types": Variant("u", 1),  # monitor source
                "multiple": Variant("b", False),
                "cursor_mode": Variant("u", 2),  # embedded cursor
            }
            await self._request(
                "org.freedesktop.portal.ScreenCast", "SelectSources",
                "oa{sv}", [self._session_handle, source_options])
            started, _ = await self._request(
                "org.freedesktop.portal.ScreenCast", "Start",
                "osa{sv}", [self._session_handle, "", {}])
            streams = started.get("streams", [])
            if not streams:
                raise RuntimeError("ScreenCast portal returned no monitor stream.")
            self._node_id = int(streams[0][0])
            remote = await self._bus.call(Message(
                destination="org.freedesktop.portal.Desktop",
                path="/org/freedesktop/portal/desktop",
                interface="org.freedesktop.portal.ScreenCast",
                member="OpenPipeWireRemote",
                signature="oa{sv}", body=[self._session_handle, {}]))
            if remote.message_type == MessageType.ERROR:
                detail = remote.body[0] if remote.body else "unknown error"
                raise RuntimeError(f"OpenPipeWireRemote failed: {detail}")
            if not remote.unix_fds:
                raise RuntimeError("ScreenCast portal returned no PipeWire file descriptor.")
            self._remote_fd = remote.unix_fds[0]
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst, GstVideo
            Gst.init(None)
            self._Gst = Gst
            self._GstVideo = GstVideo
            self._pipeline = Gst.parse_launch(
                "pipewiresrc name=source do-timestamp=true ! "
                "videoconvert ! video/x-raw,format=RGB ! "
                "appsink name=framesink emit-signals=false max-buffers=1 drop=true sync=false"
            )
            source = self._pipeline.get_by_name("source")
            source.set_property("fd", self._remote_fd)
            source.set_property("path", str(self._node_id))
            self._sink = self._pipeline.get_by_name("framesink")
            state = self._pipeline.set_state(Gst.State.PLAYING)
            if state == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("GStreamer could not start the PipeWire capture pipeline.")
            # Wait for the first real frame, but do not leave a session hanging forever.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                sample = self._sink.emit("try-pull-sample", 250 * Gst.MSECOND)
                if sample:
                    self._last_frame = sample
                    return
                message = self._pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                if message:
                    err, debug = message.parse_error()
                    raise RuntimeError(f"PipeWire stream error: {err}; {debug or ''}")
            raise RuntimeError("No video frame arrived from PipeWire within 8 seconds.")

        asyncio.run(create_session())

    async def _request(self, interface: str, member: str, signature: str, body: list):
        from dbus_next import Message, MessageType
        bus = self._bus
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        reply = await bus.call(Message(
            destination="org.freedesktop.portal.Desktop",
            path="/org/freedesktop/portal/desktop",
            interface=interface, member=member, signature=signature, body=body))
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else "unknown portal error"
            raise RuntimeError(f"{member} failed ({reply.error_name}): {detail}")
        handle = reply.body[0]
        rule = ("type='signal',sender='org.freedesktop.portal.Desktop',"
                f"path='{handle}',interface='org.freedesktop.portal.Request',member='Response'")

        def handler(message):
            if (message.message_type == MessageType.SIGNAL and message.path == handle
                and message.interface == "org.freedesktop.portal.Request"
                and message.member == "Response" and message.signature == "ua{sv}"):
                if not future.done():
                    future.set_result((message.body[0], message.body[1]))
            return False

        bus.add_message_handler(handler)
        match = await bus.call(Message(
            destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s", body=[rule]))
        if match.message_type == MessageType.ERROR:
            bus.remove_message_handler(handler)
            raise RuntimeError(f"Could not subscribe to portal response: {match.body}")
        try:
            code, results = await asyncio.wait_for(future, timeout=35)
        finally:
            await bus.call(Message(
                destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus", member="RemoveMatch", signature="s", body=[rule]))
            bus.remove_message_handler(handler)
        if code != 0:
            raise RuntimeError("ScreenCast request was cancelled or denied by the desktop.")
        return results, {}

    def capture_png(self) -> tuple[bytes, int, int]:
        if self._closed or self._sink is None:
            raise RuntimeError("ScreenCast session is not active.")
        sample = self._sink.emit("try-pull-sample", 2 * self._Gst.SECOND)
        if sample is None:
            raise RuntimeError("No fresh frame arrived from the active PipeWire screen stream.")
        self._last_frame = sample
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width, height = structure.get_value("width"), structure.get_value("height")
        buffer = sample.get_buffer()
        ok, mapped = buffer.map(self._Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("Could not read the current PipeWire video frame.")
        try:
            from PIL import Image
            video_info = self._GstVideo.VideoInfo.new_from_caps(caps)
            stride = int(video_info.stride[0])
            image = Image.frombytes("RGB", (width, height), mapped.data, "raw", "RGB", stride, 1)
            out = io.BytesIO()
            image.save(out, format="PNG")
            from plugins.desktop_capture import _decode_png
            return _decode_png(out.getvalue())
        finally:
            buffer.unmap(mapped)

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._pipeline is not None:
                self._pipeline.set_state(self._Gst.State.NULL)
        finally:
            if self._remote_fd is not None:
                try:
                    import os
                    os.close(self._remote_fd)
                except OSError:
                    pass
                self._remote_fd = None
            if self._bus is not None:
                if self._session_handle:
                    try:
                        import subprocess
                        # Use gdbus here because the setup coroutine's event
                        # loop has ended; do not reuse its D-Bus connection on
                        # a different asyncio loop.
                        subprocess.run(
                            ["gdbus", "call", "--session",
                             "--dest", "org.freedesktop.portal.Desktop",
                             "--object-path", self._session_handle,
                             "--method", "org.freedesktop.portal.Session.Close"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=3, check=False,
                        )
                    except Exception:
                        pass
                    self._session_handle = None
                try:
                    self._bus.disconnect()
                except Exception:
                    pass


def start_monitoring() -> str:
    """Request screen-sharing permission and keep one stream active."""
    global _session
    with _lock:
        if _session is not None and not _session._closed:
            return "ScreenCast session is already active."
        stream = WaylandScreenCast()
        try:
            stream.start()
        except Exception:
            stream.stop()
            raise
        _session = stream
        return "ScreenCast session active; GNOME has granted access to the selected monitor."


def capture_monitor_frame() -> tuple[bytes, int, int] | None:
    with _lock:
        stream = _session
    if stream is None or stream._closed:
        return None
    return stream.capture_png()


def monitoring_active() -> bool:
    with _lock:
        return _session is not None and not _session._closed


def stop_monitoring() -> str:
    global _session
    with _lock:
        stream, _session = _session, None
    if stream is None:
        return "No persistent ScreenCast session is active."
    stream.stop()
    return "Persistent ScreenCast session closed."
