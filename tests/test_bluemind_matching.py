from __future__ import annotations

from datetime import datetime

from debrief_meet.core.bluemind.matching import evenements_correspondants
from debrief_meet.core.bluemind.store import Evenement


def _evt(uid, debut, fin, journee_entiere=False):
    return Evenement(uid=uid, cal_uid="cal", debut_ms=debut, fin_ms=fin,
                      journee_entiere=journee_entiere, titre=uid, lieu="")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_chevauchement_pendant():
    debut = datetime(2026, 7, 8, 14, 0)
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 13, 55)), _ms(datetime(2026, 7, 8, 15, 0)))
    assert evenements_correspondants([evt], debut, 1800) == [evt]


def test_evenement_avant_hors_tolerance_exclu():
    debut = datetime(2026, 7, 8, 14, 0)
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 12, 0)), _ms(datetime(2026, 7, 8, 13, 0)))
    assert evenements_correspondants([evt], debut, 1800) == []


def test_evenement_avant_dans_tolerance_inclus():
    debut = datetime(2026, 7, 8, 14, 0)
    # événement fini à 13:52, tolérance 10 min avant 14:00 -> fenêtre débute à 13:50
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 13, 40)), _ms(datetime(2026, 7, 8, 13, 52)))
    assert evenements_correspondants([evt], debut, 1800) == [evt]


def test_evenement_apres_hors_tolerance_exclu():
    debut = datetime(2026, 7, 8, 14, 0)
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 15, 0)), _ms(datetime(2026, 7, 8, 16, 0)))
    assert evenements_correspondants([evt], debut, 1800) == []


def test_journee_entiere_exclue():
    debut = datetime(2026, 7, 8, 14, 0)
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 0, 0)), _ms(datetime(2026, 7, 9, 0, 0)), journee_entiere=True)
    assert evenements_correspondants([evt], debut, 1800) == []


def test_duree_none_traitee_comme_zero():
    debut = datetime(2026, 7, 8, 14, 0)
    evt = _evt("e1", _ms(datetime(2026, 7, 8, 13, 55)), _ms(datetime(2026, 7, 8, 14, 5)))
    assert evenements_correspondants([evt], debut, None) == [evt]


def test_plusieurs_correspondances():
    debut = datetime(2026, 7, 8, 14, 0)
    e1 = _evt("e1", _ms(datetime(2026, 7, 8, 13, 55)), _ms(datetime(2026, 7, 8, 14, 30)))
    e2 = _evt("e2", _ms(datetime(2026, 7, 8, 14, 10)), _ms(datetime(2026, 7, 8, 15, 0)))
    resultat = evenements_correspondants([e1, e2], debut, 1800)
    assert {e.uid for e in resultat} == {"e1", "e2"}
