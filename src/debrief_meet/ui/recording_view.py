"""Vue « Enregistrement en cours » — affichée pendant Dictée/Réunion/Journal actifs.

Bouton Arrêter uniquement (aucun Pause). L'affichage de cette vue (bascule de page
du shell) est piloté par `RecordingController` (Étape 7) ; ce widget ne fait que
refléter l'état de `MachineEtats` une fois visible.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.pulsing_dot import PointPulsant
from debrief_meet.ui.start_group import formater_chrono
from debrief_meet.ui.theme import C, MONO, SANS
from debrief_meet.ui.waveform_widget import WaveformWidget

_TITRES = {
    Mode.DICTEE: "Dictée en cours",
    Mode.REUNION: "Réunion en cours",
    Mode.JOURNAL: "Journal en cours",
}

_ARRET_PAR_MODE = {
    Mode.DICTEE: "toggle_dictee",
    Mode.REUNION: "toggle_reunion",
    Mode.JOURNAL: "toggle_journal",
}


class RecordingView(QWidget):
    def __init__(self, machine: MachineEtats, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._machine = machine

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        pastille = QHBoxLayout()
        pastille.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pastille.setSpacing(8)
        self._point = PointPulsant(8, self)
        label_pastille = QLabel("ENREGISTREMENT", self)
        label_pastille.setFont(QFont(MONO, 11))
        label_pastille.setStyleSheet(f"color: {C.REC};")
        pastille.addWidget(self._point)
        pastille.addWidget(label_pastille)
        layout.addLayout(pastille)

        self._titre = QLabel(self)
        self._titre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._titre.setFont(QFont(SANS, 20, QFont.Weight.Bold))
        layout.addWidget(self._titre)

        self._chrono = QLabel("00:00", self)
        self._chrono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chrono.setFont(QFont(MONO, 42, QFont.Weight.Medium))
        layout.addWidget(self._chrono)

        self._waveform = WaveformWidget(self)
        layout.addWidget(self._waveform, 0, Qt.AlignmentFlag.AlignCenter)

        self._encart = QFrame(self)
        self._encart.setStyleSheet(
            f"QFrame {{ background: {C.SUNKEN}; border: 1px solid {C.BORDER}; border-radius: 10px; }}")
        lay_encart = QVBoxLayout(self._encart)
        entete = QLabel("TRANSCRIPTION EN DIRECT", self._encart)
        entete.setFont(QFont(MONO, 10))
        entete.setStyleSheet(f"color: {C.INK300}; border: none;")
        lay_encart.addWidget(entete)
        self._texte_live = QLabel("", self._encart)
        self._texte_live.setWordWrap(True)
        self._texte_live.setStyleSheet(f"color: {C.INK700}; border: none;")
        lay_encart.addWidget(self._texte_live)
        self._encart.setFixedWidth(420)
        layout.addWidget(self._encart, 0, Qt.AlignmentFlag.AlignCenter)

        self._bouton_arreter = QPushButton(" Arrêter", self)
        self._bouton_arreter.setObjectName("danger")
        self._bouton_arreter.setIcon(icone_svg_teintee(icone_phosphor("stop"), "#FFFFFF", 16))
        self._bouton_arreter.clicked.connect(self._sur_arreter)
        layout.addWidget(self._bouton_arreter, 0, Qt.AlignmentFlag.AlignCenter)

        # Timer propre (pas d'abonnement à un timer de MachineEtats — cf. modes.py) :
        # actif seulement pendant que la vue est visible, comme WaveformWidget.
        self._timer_chrono = QTimer(self)
        self._timer_chrono.setInterval(1000)
        self._timer_chrono.timeout.connect(self._on_tick)

        machine.mode_change.connect(self._on_mode_change)
        self._on_mode_change(machine.mode)

    def definir_texte_live(self, texte: str) -> None:
        """Hook pour une future transcription en direct — aucune source ne
        l'alimente aujourd'hui (les orchestrateurs n'émettent qu'un résultat final)."""
        self._texte_live.setText(texte)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._machine.mode is not Mode.IDLE:
            self._timer_chrono.start()

    def hideEvent(self, event) -> None:
        self._timer_chrono.stop()
        super().hideEvent(event)

    def _on_mode_change(self, mode: Mode) -> None:
        if mode is Mode.IDLE:
            self._timer_chrono.stop()
            return
        self._titre.setText(_TITRES[mode])
        self._chrono.setText(formater_chrono(self._machine.elapsed_seconds()))
        if self.isVisible():
            self._timer_chrono.start()

    def _on_tick(self) -> None:
        self._chrono.setText(formater_chrono(self._machine.elapsed_seconds()))

    def _sur_arreter(self) -> None:
        methode = _ARRET_PAR_MODE.get(self._machine.mode)
        if methode is not None:
            getattr(self._machine, methode)()
