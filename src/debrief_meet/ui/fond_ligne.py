"""Fond de ligne partagé des délégués de tableau (sélection > survol > rien).

Chaque délégué de colonne (icône, texte, pilule d'état, actions) peint son
propre fond plutôt que de compter sur le rendu Qt natif — nécessaire pour un
survol qui couvre la ligne entière (`TableAvecSurvolLigne.ligne_survolee`) et
pas seulement la cellule sous le curseur (cf. `survol_ligne.py`).
"""
from __future__ import annotations

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from debrief_meet.ui.theme import C, color


def peindre_fond_ligne(painter: QPainter, option: QStyleOptionViewItem, index) -> bool:
    """Peint le fond de la cellule selon l'état de sa ligne ; renvoie `True` si sélectionnée."""
    if option.state & QStyle.StateFlag.State_Selected:
        painter.fillRect(option.rect, color(C.ACCENT_SOFT))
        return True
    table = option.widget
    if table is not None and index.row() == getattr(table, "ligne_survolee", None):
        painter.fillRect(option.rect, color(C.HOVER))
    return False
