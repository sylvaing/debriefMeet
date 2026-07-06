"""Délégué de la colonne « icône de type » (Réunion/Journal) — partagé entre
les deux tableaux : rendu de l'icône décalée du bord (CHANGELOG_v2 correctif
#3) + barre d'accent 3px si la ligne est sélectionnée.

L'icône est peinte manuellement (décalée de `INSET_GAUCHE`) plutôt que par le
rendu par défaut de `DecorationRole` (toujours plaqué contre le bord gauche de
la cellule) — `initStyleOption` vide `option.icon` pour empêcher le double
rendu tout en laissant `super().paint()` peindre le fond de sélection/survol
sur la cellule entière. `paint()` relit l'icône directement via `index.data()`
plutôt que de conserver `option.icon` : ce dernier est un objet transitoire du
style, invalidé côté C++ dès la fin de l'appel — le garder en instance fait
planter (« Internal C++ object already deleted »).
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from debrief_meet.ui.theme import C, color

INSET_GAUCHE = 20  # CHANGELOG_v2 correctif #3 — colonne icône démarre à 20px du bord
TAILLE_ICONE = 16
LARGEUR_ACCENT = 3


class IconeColonneDelegate(QStyledItemDelegate):
    """Colonne 0 (icône de type) : icône inset de 20px + barre d'accent si sélectionnée."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.icon = QIcon()  # peinte manuellement dans paint(), décalée

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().paint(painter, option, index)
        icone = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icone, QIcon) and not icone.isNull():
            x = option.rect.left() + INSET_GAUCHE
            y = option.rect.top() + (option.rect.height() - TAILLE_ICONE) / 2
            icone.paint(painter, int(x), int(y), TAILLE_ICONE, TAILLE_ICONE)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            rect = QRectF(option.rect.left(), option.rect.top(), LARGEUR_ACCENT, option.rect.height())
            painter.fillRect(rect, color(C.ACCENT))
            painter.restore()
