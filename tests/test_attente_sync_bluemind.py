"""Tests de `ui/attente_sync_bluemind.attendre_sync` — attente bornée d'une synchro
BlueMind avant la détection d'événement du flux CR Mistral (docs/42).

Aucun réseau : un faux `SynchroCalendrier` (mêmes signaux, mêmes prédicats) émet
`terminee`/`echouee` via un `QTimer` pour simuler un worker.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from debrief_meet.ui.attente_sync_bluemind import attendre_sync


class FauxSynchro(QObject):
    """Miroir de `SynchroCalendrier` réduit à ce que consomme `attendre_sync`."""

    terminee = Signal(int)
    echouee = Signal(str)

    def __init__(self, configuree=True, demarre=True, deja_en_cours=False, issue="terminee",
                 delai_ms=10):
        super().__init__()
        self._configuree = configuree
        self._demarre = demarre
        self._en_cours = deja_en_cours
        self._issue = issue
        self._delai_ms = delai_ms
        self.declenchements = 0

    def configuree(self):
        return self._configuree

    def en_cours(self):
        return self._en_cours

    def synchroniser_si_necessaire(self):
        self.declenchements += 1
        if not self._demarre:
            return False
        self._en_cours = True
        if self._issue != "jamais":     # « jamais » : worker qui ne rend pas la main
            QTimer.singleShot(self._delai_ms, self._finir)
        return True

    def _finir(self):
        self._en_cours = False
        if self._issue == "terminee":
            self.terminee.emit(3)
        else:
            self.echouee.emit("réseau injoignable")


def test_sans_synchro_est_un_noop(qapp):
    assert attendre_sync(None, None) is False


def test_non_configuree_est_un_noop(qapp):
    synchro = FauxSynchro(configuree=False)
    assert attendre_sync(synchro, None) is False
    assert synchro.declenchements == 0          # aucun appel réseau tenté


def test_attend_la_fin_de_la_sync(qapp):
    synchro = FauxSynchro()
    assert attendre_sync(synchro, None) is True
    assert synchro.declenchements == 1
    assert synchro.en_cours() is False


def test_sync_en_echec_sort_de_lattente(qapp):
    """Une panne réseau ne doit ni bloquer ni remonter d'erreur (docs/40 §1.1) : on
    enchaîne sur la réplique telle quelle."""
    synchro = FauxSynchro(issue="echouee")
    assert attendre_sync(synchro, None) is True


def test_rejoint_une_sync_deja_en_cours(qapp):
    """`synchroniser_si_necessaire()` renvoie False quand un worker tourne déjà (timer,
    ouverture de fenêtre) — il faut malgré tout attendre SA fin."""
    synchro = FauxSynchro(demarre=False, deja_en_cours=True)
    QTimer.singleShot(10, lambda: synchro.terminee.emit(1))
    assert attendre_sync(synchro, None) is True


def test_ni_demarree_ni_en_cours_sort_immediatement(qapp):
    """Configuration invalide (URL sans /api) : rien à attendre."""
    synchro = FauxSynchro(demarre=False, deja_en_cours=False)
    assert attendre_sync(synchro, None) is False


def test_timeout_garantit_la_sortie(qapp):
    """Une resync qui ne rend jamais la main ne doit pas bloquer l'utilisateur."""
    synchro = FauxSynchro(issue="jamais")
    assert attendre_sync(synchro, None, timeout_ms=30) is True
    assert synchro.en_cours() is True            # toujours en cours, on continue sans elle


def test_signaux_deconnectes_apres_chaque_attente(qapp):
    """Deux attentes successives ne doivent pas empiler les connexions (une boucle morte
    recevant un `quit` sortirait de la suivante trop tôt)."""
    synchro = FauxSynchro()
    assert attendre_sync(synchro, None) is True
    assert attendre_sync(synchro, None) is True
    assert synchro.declenchements == 2
