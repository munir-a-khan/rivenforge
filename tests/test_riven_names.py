"""
Riven-name decoder tests. The names below are REAL rivens captured while
rolling this session (plus the wiki's canonical example), so these lock in
that the syllable table + parser recover the exact positive stats.
"""

from core.riven_names import (
    decode_riven_grammar,
    decode_riven_name,
    reconcile_parsed_with_name,
    strip_weapon,
)


def test_wiki_canonical_example():
    # "Vectis Sati-critaata": Multishot + Critical Chance + Damage
    assert decode_riven_name("Vectis Sati-critaata", "vectis") == {
        "multishot", "critical_chance", "damage",
    }


def test_three_positive_names_from_live_rolls():
    assert decode_riven_name("Quatz Sati-lexitox", "quatz") == {
        "multishot", "punch_through", "toxin",
    }
    assert decode_riven_name("Spectra Sati-ampicron", "spectra") == {
        "multishot", "ammo_maximum", "critical_chance",
    }
    assert decode_riven_name("Quatz Sci-fevanok", "quatz") == {
        "slash", "reload_speed", "punch_through",
    }


def test_two_syllable_names_have_no_hyphen():
    assert decode_riven_name("Quatz Hexasus", "quatz") == {"status_chance", "slash"}
    assert decode_riven_name("Quatz Ampinok", "quatz") == {"ammo_maximum", "punch_through"}
    assert decode_riven_name("Nukor Acriata", "nukor") == {"critical_damage", "damage"}


def test_melee_remap_of_shared_syllables():
    # Visi/Ata and Croni/Dra are shared: ranged = Damage / Fire Rate,
    # melee = Melee Damage / Attack Speed.
    ranged = decode_riven_grammar("saticronidra", melee=False)  # Multishot + Fire Rate
    melee = decode_riven_grammar("saticronidra", melee=True)
    assert "fire_rate" in ranged and "attack_speed" not in ranged
    assert "attack_speed" in melee and "fire_rate" not in melee


def test_garbled_name_returns_none():
    assert decode_riven_grammar("zzzzqxqx") is None
    assert decode_riven_grammar("") is None
    assert decode_riven_grammar("ab") is None


def test_strip_weapon_handles_prefix_and_fallback():
    assert strip_weapon("Quatz Sati-lexitox", "quatz") == "Sati-lexitox"
    # Weapon OCR mismatch -> drop the first token (the weapon), keep the rest.
    assert strip_weapon("Quatz Sati-lexitox", "boltor") == "Sati-lexitox"
    # Multi-word weapon.
    assert strip_weapon("Kuva Bramma Igni-critacron", "kuva bramma") == "Igni-critacron"


def _parsed(pos, neg=None):
    return {
        "positives": [{"stat": s, "value": v} for s, v in pos],
        "negatives": [{"stat": s, "value": v} for s, v in (neg or [])],
        "status": "ok",
    }


def test_reconcile_recovers_positive_ocr_dropped():
    # THE FIELD BUG: the Spectra riven's OCR dropped Critical Chance, reading
    # only Multishot + Ammo Maximum. The name recovers all three positives.
    ocr = _parsed(
        [("Multishot", 172.0), ("Ammo Maximum", 128.9)],
        [("Damage", -232.3)],
    )
    fixed, decoded = reconcile_parsed_with_name(ocr, "Spectra Sati-ampicron", "spectra")
    pos_names = {p["stat"] for p in fixed["positives"]}
    assert pos_names == {"Multishot", "Ammo Maximum", "Critical Chance"}
    # OCR values are preserved where the stat was read.
    ms = next(p for p in fixed["positives"] if p["stat"] == "Multishot")
    assert ms["value"] == 172.0
    # The negative is taken from OCR unchanged.
    assert fixed["negatives"] == [{"stat": "Damage", "value": -232.3}]
    assert fixed["status"] == "ok"


def test_reconcile_drops_name_stat_that_is_the_negative():
    # 2-positive + curse: the name's lowest slot IS the negative. It must not
    # appear as a positive once OCR identifies it as the negative.
    ocr = _parsed([("Multishot", 130.0)], [("Damage", -80.0)])
    fixed, _ = reconcile_parsed_with_name(ocr, "Vectis Sati-critaata", "vectis")
    pos_names = {p["stat"] for p in fixed["positives"]}
    assert pos_names == {"Multishot", "Critical Chance"}
    assert "Damage" not in pos_names


def test_reconcile_no_op_on_garbled_name():
    ocr = _parsed([("Multishot", 130.0)], [("Damage", -80.0)])
    fixed, decoded = reconcile_parsed_with_name(ocr, "Weapon zzzzqxqx", "weapon")
    assert decoded is None
    assert fixed is ocr
