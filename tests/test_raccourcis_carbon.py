"""Fonctions pures de l'adaptateur Carbon (docs/28) — testables sans matériel."""
from __future__ import annotations

import pytest

from debrief_meet.platform.macos.raccourcis_carbon import (
    _KEYCODES_REPLI,
    _caractere_de_base,
    _keycode_pour_caractere,
    _mods_qt_vers_carbon,
    cmdKey,
    controlKey,
    optionKey,
    shiftKey,
)


def test_mods_qt_vers_carbon_echange_ctrl_et_meta():
    # Piège §2.1 : Qt-Ctrl (portable) → cmdKey macOS ; Qt-Meta (portable) → controlKey macOS.
    mods = _mods_qt_vers_carbon("Meta+Alt+Ctrl+D")
    assert mods == (controlKey | optionKey | cmdKey)


def test_mods_qt_vers_carbon_shift_seul():
    assert _mods_qt_vers_carbon("Shift+D") == shiftKey


def test_caractere_de_base_extrait_la_derniere_touche():
    assert _caractere_de_base("Meta+Alt+Ctrl+D") == "d"
    assert _caractere_de_base("Ctrl+F1") == "f1"


def test_table_de_repli_defauts_drj():
    assert _KEYCODES_REPLI["d"] == 0x02
    assert _KEYCODES_REPLI["r"] == 0x0F
    assert _KEYCODES_REPLI["j"] == 0x26


def test_keycode_pour_caractere_utilise_le_repli_si_carbon_indisponible(monkeypatch):
    import debrief_meet.platform.macos.raccourcis_carbon as mod
    monkeypatch.setattr(mod, "_keycode_via_tis", lambda car: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _keycode_pour_caractere("d") == 0x02


@pytest.mark.integration
def test_resolution_azerty_lettre_a():
    """Sur le Mac AZERTY de référence (docs/28 §2.2) : « a » → keycode 0x0C (position Q)."""
    assert _keycode_pour_caractere("a") == 0x0C
