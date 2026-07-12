from __future__ import annotations

from debrief_meet.ui.actions_delegate import ActionSpec
from debrief_meet.ui.actions_menu import _LARGEUR_MIN, construire_menu_actions


def test_menu_respecte_la_largeur_minimale(qapp):
    specs = [ActionSpec("file-text", "Ouvrir", True, lambda: None)]
    menu = construire_menu_actions(specs)
    assert menu.width() >= _LARGEUR_MIN


def test_menu_s_elargit_pour_ne_pas_tronquer_un_libelle_long(qapp):
    court = construire_menu_actions([ActionSpec("copy", "Copier", True, lambda: None)])
    long = construire_menu_actions([
        ActionSpec("microphone-slash", "Supprimer l'audio (garde le débrief)", True, lambda: None),
    ])
    # Le libellé long dépasse la largeur minimale → le menu s'élargit au-delà.
    assert long.width() > court.width()
    assert long.width() > _LARGEUR_MIN


def test_item_indisponible_et_destructif_construits(qapp):
    specs = [
        ActionSpec("copy", "Copier", True, lambda: None),
        ActionSpec("users", "Locuteurs déjà générés", False, lambda: None),
        ActionSpec("trash", "Tout supprimer", True, lambda: None, danger=True, separateur_avant=True),
    ]
    menu = construire_menu_actions(specs)
    # 3 items + 1 séparateur = 4 QAction.
    assert len(menu.actions()) == 4
    separateurs = [a for a in menu.actions() if a.isSeparator()]
    assert len(separateurs) == 1
