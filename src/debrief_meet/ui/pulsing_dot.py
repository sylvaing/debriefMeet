"""Point pulsant rouge — indicateur d'enregistrement actif.

Réutilisé par `StartButtonGroup` (Étape 3d) et `RecordingView` (Étape 7).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from debrief_meet.ui.theme import C, color


class PointPulsant(QWidget):
    """Cercle rouge dont l'opacité oscille 1 → 0.35 en boucle (1.4 s)."""

    def __init__(self, taille: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(taille, taille)

        self._effet = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effet)

        aller = QPropertyAnimation(self._effet, b"opacity", self)
        aller.setStartValue(1.0); aller.setEndValue(0.35); aller.setDuration(700)
        aller.setEasingCurve(QEasingCurve.Type.InOutSine)

        retour = QPropertyAnimation(self._effet, b"opacity", self)
        retour.setStartValue(0.35); retour.setEndValue(1.0); retour.setDuration(700)
        retour.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._animation = QSequentialAnimationGroup(self)
        self._animation.addAnimation(aller)
        self._animation.addAnimation(retour)
        self._animation.setLoopCount(-1)

    def demarrer(self) -> None:
        self._animation.start()

    def arreter(self) -> None:
        self._animation.stop()
        self._effet.setOpacity(1.0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.demarrer()

    def hideEvent(self, event) -> None:
        self.arreter()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(C.REC))
        painter.drawEllipse(self.rect())
