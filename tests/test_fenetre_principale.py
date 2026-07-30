from __future__ import annotations

import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.ui.fenetre_principale import (
    PAGE_DICTEE,
    PAGE_JOURNAL,
    PAGE_PREFERENCES,
    PAGE_REUNION,
    FenetrePrincipale,
)


@pytest.fixture(autouse=True)
def _edition(edition_complete_sauf_si_lite):
    """Sujet du module : les 4 pages, dont Dictée et Journal — édition complète
    épinglée sauf test lite explicite (docs/44)."""


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


def test_quatre_pages(fen):
    assert fen._pages.count() == 4


def test_reunion_est_la_page_par_defaut(fen):
    assert fen._pages.currentIndex() == PAGE_REUNION
    assert fen._nav_reunion.isChecked()


def test_nav_dictee_change_de_page(fen):
    fen._nav_dictee.click()
    assert fen._pages.currentIndex() == PAGE_DICTEE
    assert fen._nav_dictee.isChecked()


def test_nav_journal_change_de_page(fen):
    fen._nav_journal.click()
    assert fen._pages.currentIndex() == PAGE_JOURNAL
    assert fen._nav_journal.isChecked()


def test_afficher_preferences_change_de_page(fen):
    fen.afficher_preferences()
    assert fen._pages.currentIndex() == PAGE_PREFERENCES
    assert fen._bouton_prefs.isChecked()


def test_bouton_prefs_change_de_page(fen):
    fen._bouton_prefs.click()
    assert fen._pages.currentIndex() == PAGE_PREFERENCES


def test_demarrer_reunion_ne_change_pas_de_page(fen, machine):
    """Le bouton Démarrer de la section Réunion appelle machine.toggle_reunion
    directement (câblé dans ReunionView) — la page reste celle où on a cliqué."""
    machine.toggle_reunion()
    assert fen._pages.currentIndex() == PAGE_REUNION


def test_definir_etat_visuel_ne_leve_pas(fen):
    for etat in EtatVisuel:
        fen.definir_etat_visuel(etat)


def test_selectionner_reunion_ouvre_la_page_reunion(fen):
    fen.afficher_preferences()
    fen.selectionner_reunion(None)
    assert fen._pages.currentIndex() == PAGE_REUNION


def test_onglets_navigables_pendant_enregistrement(fen, machine):
    """L'enregistrement est un état global indépendant de la page affichée —
    naviguer ailleurs pendant une capture ne l'interrompt pas (CHANGELOG_v2 §6)."""
    machine.toggle_reunion()
    fen._nav_journal.click()
    assert fen._pages.currentIndex() == PAGE_JOURNAL
    assert machine.mode == Mode.REUNION


# ── Édition lite (docs/44) ───────────────────────────────────────────────────

def test_lite_deux_pages_sans_dictee_ni_journal(qapp, machine, tmp_path, edition_lite):
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    try:
        assert fenetre._pages.count() == 2          # Réunion + Préférences
        assert fenetre._dictee_view is None
        assert fenetre._journal_view is None
        assert fenetre._nav_dictee is None
        assert fenetre._nav_journal is None
    finally:
        fenetre._recording_controller._timer.stop()


def test_lite_les_pages_restantes_restent_atteignables(qapp, machine, tmp_path, edition_lite):
    """Les constantes PAGE_* ne sont plus des index de pile : Préférences est en
    position 1 en lite, et `afficher_preferences()` doit quand même y aller."""
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    try:
        fenetre.afficher_preferences()
        assert fenetre._pages.currentWidget() is fenetre._preferences_view
        fenetre.afficher_reunion()
        assert fenetre._pages.currentWidget() is fenetre._reunion_view
        assert fenetre._index_pages[PAGE_PREFERENCES] == 1
    finally:
        fenetre._recording_controller._timer.stop()
