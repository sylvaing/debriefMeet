"""Câblage de l'état d'enregistrement global (`MachineEtats`) sur les 3 pages de
capture (refonte design v2, CHANGELOG_v2 §6) — chacune expose
`definir_etat_enregistrement(mode_actif, secondes)`, qui répercute sur sa
`CaptureActionBar` (bouton bascule + point/chrono) et, pour Réunion
uniquement, sur la ligne « en cours » du tableau.

Ne duplique pas l'état : lit toujours `machine.mode`/`machine.elapsed_seconds()`.

⚠️ Garder une référence Python (ou passer un `parent`) à l'instance : un
`RecordingController()` sans propriétaire est éligible au GC dès la fin de la
ligne qui le construit, ce qui coupe silencieusement ses connexions au signal
de `MachineEtats`.
"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, QTimer

from debrief_meet.core.modes import MachineEtats, Mode


class _VueCapture(Protocol):
    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None: ...


class RecordingController(QObject):
    """Chaque page de capture affiche son propre bouton Démarrer/Arrêter — le clic
    appelle directement `machine.toggle_x` (câblé par la vue elle-même) ; ce
    contrôleur ne fait que répercuter les changements de `MachineEtats` sur les
    3 vues, avec son propre timer d'affichage (1 s, actif seulement pendant un
    enregistrement) — `elapsed_seconds()` est une pure lecture d'horloge côté
    core (cf. modes.py)."""

    def __init__(
        self,
        machine: MachineEtats,
        reunion_view: _VueCapture,
        dictee_view: _VueCapture,
        journal_view: _VueCapture,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._machine = machine
        self._vues: tuple[_VueCapture, ...] = (reunion_view, dictee_view, journal_view)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        machine.mode_change.connect(self._on_mode_change)
        self._on_mode_change(machine.mode)

    def _on_mode_change(self, mode: Mode) -> None:
        secondes = self._machine.elapsed_seconds()
        for vue in self._vues:
            vue.definir_etat_enregistrement(mode, secondes)
        if mode is Mode.IDLE:
            self._timer.stop()
        else:
            self._timer.start()

    def _on_tick(self) -> None:
        mode = self._machine.mode
        if mode is Mode.IDLE:
            return
        secondes = self._machine.elapsed_seconds()
        for vue in self._vues:
            vue.definir_etat_enregistrement(mode, secondes)
