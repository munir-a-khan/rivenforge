"""
Config panel: weapon selection, roll profiles (OR logic), roll settings.
"""

import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QSpinBox, QDoubleSpinBox, QGroupBox, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QScrollArea,
    QCheckBox, QMessageBox, QFormLayout, QFileDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal

from rag.ingest import all_weapons, weapon_lookup
from core.rules import default_profiles_from_weapon_data
from core.profile_schema import dump_profile, load_profile
from data_util import load_config, save_config

WEAPON_TYPES = ["primary", "secondary", "melee", "archgun", "robotic", "stat sticks"]

# All canonical stat names for multi-select lists
from data.stat_aliases_loader import ALL_STATS


class ProfileEditor(QDialog):
    """Dialog for creating/editing a single roll profile."""

    def __init__(self, profile: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Roll Profile")
        self.setMinimumWidth(480)
        self._build_ui(profile or {})

    def _build_ui(self, profile: dict):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self._name = QLineEdit(profile.get("name", "New Profile"))
        form.addRow("Profile Name:", self._name)

        self._min_req = QSpinBox()
        self._min_req.setRange(1, 3)
        self._min_req.setValue(profile.get("min_positives_required", 2))
        form.addRow("Min positives required:", self._min_req)

        layout.addLayout(form)

        # Desired positives
        pos_grp = QGroupBox("Desired Positives (must have ≥ min required)")
        pos_layout = QVBoxLayout(pos_grp)
        self._pos_list = _StatCheckList(
            ALL_STATS, profile.get("desired_positives", [])
        )
        pos_layout.addWidget(self._pos_list)
        layout.addWidget(pos_grp)

        # Acceptable negatives
        neg_grp = QGroupBox("Acceptable Negatives (leave empty = no negatives accepted)")
        neg_layout = QVBoxLayout(neg_grp)
        self._neg_list = _StatCheckList(
            ALL_STATS, profile.get("acceptable_negatives", [])
        )
        neg_layout.addWidget(self._neg_list)
        layout.addWidget(neg_grp)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_profile(self) -> dict:
        return {
            "name": self._name.text().strip() or "Unnamed",
            "desired_positives": self._pos_list.checked_items(),
            "min_positives_required": self._min_req.value(),
            "acceptable_negatives": self._neg_list.checked_items(),
        }


class _StatCheckList(QScrollArea):
    """Scrollable checkbox list of stat names."""

    def __init__(self, all_stats: list[str], selected: list[str], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMaximumHeight(200)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(2)
        self._checks: list[QCheckBox] = []
        selected_lower = {s.lower() for s in selected}
        for stat in sorted(all_stats):
            cb = QCheckBox(stat)
            cb.setChecked(stat.lower() in selected_lower)
            self._checks.append(cb)
            v.addWidget(cb)
        v.addStretch()
        self.setWidget(container)

    def checked_items(self) -> list[str]:
        return [cb.text() for cb in self._checks if cb.isChecked()]


class ConfigPanel(QWidget):
    """Main configuration widget."""

    profiles_changed = pyqtSignal(list)   # emitted whenever profiles list changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: list[dict] = []
        self._all_weapons: list[dict] = []
        self._build_ui()
        self._load_saved()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        # --- Weapon ---
        wep_grp = QGroupBox("Weapon")
        wep_lay = QFormLayout(wep_grp)

        self._type_combo = QComboBox()
        self._type_combo.addItems([t.title() for t in WEAPON_TYPES])
        self._type_combo.currentIndexChanged.connect(self._on_type_change)
        wep_lay.addRow("Type:", self._type_combo)

        self._wep_combo = QComboBox()
        self._wep_combo.setEditable(True)
        self._wep_combo.lineEdit().setPlaceholderText("Search weapon...")
        wep_lay.addRow("Weapon:", self._wep_combo)

        self._btn_suggest = QPushButton("Load Suggested Profiles from Tier List")
        self._btn_suggest.clicked.connect(self._load_suggested)
        wep_lay.addRow("", self._btn_suggest)

        outer.addWidget(wep_grp)

        # --- Roll Profiles ---
        prof_grp = QGroupBox("Roll Profiles  (roll stops if ANY profile matches)")
        prof_lay = QVBoxLayout(prof_grp)

        self._profile_list = QListWidget()
        self._profile_list.setMaximumHeight(140)
        self._profile_list.doubleClicked.connect(self._edit_profile)
        prof_lay.addWidget(self._profile_list)

        btn_row = QHBoxLayout()
        b_add  = QPushButton("+ Add Profile"); b_add.clicked.connect(self._add_profile)
        b_edit = QPushButton("Edit");          b_edit.clicked.connect(self._edit_profile)
        b_del  = QPushButton("Delete");        b_del.clicked.connect(self._delete_profile)
        b_dup  = QPushButton("Duplicate");     b_dup.clicked.connect(self._dup_profile)
        b_import = QPushButton("Import");      b_import.clicked.connect(self._import_profiles)
        b_export = QPushButton("Export");      b_export.clicked.connect(self._export_profiles)
        for b in (b_add, b_edit, b_del, b_dup, b_import, b_export):
            btn_row.addWidget(b)
        prof_lay.addLayout(btn_row)
        outer.addWidget(prof_grp)

        # --- Rolling settings ---
        settings_grp = QGroupBox("Rolling Settings")
        s_form = QFormLayout(settings_grp)

        self._roll_limit = QSpinBox()
        self._roll_limit.setRange(0, 9999)
        self._roll_limit.setValue(100)
        self._roll_limit.setSpecialValueText("Unlimited")
        s_form.addRow("Roll limit (0 = unlimited):", self._roll_limit)

        self._rag_thresh = QDoubleSpinBox()
        self._rag_thresh.setRange(0.0, 1.0)
        self._rag_thresh.setSingleStep(0.05)
        self._rag_thresh.setValue(0.60)
        s_form.addRow("RAG score threshold:", self._rag_thresh)

        self._anim_wait = QDoubleSpinBox()
        self._anim_wait.setRange(0.5, 10.0)
        self._anim_wait.setSingleStep(0.5)
        self._anim_wait.setValue(2.5)
        s_form.addRow("Animation wait (s):", self._anim_wait)

        outer.addWidget(settings_grp)
        outer.addStretch()

    # ------------------------------------------------------------------
    def _on_type_change(self):
        weapon_type = WEAPON_TYPES[self._type_combo.currentIndex()]
        if not self._all_weapons:
            self._all_weapons = all_weapons()
        filtered = [w["weapon"] for w in self._all_weapons
                    if w["weapon_type"] == weapon_type]
        self._wep_combo.clear()
        self._wep_combo.addItems(sorted(set(filtered)))

    def _load_suggested(self):
        weapon = self._wep_combo.currentText().strip()
        if not weapon:
            QMessageBox.warning(self, "No weapon", "Please select a weapon first.")
            return
        entries = weapon_lookup(weapon)
        if not entries:
            QMessageBox.information(self, "Not found",
                f"'{weapon}' not found in tier list. You can add profiles manually.")
            return
        new_profiles = []
        for entry in entries:
            new_profiles.extend(default_profiles_from_weapon_data(entry))
        if new_profiles:
            self._profiles = new_profiles
            self._refresh_profile_list()
            self.profiles_changed.emit(self._profiles)

    def _refresh_profile_list(self):
        self._profile_list.clear()
        for p in self._profiles:
            pos = ", ".join(p.get("desired_positives", []))
            neg = ", ".join(p.get("acceptable_negatives", [])) or "any"
            min_r = p.get("min_positives_required", 2)
            label = f"[{p['name']}]  ≥{min_r} of: {pos}  |  neg OK: {neg}"
            self._profile_list.addItem(QListWidgetItem(label))

    def _add_profile(self):
        dlg = ProfileEditor(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._profiles.append(dlg.get_profile())
            self._refresh_profile_list()
            self.profiles_changed.emit(self._profiles)

    def _edit_profile(self):
        row = self._profile_list.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        dlg = ProfileEditor(self._profiles[row], parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._profiles[row] = dlg.get_profile()
            self._refresh_profile_list()
            self.profiles_changed.emit(self._profiles)

    def _delete_profile(self):
        row = self._profile_list.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        self._profiles.pop(row)
        self._refresh_profile_list()
        self.profiles_changed.emit(self._profiles)

    def _dup_profile(self):
        row = self._profile_list.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        import copy
        dup = copy.deepcopy(self._profiles[row])
        dup["name"] += " (copy)"
        self._profiles.insert(row + 1, dup)
        self._refresh_profile_list()
        self.profiles_changed.emit(self._profiles)

    def _import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profiles", "", "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            raw_profiles = payload.get("profiles", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw_profiles, list):
                raise ValueError("Profile file must contain a list or a {'profiles': [...]} object.")
            imported = []
            for raw in raw_profiles:
                typed = load_profile(raw)
                legacy = {
                    "schema_version": typed.schema_version,
                    "name": typed.name,
                    "desired_positives": [
                        slot.label
                        for group in typed.positive_groups
                        for slot in group.slots
                        if not slot.is_any
                    ],
                    "min_positives_required": typed.positive_groups[0].min_required,
                    "acceptable_negatives": list(raw.get("acceptable_negatives", raw.get("safe_negatives", []))),
                    "rejected_negatives": list(raw.get("rejected_negatives", [])),
                    "required_negatives": list(raw.get("required_negatives", [])),
                    "min_negatives_required": typed.min_negatives_required,
                }
                imported.append(legacy)
            self._profiles = imported
            self._refresh_profile_list()
            self.profiles_changed.emit(self._profiles)
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def _export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", "riven-profiles.json", "JSON files (*.json)")
        if not path:
            return
        try:
            profiles = [dump_profile(load_profile(profile)) for profile in self._profiles]
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"schema_version": 1, "profiles": profiles}, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # ------------------------------------------------------------------
    def get_config(self) -> dict:
        return {
            "weapon":       self._wep_combo.currentText().strip(),
            "weapon_type":  WEAPON_TYPES[self._type_combo.currentIndex()],
            "profiles":     self._profiles,
            "roll_limit":   self._roll_limit.value(),
            "rag_threshold": self._rag_thresh.value(),
            "animation_wait": self._anim_wait.value(),
        }

    def _load_saved(self):
        cfg = load_config()
        # Set weapon type
        wt = cfg.get("weapon_type", "melee")
        idx = WEAPON_TYPES.index(wt) if wt in WEAPON_TYPES else 0
        self._type_combo.setCurrentIndex(idx)
        self._on_type_change()
        # Set weapon name
        wep = cfg.get("weapon", "")
        idx2 = self._wep_combo.findText(wep)
        if idx2 >= 0:
            self._wep_combo.setCurrentIndex(idx2)
        elif wep:
            self._wep_combo.setCurrentText(wep)
        # Profiles
        self._profiles = cfg.get("profiles", [])
        self._refresh_profile_list()
        # Settings
        self._roll_limit.setValue(cfg.get("roll_limit", 100))
        self._rag_thresh.setValue(cfg.get("rag_threshold", 0.60))
        self._anim_wait.setValue(cfg.get("animation_wait", 2.5))

    def save(self):
        cfg = self.get_config()
        save_config(cfg)
