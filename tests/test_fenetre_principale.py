from __future__ import annotations

import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.ui.fenetre_principale import (
    PAGE_ENREGISTREMENT,
    PAGE_HISTORIQUE,
    PAGE_PREFERENCES,
    FenetrePrincipale,
)


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path / "r"))
    cfg.set("dossier_journal", str(tmp_path / "j"))
    return cfg


@pytest.fixture
def machine(qapp):
    return MachineEtats()


@pytest.fixture
def fen(qapp, machine, tmp_path):
    """`FenetrePrincipale` avec arrêt garanti du timer de son `RecordingController`
    interne — `qapp` est partagée entre tous les tests (session pytest-qt) : un
    timer répétitif laissé actif (mode non repassé à IDLE) sur une fenêtre devenue
    non référencée peut tirer plus tard, ailleurs, sur un objet détruit (crash natif,
    cf. recording_controller.py)."""
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    yield fenetre
    fenetre._recording_controller._timer.stop()


def test_trois_pages(fen):
    assert fen._pages.count() == 3


def test_historique_est_la_page_par_defaut(fen):
    assert fen._pages.currentIndex() == PAGE_HISTORIQUE
    assert fen._nav_historique.isChecked()


def test_nav_preferences_change_de_page(fen):
    fen.afficher_preferences()
    assert fen._pages.currentIndex() == PAGE_PREFERENCES
    assert fen._nav_preferences.isChecked()


def test_demarrer_enregistrement_affiche_la_vue_sans_changer_le_nav(fen):
    fen._start_group.demarrer_demande.emit(Mode.REUNION)
    assert fen._pages.currentIndex() == PAGE_ENREGISTREMENT
    assert fen._nav_historique.isChecked()  # onglet coché inchangé


def test_clic_nav_pendant_enregistrement_bascule_quand_meme(fen):
    fen._start_group.demarrer_demande.emit(Mode.REUNION)
    fen._nav_preferences.click()
    assert fen._pages.currentIndex() == PAGE_PREFERENCES


def test_definir_etat_visuel_ne_leve_pas(fen):
    for etat in EtatVisuel:
        fen.definir_etat_visuel(etat)


def test_selectionner_reunion_ouvre_historique(fen):
    fen.afficher_preferences()
    fen.selectionner_reunion(None)
    assert fen._pages.currentIndex() == PAGE_HISTORIQUE
