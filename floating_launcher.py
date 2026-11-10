"""Compact, always-on-top JARVIS launcher for the desktop application.

The launcher is a presentation layer only. Commands and microphone state are
provided by JarvisUI, which delegates them to the existing JarvisLive runtime.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)


class FloatingLauncher(QWidget):
    """Draggable assistant orb with quick controls and a compact chat surface."""

    command_requested = pyqtSignal(str)
    mute_requested = pyqtSignal()
    open_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    reply_received = pyqtSignal(str)
    status_received = pyqtSignal(str)
    muted_received = pyqtSignal(bool)

    def __init__(self, icon: QIcon | None = None, parent=None):
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._expanded = True
        self._muted = False
        self._status = "CONNECTING"
        self.setWindowTitle("JARVIS")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(310)
        self.setMaximumWidth(350)
        self._build_ui()
        self.command_requested.connect(self._dispatch_command)
        self.mute_requested.connect(self._dispatch_mute)
        self.open_requested.connect(self._dispatch_open)
        self.quit_requested.connect(self._dispatch_quit)
        self.reply_received.connect(self._show_reply)
        self.status_received.connect(self._set_status)
        self.muted_received.connect(self._set_muted)

        self._tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(icon or QIcon(), self)
            self._tray.setToolTip("JARVIS is running")
            menu = QMenu()
            show_action = QAction("Show JARVIS", menu)
            show_action.triggered.connect(self.show_launcher)
            open_action = QAction("Open full interface", menu)
            open_action.triggered.connect(self.open_requested.emit)
            quit_action = QAction("Quit JARVIS", menu)
            quit_action.triggered.connect(self.quit_requested.emit)
            menu.addAction(show_action)
            menu.addAction(open_action)
            menu.addSeparator()
            menu.addAction(quit_action)
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(lambda _reason: self.show_launcher())
            self._tray.show()

        self._place_initially()

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget#launcherCard {
                background: #07131d;
                border: 1px solid #17617a;
                border-radius: 18px;
                color: #d8f8ff;
            }
            QLabel { background: transparent; color: #d8f8ff; }
            QLabel#brand { color: #35dfff; font-size: 13px; font-weight: 800; letter-spacing: 2px; }
            QLabel#status { color: #62a9ba; font-size: 9px; font-weight: 700; }
            QLabel#reply { color: #b9eaf2; font-size: 11px; padding: 7px; background: #0b202c; border-radius: 9px; }
            QPushButton {
                background: #0b2634; color: #9deeff; border: 1px solid #1b5268;
                border-radius: 9px; padding: 7px 10px; font-size: 10px; font-weight: 700;
            }
            QPushButton:hover { background: #10394a; border-color: #28c9ed; }
            QPushButton#primary { background: #063a4a; border-color: #00c9f0; color: #d9fbff; }
            QPushButton#danger { color: #ff9bad; border-color: #6d3041; }
            QLineEdit {
                background: #030c12; color: #e5fbff; border: 1px solid #1b5268;
                border-radius: 10px; padding: 10px; selection-background-color: #087b98;
            }
            QFrame#separator { background: #173747; max-height: 1px; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        card = QFrame()
        card.setObjectName("launcherCard")
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(13, 11, 13, 12)
        root.setSpacing(9)

        header = QHBoxLayout()
        orb = QLabel("◉")
        orb.setStyleSheet("color:#22d9ff;font-size:23px;font-weight:900;")
        header.addWidget(orb)
        identity = QVBoxLayout()
        brand = QLabel("J.A.R.V.I.S")
        brand.setObjectName("brand")
        status = QLabel("INITIALISING")
        status.setObjectName("status")
        self.status_label = status
        identity.addWidget(brand)
        identity.addWidget(status)
        header.addLayout(identity)
        header.addStretch()
        self.expand_button = QPushButton("—")
        self.expand_button.setFixedWidth(30)
        self.expand_button.setToolTip("Collapse launcher")
        self.expand_button.clicked.connect(self.toggle_expanded)
        header.addWidget(self.expand_button)
        dismiss = QPushButton("×")
        dismiss.setObjectName("danger")
        dismiss.setFixedWidth(30)
        dismiss.setToolTip("Hide to system tray")
        dismiss.clicked.connect(self.hide_to_tray)
        header.addWidget(dismiss)
        root.addLayout(header)

        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)

        controls = QHBoxLayout()
        self.open_button = QPushButton("OPEN FULL INTERFACE")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_requested.emit)
        controls.addWidget(self.open_button, 1)
        self.mute_button = QPushButton("MIC ON")
        self.mute_button.clicked.connect(self.mute_requested.emit)
        controls.addWidget(self.mute_button)
        details.addLayout(controls)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        details.addWidget(sep)

        self.reply_label = QLabel("Ready when you are. Ask JARVIS anything.")
        self.reply_label.setObjectName("reply")
        self.reply_label.setWordWrap(True)
        self.reply_label.setMinimumHeight(38)
        details.addWidget(self.reply_label)

        chat = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message JARVIS…")
        self.input.returnPressed.connect(self.send_message)
        chat.addWidget(self.input, 1)
        send = QPushButton("SEND")
        send.setObjectName("primary")
        send.clicked.connect(self.send_message)
        chat.addWidget(send)
        details.addLayout(chat)
        root.addWidget(self.details)

    def _place_initially(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(30, 80)
            return
        area = screen.availableGeometry()
        self.adjustSize()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 70)

    def _dispatch_command(self, text: str):
        # The host wires this signal to JarvisLive._on_text_command.
        callback = getattr(self, "on_command", None)
        if callable(callback):
            callback(text)

    def _dispatch_mute(self):
        callback = getattr(self, "on_mute", None)
        if callable(callback):
            callback()

    def _dispatch_open(self):
        callback = getattr(self, "on_open", None)
        if callable(callback):
            callback()

    def _dispatch_quit(self):
        callback = getattr(self, "on_quit", None)
        if callable(callback):
            callback()

    def send_message(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.reply_label.setText("YOU  ·  " + text[:240])
        callback = getattr(self, "on_command", None)
        if callable(callback):
            callback(text)

    def _show_reply(self, text: str):
        self.reply_label.setText("JARVIS  ·  " + (text or "").strip()[:700])
        self.reply_label.setToolTip(text or "")

    def _set_status(self, status: str):
        self._status = str(status or "UNKNOWN").upper()
        self.status_label.setText(self._status[:32])
        if self._tray:
            self._tray.setToolTip("JARVIS · " + self._status)

    def _set_muted(self, muted: bool):
        self._muted = bool(muted)
        self.mute_button.setText("MIC MUTED" if self._muted else "MIC ON")
        self.mute_button.setStyleSheet(
            "color:#ff9bad;border-color:#a13b55;" if self._muted else
            "color:#8cffbd;border-color:#1b7652;"
        )

    def set_reply(self, text: str):
        self.reply_received.emit(str(text or ""))

    def set_status(self, status: str):
        self.status_received.emit(str(status or ""))

    def set_muted(self, muted: bool):
        self.muted_received.emit(bool(muted))

    def toggle_expanded(self):
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self.expand_button.setText("—" if self._expanded else "+")
        self.expand_button.setToolTip("Collapse launcher" if self._expanded else "Expand launcher")
        self.adjustSize()

    def show_launcher(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        self.hide()
        if self._tray:
            self._tray.showMessage("JARVIS", "Still running in the background.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        # Closing the compact surface means dismiss, not terminate the assistant.
        event.ignore()
        self.hide_to_tray()
