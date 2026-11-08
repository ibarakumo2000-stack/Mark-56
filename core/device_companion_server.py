"""Opt-in HTTPS runtime for the Mark 56 Android companion bridge.

Importing this module never opens a socket. The application must explicitly
start the server with a TLS certificate and private key.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from core.device_companion import (
    CompanionMessageVerifier,
    InvalidCompanionMessage,
    SignedCompanionMessage,
)
from core.device_features import AndroidDeviceFeatures, DeviceFeatureError
from core.device_gateway import (
    AuthorizationError,
    DeviceGatewayError,
    DeviceRegistry,
    PairingError,
)

_MAX_REQUEST_BYTES = 16_384
_MAX_QUEUE = 32


def certificate_fingerprint(certificate_path: str | Path) -> str:
    """Return the SHA-256 fingerprint of a PEM or DER X.509 certificate."""
    raw = Path(certificate_path).expanduser().read_bytes()
    if b"-----BEGIN CERTIFICATE-----" in raw:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(raw)
        raw = cert.public_bytes(__import__("cryptography").hazmat.primitives.serialization.Encoding.DER)
    return ":".join(f"{byte:02x}" for byte in hashlib.sha256(raw).digest())


def _message(payload: Any) -> SignedCompanionMessage:
    if not isinstance(payload, dict):
        raise ValueError("Expected a signed message object")
    required = {"version", "device_id", "method", "path", "timestamp", "nonce", "body", "signature"}
    if set(payload) != required:
        raise ValueError("Invalid signed message fields")
    return SignedCompanionMessage(**payload)


def create_companion_app(registry: DeviceRegistry):
    """Create the FastAPI app; caller owns registry lifetime and TLS listener."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        # FastAPI resolves postponed annotations against module globals.
        # Keep FastAPI optional at import time, but expose Request when the
        # runtime app is constructed so request parameters are injected properly.
        globals()["Request"] = Request
    except ImportError as exc:
        raise RuntimeError("Install FastAPI to enable the Android companion bridge") from exc

    verifier = CompanionMessageVerifier(registry)
    features = AndroidDeviceFeatures(verifier)
    commands: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_QUEUE))
    wearable_commands: deque[dict[str, Any]] = deque(maxlen=_MAX_QUEUE)
    command_lock = threading.RLock()
    app = FastAPI(title="Mark 56 Companion", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def bound_request_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > _MAX_REQUEST_BYTES:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        response = await call_next(request)
        return response

    async def json_body(request: Request):
        raw = await request.body()
        if len(raw) > _MAX_REQUEST_BYTES:
            return None
        try:
            return json.loads(raw or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    @app.get("/health")
    async def health():
        return {"service": "mark56-companion", "version": 1, "status": "ready"}

    @app.post("/v1/pair")
    async def pair(request: Request):
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {
            "pairing_code", "device_name", "platform", "capabilities", "requested_scopes"
        }:
            return JSONResponse({"detail": "Invalid pairing request"}, status_code=400)
        try:
            enrolled = registry.redeem_pairing_code(
                body["pairing_code"], device_name=body["device_name"],
                device_type="android", platform=body["platform"],
                capabilities=body["capabilities"],
                requested_scopes=body["requested_scopes"],
            )
        except (PairingError, TypeError, ValueError):
            return JSONResponse({"detail": "Pairing rejected; code may be expired or permissions unapproved"}, status_code=403)
        return {
            "device_id": enrolled.device_id,
            "device_name": enrolled.device_name,
            "scopes": list(enrolled.scopes),
            "token": enrolled.token,
            "protocol": "mark56-companion",
            "version": 1,
        }

    @app.post("/v1/notifications")
    @app.post("/v1/battery")
    @app.post("/v1/media/state")
    async def ingest(request: Request):
        body = await json_body(request)
        try:
            envelope = _message(body)
            token = request.headers.get("authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            event = features.ingest(token[7:], envelope)
            return {"accepted": True, "event_type": event["type"]}
        except AuthorizationError:
            return JSONResponse({"detail": "Device is not authorized"}, status_code=403)
        except (InvalidCompanionMessage, DeviceFeatureError, ValueError, TypeError):
            return JSONResponse({"detail": "Invalid or unauthenticated companion message"}, status_code=400)

    @app.post("/v1/wearable/action")
    async def wearable_action(request: Request):
        body = await json_body(request)
        try:
            envelope = _message(body)
            if envelope.method != "POST" or envelope.path != "/v1/wearable/action":
                raise ValueError("Invalid wearable route")
            token = request.headers.get("authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            identity = verifier.verify(token[7:], envelope, required_scope="command.send")
            payload = envelope.body
            if not isinstance(payload, dict) or set(payload) != {"action", "source"}:
                raise ValueError("Invalid wearable action")
            action = payload.get("action")
            if payload.get("source") != "wear_os" or action not in {
                "assistant.ping", "media.play_pause", "media.next", "media.previous"
            }:
                raise ValueError("Unsupported wearable action")
            with command_lock:
                if len(wearable_commands) >= _MAX_QUEUE:
                    return JSONResponse({"detail": "Wearable action queue is full"}, status_code=429)
                wearable_commands.append({
                    "device_id": identity["device_id"], "source": "wear_os",
                    "action": action, "received_at": int(time.time()),
                })
            return {"accepted": True, "action": action}
        except AuthorizationError:
            return JSONResponse({"detail": "Device is not authorized"}, status_code=403)
        except (InvalidCompanionMessage, ValueError, TypeError):
            return JSONResponse({"detail": "Invalid or unauthenticated wearable action"}, status_code=400)

    @app.post("/v1/media/next")
    async def next_media_command(request: Request):
        body = await json_body(request)
        try:
            envelope = _message(body)
            if envelope.method != "POST" or envelope.path != "/v1/media/next":
                raise ValueError("Invalid media route")
            token = request.headers.get("authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            identity = verifier.verify(token[7:], envelope, required_scope="media.control")
            with command_lock:
                queue = commands[identity["device_id"]]
                command = queue.popleft() if queue else None
            return {"command": command}
        except AuthorizationError:
            return JSONResponse({"detail": "Device is not authorized"}, status_code=403)
        except (InvalidCompanionMessage, ValueError, TypeError):
            return JSONResponse({"detail": "Invalid or unauthenticated companion message"}, status_code=400)

    def queue_media_command(device_id: str, token: str, action: str) -> dict[str, Any]:
        """Queue a desktop-originated media command after local UI authorization."""
        identity = registry.authenticate(token, required_scope="media.control")
        if identity["device_id"] != device_id:
            raise AuthorizationError("Device mismatch")
        command = features.create_media_command(token, action)
        with command_lock:
            queue = commands[device_id]
            if len(queue) >= _MAX_QUEUE:
                raise RuntimeError("Device command queue is full")
            queue.append(command)
        return {"queued": True, "action": command["action"]}


    # Authenticated phone chat transport. The desktop runtime consumes the
    # inbound queue and publishes assistant replies through queue_chat_reply.
    chat_inbound: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_QUEUE))
    chat_outbound: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_QUEUE))

    @app.post("/v1/chat/send")
    async def chat_send(request: Request):
        body = await json_body(request)
        try:
            envelope = _message(body)
            if envelope.method != "POST" or envelope.path != "/v1/chat/send":
                raise ValueError("Invalid chat route")
            token = request.headers.get("authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            identity = verifier.verify(token[7:], envelope, required_scope="command.send")
            payload = envelope.body
            if not isinstance(payload, dict) or set(payload) != {"message", "message_id"}:
                raise ValueError("Invalid chat payload")
            message = payload.get("message")
            message_id = payload.get("message_id")
            if not isinstance(message, str) or not message.strip() or len(message) > 4000:
                raise ValueError("Message must contain 1–4000 characters")
            if not isinstance(message_id, str) or not 8 <= len(message_id) <= 80:
                raise ValueError("Invalid message identifier")
            device_id = identity["device_id"]
            with command_lock:
                if len(chat_inbound[device_id]) >= _MAX_QUEUE:
                    return JSONResponse({"detail": "Chat queue is full"}, status_code=429)
                chat_inbound[device_id].append({
                    "message_id": message_id, "message": message.strip(),
                    "device_id": device_id, "received_at": int(time.time()),
                })
            return {"accepted": True, "message_id": message_id}
        except AuthorizationError:
            return JSONResponse({"detail": "Device is not authorized"}, status_code=403)
        except (InvalidCompanionMessage, ValueError, TypeError):
            return JSONResponse({"detail": "Invalid or unauthenticated chat message"}, status_code=400)

    @app.post("/v1/chat/poll")
    async def chat_poll(request: Request):
        body = await json_body(request)
        try:
            envelope = _message(body)
            if envelope.method != "POST" or envelope.path != "/v1/chat/poll":
                raise ValueError("Invalid chat route")
            token = request.headers.get("authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            identity = verifier.verify(token[7:], envelope, required_scope="command.send")
            with command_lock:
                reply = chat_outbound[identity["device_id"]].popleft() if chat_outbound[identity["device_id"]] else None
            return {"reply": reply}
        except AuthorizationError:
            return JSONResponse({"detail": "Device is not authorized"}, status_code=403)
        except (InvalidCompanionMessage, ValueError, TypeError):
            return JSONResponse({"detail": "Invalid or unauthenticated chat poll"}, status_code=400)

    def drain_chat_messages(limit: int = 20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_QUEUE:
            raise ValueError("Invalid chat message limit")
        with command_lock:
            batch = []
            for device_id, queue in chat_inbound.items():
                while queue and len(batch) < limit:
                    batch.append(queue.popleft())
                if len(batch) >= limit:
                    break
            return batch

    def queue_chat_reply(device_id: str, message_id: str, reply: str):
        if not isinstance(reply, str) or not reply.strip() or len(reply) > 8000:
            raise ValueError("Reply must contain 1–8000 characters")
        with command_lock:
            queue = chat_outbound[device_id]
            if len(queue) >= _MAX_QUEUE:
                raise RuntimeError("Chat reply queue is full")
            queue.append({"message_id": message_id, "reply": reply.strip(), "sent_at": int(time.time())})
        return {"queued": True, "message_id": message_id}

    app.state.device_registry = registry
    app.state.device_verifier = verifier
    app.state.device_features = features
    app.state.media_commands = commands
    app.state.chat_inbound = chat_inbound
    app.state.chat_outbound = chat_outbound
    app.state.drain_chat_messages = drain_chat_messages
    app.state.queue_chat_reply = queue_chat_reply
    app.state.wearable_commands = wearable_commands
    def drain_wearable_commands(limit: int = 20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_QUEUE:
            raise ValueError("Invalid wearable command limit")
        with command_lock:
            return [wearable_commands.popleft() for _ in range(min(limit, len(wearable_commands)))]
    app.state.drain_wearable_commands = drain_wearable_commands
    app.state.queue_media_command = queue_media_command
    return app


class CompanionServer:
    """Explicit, stoppable Uvicorn TLS server running in a daemon thread."""

    def __init__(self, app, *, host: str, port: int,
                 certificate: str | Path, private_key: str | Path):
        if not isinstance(host, str) or not host.strip() or host in {"0.0.0.0", "::"}:
            raise ValueError("Bind to an explicit local/LAN interface address, not a wildcard")
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("Host must be an explicit IP address") from exc
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("Port must be between 1024 and 65535")
        self.app = app
        self.host, self.port = host, port
        self.certificate = str(Path(certificate).expanduser())
        self.private_key = str(Path(private_key).expanduser())
        if not Path(self.certificate).is_file() or not Path(self.private_key).is_file():
            raise FileNotFoundError("TLS certificate and private key must exist")
        # Fail early for malformed or mismatched TLS files.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.certificate, self.private_key)
        self._server = None
        self._thread = None
        self._startup_error: BaseException | None = None
        self._startup_lock = threading.Lock()

    def _run_server(self) -> None:
        """Run Uvicorn while retaining bind/startup exceptions from its thread."""
        try:
            self._server.run()
        except BaseException as exc:
            # Exceptions raised in a daemon thread otherwise disappear from the
            # authenticated start endpoint, leaving only a misleading refused
            # connection after its readiness probe times out.
            self._startup_error = exc

    def start(self, timeout: float = 8.0) -> None:
        with self._startup_lock:
            if self._thread and self._thread.is_alive():
                if self._server is not None and self._server.started:
                    return
                raise RuntimeError("The companion listener thread is already running but has not completed startup.")
            try:
                import uvicorn
            except ImportError as exc:
                raise RuntimeError("Install uvicorn to start the companion listener") from exc
            self._startup_error = None
            config = uvicorn.Config(
                self.app, host=self.host, port=self.port, log_level="warning",
                access_log=False, ssl_certfile=self.certificate,
                ssl_keyfile=self.private_key,
                # Explicitly use the server protocol constant. TLSVersion.TLSv1_2
                # is the numeric wire version 771, not an SSLContext protocol.
                ssl_version=ssl.PROTOCOL_TLS_SERVER,
                timeout_keep_alive=5, limit_max_requests=10000,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._run_server, name="mark56-companion-https", daemon=True,
            )
            self._thread.start()

        deadline = time.monotonic() + max(0.5, min(float(timeout), 20.0))
        while time.monotonic() < deadline:
            if self._server is not None and self._server.started:
                return
            if self._thread is not None and not self._thread.is_alive():
                error = self._startup_error
                detail = f"{type(error).__name__}: {error}" if error else "Uvicorn exited before opening its socket."
                self.stop()
                raise RuntimeError(f"Companion listener startup failed: {detail}") from error
            time.sleep(0.05)

        self.stop()
        raise RuntimeError(
            f"Companion listener did not finish binding to {self.host}:{self.port} "
            f"within {max(0.5, min(float(timeout), 20.0)):g} seconds. "
            "Check whether the address belongs to an active interface and whether the port is available."
        )

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=max(0.1, min(float(timeout), 15.0)))
        self._server = None
        self._thread = None
