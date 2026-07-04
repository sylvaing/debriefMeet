"""Visualisation d'onde décorative (RecordingView) — anime ~44 barres par une onde
sinusoïdale à phases échelonnées. À remplacer par le vrai niveau audio si
disponible (cf. IMPLEMENTATION_SPEC.md §7)."""
from __future__ import annotations

import math

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from debrief_meet.ui.theme import C, color

NB_BARRES = 44
LARGEUR_BARRE = 4
GAP = 3
_MIN_FRAC = 0.12
_PERIODE_MS = 900
_INTERVALLE_MS = 60


class WaveformWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._temps_ms = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVALLE_MS)
        self._timer.timeout.connect(self._avancer)
        largeur = NB_BARRES * LARGEUR_BARRE + (NB_BARRES - 1) * GAP
        self.setFixedSize(largeur, 44)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _avancer(self) -> None:
        self._temps_ms += self._timer.interval()
        self.update()

    def _hauteur_frac(self, index: int) -> float:
        phase = index * (math.pi / 6)  # délai échelonné par barre
        onde = (math.sin(2 * math.pi * self._temps_ms / _PERIODE_MS + phase) + 1) / 2
        return _MIN_FRAC + (1 - _MIN_FRAC) * onde

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        couleur = color(C.ACCENT)
        hauteur_totale = self.height()
        x = 0.0
        for i in range(NB_BARRES):
            h = self._hauteur_frac(i) * hauteur_totale
            y = (hauteur_totale - h) / 2
            chemin = QPainterPath()
            rayon = LARGEUR_BARRE / 2
            chemin.addRoundedRect(x, y, LARGEUR_BARRE, h, rayon, rayon)
            painter.fillPath(chemin, couleur)
            x += LARGEUR_BARRE + GAP
