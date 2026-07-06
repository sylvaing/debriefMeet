"""Table d'historique qui suit la ligne survolée par la souris.

Qt ne suit nativement le survol qu'au niveau de la cellule exacte sous le
curseur (`option.state & State_MouseOver` n'est vrai que pour cet unique
index) : hériter de `QTableView` et suivre ici la ligne entière permet aux
délégués de colonne de peindre un fond uniforme sur toute la ligne au survol
(CHANGELOG_v2 §1, « survol des lignes d'historique » — pas de mouse over
visible sur le build précédent).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QTableView


class TableAvecSurvolLigne(QTableView):
    """`QTableView` exposant `ligne_survolee` (int | None), tenue à jour via un
    filtre d'évènements sur le viewport (MouseMove / Leave)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ligne_survolee: int | None = None
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                row = self.indexAt(pos).row()
                nouvelle = row if row >= 0 else None
                if nouvelle != self.ligne_survolee:
                    self.ligne_survolee = nouvelle
                    self.viewport().update()
            elif event.type() == QEvent.Type.Leave:
                if self.ligne_survolee is not None:
                    self.ligne_survolee = None
                    self.viewport().update()
        return super().eventFilter(obj, event)
