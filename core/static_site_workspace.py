"""Premium PyQt workspace for the local static website builder.

The interface is deliberately split into a guided setup panel and a live preview,
so creating a site feels like a small design studio rather than a plain form.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)
from plugins import static_site_builder


class StaticSiteWorkspaceDialog(QDialog):
    """Guided, preview-first workspace for creating local static websites."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mark 56 · Website Studio")
        self.resize(1180, 800)
        self.setMinimumSize(860, 620)
        self._last_preview = None
        self._last_preview_params = None
        self.setStyleSheet("""
            QDialog { background: #060b12; color: #e8f3fb; }
            QLabel { color: #a8bdce; background: transparent; }
            QLabel#eyebrow { color: #42d9f5; font-size: 10px; font-weight: 800; letter-spacing: 2px; }
            QLabel#heroTitle { color: #f3fbff; font-size: 25px; font-weight: 800; }
            QLabel#sectionTitle { color: #e8f7ff; font-size: 13px; font-weight: 700; }
            QLabel#hint { color: #6f8a9e; font-size: 11px; }
            QFrame#surface { background: #0a1420; border: 1px solid #1b3447; border-radius: 14px; }
            QFrame#previewSurface { background: #0a1420; border: 1px solid #1b3447; border-radius: 14px; }
            QLineEdit, QComboBox, QTextEdit {
                background: #07101a; color: #eaf7ff; border: 1px solid #244256;
                border-radius: 8px; padding: 9px 11px; selection-background-color: #087f9d;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid #35c9ed; }
            QComboBox::drop-down { border: 0; width: 24px; }
            QComboBox QAbstractItemView { background: #0b1723; color: #eaf7ff; selection-background-color: #123d50; }
            QPushButton {
                background: #29c8e8; color: #04121a; border: 1px solid #29c8e8;
                border-radius: 8px; padding: 10px 15px; font-weight: 800;
            }
            QPushButton:hover { background: #71e4f6; border-color: #71e4f6; }
            QPushButton#secondary {
                background: #0c1b29; color: #b9d4e3; border: 1px solid #29495d;
            }
            QPushButton#secondary:hover { color: #f0fbff; border-color: #38c8e9; background: #102a3a; }
            QPushButton:disabled { color: #587282; background: #10202b; border-color: #213744; }
            QTextBrowser { background: #f5f8fb; color: #15202b; border: 0; border-radius: 8px; padding: 8px; }
            QScrollArea { border: 0; background: transparent; }
            QScrollBar:vertical { background: #08131d; width: 7px; margin: 2px; border-radius: 3px; }
            QScrollBar::handle:vertical { background: #2a596e; min-height: 25px; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        masthead = QHBoxLayout()
        brand = QVBoxLayout()
        eyebrow = QLabel("MARK 56  /  CREATIVE TOOLS")
        eyebrow.setObjectName("eyebrow")
        brand.addWidget(eyebrow)
        title = QLabel("Website Studio")
        title.setObjectName("heroTitle")
        brand.addWidget(title)
        intro = QLabel("Shape your site, review the design, then create clean local files.")
        intro.setObjectName("hint")
        brand.addWidget(intro)
        masthead.addLayout(brand)
        masthead.addStretch()
        badge = QLabel("LOCAL BUILD  ·  NO API KEY")
        badge.setStyleSheet("color:#73e5b1; background:#0c2824; border:1px solid #1d5949; border-radius:8px; padding:8px 11px; font-size:10px; font-weight:800;")
        masthead.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(masthead)

        workspace = QHBoxLayout()
        workspace.setSpacing(16)

        # Left: scrollable guided configuration
        setup_card = QFrame()
        setup_card.setObjectName("surface")
        setup_layout = QVBoxLayout(setup_card)
        setup_layout.setContentsMargins(18, 18, 18, 18)
        setup_layout.setSpacing(12)
        setup_heading = QLabel("01  ·  PROJECT SETUP")
        setup_heading.setObjectName("sectionTitle")
        setup_layout.addWidget(setup_heading)
        setup_hint = QLabel("Start with the essentials. You can preview before any files are written.")
        setup_hint.setWordWrap(True)
        setup_hint.setObjectName("hint")
        setup_layout.addWidget(setup_hint)

        form_host = QWidget()
        form_host.setStyleSheet("background:transparent;")
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name = QLineEdit("my-website")
        self.name.setPlaceholderText("my-website")
        self.kind = QComboBox()
        self.kind.addItems(["portfolio", "business", "landing", "church"])
        self.title = QLineEdit()
        self.title.setPlaceholderText("Your brand or project name")
        self.tagline = QLineEdit()
        self.tagline.setPlaceholderText("A clear, memorable headline")
        self.about = QTextEdit()
        self.about.setPlaceholderText("Briefly introduce your brand, mission or service…")
        self.about.setMinimumHeight(92)
        self.about.setMaximumHeight(125)
        self.email = QLineEdit("hello@example.com")
        self.services = QLineEdit("Brand identity, Web design, Creative development")
        self.services.setPlaceholderText("Separate cards with commas")
        self.accent = QComboBox()
        self.accent.addItems(["cyan", "violet", "amber", "green"])

        def field_label(text):
            label = QLabel(text)
            label.setStyleSheet("color:#a8c6d8; font-size:11px; font-weight:700;")
            return label

        form.addRow(field_label("Project folder"), self.name)
        form.addRow(field_label("Website style"), self.kind)
        form.addRow(field_label("Brand title"), self.title)
        form.addRow(field_label("Hero headline"), self.tagline)
        form.addRow(field_label("About your brand"), self.about)
        form.addRow(field_label("Contact email"), self.email)
        form.addRow(field_label("Content cards"), self.services)
        form.addRow(field_label("Accent palette"), self.accent)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_host)
        setup_layout.addWidget(form_scroll, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        self.preview_btn = QPushButton("↗   Generate live preview")
        self.preview_btn.setToolTip("Render a preview without creating files")
        self.preview_btn.clicked.connect(self._preview)
        actions.addWidget(self.preview_btn)
        secondary_actions = QHBoxLayout()
        self.create_btn = QPushButton("Create website")
        self.create_btn.setObjectName("secondary")
        self.create_btn.clicked.connect(self._create)
        self.create_btn.setEnabled(False)
        secondary_actions.addWidget(self.create_btn)
        open_btn = QPushButton("Open folder")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._open_workspace)
        secondary_actions.addWidget(open_btn)
        actions.addLayout(secondary_actions)
        setup_layout.addLayout(actions)

        # Right: preview canvas with a clear empty state
        preview_card = QFrame()
        preview_card.setObjectName("previewSurface")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(12)
        preview_top = QHBoxLayout()
        preview_title = QLabel("02  ·  LIVE PREVIEW")
        preview_title.setObjectName("sectionTitle")
        preview_top.addWidget(preview_title)
        preview_top.addStretch()
        self.preview_state = QLabel("WAITING FOR PREVIEW")
        self.preview_state.setStyleSheet("color:#8aa6b8; background:#101f2b; border:1px solid #294254; border-radius:7px; padding:6px 8px; font-size:9px; font-weight:800;")
        preview_top.addWidget(self.preview_state)
        preview_layout.addLayout(preview_top)
        preview_description = QLabel("Your generated page appears here. Nothing is saved until you confirm creation.")
        preview_description.setObjectName("hint")
        preview_description.setWordWrap(True)
        preview_layout.addWidget(preview_description)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setHtml("""
            <html><body style="margin:0;background:#0b1420;color:#b6c9d7;font-family:Arial,sans-serif;">
            <div style="height:100%;min-height:360px;display:flex;align-items:center;justify-content:center;text-align:center;padding:32px;box-sizing:border-box;">
              <div><div style="font-size:42px;color:#35c9ed;">✦</div>
              <h2 style="color:#f1f8fc;font-size:22px;margin-bottom:8px;">Your next website starts here</h2>
              <p style="line-height:1.7;max-width:340px;">Add your brand details, then generate a preview to see the first design direction.</p>
              <p style="font-size:11px;color:#66889c;">PREVIEW FIRST · CREATE WHEN READY</p></div>
            </div></body></html>
        """)
        preview_layout.addWidget(self.preview, 1)
        self.status = QLabel("Ready when you are · Preview first, then create safely.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#7f9caf; font-size:11px; padding:3px 2px;")
        preview_layout.addWidget(self.status)

        workspace.addWidget(setup_card, 5)
        workspace.addWidget(preview_card, 7)
        root.addLayout(workspace, 1)

        footer = QHBoxLayout()
        footer_note = QLabel("MARK 56  •  FILES STAY ON THIS COMPUTER  •  EXISTING FOLDERS ARE NEVER OVERWRITTEN")
        footer_note.setStyleSheet("color:#4d7186; font-size:9px; font-weight:700;")
        footer.addWidget(footer_note)
        footer.addStretch()
        close_btn = QPushButton("Close studio")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        root.addLayout(footer)

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
        try:
            result = json.loads(static_site_builder.run(self._parameters("preview")))
        except Exception as exc:
            QMessageBox.warning(self, "Preview unavailable", f"The website preview could not be generated.\n\n{type(exc).__name__}: {exc}")
            return
        if not result.get("ok"):
            QMessageBox.warning(self, "Cannot preview", result.get("message", "Invalid website settings."))
            return
        self._last_preview = result
        self._last_preview_params = self._parameters("preview")
        self.preview.setHtml(result.get("preview_html", ""))
        self.preview_state.setText("PREVIEW READY")
        self.preview_state.setStyleSheet("color:#73e5b1; background:#0c2824; border:1px solid #1d5949; border-radius:7px; padding:6px 8px; font-size:9px; font-weight:800;")
        self.create_btn.setEnabled(True)
        self.status.setText("Preview generated · " + ", ".join(result.get("files", [])) + " · No files have been written yet.")

    def _create(self):
        if self._last_preview is None:
            QMessageBox.information(self, "Preview first", "Generate and review the website preview before creating files.")
            return
        params = self._parameters("create")
        if self._last_preview_params != self._parameters("preview"):
            self.create_btn.setEnabled(False)
            self.preview_state.setText("PREVIEW OUT OF DATE")
            QMessageBox.information(self, "Preview changed", "One or more settings changed since preview. Generate a fresh preview before creating.")
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
        try:
            result = json.loads(static_site_builder.run(params))
        except Exception as exc:
            QMessageBox.warning(self, "Creation failed", f"No website was confirmed as created.\n\n{type(exc).__name__}: {exc}")
            return
        if result.get("ok"):
            destination = result.get("destination", "")
            self.status.setText("Website created successfully · " + destination)
            QMessageBox.information(self, "Website created", destination)
        else:
            QMessageBox.warning(self, "Creation blocked", result.get("message", "The site was not created."))

    def _open_workspace(self):
        from plugins.static_site_builder import _root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(_root())))