"""Authenticated FastAPI routes and desktop lifecycle for the JARVIS device gateway."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import io
import json
import socket
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from core.device_gateway import (
    AuthorizationError, DeviceRegistry, PairingError, PERMISSION_SCOPES,
)

_MEDIA_ACTIONS = frozenset({"play", "pause", "play_pause", "next", "previous", "stop"})
_COMPANION_PORT = 8765
_ONLINE_WINDOW = 45


def _is_secure_or_loopback(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    client_host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        return client_host.lower() == "localhost"


def build_device_router(
    registry: DeviceRegistry,
    *,
    owner_auth: Callable[[Request], bool],
) -> APIRouter:
    """Create owner-only device management routes.

    The companion listener is created only after an authenticated owner explicitly
    starts it. It binds to the private LAN IP used by the dashboard, never a
    wildcard address, and requires the dashboard's TLS certificate.
    """
    router = APIRouter()
    attempts: dict[str, deque[float]] = defaultdict(deque)
    attempts_lock = asyncio.Lock()
    companion_server = None
    companion_app = None
    companion_endpoint = None
    companion_fingerprint = None

    def _owner(request: Request) -> bool:
        return bool(owner_auth(request))

    def _secure(request: Request):
        if not _is_secure_or_loopback(request):
            return JSONResponse(
                {"error": "HTTPS is required for device enrollment and credentials."},
                status_code=426,
            )
        return None

    async def _rate_limited(request: Request) -> bool:
        host = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with attempts_lock:
            bucket = attempts[host]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 10:
                return True
            bucket.append(now)
        return False

    @router.get("/devices")
    async def devices_page():
        # Browser navigations cannot attach the dashboard bearer header. The
        # page itself checks sessionStorage and every data/action route remains
        # owner-authenticated.
        page = Path(__file__).parent / "static" / "devices.html"
        if not page.is_file():
            return JSONResponse({"error": "Device management UI is unavailable."}, status_code=503)
        return FileResponse(str(page), media_type="text/html")

    @router.get("/api/devices/companion")
    async def companion_status(request: Request):
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return JSONResponse({
            "running": companion_server is not None,
            "endpoint": companion_endpoint,
            "port": _COMPANION_PORT,
        })

    @router.post("/api/devices/companion/start")
    async def start_companion(request: Request):
        nonlocal companion_server, companion_app, companion_endpoint, companion_fingerprint
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if companion_server is not None:
            return JSONResponse({"ok": True, "running": True, "endpoint": companion_endpoint})
        host = request.url.hostname or ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return JSONResponse({"error": "Open the dashboard using its numeric LAN IP before starting pairing."}, status_code=400)
        if address.is_loopback or not address.is_private:
            return JSONResponse({"error": "The companion listener can bind only to a private LAN IP."}, status_code=400)
        root = Path(__file__).resolve().parent.parent
        certificate = root / "config" / "certs" / "jarvis.crt"
        private_key = root / "config" / "certs" / "jarvis.key"
        if not certificate.is_file() or not private_key.is_file():
            return JSONResponse({"error": "TLS certificate is unavailable. Start the HTTPS dashboard first."}, status_code=503)
        try:
            from core.device_companion_server import (
                CompanionServer, certificate_fingerprint, create_companion_app,
            )
            app = create_companion_app(registry)
            server = CompanionServer(
                app, host=str(address), port=_COMPANION_PORT,
                certificate=certificate, private_key=private_key,
            )
            server.start()
            ready = False
            for _ in range(30):
                try:
                    with socket.create_connection((str(address), _COMPANION_PORT), timeout=0.2):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.1)
            if not ready:
                server.stop()
                raise RuntimeError("Companion listener did not become ready; check port 8765 and the local firewall.")
            companion_app = app
            companion_server = server
            companion_endpoint = f"https://{address}:{_COMPANION_PORT}"
            companion_fingerprint = certificate_fingerprint(certificate)
        except (OSError, RuntimeError, ValueError) as exc:
            return JSONResponse({"error": f"Could not start the secure companion listener: {exc}"}, status_code=503)
        return JSONResponse({"ok": True, "running": True, "endpoint": companion_endpoint})

    @router.post("/api/devices/companion/stop")
    async def stop_companion(request: Request):
        nonlocal companion_server, companion_app, companion_endpoint, companion_fingerprint
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if companion_server is not None:
            companion_server.stop()
        companion_server = companion_app = companion_endpoint = companion_fingerprint = None
        return JSONResponse({"ok": True, "running": False})

    @router.post("/api/devices/pairing-offers")
    async def create_pairing_offer(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if companion_server is None:
            return JSONResponse({"error": "Start the secure companion listener before creating a pairing offer."}, status_code=409)
        try:
            from core.device_companion import build_pairing_payload
            body = await request.json()
            scopes = body.get("scopes", [])
            expires_in = body.get("expires_in", 300)
            offer = registry.create_pairing_offer(scopes, expires_in=expires_in)
            payload = build_pairing_payload(
                pairing_code=offer.code, expires_at=offer.expires_at,
                desktop_endpoint=companion_endpoint,
                desktop_fingerprint=companion_fingerprint,
            )
            qr_data_uri = None
            try:
                import qrcode
                image = qrcode.make(json.dumps(payload, separators=(",", ":")))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                qr_data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            except ImportError:
                pass
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({
            "ok": True, "code": offer.code, "expires_at": offer.expires_at,
            "approved_scopes": list(offer.approved_scopes),
            "pairing_payload": payload,
            "qr_data_uri": qr_data_uri,
        })

    @router.post("/api/devices/enroll")
    async def enroll_device(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if await _rate_limited(request):
            return JSONResponse(
                {"error": "Too many pairing attempts. Try again in one minute."},
                status_code=429,
            )
        try:
            body = await request.json()
            device = registry.redeem_pairing_code(
                body.get("code", ""),
                device_name=body.get("device_name", ""),
                device_type=body.get("device_type", ""),
                platform=body.get("platform", ""),
                capabilities=body.get("capabilities", []),
                requested_scopes=body.get("requested_scopes", []),
            )
        except PairingError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({
            "ok": True,
            "device": {
                "device_id": device.device_id, "device_name": device.device_name,
                "device_type": device.device_type, "platform": device.platform,
                "capabilities": list(device.capabilities), "scopes": list(device.scopes),
            },
            "device_token": device.token,
        })

    @router.get("/api/devices")
    async def list_devices(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        now = time.time()
        devices = registry.list_devices()
        for device in devices:
            seen = device.get("last_seen")
            device["online"] = bool(seen and now - seen <= _ONLINE_WINDOW)
        return JSONResponse({"devices": devices})

    @router.put("/api/devices/{device_id}/scopes")
    async def update_device_scopes(device_id: str, request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
            scopes = body.get("scopes")
            if not isinstance(scopes, list):
                raise ValueError("Scopes must be a list")
            updated = registry.update_device_scopes(device_id, scopes)
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not updated:
            return JSONResponse({"error": "Device not found or already revoked."}, status_code=404)
        return JSONResponse({"ok": True, "device_id": device_id, "scopes": sorted(set(scopes))})

    @router.delete("/api/devices/{device_id}")
    async def revoke_device(device_id: str, request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if not registry.revoke_device(device_id):
            return JSONResponse({"error": "Device not found or already revoked."}, status_code=404)
        return JSONResponse({"ok": True, "revoked": True, "device_id": device_id})

    @router.post("/api/devices/{device_id}/media")
    async def send_media_command(device_id: str, request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if companion_app is None:
            return JSONResponse({"error": "Start the companion listener first."}, status_code=409)
        try:
            body = await request.json()
            action = body.get("action")
            if action not in _MEDIA_ACTIONS:
                return JSONResponse({"error": "Unsupported media action."}, status_code=400)
            device = next((item for item in registry.list_devices()
                           if item["device_id"] == device_id), None)
            if device is None:
                return JSONResponse({"error": "Device not found or revoked."}, status_code=404)
            if "media.control" not in device["scopes"]:
                return JSONResponse({"error": "This device has not been granted media.control."}, status_code=403)
            queue = companion_app.state.media_commands[device_id]
            if len(queue) >= 32:
                return JSONResponse({"error": "Device command queue is full."}, status_code=429)
            queue.append({
                "version": 1, "device_id": device_id,
                "type": "media_control", "action": action, "created_at": int(time.time()),
            })
            return JSONResponse({"ok": True, "queued": True, "action": action})
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "Invalid command request."}, status_code=400)

    @router.get("/api/device/me")
    async def device_identity(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        try:
            device = registry.authenticate(token)
        except AuthorizationError:
            return JSONResponse({"error": "Invalid or revoked device credentials."}, status_code=401)
        return JSONResponse({"device": device})

    return router
