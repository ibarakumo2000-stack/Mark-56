"""Authenticated FastAPI routes and desktop lifecycle for the JARVIS device gateway."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import io
import json
import socket
import ssl
import hashlib
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from core.device_gateway import (
    AuthorizationError, DeviceRegistry, PairingError, PERMISSION_SCOPES,
)
from core.glasses_adapters import GlassesAdapterRegistry, GlassesCapability

_MEDIA_ACTIONS = frozenset({"play", "pause", "play_pause", "next", "previous", "stop"})
_COMPANION_PORT = 8765
_ONLINE_WINDOW = 45


def _usable_private_ipv4(value: str) -> bool:
    """Return whether value is a routable private IPv4 interface address."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.version == 4 and address.is_private
        and not address.is_loopback and not address.is_link_local
        and not address.is_multicast and not address.is_unspecified
        and not address.is_reserved
    )


def _discover_private_lan_ipv4() -> str | None:
    """Find a private LAN IPv4 address without depending on internet access."""
    for probe in ("192.168.1.1", "10.0.0.1", "172.16.0.1"):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            continue
        try:
            sock.settimeout(0.5)
            sock.connect((probe, 9))
            candidate = sock.getsockname()[0]
            if _usable_private_ipv4(candidate):
                return candidate
        except OSError:
            pass
        finally:
            sock.close()
    try:
        candidates = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        candidates = []
    for item in candidates:
        candidate = item[4][0]
        if _usable_private_ipv4(candidate):
            return candidate
    return None


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
    on_relay_event: Callable[[dict], None] | None = None,
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
    relay_runtime = None
    relay_config_path = Path.home() / ".jarvis" / "relay.json"
    glasses_runtime = GlassesAdapterRegistry(registry)
    glasses_adapter_registered = False
    glasses_discoveries = {}
    glasses_connected: set[str] = set()
    glasses_config_path = Path.home() / ".jarvis" / "glasses.json"

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
        # The dashboard commonly runs at localhost over its authenticated local
        # session. Do not mistake that browser URL for the LAN interface the
        # phone must reach; discover the computer's private Wi-Fi/Ethernet IPv4.
        requested_host = request.url.hostname or ""
        address_text = requested_host if _usable_private_ipv4(requested_host) else None
        if address_text is None:
            address_text = _discover_private_lan_ipv4()
        if address_text is None:
            return JSONResponse({
                "error": "No usable private LAN IPv4 address was found. Connect this computer and your phone to the same Wi-Fi or Ethernet network, then try again."
            }, status_code=503)
        address = ipaddress.ip_address(address_text)

        root = Path(__file__).resolve().parent.parent
        certificate = root / "config" / "certs" / "jarvis.crt"
        private_key = root / "config" / "certs" / "jarvis.key"
        try:
            # Generate a per-install TLS certificate automatically on first use.
            # dashboard.server adds localhost and the current LAN address to SAN.
            from dashboard.server import _ensure_certs
            if not _ensure_certs() or not certificate.is_file() or not private_key.is_file():
                return JSONResponse({
                    "error": "Could not prepare the local TLS certificate. Install the 'cryptography' package and restart JARVIS."
                }, status_code=503)

            from core.device_companion_server import (
                CompanionServer, certificate_fingerprint, create_companion_app,
            )
            app = create_companion_app(registry)
            server = CompanionServer(
                app, host=str(address), port=_COMPANION_PORT,
                certificate=certificate, private_key=private_key,
            )
            server.start()
            expected_fingerprint = certificate_fingerprint(certificate)
            ready = False
            last_error = None
            for _ in range(40):
                try:
                    # Probe through loopback, not the LAN interface. UFW/firewalld
                    # correctly filters inbound traffic on the Wi-Fi interface, and
                    # that must not prevent the desktop from checking its own listener.
                    # The Android phone still connects to the advertised LAN address;
                    # its access is governed by the narrowly scoped firewall rule.
                    raw_socket = socket.create_connection(("127.0.0.1", _COMPANION_PORT), timeout=0.35)
                    with raw_socket:
                        context = ssl._create_unverified_context()
                        with context.wrap_socket(raw_socket, server_hostname=str(address)) as tls_socket:
                            peer = tls_socket.getpeercert(binary_form=True)
                            actual_fingerprint = ":".join(
                                f"{byte:02x}" for byte in hashlib.sha256(peer).digest()
                            )
                            if actual_fingerprint != expected_fingerprint:
                                raise RuntimeError("Port 8765 is serving a different TLS certificate; stop the conflicting service and retry.")
                            ready = True
                            break
                except (OSError, ssl.SSLError) as exc:
                    last_error = exc
                    time.sleep(0.15)
            if not ready:
                server.stop()
                raise RuntimeError(
                    "The secure listener did not become ready on port 8765. "
                    "Check the local firewall and whether another application is using that port."
                    + (f" ({last_error})" if last_error else "")
                )
            companion_app = app
            companion_server = server
            companion_endpoint = f"https://{address}:{_COMPANION_PORT}"
            companion_fingerprint = expected_fingerprint
        except Exception as exc:
            try:
                if "server" in locals():
                    server.stop()
            except Exception:
                pass
            return JSONResponse({
                "error": f"Could not start the secure companion listener: {type(exc).__name__}: {exc}"
            }, status_code=503)
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
        device = next((item for item in registry.list_devices()
                       if item["device_id"] == device_id), None)
        if device is None:
            return JSONResponse({"error": "Device not found or already revoked."}, status_code=404)
        if device.get("device_type") == "glasses":
            try:
                import keyring
                token = keyring.get_password("mark56-glasses", device_id)
                if token:
                    try:
                        glasses_runtime.disconnect(token)
                    except AuthorizationError:
                        pass
                    keyring.delete_password("mark56-glasses", device_id)
                glasses_connected.discard(device_id)
                try:
                    saved = json.loads(glasses_config_path.read_text(encoding="utf-8"))
                    saved = [item for item in saved if item.get("device_id") != device_id]
                    glasses_config_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                except (OSError, ValueError, TypeError):
                    pass
            except Exception:
                pass
        if not registry.revoke_device(device_id):
            return JSONResponse({"error": "Device not found or already revoked."}, status_code=404)
        glasses_runtime.reconcile_revoked_sessions()
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

    @router.get("/api/devices/wearable-commands")
    async def drain_wearable_commands(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if companion_app is None:
            return JSONResponse({"error": "Start the companion listener first."}, status_code=409)
        try:
            commands = companion_app.state.drain_wearable_commands()
        except (AttributeError, ValueError):
            return JSONResponse({"error": "Wearable command queue is unavailable."}, status_code=503)
        return JSONResponse({"commands": commands})

    @router.get("/api/devices/glasses")
    async def list_glasses(request: Request):
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        config = []
        try:
            if glasses_config_path.is_file():
                config = json.loads(glasses_config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = []
        metadata = {item.get("device_id"): item for item in config if isinstance(item, dict)}
        devices = []
        for item in registry.list_devices():
            if item.get("device_type") != "glasses":
                continue
            saved = metadata.get(item["device_id"], {})
            devices.append({
                "device_id": item["device_id"],
                "device_name": item["device_name"],
                "platform": item["platform"],
                "scopes": item["scopes"],
                "vendor": saved.get("vendor", "Unknown"),
                "model": saved.get("model", "Smart glasses"),
                "connected": item["device_id"] in glasses_connected,
            })
        return JSONResponse({"devices": devices})

    @router.post("/api/devices/glasses/discover")
    async def discover_glasses(request: Request):
        nonlocal glasses_adapter_registered
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            from core.transports.registration import register_optional_glasses_adapters
            if not glasses_adapter_registered:
                registered = register_optional_glasses_adapters(
                    glasses_runtime, enable_ble=True
                )
                if "jarvis.ble.glasses" not in registered:
                    return JSONResponse({
                        "error": "BLE glasses support is unavailable. Install the optional bleak package and enable Bluetooth."
                    }, status_code=503)
                glasses_adapter_registered = True
            body = await request.json()
            timeout = body.get("timeout", 5.0)
            descriptors = glasses_runtime.discover("jarvis.ble.glasses", timeout=timeout)
            glasses_discoveries.clear()
            for descriptor in descriptors:
                if descriptor.device_id:
                    glasses_discoveries[descriptor.device_id] = descriptor
            return JSONResponse({"devices": [{
                "physical_device_id": descriptor.device_id,
                "vendor": descriptor.vendor, "model": descriptor.model,
                "platform": descriptor.platform,
                "capabilities": sorted(capability.value for capability in descriptor.capabilities),
            } for descriptor in descriptors]})
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Glasses discovery failed: " + exc.__class__.__name__}, status_code=503)

    @router.post("/api/devices/glasses/pair")
    async def pair_glasses(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
            physical_id = body.get("physical_device_id", "")
            name = body.get("device_name", "JARVIS smart glasses")
            descriptor = glasses_discoveries.get(physical_id)
            if descriptor is None:
                return JSONResponse({"error": "Scan and select a compatible JARVIS BLE glasses device first."}, status_code=409)
            existing_config = []
            if glasses_config_path.is_file():
                try:
                    existing_config = json.loads(glasses_config_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    existing_config = []
            if any(
                isinstance(item, dict) and item.get("physical_device_id") == physical_id
                for item in existing_config
            ):
                return JSONResponse({"error": "These glasses are already paired. Use the existing device entry to reconnect."}, status_code=409)
            import keyring
            if getattr(keyring.get_keyring(), "priority", 0) <= 0:
                return JSONResponse({"error": "A secure operating-system keyring is required to pair glasses."}, status_code=503)
            offer = registry.create_pairing_offer(("display.render",), expires_in=300)
            device = registry.redeem_pairing_code(
                offer.code, device_name=name, device_type="glasses",
                platform=descriptor.platform,
                capabilities=sorted(capability.value for capability in descriptor.capabilities),
                requested_scopes=("display.render",),
            )
            try:
                keyring.set_password("mark56-glasses", device.device_id, device.token)
                glasses_runtime.connect(
                    device.token, "jarvis.ble.glasses", physical_id, descriptor
                )
                glasses_runtime.grant_session_consent(
                    device.token, {GlassesCapability.DISPLAY}
                )
                glasses_connected.add(device.device_id)
                glasses_config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                try:
                    glasses_config_path.parent.chmod(0o700)
                except OSError:
                    pass
                saved = []
                if glasses_config_path.is_file():
                    try:
                        saved = json.loads(glasses_config_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        saved = []
                saved = [item for item in saved if item.get("device_id") != device.device_id]
                saved.append({
                    "device_id": device.device_id, "physical_device_id": physical_id,
                    "adapter_id": "jarvis.ble.glasses", "vendor": descriptor.vendor,
                    "model": descriptor.model, "platform": descriptor.platform,
                })
                glasses_config_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                try:
                    glasses_config_path.chmod(0o600)
                except OSError:
                    pass
            except Exception:
                try:
                    keyring.delete_password("mark56-glasses", device.device_id)
                except Exception:
                    pass
                registry.revoke_device(device.device_id)
                glasses_runtime.reconcile_revoked_sessions()
                raise
            return JSONResponse({
                "ok": True, "device": {
                    "device_id": device.device_id, "device_name": device.device_name,
                    "vendor": descriptor.vendor, "model": descriptor.model,
                    "capabilities": sorted(capability.value for capability in descriptor.capabilities),
                    "scopes": list(device.scopes),
                },
            })
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Could not pair glasses: " + exc.__class__.__name__}, status_code=503)

    @router.post("/api/devices/glasses/{device_id}/connect")
    async def reconnect_glasses(device_id: str, request: Request):
        nonlocal glasses_adapter_registered
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            import keyring
            token = keyring.get_password("mark56-glasses", device_id)
            if not token:
                return JSONResponse({"error": "Glasses credential is unavailable. Re-pair this device."}, status_code=409)
            saved = json.loads(glasses_config_path.read_text(encoding="utf-8"))
            item = next((entry for entry in saved if entry.get("device_id") == device_id), None)
            if item is None:
                return JSONResponse({"error": "Glasses metadata is missing. Scan and pair again."}, status_code=404)
            physical_id = item["physical_device_id"]
            descriptor = glasses_discoveries.get(physical_id)
            if descriptor is None:
                return JSONResponse({"error": "Scan for nearby JARVIS-compatible glasses before reconnecting."}, status_code=409)
            if not glasses_adapter_registered:
                from core.transports.registration import register_optional_glasses_adapters
                glasses_adapter_registered = bool(register_optional_glasses_adapters(
                    glasses_runtime, enable_ble=True
                ))
            glasses_runtime.connect(token, "jarvis.ble.glasses", physical_id, descriptor)
            glasses_runtime.grant_session_consent(token, {GlassesCapability.DISPLAY})
            glasses_connected.add(device_id)
            return JSONResponse({"ok": True, "connected": True})
        except Exception as exc:
            return JSONResponse({"error": "Could not reconnect glasses: " + exc.__class__.__name__}, status_code=503)

    @router.post("/api/devices/glasses/{device_id}/disconnect")
    async def disconnect_glasses(device_id: str, request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            import keyring
            token = keyring.get_password("mark56-glasses", device_id)
            if token:
                glasses_runtime.disconnect(token)
            glasses_connected.discard(device_id)
            return JSONResponse({"ok": True, "connected": False})
        except Exception as exc:
            return JSONResponse({"error": "Could not disconnect glasses: " + exc.__class__.__name__}, status_code=503)

    @router.post("/api/devices/glasses/{device_id}/display")
    async def render_glasses_card(device_id: str, request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            import keyring
            token = keyring.get_password("mark56-glasses", device_id)
            if not token:
                return JSONResponse({"error": "Glasses credential is unavailable."}, status_code=404)
            body = await request.json()
            card = body.get("card")
            glasses_runtime.render_card(token, card)
            return JSONResponse({"ok": True, "rendered": True})
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Could not render glasses card: " + exc.__class__.__name__}, status_code=503)

    @router.get("/api/devices/relay")
    async def relay_status(request: Request):
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        config = {}
        try:
            if relay_config_path.is_file():
                config = json.loads(relay_config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
        return JSONResponse({
            "configured": bool(config.get("endpoint") and config.get("channel_id") and config.get("principal_id")),
            "endpoint": config.get("endpoint"),
            "channel_id": config.get("channel_id"),
            "principal_id": config.get("principal_id"),
            "status": relay_runtime.status() if relay_runtime is not None else "stopped",
        })

    @router.post("/api/devices/relay/configure")
    async def configure_relay(request: Request):
        nonlocal relay_runtime
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
            endpoint = body.get("endpoint", "").strip()
            channel_id = body.get("channel_id", "").strip()
            principal_id = body.get("principal_id", "").strip()
            token = body.get("token", "").strip()
            from relay.desktop_bridge import relay_websocket_url
            relay_websocket_url(endpoint, channel_id, principal_id)
            if not token.startswith("rly_") or not 32 <= len(token) <= 160:
                raise ValueError("Relay token is invalid")
            import keyring
            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                return JSONResponse({"error": "No secure operating-system credential store is available."}, status_code=503)
            if relay_runtime is not None:
                relay_runtime.stop()
                relay_runtime = None
            relay_config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                relay_config_path.parent.chmod(0o700)
            except OSError:
                pass
            keyring.set_password("mark56-relay", f"{channel_id}:{principal_id}", token)
            relay_config_path.write_text(json.dumps({
                "endpoint": endpoint, "channel_id": channel_id,
                "principal_id": principal_id,
            }, indent=2), encoding="utf-8")
            try:
                relay_config_path.chmod(0o600)
            except OSError:
                pass
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Could not store relay credentials in the operating-system keyring: " + exc.__class__.__name__}, status_code=503)
        return JSONResponse({"ok": True, "configured": True, "token_stored_securely": True})

    @router.post("/api/devices/relay/start")
    async def start_relay(request: Request):
        nonlocal relay_runtime
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            config = json.loads(relay_config_path.read_text(encoding="utf-8"))
            import keyring
            token = keyring.get_password(
                "mark56-relay",
                f"{config['channel_id']}:{config['principal_id']}",
            )
            if not token:
                return JSONResponse({"error": "Relay credential is missing from the operating-system keyring. Configure the relay again."}, status_code=409)
            if relay_runtime is None:
                from relay.desktop_runtime import DesktopRelayRuntime
                relay_runtime = DesktopRelayRuntime(on_event=on_relay_event)
            state = relay_runtime.start(
                base_url=config["endpoint"], channel_id=config["channel_id"],
                principal_id=config["principal_id"], token=token,
            )
            if state == "error":
                return JSONResponse({"error": "Relay runtime could not initialize. Check the relay URL and desktop dependencies."}, status_code=503)
            return JSONResponse({"ok": True, "status": state})
        except FileNotFoundError:
            return JSONResponse({"error": "Configure the remote relay before starting it."}, status_code=409)
        except (KeyError, ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Could not start desktop relay: " + exc.__class__.__name__}, status_code=503)

    @router.post("/api/devices/relay/stop")
    async def stop_relay(request: Request):
        nonlocal relay_runtime
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if relay_runtime is not None:
            try:
                relay_runtime.stop()
            except Exception as exc:
                return JSONResponse({"error": "Could not stop desktop relay: " + exc.__class__.__name__}, status_code=503)
            relay_runtime = None
        return JSONResponse({"ok": True, "status": "stopped"})

    @router.delete("/api/devices/relay/configuration")
    async def forget_relay_configuration(request: Request):
        nonlocal relay_runtime
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if relay_runtime is not None:
            try:
                relay_runtime.stop()
            except Exception as exc:
                return JSONResponse({"error": "Could not stop desktop relay: " + exc.__class__.__name__}, status_code=503)
            relay_runtime = None
        try:
            if relay_config_path.is_file():
                config = json.loads(relay_config_path.read_text(encoding="utf-8"))
                import keyring
                if config.get("channel_id") and config.get("principal_id"):
                    try:
                        keyring.delete_password(
                            "mark56-relay",
                            f"{config['channel_id']}:{config['principal_id']}",
                        )
                    except Exception:
                        pass
                relay_config_path.unlink(missing_ok=True)
        except Exception:
            return JSONResponse({"error": "Could not clear saved relay configuration."}, status_code=503)
        return JSONResponse({"ok": True, "status": "stopped", "credentials_cleared": True})

    @router.post("/api/devices/relay/ping")
    async def ping_remote_device(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if relay_runtime is None or relay_runtime.status() != "connected":
            return JSONResponse({"error": "Start the desktop relay connection first."}, status_code=409)
        try:
            body = await request.json()
            principal_id = body.get("principal_id", "")
            if not isinstance(principal_id, str) or not principal_id.strip() or len(principal_id) > 80:
                raise ValueError("Enter a valid remote device principal ID")
            relay_runtime.send_to_device(
                principal_id, "command", {"action": "assistant.ping"}
            )
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "Remote ping failed: " + exc.__class__.__name__}, status_code=503)
        return JSONResponse({"ok": True, "sent": True, "principal_id": principal_id})

    @router.get("/api/devices/relay/events")
    async def relay_events(request: Request):
        insecure = _secure(request)
        if insecure:
            return insecure
        if not _owner(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        events = relay_runtime.drain_events() if relay_runtime is not None else []
        return JSONResponse({"events": events})

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

    @router.on_event("shutdown")
    async def shutdown_device_services():
        nonlocal companion_server, relay_runtime
        if relay_runtime is not None:
            try:
                await asyncio.to_thread(relay_runtime.stop)
            except Exception:
                pass
            relay_runtime = None
        if companion_server is not None:
            try:
                await asyncio.to_thread(companion_server.stop)
            except Exception:
                pass
            companion_server = None
        try:
            await asyncio.to_thread(glasses_runtime.close)
        except Exception:
            pass

    return router
