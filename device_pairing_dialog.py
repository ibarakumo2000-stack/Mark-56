"""Native JARVIS desktop companion pairing and device-management dialog.

All calls use the dashboard's owner-authenticated local API. TLS certificate
verification is disabled only for this local self-signed dashboard connection;
companion enrollment still uses the bridge's certificate fingerprint pin.
"""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)


SCOPES = (
    ("command.send", "Send commands"),
    ("notification.receive", "Receive notifications"),
    ("media.control", "Control media"),
    ("battery.read", "Read battery status"),
    ("voice.capture", "Voice capture"),
    ("desktop.control", "Desktop control"),
    ("display.render", "Render on glasses"),
    ("haptics.send", "Haptic feedback"),
)


class DevicePairingDialog(QDialog):
    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard
        self.base_url = str(dashboard.get_url()).rstrip("/")
        self.token = ""
        self.bridge_running = False
        self.setWindowTitle("JARVIS · Connected Devices")
        self.setMinimumSize(760, 640)
        self.resize(900, 760)
        self.setModal(False)
        self._build()
        self._authenticate()
        self.refresh_devices()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        title = QLabel("CONNECTED DEVICES")
        title.setStyleSheet("font-size:22px;font-weight:700;color:#65d9ff;")
        subtitle = QLabel("Secure local pairing · Same Wi-Fi network · Owner approval required")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#a8b8ca;")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.status = QLabel("Connecting to JARVIS dashboard…")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding:10px;border:1px solid #35465a;border-radius:8px;color:#d7e6f5;")
        root.addWidget(self.status)

        bridge_row = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start secure bridge")
        self.start_btn.clicked.connect(self.start_bridge)
        self.stop_btn = QPushButton("■  Stop bridge")
        self.stop_btn.clicked.connect(self.stop_bridge)
        bridge_row.addWidget(self.start_btn)
        bridge_row.addWidget(self.stop_btn)
        root.addLayout(bridge_row)

        scopes_title = QLabel("PHONE PERMISSIONS — choose only what this device needs")
        scopes_title.setStyleSheet("font-weight:600;color:#dbe9f8;")
        root.addWidget(scopes_title)
        scope_wrap = QWidget()
        scope_layout = QHBoxLayout(scope_wrap)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(10)
        self.scope_checks = {}
        for key, label in SCOPES:
            check = QCheckBox(label)
            check.setChecked(key in {"command.send", "notification.receive", "media.control", "battery.read"})
            check.setToolTip(key)
            self.scope_checks[key] = check
            scope_layout.addWidget(check)
        root.addWidget(scope_wrap)

        pair_row = QHBoxLayout()
        self.qr_btn = QPushButton("▦  Generate one-time QR code")
        self.qr_btn.clicked.connect(self.create_offer)
        self.qr_btn.setEnabled(False)
        pair_row.addWidget(self.qr_btn)
        self.code_label = QLabel("QR offer expires after 5 minutes")
        self.code_label.setStyleSheet("color:#9fb5cb;")
        pair_row.addWidget(self.code_label, 1)
        root.addLayout(pair_row)

        self.qr = QLabel("Start the secure bridge, then generate a QR code.")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumHeight(230)
        self.qr.setStyleSheet("background:#101722;border:1px solid #2c3e52;border-radius:10px;color:#91a7bf;")
        root.addWidget(self.qr)

        self.code = QLabel("")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setStyleSheet("font-size:24px;font-weight:700;letter-spacing:4px;color:#65d9ff;")
        root.addWidget(self.code)

        devices_head = QHBoxLayout()
        devices_head.addWidget(QLabel("PAIRED DEVICES"))
        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        devices_head.addWidget(self.refresh_btn)
        self.scan_btn = QPushButton("⌁ Scan Bluetooth glasses")
        self.scan_btn.clicked.connect(self.scan_glasses)
        devices_head.addWidget(self.scan_btn)
        root.addLayout(devices_head)

        self.devices = QListWidget()
        self.devices.setMinimumHeight(140)
        self.devices.setStyleSheet("QListWidget{background:#101722;border:1px solid #2c3e52;border-radius:8px;color:#dce8f5;} QListWidget::item{padding:8px;}")
        root.addWidget(self.devices, 1)

        self.glasses = QListWidget()
        self.glasses.setMaximumHeight(100)
        self.glasses.setStyleSheet("QListWidget{background:#101722;border:1px solid #2c3e52;border-radius:8px;color:#dce8f5;} QListWidget::item{padding:6px;}")
        root.addWidget(self.glasses)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self.setStyleSheet("""
            QDialog{background:#151d29;color:#e3edf8;}
            QPushButton{background:#24364a;color:#e7f2ff;border:1px solid #3d5872;border-radius:7px;padding:9px 12px;}
            QPushButton:hover{background:#2d4862;}
            QPushButton:disabled{color:#718196;background:#1b2633;}
            QCheckBox{color:#c9d9e9;font-size:11px;}
        """)

    def _request(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        # Dashboard is local and has a per-install self-signed TLS certificate.
        context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, context=context, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                message = detail.get("error") or detail.get("detail") or str(exc)
            except Exception:
                message = str(exc)
            raise RuntimeError(message) from exc
        except Exception as exc:
            raise RuntimeError(f"Dashboard request failed: {exc}") from exc

    def _authenticate(self):
        """Establish an owner session, retrying transient one-time-key failures.

        The desktop generates the short-lived PIN locally while the dashboard
        server consumes it over HTTPS. A stale/consumed PIN must never leave the
        dialog holding an empty bearer token: request a fresh PIN and retry.
        """
        last_error = None
        for attempt in range(3):
            try:
                pin = self.dashboard.new_key(expiry_secs=120)
                data = json.dumps({"pin": pin}).encode("utf-8")
                req = urllib.request.Request(
                    self.base_url + "/login", data=data,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                try:
                    with urllib.request.urlopen(
                        req, context=ssl._create_unverified_context(), timeout=8
                    ) as response:
                        result = json.loads(response.read().decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    # FastAPI returns a JSON body for an invalid or expired PIN.
                    # Preserve that detail rather than showing a generic HTTP 401.
                    try:
                        detail = json.loads(exc.read().decode("utf-8"))
                        message = detail.get("error") or detail.get("detail") or str(exc)
                    except Exception:
                        message = str(exc)
                    if exc.code == 401:
                        last_error = RuntimeError(
                            "The dashboard rejected the one-time owner PIN "
                            "(invalid, expired, or already consumed)."
                        )
                        continue
                    raise RuntimeError(message) from exc

                if not result.get("ok") or not result.get("token"):
                    last_error = RuntimeError(
                        result.get("error") or "Dashboard did not issue an owner session."
                    )
                    continue

                self.token = result["token"]
                self.status.setText("Owner authenticated · Ready to start local pairing.")
                self.qr_btn.setEnabled(True)
                return
            except Exception as exc:
                last_error = exc
                # Network / TLS failures are not fixed by cycling a PIN.
                break

        self.token = ""
        self.qr_btn.setEnabled(False)
        message = str(last_error or "Owner authentication failed.")
        self.status.setText("Could not authenticate to the dashboard: " + message)
        QMessageBox.warning(
            self, "JARVIS pairing",
            message + "\\n\\nClose this dialog and retry if the dashboard has just started.",
        )

    def start_bridge(self):
        try:
            result = self._request("/api/devices/companion/start", "POST", {})
            self.bridge_running = bool(result.get("running", True))
            self.status.setText("Secure companion bridge running at " + str(result.get("endpoint", "private LAN endpoint")))
            self.qr_btn.setEnabled(True)
        except Exception as exc:
            self.status.setText("Bridge could not start: " + str(exc))
            QMessageBox.warning(self, "Secure bridge", str(exc))

    def stop_bridge(self):
        try:
            self._request("/api/devices/companion/stop", "POST", {})
            self.bridge_running = False
            self.qr.setText("Bridge stopped. Start it to generate a new pairing QR.")
            self.qr.setPixmap(QPixmap())
            self.code.clear()
            self.status.setText("Secure companion bridge stopped.")
        except Exception as exc:
            QMessageBox.warning(self, "Secure bridge", str(exc))

    def create_offer(self):
        scopes = [key for key, check in self.scope_checks.items() if check.isChecked()]
        if not scopes:
            QMessageBox.information(self, "Permissions", "Select at least one permission for the phone.")
            return
        try:
            result = self._request("/api/devices/pairing-offers", "POST", {"scopes": scopes, "expires_in": 300})
            self.code.setText(result.get("code", ""))
            self.code_label.setText("One-time code · expires " + __import__("datetime").datetime.fromtimestamp(result["expires_at"]).strftime("%H:%M:%S"))
            uri = result.get("qr_data_uri", "")
            if uri.startswith("data:image/png;base64,"):
                raw = base64.b64decode(uri.split(",", 1)[1])
                pixmap = QPixmap()
                if pixmap.loadFromData(raw, "PNG"):
                    self.qr.setPixmap(pixmap.scaled(260, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    self.qr.setText("")
                else:
                    self.qr.setText("QR image could not be rendered.")
            else:
                self.qr.setText("QR library missing. Install qrcode[pil] to display the code. Pairing code: " + result.get("code", ""))
            self.status.setText("Scan this QR from the JARVIS Android companion while both devices are on the same Wi-Fi.")
        except Exception as exc:
            self.status.setText("QR generation failed: " + str(exc))
            QMessageBox.warning(self, "Pairing QR", str(exc))

    def refresh_devices(self):
        if not self.token:
            return
        try:
            result = self._request("/api/devices")
            self.devices.clear()
            for device in result.get("devices", []):
                name = device.get("device_name", "Unnamed device")
                platform = device.get("platform", "Unknown platform")
                online = "ONLINE" if device.get("online") else "OFFLINE"
                scopes = ", ".join(device.get("scopes", [])) or "no permissions"
                item = QListWidgetItem()
                item.setSizeHint(item.sizeHint())
                self.devices.addItem(item)
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(8, 4, 8, 4)
                label = QLabel(f"{name} · {platform} · {online}\\nPermissions: {scopes}")
                label.setWordWrap(True)
                layout.addWidget(label, 1)
                button = QPushButton("Revoke")
                device_id = device.get("device_id")
                button.clicked.connect(lambda checked=False, identifier=device_id: self.revoke_device(identifier))
                layout.addWidget(button)
                self.devices.setItemWidget(item, row)
                item.setSizeHint(row.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, device_id)
            self.status.setText(f"Loaded {self.devices.count()} paired device(s).")
        except Exception as exc:
            self.status.setText("Could not load paired devices: " + str(exc))

    def revoke_device(self, device_id):
        if not device_id:
            return
        answer = QMessageBox.question(self, "Revoke device", "Revoke this device's credentials and permissions?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._request("/api/devices/" + str(device_id), "DELETE")
            self.refresh_devices()
            self.status.setText("Device revoked. Its credentials can no longer be used.")
        except Exception as exc:
            QMessageBox.warning(self, "Revoke device", str(exc))

    def scan_glasses(self):
        self.glasses.clear()
        self.glasses.addItem("Scanning nearby Bluetooth devices…")
        self.scan_btn.setEnabled(False)
        try:
            result = self._request("/api/devices/glasses/discover", "POST", {"timeout": 5.0})
            self.glasses.clear()
            devices = result.get("devices", [])
            if not devices:
                self.glasses.addItem("No compatible JARVIS BLE glasses detected. Vendor-specific models may need an adapter.")
                return
            for device in devices:
                physical_id = device.get("physical_device_id", "")
                row = QListWidgetItem(f"{device.get('vendor', 'Unknown')} {device.get('model', 'Glasses')} · {physical_id}")
                row.setData(Qt.ItemDataRole.UserRole, device)
                self.glasses.addItem(row)
            self.glasses.itemDoubleClicked.connect(self.pair_glasses)
        except Exception as exc:
            self.glasses.clear()
            self.glasses.addItem("Bluetooth scan failed: " + str(exc))
        finally:
            self.scan_btn.setEnabled(True)

    def pair_glasses(self, item):
        device = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(device, dict):
            return
        name = device.get("vendor", "JARVIS") + " " + device.get("model", "glasses")
        try:
            result = self._request("/api/devices/glasses/pair", "POST", {
                "physical_device_id": device.get("physical_device_id", ""),
                "device_name": name,
            })
            QMessageBox.information(self, "Smart glasses", "Paired and connected: " + result.get("device_name", name))
            self.refresh_devices()
        except Exception as exc:
            QMessageBox.warning(self, "Smart glasses", str(exc))
