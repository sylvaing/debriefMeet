"""Arbitre de l'état visuel de l'icône (tray + toolbar) — 2026-08-21.

Historiquement seuls les orchestrateurs d'enregistrement (dictée/réunion/journal)
pilotaient la couleur de l'icône : les jobs lancés depuis l'Historique
(transcription locale différée, génération des locuteurs, CR Mistral) tournaient
sans aucun retour visuel. Cet arbitre fusionne les deux sources :

* l'état des orchestrateurs **gagne toujours** (le rouge enregistrement prime sur
  l'orange d'un job) ;
* sinon, un flash bref de fin de job (vert TERMINE / gris ERREUR) ;
* sinon, un job en cours ⇒ orange TRANSCRIPTION — y compris au retour à IDLE d'un
  enregistrement pendant lequel un job tournait encore ;
* sinon REPOS.

Les connexions directes `orchestrateur → tray/fenêtre` sont remplacées par
`orchestrateur → arbitre → tray/fenêtre` (câblage dans `__main__`). L'arbitre
n'émet que sur changement effectif — les repaints d'icône ne sont pas gratuits.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from debrief_meet.core.modes import EtatVisuel

_DELAI_FLASH_MS = 3000


class ArbitreEtatVisuel(QObject):
    etat_change = Signal(object)  # EtatVisuel

    def __init__(self, parent: QObject | None = None,
                 delai_flash_ms: int = _DELAI_FLASH_MS) -> None:
        super().__init__(parent)
        self._delai_flash_ms = delai_flash_ms
        self._etat_orchestrateur = EtatVisuel.REPOS
        self._jobs: set[str] = set()
        self._flash: EtatVisuel | None = None
        self._dernier_emis: EtatVisuel | None = None

    # ── Câblage ──────────────────────────────────────────────────────────────

    def suivre_orchestrateur(self, orchestrateur) -> None:
        orchestrateur.etat_visuel_change.connect(self._sur_orchestrateur)

    def suivre_gestionnaire(self, gestionnaire, cle: str) -> None:
        """`gestionnaire` expose demarre(md) / termine(md, sortie) / echoue(md, msg)
        (GestionnaireDiarization comme GestionnaireCRMistral). `cle` distingue les
        sources : deux jobs simultanés ne s'éteignent pas l'un l'autre."""
        gestionnaire.demarre.connect(lambda _md, c=cle: self._sur_job_demarre(c))
        gestionnaire.termine.connect(
            lambda _md, _sortie, c=cle: self._sur_job_fini(c, EtatVisuel.TERMINE))
        gestionnaire.echoue.connect(
            lambda _md, _msg, c=cle: self._sur_job_fini(c, EtatVisuel.ERREUR))

    # ── Événements ───────────────────────────────────────────────────────────

    @Slot(object)
    def _sur_orchestrateur(self, etat: EtatVisuel) -> None:
        self._etat_orchestrateur = etat
        self._emettre()

    def _sur_job_demarre(self, cle: str) -> None:
        self._jobs.add(cle)
        self._flash = None
        self._emettre()

    def _sur_job_fini(self, cle: str, flash: EtatVisuel) -> None:
        self._jobs.discard(cle)
        self._flash = flash
        self._emettre()
        # `self` en contexte : le timer meurt avec l'arbitre (piège QTimer en tests).
        QTimer.singleShot(self._delai_flash_ms, self, self._fin_flash)

    def _fin_flash(self) -> None:
        self._flash = None
        self._emettre()

    # ── Décision ─────────────────────────────────────────────────────────────

    def _etat_courant(self) -> EtatVisuel:
        if self._etat_orchestrateur != EtatVisuel.REPOS:
            return self._etat_orchestrateur
        if self._flash is not None:
            return self._flash
        if self._jobs:
            return EtatVisuel.TRANSCRIPTION
        return EtatVisuel.REPOS

    def _emettre(self) -> None:
        etat = self._etat_courant()
        if etat != self._dernier_emis:
            self._dernier_emis = etat
            self.etat_change.emit(etat)
