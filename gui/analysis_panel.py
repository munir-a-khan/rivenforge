from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.analysis import analyze_pipeline_result
from core.ocr_pipeline import StaticTextOcrEngine, analyze_screenshot
from core.parser import format_stats
from core.profile_schema import load_profile
from data_util import load_config


class AnalysisPanel(QWidget):
    debug_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._screenshot_path: str | None = None
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        self._btn_load = QPushButton("Load Screenshot")
        self._btn_load.clicked.connect(self._load_screenshot)
        self._btn_paste = QPushButton("Paste Image")
        self._btn_paste.clicked.connect(self._paste_screenshot)
        self._crop_mode = QComboBox()
        self._crop_mode.addItem("New card", "new_card")
        self._crop_mode.addItem("Single card", "single_card")
        self._crop_mode.addItem("Full screen", "full")
        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.clicked.connect(self._analyze)
        top.addWidget(self._btn_load)
        top.addWidget(self._btn_paste)
        top.addWidget(QLabel("Crop:"))
        top.addWidget(self._crop_mode)
        top.addStretch()
        top.addWidget(self._btn_analyze)
        outer.addLayout(top)

        self._preview = QLabel("No screenshot loaded")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(220)
        self._preview.setStyleSheet("border: 1px solid #444; background: #111;")
        outer.addWidget(self._preview)

        self._crop_help = QLabel(
            "New card: right-side comparison roll. Single card: centered riven before/after rolling. "
            "Full screen: no crop, useful for dialogs or OCR debugging."
        )
        self._crop_help.setWordWrap(True)
        outer.addWidget(self._crop_help)

        manual_grp = QGroupBox("Manual OCR Lines")
        manual_layout = QVBoxLayout(manual_grp)
        self._manual_ocr = QTextEdit()
        self._manual_ocr.setPlaceholderText("Optional: paste OCR/stat lines here to replay without an OCR engine.")
        self._manual_ocr.setMaximumHeight(100)
        manual_layout.addWidget(self._manual_ocr)
        outer.addWidget(manual_grp)

        result_grp = QGroupBox("Result")
        result_form = QFormLayout(result_grp)
        self._parsed = QLabel("-")
        self._parsed.setWordWrap(True)
        self._decision = QLabel("-")
        self._decision.setWordWrap(True)
        self._confidence = QLabel("-")
        self._profile = QLabel("-")
        result_form.addRow("Parsed riven:", self._parsed)
        result_form.addRow("Decision:", self._decision)
        result_form.addRow("Confidence:", self._confidence)
        result_form.addRow("Profile:", self._profile)
        outer.addWidget(result_grp)

    def _load_screenshot(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Screenshot", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        self._screenshot_path = path
        self._show_preview(path)

    def _paste_screenshot(self):
        image = QApplication.clipboard().image()
        if image.isNull():
            QMessageBox.warning(self, "Clipboard empty", "Copy a screenshot image first, then paste it here.")
            return
        target = Path(tempfile.gettempdir()) / "wfrivenpicker_clipboard.png"
        if not image.save(str(target), "PNG"):
            QMessageBox.critical(self, "Paste failed", "Could not save clipboard image for analysis.")
            return
        self._screenshot_path = str(target)
        self._show_preview(str(target))

    def _show_preview(self, path: str):
        pix = QPixmap(path)
        if not pix.isNull():
            self._preview.setPixmap(pix.scaled(self._preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._preview.setText(Path(path).name)

    def _load_profiles(self):
        profiles = []
        for raw in load_config().get("profiles", []):
            try:
                profiles.append(load_profile(raw))
            except Exception:
                continue
        return profiles

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self._paste_screenshot()
            return
        super().keyPressEvent(event)

    def _analyze(self):
        if not self._screenshot_path:
            QMessageBox.warning(self, "No screenshot", "Load a screenshot first.")
            return

        manual_lines = tuple(
            line.strip()
            for line in self._manual_ocr.toPlainText().splitlines()
            if line.strip()
        )
        ocr_engine = StaticTextOcrEngine(manual_lines) if manual_lines else None

        try:
            pipeline = analyze_screenshot(
                self._screenshot_path,
                crop_mode=self._crop_mode.currentData(),
                ocr_engine=ocr_engine,
            )
            analysis = analyze_pipeline_result(pipeline, self._load_profiles())
        except Exception as e:
            QMessageBox.critical(self, "Analysis failed", str(e))
            return

        parsed_legacy = pipeline.parse.to_legacy()
        self._parsed.setText(format_stats(parsed_legacy))
        self._decision.setText(f"{analysis.decision.decision}: {analysis.decision.details}")
        self._confidence.setText(f"{pipeline.average_confidence:.2f}")
        self._profile.setText(analysis.decision.profile_matched or "-")

        debug_lines = [
            f"Screenshot: {self._screenshot_path}",
            f"Crop mode: {self._crop_mode.currentData()}",
            f"Image size: {pipeline.raw_image_size}",
            f"Crop size: {pipeline.crop_image_size}",
            f"Average confidence: {pipeline.average_confidence:.2f}",
            "",
            "OCR lines:",
            *[f"  {line}" for line in pipeline.cleaned_lines],
            "",
            f"Parser status: {pipeline.parse.status.value}",
            f"Parsed: {format_stats(parsed_legacy)}",
            "",
            f"Decision: {analysis.decision.decision}",
            f"Details: {analysis.decision.details}",
            "",
            "Rule/OCR trace:",
            *[f"  [{'ok' if trace.matched else 'no'}] {trace.code}: {trace.message}" for trace in analysis.decision.traces],
        ]
        self.debug_ready.emit("\n".join(debug_lines))
