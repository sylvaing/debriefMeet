"""Câblage de l'état d'enregistrement global (`MachineEtats`) sur les composants
qui le reflètent — StartButtonGroup aujourd'hui, icônes toolbar/tray à l'Étape 8.

Ne duplique pas l'état : lit toujours `machine.mode`/`machine.elapsed_seconds()`.
La bascule de page réelle (afficher `RecordingView`) est déléguée au shell
(Étape 4) via le signal `showRequested`.

⚠️ Garder une référence Python (ou passer un `parent`) à l'instance : un
`RecordingController()` sans propriétaire est éligible au GC dès la fin de la
ligne qui le construit, ce qui coupe silencieusement ses connexions aux
signaux de `MachineEtats`/`StartButtonGroup`.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.start_group import StartButtonGroup

_DEMARRER_PAR_MODE = {
    Mode.DICTEE: "toggle_dictee",
    Mode.REUNION: "toggle_reunion",
    Mode.JOURNAL: "toggle_journal",
}


class RecordingController(QObject):
    """Logique de `start(t)` de la spec (§7) : re-clic du type actif → ré-affichage
    sans relance ; autre type actif → ignoré ; sinon démarrage.

    Possède son propre timer d'affichage (démarré/arrêté avec le mode) plutôt que
    de s'abonner à un timer de `MachineEtats` — `elapsed_seconds()` est une pure
    lecture d'horloge côté core (cf. modes.py), la mise à jour périodique de
    l'UI est une responsabilité de ce contrôleur."""

    showRequested = Signal()

    def __init__(self, machine: MachineEtats, start_group: StartButtonGroup,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._machine = machine
        self._start_group = start_group

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        machine.mode_change.connect(self._on_mode_change)
        start_group.demarrer_demande.connect(self._on_demarrer_demande)

        self._on_mode_change(machine.mode)

    def _on_demarrer_demande(self, mode: Mode) -> None:
        if self._machine.mode == mode:
            self.showRequested.emit()
            return
        if self._machine.mode is not Mode.IDLE:
            return  # un autre type est actif — bouton normalement déjà désactivé
        getattr(self._machine, _DEMARRER_PAR_MODE[mode])()
        self.showRequested.emit()

    def _on_mode_change(self, mode: Mode) -> None:
        self._start_group.definir_etat(mode, self._machine.elapsed_seconds())
        if mode is Mode.IDLE:
            self._timer.stop()
        else:
            self._timer.start()

    def _on_tick(self) -> None:
        if self._machine.mode is not Mode.IDLE:
            self._start_group.definir_etat(self._machine.mode, self._machine.elapsed_seconds())
