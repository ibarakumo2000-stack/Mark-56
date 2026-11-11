"""Optional voice-engine settings dialog for Mark 56.

Provider implementations are ported from FatihMakes/Mark-LVII under the
repository's existing CC BY-NC 4.0 attribution terms. This panel is native to
Mark 56's PyQt UI and does not replace its existing setup or controls drawers.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from memory.config_manager import (
    get_pipeline, get_provider_config, get_provider_mode, save_providers,
)
from . import registry


_STYLE = """
QDialog, QWidget { background: #07151b; color: #d9edf0; }
QLabel { color: #a9c7cc; }
QGroupBox { border: 1px solid #1b4650; border-radius: 9px; margin-top: 12px;
            padding: 12px 9px 9px; font-weight: 600; color: #69d8d0; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QDoubleSpinBox {
    background: #0b2028; border: 1px solid #24515b; border-radius: 6px;
    padding: 7px; color: #e4f5f5; min-height: 20px;
}
QComboBox QAbstractItemView { background: #0b2028; color: #e4f5f5;
                               selection-background-color: #176b70; }
QPushButton { background: #12343c; border: 1px solid #28616a; border-radius: 7px;
              padding: 8px 16px; color: #e5ffff; font-weight: 600; }
QPushButton:hover { background: #18515a; }
QPushButton#apply { background: #126b68; border-color: #269b91; }
QPushButton#apply:hover { background: #17847e; }
QScrollArea { border: none; }
"""


class ProviderSettingsDialog(QDialog):
    """Choose Gemini Live or a configurable STT → LLM → TTS conversation."""

    def __init__(self, parent: QWidget | None = None,
                 on_applied: Callable[[], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS · Engine & Providers")
        self.setMinimumSize(620, 620)
        self.resize(700, 760)
        self.setStyleSheet(_STYLE)
        self._on_applied = on_applied
        self._declarations: dict[str, list[dict]] = {
            kind: registry.discover(kind) for kind in ("llm", "stt", "tts")
        }
        self._options: dict[str, list[tuple[str, str, dict]]] = {}
        self._combos: dict[str, QComboBox] = {}
        self._forms: dict[str, QFormLayout] = {}
        self._field_widgets: dict[str, dict[str, QWidget]] = {}
        self._drafts: dict[str, dict] = {}
        self._service_ids: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        heading = QLabel("ENGINE & PROVIDERS")
        heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #75e1d8;")
        root.addWidget(heading)
        intro = QLabel(
            "Keep Gemini Live, or assemble a private / custom voice engine from "
            "speech recognition, a language model and a voice."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(2, 4, 8, 4)
        body_layout.setSpacing(12)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        engine_group = QGroupBox("Conversation engine")
        engine_form = QFormLayout(engine_group)
        self.mode = QComboBox()
        self.mode.addItem("Gemini Live · recommended default", "gemini")
        self.mode.addItem("My own setup · STT + LLM + TTS", "pipeline")
        self.mode.setCurrentIndex(1 if get_provider_mode() == "pipeline" else 0)
        engine_form.addRow("Engine", self.mode)
        privacy = QLabel(
            "Privacy: local providers keep audio and text on this computer. "
            "Hosted providers send the data they process to that provider."
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color: #79aaa9; font-size: 11px;")
        engine_form.addRow(privacy)
        body_layout.addWidget(engine_group)

        pipeline = get_pipeline()
        for kind, title, note in (
            ("stt", "Speech recognition", "Turns microphone audio into text."),
            ("llm", "Language model", "Reasons, responds and selects tools."),
            ("tts", "Voice synthesis", "Speaks the answer aloud; optional for text-only output."),
        ):
            group = QGroupBox(title)
            form = QFormLayout(group)
            combo = QComboBox()
            combo.addItem("Not selected" if kind == "tts" else "Choose a provider…", "")
            self._options[kind] = self._build_options(kind)
            for service_id, label, entry in self._options[kind]:
                combo.addItem(label, service_id)
            selected = str(pipeline.get(kind) or "")
            idx = combo.findData(selected)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            self._combos[kind] = combo
            self._forms[kind] = form
            self._field_widgets[kind] = {}
            form.addRow("Provider", combo)
            hint = QLabel(note)
            hint.setStyleSheet("color: #79aaa9; font-size: 11px;")
            form.addRow(hint)
            body_layout.addWidget(group)
            combo.currentIndexChanged.connect(lambda _i, k=kind: self._provider_changed(k))
            self._provider_changed(kind)

        footer_note = QLabel(
            "Local Whisper requires the optional faster-whisper package. "
            "Piper requires piper-tts. They are not installed unless you choose them."
        )
        footer_note.setWordWrap(True)
        footer_note.setStyleSheet("color: #8eacb1; font-size: 11px;")
        body_layout.addWidget(footer_note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("Save & Apply")
        apply.setObjectName("apply")
        apply.clicked.connect(self._apply)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        root.addLayout(buttons)

    def _build_options(self, kind: str) -> list[tuple[str, str, dict]]:
        out = []
        for decl in self._declarations.get(kind, []):
            catalog = decl.get("catalog") or ()
            if catalog:
                for entry in catalog:
                    service_id = f"{decl['id']}@{entry['id']}"
                    label = entry.get("label") or decl.get("label") or service_id
                    if not decl.get("_available", True):
                        label += " · optional dependency missing"
                    out.append((service_id, label, dict(entry.get("values") or {})))
            else:
                out.append((decl["id"], decl.get("label", decl["id"]), {}))
        return out

    def _capture(self, kind: str) -> None:
        service_id = self._service_ids.get(kind)
        if not service_id:
            return
        values = dict(self._drafts.get(service_id, {}))
        for key, widget in self._field_widgets.get(kind, {}).items():
            if isinstance(widget, QComboBox):
                value = widget.currentText()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                value = widget.value()
            else:
                value = widget.text()
            values[key] = value
        self._drafts[service_id] = values

    def _provider_changed(self, kind: str) -> None:
        self._capture(kind)
        form = self._forms[kind]
        while form.rowCount() > 2:
            form.removeRow(2)
        self._field_widgets[kind] = {}
        service_id = str(self._combos[kind].currentData() or "")
        self._service_ids[kind] = service_id
        if not service_id:
            return
        decl = registry.get_declaration(service_id)
        if not decl:
            return
        entry_values = next(
            (values for sid, _label, values in self._options[kind] if sid == service_id), {}
        )
        defaults = registry.defaults(service_id)
        saved = get_provider_config(service_id)
        values = dict(defaults)
        values.update(entry_values)
        values.update(self._drafts.get(service_id, {}))
        values.update(saved)
        self._drafts[service_id] = values

        for field in decl.get("needs", ()):
            if getattr(field, "advanced", False):
                continue
            key = field.key
            current = values.get(key, field.default)
            if field.kind == "bool":
                widget = QCheckBox()
                widget.setChecked(str(current).lower() in ("1", "true", "yes", "on"))
            elif field.kind == "choice" and field.choices:
                widget = QComboBox()
                widget.setEditable(True)
                for choice in field.choices:
                    widget.addItem(str(choice))
                widget.setCurrentText(str(current or ""))
            elif field.kind == "number":
                widget = QDoubleSpinBox()
                widget.setRange(-1000000, 1000000)
                widget.setDecimals(3)
                try:
                    widget.setValue(float(current or 0))
                except (TypeError, ValueError):
                    widget.setValue(0)
            else:
                widget = QLineEdit(str(current or ""))
                if field.kind == "secret":
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
            if field.hint:
                widget.setToolTip(field.hint)
            self._field_widgets[kind][key] = widget
            form.addRow(field.label, widget)

    def _apply(self) -> None:
        mode = str(self.mode.currentData() or "gemini")
        pipeline = {kind: str(combo.currentData() or "") for kind, combo in self._combos.items()}
        for kind in ("stt", "llm", "tts"):
            self._capture(kind)

        creds: dict[str, dict] = {}
        for service_id, values in self._drafts.items():
            if values:
                creds[service_id] = values

        if mode == "pipeline":
            if not pipeline["stt"] or not pipeline["llm"]:
                QMessageBox.warning(self, "Provider setup incomplete",
                                    "Choose both speech recognition and a language model.")
                return
            for service_id in (pipeline["stt"], pipeline["llm"], pipeline["tts"]):
                if not service_id:
                    continue
                missing = registry.missing_fields(service_id, creds.get(service_id, get_provider_config(service_id)))
                if missing:
                    QMessageBox.warning(
                        self, "Provider setup incomplete",
                        f"{service_id} needs: {', '.join(missing)}"
                    )
                    return

        try:
            save_providers(mode=mode, pipeline=pipeline, creds=creds)
            registry.reset()
            if self._on_applied:
                self._on_applied()
        except Exception as exc:
            QMessageBox.critical(self, "Could not save provider settings", str(exc))
            return

        QMessageBox.information(
            self, "Engine settings saved",
            "Settings saved. JARVIS will reconnect and use the selected engine."
            if mode == "pipeline" else "Gemini Live is selected. Your provider settings were saved."
        )
        self.accept()
