"""StartButtonGroup — 3 boutons Dictée/Réunion/Journal accolés (refonte design).

Réutilise l'énum `Mode` existante (`core/modes.py`) plutôt qu'un type parallèle :
elle porte déjà exactement IDLE/DICTEE/REUNION/JOURNAL. Le câblage à l'état
d'enregistrement global (`MachineEtats`) se fait à l'Étape 7 ; ce composant
n'expose qu'une API `definir_etat()` / un signal `demarrer_demande`.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from debrief_meet.core.modes import Mode
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.pulsing_dot import PointPulsant
from debrief_meet.ui.theme import C, MONO, SANS, color

_ICONES = {
    Mode.DICTEE: "microphone",
    Mode.REUNION: "users-three",
    Mode.JOURNAL: "notebook",
}
_LABELS = {
    Mode.DICTEE: "Dictée",
    Mode.REUNION: "Réunion",
    Mode.JOURNAL: "Journal",
}


def formater_chrono(secondes: int) -> str:
    m, s = divmod(max(0, secondes), 60)
    return f"{m:02d}:{s:02d}"


class _BoutonDemarrage(QFrame):
    clicked = Signal()

    def __init__(self, mode: Mode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("boutonDemarrage")
        self._mode = mode
        self._effet_opacite = QGraphicsOpacityEffect(self)
        self._effet_opacite.setOpacity(1.0)
        self.setGraphicsEffect(self._effet_opacite)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        self._point = PointPulsant(8, self)
        self._point.hide()

        self._icone_label = QLabel(self)
        self._icone_label.setFixedSize(16, 16)

        self._texte = QLabel(_LABELS[mode], self)
        self._texte.setFont(QFont(SANS, 13, QFont.Weight.DemiBold))

        self._chrono = QLabel(self)
        self._chrono.setFont(QFont(MONO, 12))
        self._chrono.hide()

        layout.addWidget(self._point)
        layout.addWidget(self._icone_label)
        layout.addWidget(self._texte)
        layout.addStretch()
        layout.addWidget(self._chrono)

        self.definir_etat("repos")

    def mousePressEvent(self, event) -> None:
        if self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)

    def definir_etat(self, etat: str, secondes: int = 0) -> None:
        """`etat` ∈ {"repos", "actif", "desactive"}."""
        if etat == "actif":
            self.setEnabled(True)
            self._effet_opacite.setOpacity(1.0)
            self._icone_label.hide()
            self._point.show()
            self._texte.setStyleSheet(f"color: {C.REC};")
            self._chrono.setStyleSheet(f"color: {C.REC};")
            self._chrono.setText(formater_chrono(secondes))
            self._chrono.show()
            self.setStyleSheet(f"#boutonDemarrage {{ background: {C.REC_BG}; border-radius: 8px; }}")
        elif etat == "desactive":
            self.setEnabled(False)
            self._point.hide()
            self._icone_label.show()
            self._icone_label.setPixmap(
                icone_svg_teintee(icone_phosphor(_ICONES[self._mode]), C.ACCENT, 16).pixmap(16, 16)
            )
            self._texte.setStyleSheet(f"color: {C.INK700};")
            self._chrono.hide()
            self.setStyleSheet("")
            self._effet_opacite.setOpacity(0.55)
        else:  # repos
            self.setEnabled(True)
            self._effet_opacite.setOpacity(1.0)
            self._point.hide()
            self._icone_label.show()
            self._icone_label.setPixmap(
                icone_svg_teintee(icone_phosphor(_ICONES[self._mode]), C.ACCENT, 16).pixmap(16, 16)
            )
            self._texte.setStyleSheet(f"color: {C.INK700};")
            self._chrono.hide()
            self.setStyleSheet("")


class StartButtonGroup(QFrame):
    """3 boutons Dictée/Réunion/Journal — un seul actif à la fois (cf. Étape 7)."""

    demarrer_demande = Signal(Mode)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startGroup")
        self.setStyleSheet(
            f"QFrame#startGroup {{ border: 1px solid {C.BORDER}; border-radius: 9px; background: {C.SURFACE}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._boutons: dict[Mode, _BoutonDemarrage] = {}
        for i, mode in enumerate((Mode.DICTEE, Mode.REUNION, Mode.JOURNAL)):
            if i > 0:
                separateur = QFrame(self)
                separateur.setFrameShape(QFrame.Shape.VLine)
                separateur.setStyleSheet(f"color: {C.BORDER};")
                layout.addWidget(separateur)
            bouton = _BoutonDemarrage(mode, self)
            bouton.clicked.connect(lambda m=mode: self.demarrer_demande.emit(m))
            layout.addWidget(bouton)
            self._boutons[mode] = bouton

    def definir_etat(self, mode_actif: Mode, secondes: int = 0) -> None:
        """`mode_actif` = `Mode.IDLE` si rien n'enregistre."""
        for mode, bouton in self._boutons.items():
            if mode == mode_actif:
                bouton.definir_etat("actif", secondes)
            elif mode_actif is Mode.IDLE:
                bouton.definir_etat("repos")
            else:
                bouton.definir_etat("desactive")
