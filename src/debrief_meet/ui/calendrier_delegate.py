"""Délégué de la colonne « lien calendrier » (interco BlueMind, DESIGN.md
§8.6.2) — icône 28×28 alignée à droite, alignement constant quelle que soit la
longueur du titre. Trois états : associé (vert, passif) / associable (accent,
cliquable) / vide (aucune correspondance ou BlueMind non configuré).

Même architecture que `ActionsDelegate` : le fournisseur (`ReunionView.
_calendrier_pour_index`) calcule l'état par ligne (accès à `core/bluemind`),
le délégué ne fait que peindre + gérer le clic/tooltip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QRectF, QSize
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip

from debrief_meet.ui.fond_ligne import peindre_fond_ligne
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, color

TAILLE = 28
TAILLE_ICONE = 17
RAYON = 7
# Recule l'icône du bord droit pour égaliser l'écart « icône calendrier ↔ bouton
# Copier » avec l'écart « Copier ↔ ⋯ » de la colonne actions voisine (§8.6.2).
MARGE_DROITE = 3


@dataclass(frozen=True)
class CalendrierSpec:
    icone: str | None  # None → colonne vide (§8.6.2 « aucune correspondance »)
    couleur: str
    tooltip: str
    cliquable: bool
    on_click: Callable[[], None] | None = None


class CalendrierColonneDelegate(QStyledItemDelegate):
    def __init__(
        self, fournisseur: Callable[[QModelIndex], CalendrierSpec | None], parent=None,
    ) -> None:
        super().__init__(parent)
        self._fournisseur = fournisseur
        self._table = parent
        self._survol_index = QPersistentModelIndex()
        self._survol_pos = None
        if parent is not None:
            parent.viewport().setMouseTracking(True)
            parent.viewport().installEventFilter(self)

    def _rect(self, option: QStyleOptionViewItem) -> QRectF:
        bord_droit = option.rect.left() + option.rect.width()  # cf. ActionsDelegate : .right() est inclusif
        x = bord_droit - TAILLE - MARGE_DROITE
        y = option.rect.top() + (option.rect.height() - TAILLE) / 2
        return QRectF(x, y, TAILLE, TAILLE)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        peindre_fond_ligne(painter, option, index)
        spec = self._fournisseur(index)
        if spec is None or spec.icone is None:
            return
        rect = self._rect(option)
        hover = (spec.cliquable and self._survol_index == index
                 and self._survol_pos is not None and rect.toRect().contains(self._survol_pos))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hover:
            fond = QPainterPath()
            fond.addRoundedRect(rect, RAYON, RAYON)
            painter.fillPath(fond, color(C.ACCENT_SOFT))
        icone = icone_svg_teintee(icone_phosphor(spec.icone), spec.couleur, TAILLE_ICONE)
        cx = rect.center().x() - TAILLE_ICONE / 2
        cy = rect.center().y() - TAILLE_ICONE / 2
        icone.paint(painter, int(cx), int(cy), TAILLE_ICONE, TAILLE_ICONE)
        painter.restore()

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        spec = self._fournisseur(index)
        if spec is None or not spec.cliquable or spec.on_click is None:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._rect(option).toRect().contains(pos):
            spec.on_click()
            return True
        return False

    def eventFilter(self, obj, event) -> bool:
        # Survol (fond accent-soft sur l'état « associable ») — même mécanisme que
        # ActionsDelegate : MouseMove capté sur le viewport (mouse tracking actif).
        if event.type() == QEvent.Type.MouseMove and self._table is not None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            index = self._table.indexAt(pos)
            gere = (index.isValid()
                    and self._table.itemDelegateForColumn(index.column()) is self)
            if gere:
                if self._survol_index != index or self._survol_pos != pos:
                    self._survol_index = QPersistentModelIndex(index)
                    self._survol_pos = pos
                    self._table.viewport().update()
            elif self._survol_index.isValid():
                self._survol_index = QPersistentModelIndex()
                self._survol_pos = None
                self._table.viewport().update()
        elif event.type() == QEvent.Type.Leave and self._survol_index.isValid():
            self._survol_index = QPersistentModelIndex()
            self._survol_pos = None
            obj.update()
        return super().eventFilter(obj, event)

    def helpEvent(self, event, view, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return super().helpEvent(event, view, option, index)
        spec = self._fournisseur(index)
        if spec is not None and spec.tooltip:
            QToolTip.showText(event.globalPos(), spec.tooltip, view)
            return True
        QToolTip.hideText()
        return True

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(TAILLE + 6, TAILLE + 16)
