"""First-run OpenAI setup dialog for Mark 56 Website Studio."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

from core import website_studio_credentials as credentials


class WebsiteStudioSetupDialog(QDialog):
    """Collect, validate, and securely save the Website Studio-only API key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mark 56 · Connect Website Studio")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet("""
            QDialog { background:#07101a; color:#eaf5fc; }
            QLabel { color:#a9c2d3; background:transparent; }
            QLabel#title { color:#f4fbff; font-size:22px; font-weight:800; }
            QLabel#eyebrow { color:#45d8f1; font-size:10px; font-weight:800; letter-spacing:2px; }
            QFrame#card { background:#0b1926; border:1px solid #234155; border-radius:14px; }
            QLineEdit { background:#06101a; color:#f0f8ff; border:1px solid #29495d;
                        border-radius:8px; padding:11px; selection-background-color:#087f9d; }
            QLineEdit:focus { border:1px solid #35c9ed; }
            QPushButton { background:#29c8e8; color:#04121a; border:1px solid #29c8e8;
                          border-radius:8px; padding:10px 14px; font-weight:800; }
            QPushButton#secondary { background:#0c1b29; color:#b9d4e3; border:1px solid #29495d; }
            QPushButton:disabled { color:#587282; background:#10202b; border-color:#213744; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        eyebrow = QLabel("MARK 56  /  WEBSITE STUDIO")
        eyebrow.setObjectName("eyebrow")
        root.addWidget(eyebrow)
        title = QLabel("Connect your OpenAI API")
        title.setObjectName("title")
        root.addWidget(title)
        intro = QLabel(
            "Set this up once to prepare Website Studio for AI-powered planning and code generation. "
            "Your key is checked with OpenAI before it is saved."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)
        card_layout.addWidget(QLabel("OpenAI API key"))
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Paste your API key")
        self.key_input.setClearButtonEnabled(True)
        self.key_input.setToolTip("The key is sent only to OpenAI for validation, then stored in the OS credential store.")
        card_layout.addWidget(self.key_input)

        note = QLabel(
            "Stored separately from Mark 56's global Gemini settings, in your operating-system "
            "credential store. It is not written to api_keys.json or website files."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#82a0b4; font-size:11px;")
        card_layout.addWidget(note)
        root.addWidget(card)

        links = QHBoxLayout()
        help_link = QPushButton("Get an API key")
        help_link.setObjectName("secondary")
        help_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://platform.openai.com/api-keys")))
        links.addWidget(help_link)
        links.addStretch()
        root.addLayout(links)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.connect_button = QPushButton("Validate and save securely")
        self.connect_button.clicked.connect(self._save)
        actions.addWidget(self.connect_button)
        root.addLayout(actions)

        self.key_input.returnPressed.connect(self._save)
        self.key_input.setFocus()

    def _save(self):
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "API key required", "Paste your OpenAI API key to continue.")
            return
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Validating…")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            credentials.save_api_key(key)
        except credentials.CredentialError as exc:
            QMessageBox.warning(self, "Could not connect", str(exc))
            return
        except Exception:
            QMessageBox.warning(
                self, "Could not save key",
                "The key could not be saved securely. No plain-text fallback was used."
            )
            return
        finally:
            self.unsetCursor()
            self.connect_button.setEnabled(True)
            self.connect_button.setText("Validate and save securely")

        self.key_input.clear()
        QMessageBox.information(
            self, "Website Studio connected",
            "OpenAI validated the key and it was saved in your operating-system credential store."
        )
        self.accept()
