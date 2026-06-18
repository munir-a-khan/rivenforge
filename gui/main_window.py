"""
Main PyQt5 application window.
Tabs: Config | Roll Log | Settings
"""

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import automation
from core.hotkey import DEFAULT_LABEL as HOTKEY_LABEL, HotkeyListener
from core.roller import RollerThread
from data_util import load_config
from gui.analysis_panel import AnalysisPanel
from gui.config_panel import ConfigPanel
from gui.debug_panel import DebugPanel
from gui.roll_log import RollLogWidget
from gui.settings_panel import SettingsPanel
from rag import rag as rag_mod


class _RollerSignals(QObject):
    roll   = pyqtSignal(int, dict, dict, dict, bool)  # roll#, parsed, rule, rag, accepted
    done   = pyqtSignal(str)
    error  = pyqtSignal(str)
    hotkey_stop = pyqtSignal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WF Riven Roller")
        self.setMinimumSize(900, 640)
        self._roller: RollerThread | None = None
        self._hotkey: HotkeyListener | None = None
        self._signals = _RollerSignals()
        self._signals.roll.connect(self._on_roll)
        self._signals.done.connect(self._on_done)
        self._signals.error.connect(self._on_error)
        self._signals.hotkey_stop.connect(self._on_hotkey_stop)
        self._build_ui()
        self._load_coords()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # --- Title bar ---
        title = QLabel("WF Riven Roller")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # --- Tabs ---
        self._tabs = QTabWidget()
        self._analysis_panel = AnalysisPanel()
        self._config_panel   = ConfigPanel()
        self._roll_log       = RollLogWidget()
        self._debug_panel    = DebugPanel()
        self._settings_panel = SettingsPanel()
        self._analysis_panel.debug_ready.connect(self._debug_panel.set_debug_text)

        self._tabs.addTab(self._analysis_panel, "Manual Roll")
        self._tabs.addTab(self._config_panel,   "Profiles")
        self._tabs.addTab(self._roll_log,        "Roll Log")
        self._tabs.addTab(self._debug_panel,     "Debug")
        self._tabs.addTab(self._settings_panel,  "Settings")
        main_layout.addWidget(self._tabs)

        # --- Start / Stop ---
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("▶  Start Rolling")
        self._btn_start.setFixedHeight(44)
        self._btn_start.setFont(QFont("Arial", 12, QFont.Bold))
        self._btn_start.clicked.connect(self._start_rolling)

        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setFixedHeight(44)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_rolling)

        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        main_layout.addLayout(btn_row)

        # --- Status bar ---
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready — configure your weapon and profiles, then click Start.")

    def _load_coords(self):
        cfg = load_config()
        automation.load_coords(cfg)

    def _start_rolling(self):
        # Validate
        if not rag_mod.is_db_ready():
            resp = QMessageBox.question(
                self, "RAG DB Not Ready",
                "The RAG knowledge base hasn't been built yet.\n"
                "Go to Settings → Rebuild RAG Database first.\n\n"
                "Start rolling with rules-only (no RAG scoring)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.No:
                self._tabs.setCurrentIndex(2)  # Jump to Settings
                return

        cfg = self._config_panel.get_config()
        self._config_panel.save()

        if not cfg["weapon"]:
            QMessageBox.warning(self, "No weapon", "Please select a weapon before starting.")
            return
        if not cfg["profiles"]:
            QMessageBox.warning(self, "No profiles",
                "Add at least one roll profile before starting.")
            return

        # Disable RAG if DB not ready
        rag_thresh = cfg["rag_threshold"] if rag_mod.is_db_ready() else 0.0

        self._roller = RollerThread(
            weapon         = cfg["weapon"],
            weapon_type    = cfg["weapon_type"],
            profiles       = cfg["profiles"],
            roll_limit     = cfg["roll_limit"],
            rag_threshold  = rag_thresh,
            animation_wait = cfg["animation_wait"],
            on_roll  = lambda *a: self._signals.roll.emit(*a),
            on_done  = lambda r: self._signals.done.emit(r),
            on_error = lambda e: self._signals.error.emit(e),
        )

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._tabs.setCurrentIndex(1)  # Switch to Roll Log

        # Global hotkey: the GUI Stop button is unreachable once the bot
        # starts moving the mouse, so register a system-wide hotkey that
        # works even while Warframe has focus.
        self._hotkey = HotkeyListener(
            on_pressed=lambda: self._signals.hotkey_stop.emit()
        )
        registered = self._hotkey.start()
        hotkey_msg = (
            f" — press {HOTKEY_LABEL} to stop"
            if registered else
            f" — WARNING: {HOTKEY_LABEL} not available (already bound)"
        )

        self._status.showMessage(
            f"Rolling {cfg['weapon']} — limit: "
            f"{'unlimited' if cfg['roll_limit'] == 0 else cfg['roll_limit']}"
            f"{hotkey_msg}"
        )
        self._roller.start()

    def _stop_rolling(self):
        if self._roller:
            self._roller.stop()
        self._teardown_hotkey()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.showMessage("Stopped by user.")

    def _on_hotkey_stop(self):
        # Runs on the Qt main thread (bounced via signal). Identical to
        # clicking Stop, but the status line calls out that the user
        # used the global hotkey.
        if self._roller:
            self._roller.stop()
        self._teardown_hotkey()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.showMessage(f"Stopped by hotkey ({HOTKEY_LABEL}).")

    def _teardown_hotkey(self):
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
            self._hotkey = None

    def _on_roll(self, roll_num, parsed, rule_result, rag_result, accepted):
        self._roll_log.add_roll(roll_num, parsed, rule_result, rag_result, accepted)
        self._status.showMessage(
            f"Roll #{roll_num} — {rule_result['details']} | "
            f"RAG: {rag_result.get('score', 0.0):.2f} | "
            f"{'ACCEPTED' if accepted else 'rejected'}"
        )

    def _on_done(self, reason: str):
        self._teardown_hotkey()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.showMessage(f"Done: {reason}")
        QMessageBox.information(self, "Rolling Complete", reason)

    def _on_error(self, error: str):
        self._teardown_hotkey()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.showMessage(f"Error: {error}")
        QMessageBox.critical(self, "Roller Error", error)

    def closeEvent(self, event):
        if self._roller and self._roller.is_alive():
            self._roller.stop()
        self._teardown_hotkey()
        self._config_panel.save()
        event.accept()
