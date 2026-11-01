"""Authenticated FastAPI routes for the JARVIS device gateway.

The router is mounted by DashboardServer. Pairing and device credentials are
accepted only over TLS, except for loopback clients used by local development.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from ipaddress import ip_address
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.device_gateway import (
    AuthorizationError,
    DeviceRegistry,
    PairingError,
)


def _is_secure_or_loopback(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    client_host = request.client.host if request.client else ""
    try:
        return ip_address(client_host).is_loopback
    except ValueError:
        return client_host.lower() == "localhost"


def build_device_router(
    registry: DeviceRegistry,
    *,
    owner_auth: Callable[[Request], bool],
) -> APIRouter:
    router = APIRouter()
    attempts: dict[str, deque[float]] = defaultdict(deque)
    attempts_lock = asyncio.Lock()

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

    @router.post("/api/devices/pairing-offers")
    async def create_pairing_offer(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
            scopes = body.get("scopes", [])
            expires_in = body.get("expires_in", 300)
            offer = registry.create_pairing_offer(scopes, expires_in=expires_in)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({
            "ok": True,
            "code": offer.code,
            "expires_at": offer.expires_at,
            "approved_scopes": list(offer.approved_scopes),
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
        # The raw token is returned exactly once; the registry stores only its hash.
        return JSONResponse({
            "ok": True,
            "device": {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "device_type": device.device_type,
                "platform": device.platform,
                "capabilities": list(device.capabilities),
                "scopes": list(device.scopes),
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
        return JSONResponse({"devices": registry.list_devices()})

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
