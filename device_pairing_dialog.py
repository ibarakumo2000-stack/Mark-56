"""Premium JARVIS desktop companion pairing and device-management dialog.

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
    QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
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
    """A polished, responsive pairing drawer that retains the secure API flow."""

    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard
        self.base_url = str(dashboard.get_url()).rstrip("/")
        self.token = ""
        self.bridge_running = False
        self.setWindowTitle("JARVIS · Pair Device & Phone")
        self.setMinimumSize(780, 650)
        self.resize(980, 820)
        self.setModal(False)
        self._build()
        self._authenticate()
        self.refresh_devices()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Header
        header = QFrame()
        header.setObjectName("hero")
        hero_layout = QHBoxLayout(header)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(16)

        icon = QLabel("⌁")
        icon.setObjectName("heroIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(64, 64)
        hero_layout.addWidget(icon)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(5)
        title = QLabel("Pair Device & Phone")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Secure local pairing  ·  Same Wi-Fi network  ·  Owner approval required")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        hero_layout.addLayout(title_stack, 1)

        privacy = QLabel("◆  Your privacy. Our priority.")
        privacy.setObjectName("privacyBadge")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(privacy, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(header)

        # Connection status
        self.status = QLabel("Connecting to JARVIS dashboard…")
        self.status.setObjectName("statusBanner")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # Bridge controls
        bridge_row = QHBoxLayout()
        bridge_row.setSpacing(12)
        self.start_btn = QPushButton("▶   Start secure bridge")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_bridge)
        self.stop_btn = QPushButton("■   Stop bridge")
        self.stop_btn.setObjectName("secondaryButton")
        self.stop_btn.clicked.connect(self.stop_bridge)
        bridge_row.addWidget(self.start_btn, 1)
        bridge_row.addWidget(self.stop_btn, 1)
        root.addLayout(bridge_row)

        # Permissions card
        permissions_card = QFrame()
        permissions_card.setObjectName("surfaceCard")
        permissions_layout = QVBoxLayout(permissions_card)
        permissions_layout.setContentsMargins(16, 14, 16, 14)
        permissions_layout.setSpacing(12)

        permissions_head = QHBoxLayout()
        shield = QLabel("⬡")
        shield.setObjectName("sectionIcon")
        permissions_head.addWidget(shield)
        scopes_title = QLabel("PHONE PERMISSIONS")
        scopes_title.setObjectName("sectionTitle")
        permissions_head.addWidget(scopes_title)
        hint = QLabel("Choose only what this device needs")
        hint.setObjectName("mutedText")
        permissions_head.addWidget(hint, 1)
        info = QLabel("ⓘ")
        info.setObjectName("infoIcon")
        permissions_head.addWidget(info)
        permissions_layout.addLayout(permissions_head)

        scope_grid = QGridLayout()
        scope_grid.setHorizontalSpacing(10)
        scope_grid.setVerticalSpacing(9)
        self.scope_checks = {}
        defaults = {"command.send", "notification.receive", "media.control", "battery.read"}
        for index, (key, label) in enumerate(SCOPES):
            check = QCheckBox(label)
            check.setObjectName("permissionCheck")
            check.setChecked(key in defaults)
            check.setToolTip(key)
            self.scope_checks[key] = check
            scope_grid.addWidget(check, index // 4, index % 4)
        permissions_layout.addLayout(scope_grid)
        root.addWidget(permissions_card)

        # QR pairing call-to-action
        pair_card = QFrame()
        pair_card.setObjectName("pairCard")
        pair_row = QHBoxLayout(pair_card)
        pair_row.setContentsMargins(16, 12, 16, 12)
        pair_row.setSpacing(14)

        qr_icon = QLabel("▦")
        qr_icon.setObjectName("qrIcon")
        qr_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_icon.setFixedSize(54, 54)
        pair_row.addWidget(qr_icon)

        pair_text = QVBoxLayout()
        pair_text.setSpacing(4)
        self.qr_btn = QPushButton("Generate one-time QR code")
        self.qr_btn.setObjectName("pairAction")
        self.qr_btn.clicked.connect(self.create_offer)
        self.qr_btn.setEnabled(False)
        pair_text.addWidget(self.qr_btn)
        pair_hint = QLabel("Scan with your Android device to pair securely")
        pair_hint.setObjectName("mutedText")
        pair_text.addWidget(pair_hint)
        pair_row.addLayout(pair_text, 1)

        divider = QFrame()
        divider.setObjectName("verticalDivider")
        divider.setFixedWidth(1)
        pair_row.addWidget(divider)

        expiry_stack = QVBoxLayout()
        expiry_stack.setSpacing(3)
        expiry_title = QLabel("◷  QR OFFER")
        expiry_title.setObjectName("expiryTitle")
        self.code_label = QLabel("Expires after 5 minutes")
        self.code_label.setObjectName("expiryText")
        self.code_label.setWordWrap(True)
        expiry_stack.addWidget(expiry_title)
        expiry_stack.addWidget(self.code_label)
        pair_row.addLayout(expiry_stack)
        root.addWidget(pair_card)

        # QR preview / pairing code
        qr_panel = QFrame()
        qr_panel.setObjectName("qrPanel")
        qr_panel_layout = QVBoxLayout(qr_panel)
        qr_panel_layout.setContentsMargins(12, 12, 12, 12)
        qr_panel_layout.setSpacing(8)
        self.qr = QLabel("Start the secure bridge, then generate a QR code.")
        self.qr.setObjectName("qrPreview")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumHeight(150)
        self.qr.setWordWrap(True)
        qr_panel_layout.addWidget(self.qr, 1)
        self.code = QLabel("")
        self.code.setObjectName("pairingCode")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_panel_layout.addWidget(self.code)
        root.addWidget(qr_panel)

        # Paired device management
        devices_card = QFrame()
        devices_card.setObjectName("surfaceCard")
        devices_layout = QVBoxLayout(devices_card)
        devices_layout.setContentsMargins(14, 12, 14, 12)
        devices_layout.setSpacing(10)

        devices_head = QHBoxLayout()
        device_icon = QLabel("▣")
        device_icon.setObjectName("sectionIcon")
        devices_head.addWidget(device_icon)
        devices_title = QLabel("PAIRED DEVICES")
        devices_title.setObjectName("sectionTitle")
        devices_head.addWidget(devices_title, 1)
        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setObjectName("smallButton")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        devices_head.addWidget(self.refresh_btn)
        self.scan_btn = QPushButton("⌁  Scan Bluetooth glasses")
        self.scan_btn.setObjectName("smallButton")
        self.scan_btn.clicked.connect(self.scan_glasses)
        devices_head.addWidget(self.scan_btn)
        devices_layout.addLayout(devices_head)

        self.devices = QListWidget()
        self.devices.setObjectName("deviceList")
        self.devices.setMinimumHeight(105)
        devices_layout.addWidget(self.devices, 1)

        self.glasses = QListWidget()
        self.glasses.setObjectName("deviceList")
        self.glasses.setMaximumHeight(90)
        devices_layout.addWidget(self.glasses)
        root.addWidget(devices_card, 1)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("✕   Close")
        close_btn.setObjectName("closeButton")
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self.setStyleSheet("""
            QDialog {
                background: #080f1e;
                color: #eaf3ff;
                font-family: "Inter", "Segoe UI", sans-serif;
            }
            QFrame#hero {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #0b1c3c, stop:0.65 #101a37, stop:1 #151032);
                border: 1px solid #1767bd;
                border-bottom: 2px solid #05bfff;
                border-radius: 15px;
            }
            QLabel#heroIcon {
                color: #27caff; font-size: 36px; font-weight: 700;
                background: #07172d; border: 1px solid #0aaeff;
                border-radius: 13px;
            }
            QLabel#heroTitle { color: #f2f8ff; font-size: 23px; font-weight: 700; }
            QLabel#heroSubtitle { color: #a9c9ec; font-size: 12px; }
            QLabel#privacyBadge {
                color: #3df2a1; background: #08271f;
                border: 1px solid #087f67; border-radius: 12px;
                padding: 8px 11px; font-size: 11px; font-weight: 600;
            }
            QLabel#statusBanner {
                color: #c7e3ff; background: #0c1b33;
                border: 1px solid #244d7c; border-radius: 10px;
                padding: 10px 13px; font-size: 12px;
            }
            QFrame#surfaceCard {
                background: #0b1527; border: 1px solid #1e4c82;
                border-radius: 13px;
            }
            QLabel#sectionIcon { color: #21c8ff; font-size: 20px; font-weight: 700; }
            QLabel#sectionTitle { color: #eaf4ff; font-size: 12px; font-weight: 700; }
            QLabel#mutedText { color: #9db8d8; font-size: 11px; }
            QLabel#infoIcon { color: #55cfff; font-size: 17px; }
            QCheckBox#permissionCheck {
                color: #d9eaff; background: #0a172a;
                border: 1px solid #1d416b; border-radius: 8px;
                padding: 8px 9px; font-size: 11px; spacing: 8px;
            }
            QCheckBox#permissionCheck:hover { border-color: #10aaff; background: #102441; }
            QCheckBox#permissionCheck::indicator {
                width: 16px; height: 16px; border-radius: 4px;
                border: 1px solid #587ba5; background: #17263e;
            }
            QCheckBox#permissionCheck::indicator:checked {
                background: #087fff; border: 1px solid #26cfff;
            }
            QFrame#pairCard {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #0b2450, stop:0.75 #101c3b, stop:1 #20113c);
                border: 1px solid #05bfff; border-radius: 13px;
            }
            QLabel#qrIcon {
                color: #20caff; background: #071a36;
                border: 1px solid #138bdc; border-radius: 10px;
                font-size: 30px; font-weight: 700;
            }
            QPushButton#pairAction {
                color: #f3f9ff; background: transparent; border: none;
                text-align: left; font-size: 14px; font-weight: 700; padding: 0;
            }
            QPushButton#pairAction:hover { color: #4bd8ff; }
            QLabel#expiryTitle { color: #48caff; font-size: 11px; font-weight: 700; }
            QLabel#expiryText { color: #c3ddf9; font-size: 11px; }
            QFrame#verticalDivider { background: #168bdb; }
            QFrame#qrPanel {
                background: #071221; border: 1px solid #21446b; border-radius: 12px;
            }
            QLabel#qrPreview { color: #8fb1d6; font-size: 12px; }
            QLabel#pairingCode { color: #38caff; font-size: 20px; font-weight: 700; letter-spacing: 4px; }
            QListWidget#deviceList {
                background: #071221; color: #d9eaff;
                border: 1px solid #203c5b; border-radius: 8px;
                outline: none; font-size: 11px;
            }
            QListWidget#deviceList::item { padding: 6px; border-bottom: 1px solid #142b45; }
            QListWidget#deviceList::item:selected { background: #123d70; }
            QPushButton {
                color: #eaf4ff; background: #142b49;
                border: 1px solid #315d8c; border-radius: 9px;
                padding: 9px 12px; font-size: 12px;
            }
            QPushButton:hover { background: #1b3c62; border-color: #22bfff; }
            QPushButton:disabled { color: #627a98; background: #101a2a; border-color: #23354a; }
            QPushButton#primaryButton {
                color: white; font-size: 14px; font-weight: 700;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0758d8, stop:0.65 #087fff, stop:1 #08b9ed);
                border: 1px solid #23d0ff; border-radius: 10px; padding: 12px;
            }
            QPushButton#primaryButton:hover { background: #087fff; }
            QPushButton#secondaryButton {
                background: #132641; border: 1px solid #5077a8;
                font-size: 14px; padding: 12px; border-radius: 10px;
            }
            QPushButton#smallButton { padding: 7px 10px; font-size: 11px; }
            QPushButton#closeButton {
                background: #102747; border: 1px solid #0baeff;
                color: #eaf8ff; font-weight: 600; padding: 9px 15px;
            }
        """)

    def _request(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
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
        """Establish an owner session, retrying transient one-time-key failures."""
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
                break

        self.token = ""
        self.qr_btn.setEnabled(False)
        message = str(last_error or "Owner authentication failed.")
        self.status.setText("Could not authenticate to the dashboard: " + message)
        QMessageBox.warning(
            self, "JARVIS pairing",
            message + "\n\nClose this dialog and retry if the dashboard has just started.",
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
            result = self._request(
                "/api/devices/pairing-offers", "POST",
                {"scopes": scopes, "expires_in": 300},
            )
            self.code.setText(result.get("code", ""))
            self.code_label.setText(
                "One-time code · expires " +
                __import__("datetime").datetime.fromtimestamp(result["expires_at"]).strftime("%H:%M:%S")
            )
            uri = result.get("qr_data_uri", "")
            if uri.startswith("data:image/png;base64,"):
                raw = base64.b64decode(uri.split(",", 1)[1])
                pixmap = QPixmap()
                if pixmap.loadFromData(raw, "PNG"):
                    self.qr.setPixmap(pixmap.scaled(
                        240, 240, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self.qr.setText("")
                else:
                    self.qr.setText("QR image could not be rendered.")
            else:
                self.qr.setText(
                    "QR library missing. Install qrcode[pil] to display the code. "
                    "Pairing code: " + result.get("code", "")
                )
            self.status.setText(
                "Scan this QR from the JARVIS Android companion while both devices are on the same Wi-Fi."
            )
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
                self.devices.addItem(item)
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(8, 4, 8, 4)
                label = QLabel(f"{name} · {platform} · {online}\nPermissions: {scopes}")
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
        answer = QMessageBox.question(
            self, "Revoke device",
            "Revoke this device's credentials and permissions?",
        )
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
                self.glasses.addItem(
                    "No compatible JARVIS BLE glasses detected. Vendor-specific models may need an adapter."
                )
                return
            for device in devices:
                physical_id = device.get("physical_device_id", "")
                row = QListWidgetItem(
                    f"{device.get('vendor', 'Unknown')} {device.get('model', 'Glasses')} · {physical_id}"
                )
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
            QMessageBox.information(
                self, "Smart glasses",
                "Paired and connected: " + result.get("device_name", name),
            )
            self.refresh_devices()
        except Exception as exc:
            QMessageBox.warning(self, "Smart glasses", str(exc))
