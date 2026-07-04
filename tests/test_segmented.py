from __future__ import annotations

from debrief_meet.ui.segmented import SegmentedControl


def test_premier_segment_actif_par_defaut(qapp):
    sc = SegmentedControl(["Réunions", "Journal"])
    assert sc.index_actif() == 0


def test_definir_index_change_le_segment_actif(qapp):
    sc = SegmentedControl(["Réunions", "Journal"])
    sc.definir_index(1)
    assert sc.index_actif() == 1


def test_clic_emet_changed(qapp, qtbot):
    sc = SegmentedControl(["Réunions", "Journal"])
    with qtbot.waitSignal(sc.changed, timeout=1000) as bloqueur:
        sc._boutons[1].click()
    assert bloqueur.args == [1]


def test_definir_index_emet_aussi_changed(qapp, qtbot):
    """`QButtonGroup.idClicked` ne se déclenche que sur clic réel — `definir_index`
    (appel programmatique) doit émettre `changed` lui-même."""
    sc = SegmentedControl(["Réunions", "Journal"])
    with qtbot.waitSignal(sc.changed, timeout=1000) as bloqueur:
        sc.definir_index(1)
    assert bloqueur.args == [1]


def test_definir_index_sur_le_meme_segment_ne_re_emet_pas(qapp, qtbot):
    sc = SegmentedControl(["Réunions", "Journal"])
    with qtbot.assertNotEmitted(sc.changed):
        sc.definir_index(0)
