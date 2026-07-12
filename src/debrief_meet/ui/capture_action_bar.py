"""Barre d'action de section (Réunion/Dictée/Journal) — bouton bascule
Démarrer/Arrêter + recherche optionnelle (refonte design v2, CHANGELOG_v2 §1/§2).

Remplace le `StartButtonGroup` segmenté de la toolbar (supprimé) : chaque page
de type porte désormais sa propre barre, avec un seul bouton bascule dont
l'état dépend de `MachineEtats.mode` (repos/actif/desactive), piloté par
`RecordingController`. Le bouton n'émet qu'un signal sans argument — `mode`
est déjà fixé à la construction — la cible (`machine.toggle_x`) gère elle-même
démarrage/arrêt selon son propre état ; l'état « desactive » (un autre type
enregistre) désactive le bouton, ce qui empêche déjà tout clic indésirable.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from debrief_meet.core.modes import Mode
from debrief_meet.ui.bulk_action_bar import BulkActionBar
from debrief_meet.ui.chrono import formater_chrono
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.pulsing_dot import PointPulsant
from debrief_meet.ui.theme import C, MONO, SANS

_ICONES = {
    Mode.DICTEE: "microphone",
    Mode.REUNION: "users-three",
    Mode.JOURNAL: "notebook",
}
_LABELS_DEMARRER = {
    Mode.DICTEE: "Démarrer la dictée",
    Mode.REUNION: "Démarrer la réunion",
    Mode.JOURNAL: "Démarrer le journal",
}

_STYLE_PRIMAIRE = (
    f"QPushButton {{ background: {C.ACCENT}; color: #fff; border: none;"
    f" border-radius: 9px; padding: 9px 18px; font-weight: 600; }}"
    f"QPushButton:hover {{ background: {C.ACCENT_INK}; }}"
)
_STYLE_DANGER = (
    f"QPushButton {{ background: {C.REC}; color: #fff; border: none;"
    f" border-radius: 9px; padding: 9px 18px; font-weight: 600; }}"
)
_STYLE_DESACTIVE = (
    f"QPushButton {{ background: {C.NEUTRAL_BG}; color: {C.INK300}; border: none;"
    f" border-radius: 9px; padding: 9px 18px; font-weight: 600; }}"
)


class CaptureActionBar(QWidget):
    """Barre en tête de section : bouton bascule Démarrer/Arrêter, aside pendant
    l'enregistrement le point pulsant + chrono, et (optionnel) recherche."""

    demande_bascule = Signal()
    recherche_change = Signal(str)
    # Actions en masse (§8.6.4) — relayées depuis la BulkActionBar interne.
    demande_ignorer_audio_masse = Signal()
    demande_supprimer_masse = Signal()
    demande_deselection = Signal()

    def __init__(
        self,
        mode: Mode,
        avec_recherche: bool,
        placeholder_recherche: str = "Rechercher…",
        actions_masse: bool = False,
        avec_ignorer_audio: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self.setStyleSheet(f"border-bottom: 1px solid {C.BORDER_SOFT};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        self._bouton = QPushButton(self)
        self._bouton.setFont(QFont(SANS, 13, QFont.Weight.DemiBold))
        self._bouton.setIconSize(QSize(16, 16))
        self._bouton.clicked.connect(self.demande_bascule.emit)
        layout.addWidget(self._bouton)

        self._point = PointPulsant(9, self)
        self._point.hide()
        layout.addWidget(self._point)

        self._chrono = QLabel(self)
        self._chrono.setFont(QFont(MONO, 15, QFont.Weight.Medium))
        self._chrono.setStyleSheet(f"color: {C.REC};")
        self._chrono.hide()
        layout.addWidget(self._chrono)

        self._msg_autre = QLabel("Un enregistrement est déjà en cours.", self)
        self._msg_autre.setStyleSheet(f"color: {C.INK300}; font-size: 12px;")
        self._msg_autre.hide()
        layout.addWidget(self._msg_autre)

        self._bulk: BulkActionBar | None = None
        if actions_masse:
            self._bulk = BulkActionBar(avec_ignorer_audio, self)
            self._bulk.ignorer_audio.connect(self.demande_ignorer_audio_masse.emit)
            self._bulk.supprimer.connect(self.demande_supprimer_masse.emit)
            self._bulk.deselection.connect(self.demande_deselection.emit)
            layout.addWidget(self._bulk)

        layout.addStretch()

        self._recherche: QLineEdit | None = None
        if avec_recherche:
            self._recherche = QLineEdit(self)
            self._recherche.setObjectName("searchField")
            self._recherche.setPlaceholderText(placeholder_recherche)
            self._recherche.setFixedWidth(260)
            self._recherche.textChanged.connect(self.recherche_change.emit)
            layout.addWidget(self._recherche)

        self.definir_etat(Mode.IDLE)

    def definir_compte_selection(self, n: int) -> None:
        """Actualise la barre d'actions en masse (visible dès n ≥ 2, §8.6.4)."""
        if self._bulk is not None:
            self._bulk.definir_compte(n)

    def definir_etat(self, mode_actif: Mode, secondes: int = 0) -> None:
        """`mode_actif` = `Mode.IDLE` si rien n'enregistre."""
        if mode_actif == self._mode:
            self._configurer_actif(secondes)
        elif mode_actif is Mode.IDLE:
            self._configurer_repos()
        else:
            self._configurer_desactive()

    def _configurer_repos(self) -> None:
        self._bouton.setEnabled(True)
        self._bouton.setStyleSheet(_STYLE_PRIMAIRE)
        self._bouton.setText(" " + _LABELS_DEMARRER[self._mode])
        self._bouton.setIcon(icone_svg_teintee(icone_phosphor(_ICONES[self._mode]), "#FFFFFF", 16))
        self._point.hide()
        self._chrono.hide()
        self._msg_autre.hide()

    def _configurer_actif(self, secondes: int) -> None:
        self._bouton.setEnabled(True)
        self._bouton.setStyleSheet(_STYLE_DANGER)
        self._bouton.setText(" Arrêter")
        self._bouton.setIcon(icone_svg_teintee(icone_phosphor("stop"), "#FFFFFF", 14))
        self._chrono.setText(formater_chrono(secondes))
        self._point.show()
        self._chrono.show()
        self._msg_autre.hide()

    def _configurer_desactive(self) -> None:
        self._bouton.setEnabled(False)
        self._bouton.setStyleSheet(_STYLE_DESACTIVE)
        self._bouton.setText(" " + _LABELS_DEMARRER[self._mode])
        self._bouton.setIcon(icone_svg_teintee(icone_phosphor(_ICONES[self._mode]), C.INK300, 16))
        self._point.hide()
        self._chrono.hide()
        self._msg_autre.show()
