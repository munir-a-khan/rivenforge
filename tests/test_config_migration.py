from __future__ import annotations

import json

import data_util


def test_load_config_migrates_legacy_config_and_writes_backup(tmp_path, monkeypatch):
    cfg_path = tmp_path / "user_config.json"
    cfg_path.write_text(json.dumps({"weapon": "Sobek", "weapon_type": "primary", "profiles": []}))
    monkeypatch.setattr(data_util, "CONFIG_PATH", str(cfg_path))

    cfg = data_util.load_config()

    assert cfg["schema_version"] == data_util.CURRENT_CONFIG_SCHEMA_VERSION
    assert cfg["weapon"] == "Sobek"
    assert json.loads(cfg_path.read_text())["schema_version"] == data_util.CURRENT_CONFIG_SCHEMA_VERSION
    assert list(tmp_path.glob("user_config.json.bak.*"))
