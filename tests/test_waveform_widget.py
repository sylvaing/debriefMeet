from __future__ import annotations

from debrief_meet.ui.waveform_widget import GAP, LARGEUR_BARRE, NB_BARRES, WaveformWidget


def test_taille_fixe_selon_le_nombre_de_barres(qapp):
    w = WaveformWidget()
    largeur_attendue = NB_BARRES * LARGEUR_BARRE + (NB_BARRES - 1) * GAP
    assert w.width() == largeur_attendue


def test_hauteur_frac_dans_les_bornes(qapp):
    w = WaveformWidget()
    for t in range(0, 3000, 137):
        w._temps_ms = t
        for i in range(NB_BARRES):
            frac = w._hauteur_frac(i)
            assert 0.0 <= frac <= 1.0


def test_avancer_incremente_le_temps_et_declenche_repaint(qapp):
    w = WaveformWidget()
    avant = w._temps_ms
    w._avancer()
    assert w._temps_ms == avant + w._timer.interval()


def test_show_hide_pilotent_le_timer(qapp):
    w = WaveformWidget()
    w.show()
    assert w._timer.isActive()
    w.hide()
    assert not w._timer.isActive()
