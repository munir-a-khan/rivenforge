"""
Settings tab: visual detection test, RAG rebuild, animation timing.
No manual calibration needed — buttons are found by OCR at roll time.
"""

import threading
import time
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QPushButton,
    QLabel, QProgressBar, QMessageBox, QDoubleSpinBox,
)
from PyQt5.QtCore import pyqtSignal, QObject

from data_util import load_config, save_config


class _Signals(QObject):
    progress   = pyqtSignal(int, int)   # ingest: current, total
    done       = pyqtSignal(int)        # ingest: total ingested
    error      = pyqtSignal(str)        # error message
    detect_done = pyqtSignal(str)       # visual detection test result


class SettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = load_config()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_ingest_done)
        self._signals.error.connect(self._on_ingest_error)
        self._signals.detect_done.connect(self._on_detect_done)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- General ---
        gen_grp = QGroupBox("General")
        gen_lay = QFormLayout(gen_grp)
        gen_lay.addRow(QLabel("OCR Engine: Windows built-in (WinRT) — no GPU required"))
        gen_lay.addRow(QLabel("Button Detection: Visual (OCR) — no calibration needed"))
        layout.addWidget(gen_grp)

        # --- Animation timing ---
        timing_grp = QGroupBox("Timing")
        timing_lay = QFormLayout(timing_grp)
        self._anim_spin = QDoubleSpinBox()
        self._anim_spin.setRange(1.0, 6.0)
        self._anim_spin.setSingleStep(0.25)
        self._anim_spin.setSuffix(" s")
        self._anim_spin.setValue(self._cfg.get("animation_wait", 2.5))
        self._anim_spin.valueChanged.connect(self._save_timing)
        timing_lay.addRow("Roll animation wait:", self._anim_spin)
        timing_lay.addRow(QLabel(
            "Increase if the roller reads old stats (animation not done).\n"
            "Decrease for faster rolling once stable."
        ))
        layout.addWidget(timing_grp)

        # --- Visual detection test ---
        vis_grp = QGroupBox("Visual Button Detection")
        vis_lay = QVBoxLayout(vis_grp)
        vis_lay.addWidget(QLabel(
            "Buttons are found automatically by scanning the Warframe screen.\n"
            "No calibration required. Click Test to verify detection."
        ))
        self._detect_status = QLabel("")
        self._detect_status.setStyleSheet("color: #f0a020; font-weight: bold;")
        self._detect_status.setWordWrap(True)
        vis_lay.addWidget(self._detect_status)
        btn_test = QPushButton("Test Visual Detection (Warframe must be on riven screen)")
        btn_test.clicked.connect(self._test_detection)
        vis_lay.addWidget(btn_test)
        layout.addWidget(vis_grp)

        # --- RAG knowledge base ---
        rag_grp = QGroupBox("RAG Knowledge Base")
        rag_lay = QVBoxLayout(rag_grp)
        self._lbl_db = QLabel("Status: unknown")
        rag_lay.addWidget(self._lbl_db)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        rag_lay.addWidget(self._progress)
        btn_rebuild = QPushButton("Rebuild RAG Database from Tier List")
        btn_rebuild.clicked.connect(self._rebuild_rag)
        rag_lay.addWidget(btn_rebuild)
        layout.addWidget(rag_grp)
        self._check_db_status()

        layout.addStretch()

    def _save_timing(self, value: float):
        cfg = load_config()
        cfg["animation_wait"] = value
        save_config(cfg)

    def _test_detection(self):
        self._detect_status.setText("Scanning Warframe screen...")

        def run():
            try:
                from core.automation import activate_warframe
                from core.capture import grab_frame
                from core.vision import find_all_buttons, find_riven_stats
                from core import parser

                activate_warframe()
                time.sleep(0.3)
                frame   = grab_frame()
                buttons = find_all_buttons(frame)
                stats   = find_riven_stats(frame)
                parsed  = parser.parse(stats)

                lines = []
                for key in ["cycle_button", "cycle_yes", "confirm_button",
                            "keep_yes", "keep_no"]:
                    pos = buttons.get(key)
                    if pos:
                        lines.append(f"  ✓ {key}: {pos}")
                    else:
                        lines.append(f"  ✗ {key}: NOT FOUND")

                if parsed["positives"] or parsed["negatives"]:
                    from core.parser import format_stats
                    lines.append(f"  Card stats: {format_stats(parsed)}")
                else:
                    lines.append("  Card stats: none detected (riven card not visible?)")

                self._signals.detect_done.emit("\n".join(lines))
            except Exception as e:
                self._signals.error.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_detect_done(self, result: str):
        self._detect_status.setText(result)

    def _check_db_status(self):
        from rag import rag as rag_mod
        if rag_mod.is_db_ready():
            self._lbl_db.setText("Status: Index ready (TF-IDF, 417 entries)")
        else:
            self._lbl_db.setText("Status: Not built — click Rebuild")

    def _rebuild_rag(self):
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._lbl_db.setText("Building...")

        def run():
            try:
                from rag.ingest import ingest
                total = ingest(
                    progress_cb=lambda c, t: self._signals.progress.emit(c, t),
                )
                self._signals.done.emit(total)
            except Exception as e:
                self._signals.error.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, current: int, total: int):
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_ingest_done(self, total: int):
        self._progress.setVisible(False)
        self._lbl_db.setText(f"Status: Built ({total} entries)")
        from rag import rag as rag_mod
        rag_mod.reset_client()

    def _on_ingest_error(self, err: str):
        self._progress.setVisible(False)
        self._lbl_db.setText(f"Error: {err}")
        QMessageBox.critical(self, "Error", err)
