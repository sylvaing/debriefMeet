"""Tests unitaires — SurveillantPeripheriques : anti-rebond des changements."""
from __future__ import annotations

from debrief_meet.platform.commun.surveillant_peripheriques import SurveillantPeripheriques


def test_rafale_evenements_emet_un_seul_change(qapp, qtbot):
    """Plusieurs changements rapprochés (un retrait en émet plusieurs) → 1 seul `change`."""
    s = SurveillantPeripheriques(debounce_ms=80)
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    s._planifier()
    s._planifier()

    qtbot.wait(200)
    assert len(recus) == 1


def test_aucun_evenement_aucun_change(qapp, qtbot):
    s = SurveillantPeripheriques(debounce_ms=80)
    recus = []
    s.change.connect(lambda: recus.append(1))

    qtbot.wait(200)
    assert recus == []


def test_deux_salves_espacees_emettent_deux_change(qapp, qtbot):
    s = SurveillantPeripheriques(debounce_ms=80)
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    qtbot.wait(200)
    s._planifier()
    qtbot.wait(200)

    assert len(recus) == 2
