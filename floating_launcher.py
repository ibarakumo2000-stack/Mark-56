"""Minimal holographic JARVIS face launcher.

The face reuses the live HoloAvatar instance owned by HudCanvas, so its blink,
gaze and speech animation stay in sync with the main assistant's audio pipeline.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication, QInputDialog, QMenu, QSystemTrayIcon, QToolTip, QWidget,
)


class FloatingLauncher(QWidget):
    """Small transparent, draggable holographic face with a right-click menu."""

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
        self._muted = False
        self._status = "CONNECTING"
        self._reply = ""
        self._avatar = None
        self._primary = QColor("#00d4ff")
        self._accent = QColor("#ff6b00")
        self._background = QColor("#00060a")
        self._large = False
        self._allow_close = False

        self.setWindowTitle("JARVIS Hologram")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(156, 166)
        self.setToolTip("J.A.R.V.I.S · Right-click for controls")
        self.setMouseTracking(True)

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
            tray_menu = QMenu()
            show_action = QAction("Show hologram", tray_menu)
            show_action.triggered.connect(self.show_launcher)
            open_action = QAction("Open full interface", tray_menu)
            open_action.triggered.connect(self.open_requested.emit)
            quit_action = QAction("Quit JARVIS", tray_menu)
            quit_action.triggered.connect(self.quit_requested.emit)
            tray_menu.addAction(show_action)
            tray_menu.addAction(open_action)
            tray_menu.addSeparator()
            tray_menu.addAction(quit_action)
            self._tray.setContextMenu(tray_menu)
            self._tray.activated.connect(lambda _reason: self.show_launcher())
            self._tray.show()

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self.update)
        self._animation_timer.start(33)
        self._place_initially()

    def set_avatar(self, avatar, primary=None, accent=None, background=None):
        """Share the main HUD's animated avatar rather than creating a second one."""
        self._avatar = avatar
        if primary is not None:
            self._primary = QColor(primary)
        if accent is not None:
            self._accent = QColor(accent)
        if background is not None:
            self._background = QColor(background)
        self.update()

    def _place_initially(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(30, 80)
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 30, area.bottom() - self.height() - 90)

    def _dispatch_command(self, text: str):
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

    def open_quick_chat(self):
        message, accepted = QInputDialog.getText(
            self, "Talk to JARVIS", "Message JARVIS:"
        )
        message = message.strip()
        if accepted and message:
            self._reply = "You: " + message
            self.setToolTip(self._reply + "\nJARVIS is responding…")
            self.command_requested.emit(message)

    def send_message(self, text: str | None = None):
        """Compatibility entry point for quick-chat integrations."""
        if text is None:
            self.open_quick_chat()
            return
        message = str(text).strip()
        if message:
            self.command_requested.emit(message)

    def _show_reply(self, text: str):
        self._reply = (text or "").strip()
        if self._reply:
            self.setToolTip("JARVIS · " + self._reply[:700])
            if self.isVisible():
                QToolTip.showText(
                    self.mapToGlobal(QPoint(self.width() // 2, self.height() - 8)),
                    "JARVIS\n" + self._reply[:260],
                    self,
                    self.rect(),
                    5500,
                )

    def _set_status(self, status: str):
        self._status = str(status or "UNKNOWN").upper()
        if self._tray:
            self._tray.setToolTip("JARVIS · " + self._status)
        self.setToolTip(
            f"J.A.R.V.I.S · {self._status} · Right-click for controls"
        )

    def _set_muted(self, muted: bool):
        self._muted = bool(muted)
        self.update()

    def set_reply(self, text: str):
        self.reply_received.emit(str(text or ""))

    def set_status(self, status: str):
        self.status_received.emit(str(status or ""))

    def set_muted(self, muted: bool):
        self.muted_received.emit(bool(muted))

    def toggle_expanded(self):
        # Kept as a compact compatibility action: enlarge the face slightly,
        # never reveal a rectangular control panel.
        self._large = not self._large
        self.setFixedSize(178, 188) if self._large else self.setFixedSize(156, 166)
        self.update()

    def show_launcher(self):
        self.show()
        self.raise_()

    def hide_to_tray(self):
        if self._tray:
            self.hide()
            self._tray.showMessage("JARVIS", "Still running in the background.")
            return
        # Without a tray host, keep the hologram reachable instead of hiding
        # the live assistant behind an invisible process.
        self.setToolTip("JARVIS is running · This desktop has no system tray")
        self._large = False
        self.setFixedSize(156, 166)
        self.show_launcher()

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #061722; color: #d8f8ff;
                border: 1px solid #1686a5; padding: 6px;
            }
            QMenu::item { padding: 8px 24px; }
            QMenu::item:selected { background: #0b5269; }
            QMenu::separator { height: 1px; background: #174052; margin: 4px 8px; }
        """)
        chat = QAction("Quick chat with JARVIS…", menu)
        chat.triggered.connect(self.open_quick_chat)
        menu.addAction(chat)

        mic = QAction(
            "Unmute microphone" if self._muted else "Mute microphone", menu
        )
        mic.triggered.connect(self.mute_requested.emit)
        menu.addAction(mic)

        menu.addSeparator()
        open_full = QAction("Open full JARVIS interface", menu)
        open_full.triggered.connect(self.open_requested.emit)
        menu.addAction(open_full)

        size_action = QAction(
            "Restore hologram size" if self._large else "Enlarge hologram slightly",
            menu,
        )
        size_action.triggered.connect(self.toggle_expanded)
        menu.addAction(size_action)

        if self._tray:
            hide_action = QAction("Hide hologram to system tray", menu)
            hide_action.triggered.connect(self.hide_to_tray)
            menu.addAction(hide_action)

        menu.addSeparator()
        quit_action = QAction("Quit JARVIS completely", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)
        return menu

    def contextMenuEvent(self, event):
        self._build_context_menu().exec(event.globalPos())
        event.accept()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2.0
        cy = self.height() / 2.0 + 2.0

        # A restrained aura keeps the face legible without drawing a panel,
        # card, border or opaque backdrop.
        halo = QRadialGradient(cx, cy, min(self.width(), self.height()) * 0.48)
        halo.setColorAt(0.0, QColor(0, 212, 255, 24))
        halo.setColorAt(0.55, QColor(0, 160, 210, 13))
        halo.setColorAt(1.0, QColor(0, 100, 150, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(
            int(cx - 70), int(cy - 76), 140 if not self._large else 160,
            148 if not self._large else 166,
        )

        if self._avatar is not None:
            try:
                radius = 43.0 if not self._large else 49.0
                self._avatar.paint(
                    painter, cx, cy, radius,
                    self._primary, self._accent, self._background,
                )
            except Exception:
                self._paint_fallback_face(painter, cx, cy)
        else:
            self._paint_fallback_face(painter, cx, cy)

        # Small state indicator, integrated into the hologram rather than a
        # label or control strip.
        state_color = QColor("#ff5577") if self._muted else QColor("#55ffbd")
        if self._status in ("SPEAKING", "THINKING", "PROCESSING"):
            state_color = QColor("#00dfff")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(state_color))
        painter.drawEllipse(int(cx + 43), int(cy + 47), 7, 7)
        painter.end()

    def _paint_fallback_face(self, painter: QPainter, cx: float, cy: float):
        color = QColor(self._primary)
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(int(cx - 35), int(cy - 48), 70, 96)
        painter.drawArc(int(cx - 22), int(cy - 22), 17, 11, 0, 180 * 16)
        painter.drawArc(int(cx + 5), int(cy - 22), 17, 11, 0, 180 * 16)
        painter.drawArc(int(cx - 13), int(cy + 7), 26, 14, 190 * 16, 160 * 16)

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
        if self._allow_close:
            event.accept()
            return
        # A window-manager close dismisses the launcher, not the assistant.
        event.ignore()
        self.hide_to_tray()
