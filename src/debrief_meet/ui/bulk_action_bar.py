"""Barre d'actions en masse (DESIGN.md §8.6.4) — insérée dans la barre d'action
de section (`CaptureActionBar`), juste après le bouton Démarrer, séparée par un
filet vertical. Visible **uniquement** dès ≥ 2 lignes sélectionnées dans
l'historique (le cas unitaire reste couvert par le menu ⋯ par ligne, §8.6.3).

N'embarque **aucune** logique métier : elle n'émet que des signaux
(`ignorer_audio`, `supprimer`, `deselection`) que la vue relie à ses handlers
existants (suppression / ignore-audio de lot via `_cibles(None)` = sélection).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, SANS

_STYLE_SECONDAIRE = (
    f"QPushButton {{ background: #fff; color: {C.INK700}; border: 1px solid #D6D9DE;"
    f" border-radius: 8px; padding: 7px 12px; font-weight: 600; font-size: 12px; }}"
    f"QPushButton:hover {{ border-color: {C.ACCENT}; color: {C.ACCENT_INK}; }}"
)
_STYLE_DESTRUCTIF = (
    f"QPushButton {{ background: #fff; color: {C.DANGER}; border: 1px solid #F4C9C7;"
    f" border-radius: 8px; padding: 7px 12px; font-weight: 600; font-size: 12px; }}"
    f"QPushButton:hover {{ background: {C.DANGER_BG}; }}"
)
_STYLE_GHOST = (
    f"QPushButton {{ background: transparent; border: none; border-radius: 7px; }}"
    f"QPushButton:hover {{ background: {C.NEUTRAL_BG}; }}"
)


class BulkActionBar(QWidget):
    ignorer_audio = Signal()
    supprimer = Signal()
    deselection = Signal()

    def __init__(self, avec_ignorer_audio: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filet = QFrame(self)
        filet.setFixedSize(1, 22)
        filet.setStyleSheet(f"background: {C.BORDER};")
        layout.addWidget(filet)
        layout.addSpacing(4)

        self._compteur = QLabel(self)
        self._compteur.setFont(QFont(SANS, 12))
        layout.addWidget(self._compteur)

        if avec_ignorer_audio:
            btn_audio = QPushButton(" Ignorer l'audio", self)
            btn_audio.setStyleSheet(_STYLE_SECONDAIRE)
            btn_audio.setIcon(icone_svg_teintee(icone_phosphor("microphone-slash"), C.INK700, 15))
            btn_audio.setIconSize(QSize(15, 15))
            btn_audio.setToolTip("Ignorer l'audio des éléments sélectionnés")
            btn_audio.clicked.connect(self.ignorer_audio.emit)
            layout.addWidget(btn_audio)

        btn_suppr = QPushButton(" Supprimer", self)
        btn_suppr.setStyleSheet(_STYLE_DESTRUCTIF)
        btn_suppr.setIcon(icone_svg_teintee(icone_phosphor("trash"), C.DANGER, 15))
        btn_suppr.setIconSize(QSize(15, 15))
        btn_suppr.setToolTip("Supprimer les éléments sélectionnés")
        btn_suppr.clicked.connect(self.supprimer.emit)
        layout.addWidget(btn_suppr)

        btn_x = QPushButton(self)
        btn_x.setStyleSheet(_STYLE_GHOST)
        btn_x.setFixedSize(30, 30)
        btn_x.setIcon(icone_svg_teintee(icone_phosphor("x"), C.INK300, 15))
        btn_x.setIconSize(QSize(15, 15))
        btn_x.setToolTip("Désélectionner")
        btn_x.clicked.connect(self.deselection.emit)
        layout.addWidget(btn_x)

        self.hide()

    def definir_compte(self, n: int) -> None:
        """Affiche la barre (compteur « {n} sélectionnés ») dès n ≥ 2, la cache sinon."""
        if n >= 2:
            self._compteur.setText(
                f"<b style='color:{C.INK900};'>{n}</b> "
                f"<span style='color:{C.INK600};'>sélectionnés</span>")
            self.show()
        else:
            self.hide()
