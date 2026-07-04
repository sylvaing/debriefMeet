"""Segmented control (ex : Réunions | Journal) — refonte design."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton

from debrief_meet.ui.theme import C, M


class SegmentedControl(QFrame):
    """Groupe de boutons exclusifs ; le segment actif a un fond plein (`Accent`)."""

    changed = Signal(int)  # index du segment actif

    def __init__(self, options: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setStyleSheet(f"""
            QFrame#segmented {{ border: 1px solid {C.BORDER}; border-radius: {M.R_BUTTON}px;
                background: {C.SURFACE}; }}
            QFrame#segmented QPushButton {{ border: none; border-radius: 0; background: transparent;
                color: {C.INK700}; font-size: 13.5px; font-weight: 600; padding: 6px 14px; }}
            QFrame#segmented QPushButton:checked {{ background: {C.ACCENT}; color: #FFFFFF; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._groupe = QButtonGroup(self)
        self._groupe.setExclusive(True)
        self._boutons: list[QPushButton] = []
        for i, label in enumerate(options):
            bouton = QPushButton(label)
            bouton.setCheckable(True)
            layout.addWidget(bouton)
            self._groupe.addButton(bouton, i)
            self._boutons.append(bouton)
        if self._boutons:
            self._boutons[0].setChecked(True)
        self._groupe.idClicked.connect(self.changed.emit)

    def index_actif(self) -> int:
        return self._groupe.checkedId()

    def definir_index(self, index: int) -> None:
        """Change le segment actif — émet `changed` même hors clic utilisateur
        (`QButtonGroup.idClicked` ne se déclenche que sur clic réel)."""
        if 0 <= index < len(self._boutons) and index != self.index_actif():
            self._boutons[index].setChecked(True)
            self.changed.emit(index)
