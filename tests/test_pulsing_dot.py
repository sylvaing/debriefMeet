from __future__ import annotations

from debrief_meet.ui.pulsing_dot import PointPulsant


def test_demarrer_et_arreter_ne_levent_pas(qapp):
    point = PointPulsant(8)
    point.demarrer()
    point.arreter()
    assert point._effet.opacity() == 1.0


def test_taille_respectee(qapp):
    point = PointPulsant(10)
    assert point.size().width() == 10
    assert point.size().height() == 10
