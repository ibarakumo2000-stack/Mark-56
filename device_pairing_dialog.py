"""Premium native JARVIS desktop companion pairing and device-management dialog.

The visual layer is intentionally separated from the pairing API methods so
that the UI can evolve without changing the secure local enrollment flow.
"""
from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
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

DEFAULT_SCOPES = {
    "command.send", "notification.receive", "media.control", "battery.read"
}


class DevicePairingDialog(QDialog):
    """Premium JARVIS pairing drawer backed by the existing local dashboard API."""

    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard
        # Native desktop management must talk to this machine's dashboard,
        # not a LAN address that could resolve to another/stale JARVIS process.
        local_url = getattr(dashboard, "get_local_url", None)
        self.base_url = str(local_url() if callable(local_url) else dashboard.get_url()).rstrip("/")
        self.token = ""
        self.bridge_running = False
        self._offer_expires_at = 0
        self._offer_timer = QTimer(self)
        self._offer_timer.setInterval(1000)
        self._offer_timer.timeout.connect(self._update_offer_countdown)

        self.setWindowTitle("JARVIS · Connected Devices")
        self.setMinimumSize(760, 650)
        self.resize(980, 820)
        self.setModal(False)
        self.setObjectName("pairingDialog")
        self._build()
        self._authenticate()
        self.refresh_devices()

    def _card(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setFrameShape(QFrame.Shape.NoFrame)
        return frame

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)

        # Keep the dialog frame stable while the content grows or shrinks.
        # The scroll area prevents QR activation from pushing controls off-screen
        # on smaller displays or when the device list contains several entries.
        scroll = QScrollArea(self)
        scroll.setObjectName("pairingScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        shell = self._card("drawerShell")
        shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(20, 18, 20, 16)
        shell_layout.setSpacing(14)
        scroll.setWidget(shell)
        outer.addWidget(scroll)

        # Header
        header = self._card("heroHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(18, 15, 18, 15)
        header_row.setSpacing(14)

        emblem = QLabel("⌁")
        emblem.setObjectName("heroEmblem")
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emblem.setFixedSize(58, 58)
        header_row.addWidget(emblem)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(3)
        title = QLabel("Connected Devices")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "Secure local pairing  ·  Same Wi-Fi network  ·  Owner approval required"
        )
        subtitle.setObjectName("heroSubtitle")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header_row.addLayout(title_stack, 1)

        privacy = QLabel("◆  YOUR PRIVACY, OUR PRIORITY")
        privacy.setObjectName("privacyBadge")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(privacy, 0, Qt.AlignmentFlag.AlignVCenter)
        shell_layout.addWidget(header)

        # Connection status
        status_card = self._card("statusCard")
        status_row = QHBoxLayout(status_card)
        status_row.setContentsMargins(15, 11, 15, 11)
        status_row.setSpacing(10)
        status_icon = QLabel("▣")
        status_icon.setObjectName("statusIcon")
        status_row.addWidget(status_icon)
        self.status = QLabel("Connecting to JARVIS dashboard…")
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        shell_layout.addWidget(status_card)

        # Bridge controls
        bridge_row = QHBoxLayout()
        bridge_row.setSpacing(12)
        self.start_btn = QPushButton("▶   Start secure bridge")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.clicked.connect(self.start_bridge)
        self.stop_btn = QPushButton("■   Stop bridge")
        self.stop_btn.setObjectName("secondaryButton")
        self.stop_btn.setMinimumHeight(48)
        self.stop_btn.clicked.connect(self.stop_bridge)
        bridge_row.addWidget(self.start_btn, 1)
        bridge_row.addWidget(self.stop_btn, 1)
        shell_layout.addLayout(bridge_row)

        # Permission controls
        permission_card = self._card("contentCard")
        permission_layout = QVBoxLayout(permission_card)
        permission_layout.setContentsMargins(16, 14, 16, 15)
        permission_layout.setSpacing(11)
        permission_head = QHBoxLayout()
        permission_head.addWidget(self._section_title("PHONE PERMISSIONS"))
        permission_hint = QLabel("Choose only what this device needs")
        permission_hint.setObjectName("mutedText")
        permission_head.addWidget(permission_hint, 1)
        permission_layout.addLayout(permission_head)

        scope_grid = QGridLayout()
        scope_grid.setHorizontalSpacing(9)
        scope_grid.setVerticalSpacing(8)
        self.scope_checks = {}
        for index, (key, label) in enumerate(SCOPES):
            check = QCheckBox(label)
            check.setObjectName("permissionCheck")
            check.setChecked(key in DEFAULT_SCOPES)
            check.setToolTip(key)
            self.scope_checks[key] = check
            scope_grid.addWidget(check, index // 4, index % 4)
        permission_layout.addLayout(scope_grid)
        shell_layout.addWidget(permission_card)

        # Pairing panel
        pairing_card = self._card("pairingCard")
        pairing_layout = QVBoxLayout(pairing_card)
        pairing_layout.setContentsMargins(16, 14, 16, 14)
        pairing_layout.setSpacing(10)

        pair_head = QHBoxLayout()
        qr_icon = QLabel("▦")
        qr_icon.setObjectName("qrIcon")
        pair_head.addWidget(qr_icon)
        pair_titles = QVBoxLayout()
        pair_titles.setSpacing(1)
        pair_title = QLabel("Pair your phone")
        pair_title.setObjectName("pairTitle")
        pair_subtitle = QLabel("Scan the one-time QR code with your JARVIS Android companion")
        pair_subtitle.setObjectName("mutedText")
        pair_subtitle.setWordWrap(True)
        pair_titles.addWidget(pair_title)
        pair_titles.addWidget(pair_subtitle)
        pair_head.addLayout(pair_titles, 1)

        self.qr_btn = QPushButton("Generate one-time QR code")
        self.qr_btn.setObjectName("qrButton")
        self.qr_btn.setMinimumHeight(42)
        self.qr_btn.setEnabled(False)
        self.qr_btn.clicked.connect(self.create_offer)
        pair_head.addWidget(self.qr_btn)
        pairing_layout.addLayout(pair_head)

        # QR results live in their own collapsible panel. Generating a code
        # reveals this panel without rebuilding or reflowing the surrounding
        # permissions, bridge controls, or connected-device sections.
        self.qr_panel = QWidget()
        self.qr_panel.setObjectName("qrResultPanel")
        qr_content = QHBoxLayout(self.qr_panel)
        qr_content.setContentsMargins(0, 4, 0, 0)
        qr_content.setSpacing(16)
        self.qr = QLabel("Start the secure bridge, then generate a QR code.")
        self.qr.setObjectName("qrCanvas")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumSize(190, 190)
        self.qr.setMaximumSize(220, 220)
        self.qr.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        qr_content.addWidget(self.qr)

        qr_details = QVBoxLayout()
        qr_details.setSpacing(8)
        self.code = QLabel("")
        self.code.setObjectName("pairCode")
        self.code.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        qr_details.addWidget(self.code)
        self.code_label = QLabel("QR offer expires after 5 minutes")
        self.code_label.setObjectName("expiryText")
        self.code_label.setWordWrap(True)
        qr_details.addWidget(self.code_label)
        instructions = QLabel(
            "1. Keep your phone and computer on the same Wi-Fi network.\n"
            "2. Scan this code in the JARVIS companion app.\n"
            "3. Review the requested permissions and approve pairing."
        )
        instructions.setObjectName("instructions")
        instructions.setWordWrap(True)
        qr_details.addWidget(instructions)
        qr_details.addStretch(1)
        qr_content.addLayout(qr_details, 1)
        self.qr_panel.setVisible(False)
        pairing_layout.addWidget(self.qr_panel)
        shell_layout.addWidget(pairing_card)

        # Paired devices and Bluetooth glasses
        devices_card = self._card("contentCard")
        devices_layout = QVBoxLayout(devices_card)
        devices_layout.setContentsMargins(16, 14, 16, 14)
        devices_layout.setSpacing(10)
        devices_head = QHBoxLayout()
        devices_head.addWidget(self._section_title("PAIRED DEVICES"))
        self.device_count = QLabel("0 CONNECTED")
        self.device_count.setObjectName("connectedBadge")
        devices_head.addWidget(self.device_count)
        devices_head.addStretch(1)
        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setObjectName("secondaryButton")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        devices_head.addWidget(self.refresh_btn)
        self.scan_btn = QPushButton("⌁  Scan Bluetooth glasses")
        self.scan_btn.setObjectName("secondaryButton")
        self.scan_btn.clicked.connect(self.scan_glasses)
        devices_head.addWidget(self.scan_btn)
        devices_layout.addLayout(devices_head)

        self.devices = QListWidget()
        self.devices.setObjectName("deviceList")
        self.devices.setMinimumHeight(104)
        self.devices.setMaximumHeight(190)
        self.devices.setSpacing(5)
        devices_layout.addWidget(self.devices)

        self.glasses = QListWidget()
        self.glasses.setObjectName("glassesList")
        self.glasses.setMinimumHeight(42)
        self.glasses.setMaximumHeight(92)
        self.glasses.setSpacing(4)
        devices_layout.addWidget(self.glasses)
        shell_layout.addWidget(devices_card, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("✕   Close")
        close_btn.setObjectName("closeButton")
        close_btn.setMinimumWidth(112)
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        shell_layout.addLayout(footer)

        self.setStyleSheet("""
            QDialog#pairingDialog {
                background: #050812;
                color: #edf2ff;
                font-family: Inter, "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QScrollArea#pairingScroll { background: transparent; border: 0; }
            QScrollArea#pairingScroll > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical {
                background: #081224; width: 9px; margin: 3px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #315b91; min-height: 32px; border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #438ed8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QFrame#drawerShell {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #0c1425, stop:0.55 #080f1e, stop:1 #10112b);
                border: 1px solid rgba(91,125,255,0.42);
                border-radius: 18px;
            }
            QFrame#heroHeader {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #14254a, stop:0.55 #0c1832, stop:1 #111536);
                border: 1px solid rgba(67,154,255,0.62);
                border-radius: 15px;
            }
            QLabel#heroEmblem {
                color: #39caff; font-size: 34px; font-weight: 700;
                background: #0a1b37; border: 1px solid #248eff; border-radius: 14px;
            }
            QLabel#heroTitle { color: #f2f6ff; font-size: 25px; font-weight: 750; }
            QLabel#heroSubtitle { color: #a9c5e8; font-size: 12px; }
            QLabel#privacyBadge {
                color: #6ce9b7; background: rgba(23,155,112,0.12);
                border: 1px solid rgba(67,220,165,0.38); border-radius: 12px;
                padding: 8px 10px; font-size: 9px; font-weight: 700;
            }
            QFrame#statusCard {
                background: rgba(19,34,60,0.88);
                border: 1px solid rgba(85,142,220,0.35); border-radius: 12px;
            }
            QLabel#statusIcon { color: #6f9cff; font-size: 21px; }
            QLabel#statusText { color: #d6e5ff; font-size: 13px; }
            QFrame#contentCard {
                background: rgba(13,23,41,0.94);
                border: 1px solid rgba(107,139,190,0.25); border-radius: 14px;
            }
            QFrame#pairingCard {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(16,37,73,0.98), stop:1 rgba(15,18,48,0.98));
                border: 1px solid rgba(32,172,255,0.68); border-radius: 14px;
            }
            QLabel#sectionTitle {
                color: #eef3ff; font-size: 13px; font-weight: 750; letter-spacing: 1px;
            }
            QLabel#mutedText { color: #91a8c8; font-size: 11px; }
            QLabel#qrIcon { color: #42c9ff; font-size: 25px; padding-right: 5px; }
            QLabel#pairTitle { color: #f3f6ff; font-size: 16px; font-weight: 700; }
            QLabel#qrCanvas {
                color: #93a9c7; background: rgba(4,10,22,0.88);
                border: 1px solid rgba(81,155,255,0.38); border-radius: 12px;
                padding: 8px; font-size: 11px;
            }
            QLabel#pairCode { color: #62d4ff; font-size: 22px; font-weight: 800; letter-spacing: 4px; }
            QLabel#expiryText { color: #6dcfff; font-size: 12px; font-weight: 600; }
            QLabel#instructions { color: #b0c2df; font-size: 11px; line-height: 1.5; }
            QLabel#connectedBadge {
                color: #62e6b1; background: rgba(36,172,123,0.12);
                border: 1px solid rgba(68,215,164,0.3); border-radius: 10px;
                padding: 5px 8px; font-size: 9px; font-weight: 750;
            }
            QCheckBox#permissionCheck {
                color: #d3e2f7; background: rgba(5,13,27,0.62);
                border: 1px solid rgba(103,139,194,0.28); border-radius: 9px;
                padding: 8px 9px; spacing: 7px; font-size: 11px;
            }
            QCheckBox#permissionCheck::indicator {
                width: 16px; height: 16px; border-radius: 4px;
                background: #17243a; border: 1px solid #627b9f;
            }
            QCheckBox#permissionCheck::indicator:checked {
                background: #167dff; border: 1px solid #4fcaff;
            }
            QListWidget#deviceList, QListWidget#glassesList {
                color: #dce8fa; background: rgba(4,11,23,0.75);
                border: 1px solid rgba(89,125,179,0.28); border-radius: 10px;
                padding: 5px; outline: 0;
            }
            QListWidget::item { border: 1px solid rgba(104,135,185,0.16);
                border-radius: 8px; padding: 7px; }
            QListWidget::item:selected { background: rgba(56,104,184,0.3); }
            QPushButton {
                color: #eaf2ff; background: rgba(30,48,76,0.92);
                border: 1px solid rgba(112,150,201,0.4); border-radius: 10px;
                padding: 10px 13px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background: rgba(44,72,112,0.98); border-color: #559fff; }
            QPushButton:pressed { background: #142c50; }
            QPushButton:disabled { color: #62738c; background: #111b2b; border-color: #25344a; }
            QPushButton#primaryButton {
                color: white; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0877f9, stop:0.55 #235cff, stop:1 #078fda);
                border: 1px solid #48c9ff; font-size: 13px; font-weight: 750;
            }
            QPushButton#primaryButton:hover { background: #168bff; }
            QPushButton#qrButton {
                color: white; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #087ce9, stop:1 #514cf0);
                border: 1px solid #39c5ff; font-weight: 750;
            }
            QPushButton#closeButton {
                background: rgba(21,38,64,0.9); border: 1px solid #368dff;
                color: #eaf3ff; padding: 10px 15px;
            }
            @media (max-width: 820px) {
                QLabel#privacyBadge { font-size: 8px; }
            }
        """)

    def _request(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        context = ssl._create_unverified_context()
        for attempt in range(2):
            headers = {
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            }
            req = urllib.request.Request(
                self.base_url + path, data=data, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(req, context=context, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                try:
                    detail = json.loads(exc.read().decode("utf-8"))
                    message = detail.get("error") or detail.get("detail") or str(exc)
                except Exception:
                    message = str(exc)
                # Dashboard sessions are process-local. If JARVIS restarted
                # between opening the drawer and an action, renew once using
                # the same trusted in-process DashboardServer instance.
                if exc.code == 401 and attempt == 0:
                    renew = getattr(self.dashboard, "create_owner_session", None)
                    if callable(renew):
                        self.token = renew()
                        continue
                    message = "Dashboard owner session expired. Close and reopen the device drawer."
                raise RuntimeError(message) from exc
            except Exception as exc:
                raise RuntimeError(
                    f"Dashboard request failed at {self.base_url}: {exc}"
                ) from exc
        raise RuntimeError("Dashboard rejected the renewed owner session.")

    def _authenticate(self):
        """Create an owner session from the exact dashboard instance we own."""
        try:
            issue = getattr(self.dashboard, "create_owner_session", None)
            if callable(issue):
                self.token = issue()
            else:
                # Compatibility with older DashboardServer builds.
                pin = self.dashboard.new_key(expiry_secs=120)
                data = json.dumps({"pin": pin}).encode("utf-8")
                req = urllib.request.Request(
                    self.base_url + "/login", data=data,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(
                    req, context=ssl._create_unverified_context(), timeout=8
                ) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.token = result.get("token", "")
            if not self.token:
                raise RuntimeError("Dashboard did not issue an owner session.")
            # Verify that the HTTP listener is serving the same live runtime
            # before enabling any bridge or pairing action.
            self._request("/api/devices/companion")
            self.status.setText("Owner authenticated · Ready to start local pairing.")
            self.qr_btn.setEnabled(True)
        except Exception as exc:
            self.token = ""
            self.qr_btn.setEnabled(False)
            message = str(exc)
            if "401" in message or "Unauthorized" in message:
                message = (
                    "The local dashboard rejected its owner session. This usually means "
                    "another or stale JARVIS process owns port 8000. Close duplicate JARVIS "
                    "instances, then restart this app. Details: " + message
                )
            self.status.setText("Could not authenticate to the dashboard: " + message)
            QMessageBox.warning(self, "JARVIS pairing", message)

    def start_bridge(self):
        try:
            result = self._request("/api/devices/companion/start", "POST", {})
            self.bridge_running = bool(result.get("running", True))
            endpoint = result.get("endpoint", "private LAN endpoint")
            self.status.setText("Secure companion bridge running at " + str(endpoint))
            self.qr_btn.setEnabled(True)
        except Exception as exc:
            self.status.setText("Bridge could not start: " + str(exc))
            QMessageBox.warning(self, "Secure bridge", str(exc))

    def stop_bridge(self):
        try:
            self._request("/api/devices/companion/stop", "POST", {})
            self.bridge_running = False
            self._offer_timer.stop()
            self._offer_expires_at = 0
            self.qr.setPixmap(QPixmap())
            self.qr.setText("Bridge stopped. Start it to generate a new pairing QR.")
            self.code.clear()
            self.qr_panel.setVisible(False)
            self.qr_btn.setText("Generate one-time QR code")
            self.code_label.setText("QR offer expires after 5 minutes")
            self.status.setText("Secure companion bridge stopped.")
        except Exception as exc:
            QMessageBox.warning(self, "Secure bridge", str(exc))

    def create_offer(self):
        scopes = [key for key, check in self.scope_checks.items() if check.isChecked()]
        if not scopes:
            QMessageBox.information(self, "Permissions", "Select at least one permission for the phone.")
            return
        if not self.bridge_running:
            QMessageBox.information(self, "Secure bridge", "Start the secure bridge before generating a QR code.")
            return
        try:
            result = self._request(
                "/api/devices/pairing-offers", "POST",
                {"scopes": scopes, "expires_in": 300},
            )
            self.code.setText(result.get("code", ""))
            self.qr_panel.setVisible(True)
            self.qr_btn.setText("Generate a new QR code")
            self._offer_expires_at = int(result.get("expires_at", time.time() + 300))
            self._update_offer_countdown()
            self._offer_timer.start()

            uri = result.get("qr_data_uri", "")
            self.qr.setPixmap(QPixmap())
            if uri.startswith("data:image/png;base64,"):
                raw = base64.b64decode(uri.split(",", 1)[1])
                pixmap = QPixmap()
                if pixmap.loadFromData(raw, "PNG"):
                    self.qr.setPixmap(pixmap.scaled(
                        196, 196, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self.qr.setText("")
                else:
                    self.qr.setText("QR image could not be rendered.")
            else:
                self.qr.setText("QR library missing. Install qrcode[pil] to display the code.")

            self.status.setText(
                "Scan this QR from the JARVIS Android companion while both devices are on the same Wi-Fi."
            )
        except Exception as exc:
            self.status.setText("QR generation failed: " + str(exc))
            QMessageBox.warning(self, "Pairing QR", str(exc))

    def _update_offer_countdown(self):
        remaining = max(0, self._offer_expires_at - int(time.time()))
        if remaining <= 0:
            self._offer_timer.stop()
            self.code_label.setText("QR offer expired · Generate a new code")
            self.code.clear()
            self.qr.setPixmap(QPixmap())
            self.qr.setText("This pairing code has expired. Generate a new one to continue.")
            self.qr_btn.setText("Generate a new QR code")
            return
        minutes, seconds = divmod(remaining, 60)
        self.code_label.setText(f"QR offer expires in {minutes}:{seconds:02d}")

    def refresh_devices(self):
        if not self.token:
            return
        try:
            result = self._request("/api/devices")
            self.devices.clear()
            devices = result.get("devices", [])
            for device in devices:
                name = device.get("device_name", "Unnamed device")
                platform = device.get("platform", "Unknown platform")
                online = bool(device.get("online"))
                scopes = ", ".join(device.get("scopes", [])) or "No permissions"
                item = QListWidgetItem()
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(8, 5, 8, 5)
                layout.setSpacing(10)
                icon = QLabel("▣" if "android" in str(platform).lower() or "phone" in str(platform).lower() else "⌘")
                icon.setStyleSheet("color:#65caff;font-size:20px;")
                layout.addWidget(icon)
                detail = QVBoxLayout()
                detail.setSpacing(1)
                name_label = QLabel(f"{name}  ·  {platform}")
                name_label.setStyleSheet("color:#edf3ff;font-weight:700;")
                state_label = QLabel(("● ONLINE" if online else "● OFFLINE") + f"   ·   {scopes}")
                state_label.setStyleSheet(
                    "color:#62e6b1;font-size:10px;" if online
                    else "color:#8999b2;font-size:10px;"
                )
                detail.addWidget(name_label)
                detail.addWidget(state_label)
                layout.addLayout(detail, 1)
                revoke = QPushButton("Revoke")
                revoke.setObjectName("secondaryButton")
                revoke.setMinimumWidth(78)
                device_id = device.get("device_id")
                revoke.clicked.connect(
                    lambda checked=False, identifier=device_id: self.revoke_device(identifier)
                )
                layout.addWidget(revoke)
                self.devices.addItem(item)
                self.devices.setItemWidget(item, row)
                item.setSizeHint(row.sizeHint())
                item.setData(Qt.ItemDataRole.UserRole, device_id)

            count = len(devices)
            self.device_count.setText(f"{count} CONNECTED" if count else "0 CONNECTED")
            self.status.setText(f"Loaded {count} paired device(s).")
            if not count:
                self.devices.addItem("No devices paired yet · Start the secure bridge and scan the QR code above.")
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
            result = self._request(
                "/api/devices/glasses/discover", "POST", {"timeout": 5.0}
            )
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

    def closeEvent(self, event):
        self._offer_timer.stop()
        super().closeEvent(event)
