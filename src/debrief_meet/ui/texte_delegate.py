"""Délégué par défaut des colonnes texte des tableaux d'historique (titre,
date, durée, fichier, note) — peint le fond de ligne uniforme (§ CHANGELOG_v2
« survol des lignes ») puis laisse Qt dessiner le texte, police/couleur lues
depuis `Qt.FontRole`/`Qt.ForegroundRole` (posées par `CaptureModel.data()`).
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from debrief_meet.ui.fond_ligne import peindre_fond_ligne


class TexteLigneDelegate(QStyledItemDelegate):
    """Délégué par défaut d'une table (`setItemDelegate`) : les colonnes dotées
    d'un délégué dédié (icône, pilule, actions) restent prioritaires."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        option = QStyleOptionViewItem(option)
        peindre_fond_ligne(painter, option, index)
        option.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        super().paint(painter, option, index)
