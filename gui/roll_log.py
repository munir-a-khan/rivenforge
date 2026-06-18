"""
Live roll log table.
Columns: Roll # | Kuva | Stats | Profile | Score | Plat | Decision
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QHBoxLayout, QLabel,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from core.parser import format_stats

_GREEN  = QColor(50, 140, 50)    # accepted / full match
_BLUE   = QColor(40,  90, 160)   # kept as new best
_DARK   = QColor(50,  50,  50)   # rejected / reverted
_WHITE  = QColor(240, 240, 240)
_GOLD   = QColor(240, 180,  40)


class RollLogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        hdr = QHBoxLayout()
        self._lbl_total  = QLabel("Rolls: 0")
        self._lbl_kuva   = QLabel("Kuva: 0")
        self._lbl_best   = QLabel("Best so far: —")
        self._lbl_accept = QLabel("Accepted: —")
        self._lbl_kuva.setStyleSheet("color: #f0b428;")
        self._lbl_best.setStyleSheet("color: #60aaff;")
        self._lbl_accept.setStyleSheet("color: #50cc50;")
        hdr.addWidget(self._lbl_total)
        hdr.addStretch()
        hdr.addWidget(self._lbl_kuva)
        hdr.addStretch()
        hdr.addWidget(self._lbl_best)
        hdr.addStretch()
        hdr.addWidget(self._lbl_accept)
        layout.addLayout(hdr)

        # Table — added "Plat" column between Score and Decision
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Roll #", "Kuva", "Stats Detected", "Profile", "Score", "Plat", "Decision"]
        )
        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.Stretch)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(self.clear)
        layout.addWidget(btn_clear)

        self._roll_count = 0

    def add_roll(self, roll_num: int, parsed: dict, rule_result: dict,
                 rag_result: dict, accepted: bool):
        self._roll_count = roll_num
        kuva_cost    = rag_result.get("kuva_cost",    0)
        kuva_total   = rag_result.get("kuva_total",   0)
        new_score    = rag_result.get("new_score",    0.0)
        is_better    = rag_result.get("is_better",    False)
        plat_low     = rag_result.get("plat_low",     None)
        plat_median  = rag_result.get("plat_median",  None)
        wfm_source   = rag_result.get("wfm_source",   "none")
        melee_bonus  = rag_result.get("melee_bonus",  0.0)

        self._lbl_total.setText(f"Rolls: {roll_num}")
        self._lbl_kuva.setText(f"Kuva: {kuva_total:,}")

        stats_str   = format_stats(parsed)
        profile_str = rule_result.get("profile_matched") or "—"

        # Score column: -9999 means unreadable OCR
        score_str = "OCR fail" if new_score <= -999 else f"{new_score:.0f}"

        # Plat column: show low / median if available
        if plat_median is not None:
            plat_str = f"{plat_low}p / {plat_median}p"
        elif wfm_source == "none":
            plat_str = "—"
        else:
            plat_str = "no data"

        # Append melee priority note if significant
        if abs(melee_bonus) >= 0.05:
            sign = "+" if melee_bonus > 0 else ""
            plat_str += f"  ({sign}{melee_bonus:.2f}M)"

        if accepted:
            decision = "✓ ACCEPTED"
            bg = _GREEN
            self._lbl_accept.setText(f"✓ Accepted #{roll_num}!")
        elif is_better:
            decision = "↑ NEW BEST"
            bg = _BLUE
            self._lbl_best.setText(f"Best: {stats_str}")
        else:
            decision = "↓ reverted"
            bg = _DARK

        row = self._table.rowCount()
        self._table.insertRow(row)

        for i, text in enumerate([
            str(roll_num), f"{kuva_cost:,}", stats_str,
            profile_str, score_str, plat_str, decision
        ]):
            item = QTableWidgetItem(text)
            item.setForeground(_WHITE)
            item.setBackground(bg)
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self._table.setItem(row, i, item)

        self._table.scrollToBottom()

    def clear(self):
        self._table.setRowCount(0)
        self._roll_count = 0
        self._lbl_total.setText("Rolls: 0")
        self._lbl_kuva.setText("Kuva: 0")
        self._lbl_best.setText("Best so far: —")
        self._lbl_accept.setText("Accepted: —")
