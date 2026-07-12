"""Délégué de la colonne « actions » (Historique, DESIGN.md §8.6.1) — deux
emplacements fixes alignés à droite, identiques sur toutes les lignes :
**Copier** (bouton dédié) + **⋯** (ouvre le popover d'actions libellées,
§8.6.3, cf. `actions_menu.py`). Remplace l'ancienne rangée d'icônes à nombre
variable, qui rendait la colonne irrégulière et illisible.

La liste des actions (icône, tooltip, actif, callback) est toujours fournie à
la volée par la vue via `fournisseur(index)` — elle dépend de l'état du
gestionnaire de job (transcription/diarization en cours), pas seulement du
fichier lui-même. `specs[0]` est toujours l'action Copier (peinte en bouton
dédié, masquée mais l'emplacement reste réservé si `actif=False`) ; `specs[1:]`
alimentent le menu ⋯.

Survol/pressé (CHANGELOG_v2 correctif #7) : le délégué suit la position de la
souris via `editorEvent` (appelé pour les MouseMove tant que
`viewport().setMouseTracking(True)` est actif) et un filtre d'évènements sur le
viewport pour détecter la sortie (`Leave`) — sans ça, le survol resterait figé
sur le dernier bouton visité en quittant la colonne.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRectF, QSize
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip

from debrief_meet.ui.fond_ligne import peindre_fond_ligne
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, color

TAILLE_BOUTON = 30
TAILLE_ICONE = 16
ESPACEMENT = 2
MARGE_DROITE = 20  # CHANGELOG_v2 correctif #3 — colonne actions s'arrête à 20px du bord
RAYON_BOUTON = 7
_ICONE_MENU = "dots-three-vertical"

_NUM_COPIER = 0
_NUM_MENU = 1


@dataclass(frozen=True)
class ActionSpec:
    icone: str  # nom logique Phosphor
    tooltip: str
    actif: bool
    on_click: Callable[[], None]
    danger: bool = False           # rouge permanent dans le menu ⋯ (§8.6.3, ex. Tout supprimer)
    separateur_avant: bool = False  # filet avant cet item dans le menu ⋯


class ActionsDelegate(QStyledItemDelegate):
    """Peint 2 boutons fixes (Copier + ⋯) ; `fournisseur` calcule la liste
    complète par ligne (dépend du fichier ET de l'état du job en cours) — seul
    `specs[0]` (Copier) est peint directement, `specs[1:]` alimentent le menu."""

    def __init__(self, fournisseur: Callable[[QModelIndex], list[ActionSpec]], parent=None) -> None:
        super().__init__(parent)
        self._fournisseur = fournisseur
        self._table = parent
        self._survol_index = QPersistentModelIndex()
        self._survol_pos = None
        self._presse_index = QPersistentModelIndex()
        self._presse_num = -1
        if parent is not None:
            parent.viewport().setMouseTracking(True)
            parent.viewport().installEventFilter(self)

    def _rect_copier(self, option: QStyleOptionViewItem) -> QRectF:
        # NB : `option.rect.left() + width()`, pas `.right()` (inclusif = left+width-1,
        # qui décalerait les boutons d'1px et les ferait déborder de la colonne).
        bord_droit = option.rect.left() + option.rect.width()
        x = bord_droit - MARGE_DROITE - 2 * TAILLE_BOUTON - ESPACEMENT
        y = option.rect.top() + (option.rect.height() - TAILLE_BOUTON) / 2
        return QRectF(x, y, TAILLE_BOUTON, TAILLE_BOUTON)

    def _rect_menu(self, option: QStyleOptionViewItem) -> QRectF:
        bord_droit = option.rect.left() + option.rect.width()
        x = bord_droit - MARGE_DROITE - TAILLE_BOUTON
        y = option.rect.top() + (option.rect.height() - TAILLE_BOUTON) / 2
        return QRectF(x, y, TAILLE_BOUTON, TAILLE_BOUTON)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        peindre_fond_ligne(painter, option, index)
        specs = self._fournisseur(index)
        if not specs:
            return
        survole = self._survol_index == index
        pos = self._survol_pos if survole else None

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if specs[0].actif:
            self._peindre_bouton(painter, self._rect_copier(option), specs[0].icone, pos, _NUM_COPIER, index)
        if len(specs) > 1:
            self._peindre_bouton(painter, self._rect_menu(option), _ICONE_MENU, pos, _NUM_MENU, index)
        painter.restore()

    def _peindre_bouton(self, painter: QPainter, rect: QRectF, icone_nom: str, pos, num: int, index: QModelIndex) -> None:
        hover = pos is not None and rect.toRect().contains(pos)
        presse = hover and self._presse_index == index and self._presse_num == num
        if hover:
            fond = QPainterPath()
            fond.addRoundedRect(rect, RAYON_BOUTON, RAYON_BOUTON)
            painter.fillPath(fond, color("#E9EBEF" if presse else "#FFFFFF"))
        teinte = C.ACCENT_INK if hover else C.INK300
        icone = icone_svg_teintee(icone_phosphor(icone_nom), teinte, TAILLE_ICONE)
        cx = rect.center().x() - TAILLE_ICONE / 2
        cy = rect.center().y() - TAILLE_ICONE / 2
        icone.paint(painter, int(cx), int(cy), TAILLE_ICONE, TAILLE_ICONE)

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        # NB : le survol (MouseMove sans bouton) n'est PAS routé vers editorEvent par
        # Qt — seuls Press/Release/DblClick le sont. Le hover est donc géré dans
        # eventFilter (viewport, mouse tracking actif), comme TableAvecSurvolLigne.
        vue = option.widget
        specs = self._fournisseur(index)
        if not specs:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.type() == QEvent.Type.MouseButtonPress:
            if specs[0].actif and self._rect_copier(option).toRect().contains(pos):
                self._presse_index = QPersistentModelIndex(index)
                self._presse_num = _NUM_COPIER
                if vue is not None:
                    vue.update()
            elif len(specs) > 1 and self._rect_menu(option).toRect().contains(pos):
                self._presse_index = QPersistentModelIndex(index)
                self._presse_num = _NUM_MENU
                if vue is not None:
                    vue.update()
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._presse_index = QPersistentModelIndex()
            self._presse_num = -1
            if specs[0].actif and self._rect_copier(option).toRect().contains(pos):
                specs[0].on_click()
                return True
            if len(specs) > 1 and self._rect_menu(option).toRect().contains(pos):
                self._ouvrir_menu(specs[1:], option, vue)
                return True
            if vue is not None:
                vue.update()
        return False

    def _ouvrir_menu(self, specs: list[ActionSpec], option: QStyleOptionViewItem, vue) -> None:
        from debrief_meet.ui.actions_menu import construire_menu_actions

        menu = construire_menu_actions(specs, vue)
        rect = self._rect_menu(option)
        point_bas = QPoint(int(rect.left()), int(rect.bottom()))
        point_global = vue.viewport().mapToGlobal(point_bas) if vue is not None else point_bas
        menu.popup(point_global)  # Qt replie déjà le popup vers le haut s'il dépasse l'écran

    def eventFilter(self, obj, event) -> bool:
        # Le viewport a le mouse tracking actif → on reçoit les MouseMove sans bouton
        # pressé ici (là où editorEvent ne les voit pas). On ne réagit qu'aux lignes
        # dont CETTE colonne est bien gérée par ce délégué.
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
        specs = self._fournisseur(index)
        if specs:
            if specs[0].actif and self._rect_copier(option).toRect().contains(event.pos()):
                QToolTip.showText(event.globalPos(), specs[0].tooltip, view)
                return True
            if len(specs) > 1 and self._rect_menu(option).toRect().contains(event.pos()):
                QToolTip.showText(event.globalPos(), "Actions", view)
                return True
        QToolTip.hideText()
        return True

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        largeur = MARGE_DROITE + 2 * TAILLE_BOUTON + ESPACEMENT
        return QSize(largeur, TAILLE_BOUTON + 16)
