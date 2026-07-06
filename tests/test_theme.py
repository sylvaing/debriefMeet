from __future__ import annotations

from debrief_meet.ui.theme import C, M, charger_theme, color


def test_charger_theme_applique_le_qss(qapp):
    charger_theme(qapp)
    qss = qapp.styleSheet()
    assert qss
    assert "__CHECK_WHITE__" not in qss  # jeton bien substitué
    assert "#3B5BDB" in qss  # accent (QPushButton#primary)


def test_couleur_helper(qapp):
    assert color(C.ACCENT).name().upper() == C.ACCENT

    q = color(C.ACCENT)
    assert q.isValid()


def test_metriques_positives():
    for nom in ("TITLEBAR_H", "TOOLBAR_H", "ROW_H", "PAD_CONTENT", "PAD_FORM", "PREF_NAV_W"):
        assert getattr(M, nom) > 0
