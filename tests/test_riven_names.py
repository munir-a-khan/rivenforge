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


def test_reconcile_caps_curse_removal_at_one():
    # THE FIELD BUG: OCR sign-noise marked TWO of the three NAME stats negative.
    # A riven has at most one curse, so only the strongest may be removed — the
    # other must stay a positive instead of collapsing the read to ONE positive.
    ocr = _parsed(
        [("Toxin", 90.0)],
        [("Multishot", -30.0), ("Punch Through", -120.0)],
    )
    fixed, _ = reconcile_parsed_with_name(ocr, "Quatz Sati-lexitox", "quatz")
    pos = {p["stat"] for p in fixed["positives"]}
    # decoded = {Multishot, Punch Through, Toxin}; strongest in-name negative is
    # Punch Through -> the one curse. Multishot stays positive: TWO positives.
    assert pos == {"Multishot", "Toxin"}
    assert len(fixed["positives"]) == 2


def test_reconcile_drops_phantom_negatives_from_the_negatives_list():
    # A stat restored as a positive must NOT still be listed as a negative:
    # rules.evaluate checks every negative against acceptable_negatives, so a
    # leftover phantom negative rejected an otherwise-good roll.
    ocr = _parsed(
        [("Toxin", 90.0)],
        [("Multishot", -30.0), ("Punch Through", -120.0)],
    )
    fixed, _ = reconcile_parsed_with_name(ocr, "Quatz Sati-lexitox", "quatz")
    assert fixed["negatives"] == [{"stat": "Punch Through", "value": -120.0}]
    neg_names = {n["stat"] for n in fixed["negatives"]}
    pos_names = {p["stat"] for p in fixed["positives"]}
    assert not (neg_names & pos_names)      # never both positive and negative
    assert fixed["status"] == "ok"          # 2 positives + 1 curse is valid


def test_reconcile_two_stat_name_never_yields_one_positive():
    # FIELD BUG roll #22: 'Zetiata' (Recoil + Damage) displayed as
    # "Recoil / -Damage" — 1 positive + 1 negative, which does not exist
    # in-game. A 2-stat name is 2 POSITIVES by definition, so the in-name
    # "negative" is sign noise: both stay positive, phantom negative dropped.
    ocr = _parsed([("Recoil", 90.0)], [("Damage", -50.0)])
    fixed, decoded = reconcile_parsed_with_name(ocr, "Quatz Zetiata", "quatz")
    assert decoded == {"recoil", "damage"}
    assert {p["stat"] for p in fixed["positives"]} == {"Recoil", "Damage"}
    assert fixed["negatives"] == []
    assert len(fixed["positives"]) >= 2


def test_reconcile_two_stat_name_keeps_out_of_name_curse():
    # 2-stat name + a REAL curse: the curse is a third stat NOT in the name.
    ocr = _parsed([("Ammo Maximum", 66.0)], [("Zoom", -40.0)])
    fixed, _ = reconcile_parsed_with_name(ocr, "Quatz Ampinok", "quatz")
    assert {p["stat"] for p in fixed["positives"]} == {"Ammo Maximum", "Punch Through"}
    assert fixed["negatives"] == [{"stat": "Zoom", "value": -40.0}]


def test_decode_rejects_single_stat_fragments():
    # A bare suffix ("cron") decodes to one stat — no real riven has fewer
    # than 2 positives, so it must be treated as garble, not a name.
    assert decode_riven_grammar("cron") is None


def test_reconcile_ignores_negative_not_in_name():
    # A negative for a stat the name doesn't contain is an OCR hallucination and
    # must not remove any real positive.
    ocr = _parsed(
        [("Multishot", 170.0), ("Ammo Maximum", 120.0)],
        [("Damage", -232.0)],  # not part of Sati-ampicron
    )
    fixed, _ = reconcile_parsed_with_name(ocr, "Spectra Sati-ampicron", "spectra")
    pos = {p["stat"] for p in fixed["positives"]}
    assert pos == {"Multishot", "Ammo Maximum", "Critical Chance"}


def test_reconcile_no_op_on_garbled_name():
    ocr = _parsed([("Multishot", 130.0)], [("Damage", -80.0)])
    fixed, decoded = reconcile_parsed_with_name(ocr, "Weapon zzzzqxqx", "weapon")
    assert decoded is None
    assert fixed is ocr
