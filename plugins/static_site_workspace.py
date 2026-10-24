"""Small PyQt visual workspace for the local static site builder."""
from __future__ import annotations
import json
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextBrowser, QTextEdit, QVBoxLayout,
)
from plugins import static_site_builder


class StaticSiteWorkspaceDialog(QDialog):
    """Preview and create provider-independent static websites from a visual form."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mark 56 · Local Website Builder")
        self.resize(980, 760)
        self._last_preview = None
        self.setStyleSheet("""
            QDialog { background: #080d16; color: #edf4fb; }
            QLabel { color: #a9b8c9; }
            QLineEdit, QComboBox, QTextEdit { background: #111c2a; color: #edf4fb;
                border: 1px solid #2b3b50; border-radius: 6px; padding: 8px; }
            QPushButton { background: #65e5f0; color: #071018; border: 0;
                border-radius: 6px; padding: 9px 14px; font-weight: 700; }
            QPushButton#secondary { background: #172536; color: #edf4fb;
                border: 1px solid #2b3b50; }
            QTextBrowser { background: #f7f8fa; color: #121820; border: 1px solid #2b3b50; }
        """)
        layout = QVBoxLayout(self)
        heading = QLabel("LOCAL STATIC WEBSITE BUILDER")
        heading.setFont(QFont("Sans Serif", 14, QFont.Weight.Bold))
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "Builds a responsive HTML/CSS/JavaScript site on this computer. "
            "No AI provider, API key, or network request is used."
        ))
        form = QFormLayout()
        self.name = QLineEdit("my-website")
        self.kind = QComboBox()
        self.kind.addItems(["portfolio", "business", "landing", "church"])
        self.title = QLineEdit()
        self.tagline = QLineEdit()
        self.about = QTextEdit()
        self.about.setFixedHeight(68)
        self.email = QLineEdit("hello@example.com")
        self.services = QLineEdit("Brand identity, Web design, Creative development")
        self.accent = QComboBox()
        self.accent.addItems(["cyan", "violet", "amber", "green"])
        form.addRow("Project folder", self.name)
        form.addRow("Website type", self.kind)
        form.addRow("Site / brand title", self.title)
        form.addRow("Hero headline", self.tagline)
        form.addRow("About text", self.about)
        form.addRow("Contact email", self.email)
        form.addRow("Cards (comma separated)", self.services)
        form.addRow("Accent color", self.accent)
        layout.addLayout(form)
        actions = QHBoxLayout()
        preview_btn = QPushButton("Preview website")
        preview_btn.clicked.connect(self._preview)
        actions.addWidget(preview_btn)
        self.create_btn = QPushButton("Create website")
        self.create_btn.clicked.connect(self._create)
        actions.addWidget(self.create_btn)
        open_btn = QPushButton("Open workspace folder")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._open_workspace)
        actions.addWidget(open_btn)
        layout.addLayout(actions)
        self.status = QLabel("Preview first. Creation will not overwrite an existing folder.")
        layout.addWidget(self.status)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        layout.addWidget(self.preview, 1)

    def _parameters(self, operation):
        services = [x.strip() for x in self.services.text().split(",") if x.strip()]
        return {
            "operation": operation, "name": self.name.text().strip(),
            "kind": self.kind.currentText(), "site_title": self.title.text().strip(),
            "tagline": self.tagline.text().strip(), "about": self.about.toPlainText().strip(),
            "email": self.email.text().strip(), "services": services,
            "accent": self.accent.currentText(),
        }

    def _preview(self):
        result = json.loads(static_site_builder.run(self._parameters("preview")))
        if not result.get("ok"):
            QMessageBox.warning(self, "Cannot preview", result.get("message", "Invalid website settings."))
            return
        self._last_preview = result
        self.preview.setHtml(result.get("preview_html", ""))
        self.status.setText(
            "Preview only — nothing has been written. Files: " + ", ".join(result["files"])
        )

    def _create(self):
        if self._last_preview is None:
            QMessageBox.information(self, "Preview first", "Generate and review the website preview before creating files.")
            return
        params = self._parameters("create")
        if params["name"] != self._last_preview["name"]:
            QMessageBox.information(self, "Preview changed", "Settings changed since preview. Preview again before creating.")
            return
        answer = QMessageBox.question(
            self, "Create local website?",
            "Create this website in the configured Mark 56 workspace? Existing folders are never overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        params["confirmed"] = True
        result = json.loads(static_site_builder.run(params))
        if result.get("ok"):
            self.status.setText("Created: " + result["destination"])
            QMessageBox.information(self, "Website created", result["destination"])
        else:
            QMessageBox.warning(self, "Creation blocked", result.get("message", "The site was not created."))

    def _open_workspace(self):
        from plugins.static_site_builder import _root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(_root())))
