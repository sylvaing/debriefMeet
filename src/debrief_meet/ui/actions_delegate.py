"""Délégué de la colonne « actions » (Historique, refonte design).

La liste des actions (icône, tooltip, actif, callback) est fournie à la volée par
la vue via `fournisseur(index)` — elle dépend de l'état du gestionnaire de job
(transcription/diarization en cours), pas seulement du fichier lui-même.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QModelIndex, QRectF, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip

from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C

TAILLE_BOUTON = 30
TAILLE_ICONE = 16
ESPACEMENT = 2
MARGE_DROITE = 8


@dataclass(frozen=True)
class ActionSpec:
    icone: str  # nom logique Phosphor
    tooltip: str
    actif: bool
    on_click: Callable[[], None]


class ActionsDelegate(QStyledItemDelegate):
    """Peint des boutons icône alignés à droite ; `fournisseur` calcule la liste
    par ligne (dépend du fichier ET de l'état du job en cours)."""

    def __init__(self, fournisseur: Callable[[QModelIndex], list[ActionSpec]], parent=None) -> None:
        super().__init__(parent)
        self._fournisseur = fournisseur

    def _rects(self, option: QStyleOptionViewItem, specs: list[ActionSpec]) -> list[QRectF]:
        n = len(specs)
        if n == 0:
            return []
        largeur_totale = n * TAILLE_BOUTON + (n - 1) * ESPACEMENT
        x = option.rect.right() - largeur_totale - MARGE_DROITE
        y = option.rect.top() + (option.rect.height() - TAILLE_BOUTON) / 2
        rects = []
        for _ in specs:
            rects.append(QRectF(x, y, TAILLE_BOUTON, TAILLE_BOUTON))
            x += TAILLE_BOUTON + ESPACEMENT
        return rects

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        specs = self._fournisseur(index)
        rects = self._rects(option, specs)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for spec, rect in zip(specs, rects):
            teinte = C.INK300 if spec.actif else C.BORDER_SOFT
            icone = icone_svg_teintee(icone_phosphor(spec.icone), teinte, TAILLE_ICONE)
            cx = rect.center().x() - TAILLE_ICONE / 2
            cy = rect.center().y() - TAILLE_ICONE / 2
            icone.paint(painter, int(cx), int(cy), TAILLE_ICONE, TAILLE_ICONE)
        painter.restore()

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        specs = self._fournisseur(index)
        rects = self._rects(option, specs)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        for spec, rect in zip(specs, rects):
            if spec.actif and rect.toRect().contains(pos):
                spec.on_click()
                return True
        return False

    def helpEvent(self, event, view, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return super().helpEvent(event, view, option, index)
        specs = self._fournisseur(index)
        rects = self._rects(option, specs)
        for spec, rect in zip(specs, rects):
            if rect.toRect().contains(event.pos()):
                QToolTip.showText(event.globalPos(), spec.tooltip, view)
                return True
        QToolTip.hideText()
        return True

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        specs = self._fournisseur(index)
        n = len(specs)
        if n == 0:
            return QSize(0, TAILLE_BOUTON + 16)
        largeur = n * TAILLE_BOUTON + (n - 1) * ESPACEMENT + MARGE_DROITE
        return QSize(largeur, TAILLE_BOUTON + 16)
