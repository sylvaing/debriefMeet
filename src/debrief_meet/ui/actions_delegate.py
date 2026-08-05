"""Délégué de la colonne « actions » (Historique, DESIGN.md §8.6.1) — des
boutons dédiés alignés à droite + **⋯** (ouvre le popover d'actions libellées,
§8.6.3, cf. `actions_menu.py`), identiques sur toutes les lignes d'une vue.

La vue fournit à la volée un `ActionsLigne` via `fournisseur(index)` — il
dépend de l'état du gestionnaire de job (transcription/diarization/CR en
cours), pas seulement du fichier lui-même :

- `boutons` : les boutons dédiés, peints même inactifs (grisés, l'infobulle
  explique pourquoi) pour garder la colonne régulière. Un bouton peut porter
  un `menu_deroulant` : il est alors peint en *split button* — zone principale
  + flèche accolée (caret-down) qui ouvre un popover secondaire (ex. choisir
  le prompt du CR Mistral).
- `menu` : la liste **complète** des actions du popover ⋯ (les actions des
  boutons dédiés y figurent aussi — le menu est exhaustif).

Survol/pressé (CHANGELOG_v2 correctif #7) : le délégué suit la position de la
souris via `editorEvent` (appelé pour les MouseMove tant que
`viewport().setMouseTracking(True)` est actif) et un filtre d'évènements sur le
viewport pour détecter la sortie (`Leave`) — sans ça, le survol resterait figé
sur le dernier bouton visité en quittant la colonne.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPoint, QRectF, QSize
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip

from debrief_meet.ui.fond_ligne import peindre_fond_ligne
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, color

TAILLE_BOUTON = 30
LARGEUR_FLECHE = 16
TAILLE_ICONE = 16
TAILLE_ICONE_FLECHE = 10
ESPACEMENT = 2
MARGE_DROITE = 20  # CHANGELOG_v2 correctif #3 — colonne actions s'arrête à 20px du bord
RAYON_BOUTON = 7
_ICONE_MENU = "dots-three-vertical"
_ICONE_FLECHE = "caret-down"


@dataclass(frozen=True)
class ActionSpec:
    icone: str  # nom logique Phosphor
    tooltip: str
    actif: bool
    on_click: Callable[[], None]
    danger: bool = False           # rouge permanent dans le menu ⋯ (§8.6.3, ex. Tout supprimer)
    separateur_avant: bool = False  # filet avant cet item dans le menu ⋯


@dataclass(frozen=True)
class BoutonSpec:
    """Bouton dédié de la colonne actions. Peint grisé quand `actif=False`
    (l'infobulle reste consultable). `menu_deroulant` en fait un split button :
    une flèche accolée ouvre un popover secondaire avec ces items."""

    icone: str  # nom logique Phosphor
    tooltip: str
    actif: bool
    on_click: Callable[[], None]
    menu_deroulant: list[ActionSpec] | None = None
    tooltip_fleche: str = ""


@dataclass(frozen=True)
class ActionsLigne:
    """Actions d'une ligne : boutons dédiés + contenu (exhaustif) du menu ⋯."""

    boutons: list[BoutonSpec] = field(default_factory=list)
    menu: list[ActionSpec] = field(default_factory=list)

    @property
    def vide(self) -> bool:
        return not self.boutons and not self.menu


def largeur_colonne(nb_boutons: int, nb_fleches: int = 0) -> int:
    """Largeur de colonne pour `nb_boutons` dédiés (dont `nb_fleches` split
    buttons) + le bouton ⋯. La colonne doit être dimensionnée là-dessus, sinon
    les boutons débordent à gauche (chevauchement avec la colonne voisine)."""
    return (MARGE_DROITE + (nb_boutons + 1) * TAILLE_BOUTON
            + nb_fleches * LARGEUR_FLECHE + nb_boutons * ESPACEMENT)


@dataclass(frozen=True)
class _Zone:
    """Zone cliquable d'une ligne (bouton, flèche de split button, ou ⋯)."""

    rect: QRectF
    genre: str  # "bouton" | "fleche" | "menu"
    bouton: BoutonSpec | None = None


class ActionsDelegate(QStyledItemDelegate):
    """Peint les boutons dédiés + ⋯ ; `fournisseur` calcule l'`ActionsLigne`
    par ligne (dépend du fichier ET de l'état des jobs en cours)."""

    def __init__(self, fournisseur: Callable[[QModelIndex], ActionsLigne], parent=None) -> None:
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

    # ── Géométrie ───────────────────────────────────────────────────────────────

    def _zones(self, option: QStyleOptionViewItem, ligne: ActionsLigne) -> list[_Zone]:
        """Zones cliquables, de gauche à droite. Construites depuis le bord droit
        (NB : `option.rect.left() + width()`, pas `.right()` qui est inclusif =
        left+width-1 et décalerait tout d'1px hors de la colonne)."""
        zones: list[_Zone] = []
        x = option.rect.left() + option.rect.width() - MARGE_DROITE
        y = option.rect.top() + (option.rect.height() - TAILLE_BOUTON) / 2
        if ligne.menu:
            x -= TAILLE_BOUTON
            zones.append(_Zone(QRectF(x, y, TAILLE_BOUTON, TAILLE_BOUTON), "menu"))
            x -= ESPACEMENT
        for bouton in reversed(ligne.boutons):
            if bouton.menu_deroulant:
                x -= LARGEUR_FLECHE
                zones.append(_Zone(QRectF(x, y, LARGEUR_FLECHE, TAILLE_BOUTON), "fleche", bouton))
            x -= TAILLE_BOUTON
            zones.append(_Zone(QRectF(x, y, TAILLE_BOUTON, TAILLE_BOUTON), "bouton", bouton))
            x -= ESPACEMENT
        zones.reverse()
        return zones

    @staticmethod
    def _zone_active(zone: _Zone) -> bool:
        return zone.genre == "menu" or (zone.bouton is not None and zone.bouton.actif)

    # ── Peinture ────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        peindre_fond_ligne(painter, option, index)
        ligne = self._fournisseur(index)
        if ligne is None or ligne.vide:
            return
        survole = self._survol_index == index
        pos = self._survol_pos if survole else None

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for num, zone in enumerate(self._zones(option, ligne)):
            self._peindre_zone(painter, zone, pos, num, index)
        painter.restore()

    def _peindre_zone(self, painter: QPainter, zone: _Zone, pos, num: int, index: QModelIndex) -> None:
        actif = self._zone_active(zone)
        hover = actif and pos is not None and zone.rect.toRect().contains(pos)
        presse = hover and self._presse_index == index and self._presse_num == num
        if hover:
            fond = QPainterPath()
            fond.addRoundedRect(zone.rect, RAYON_BOUTON, RAYON_BOUTON)
            painter.fillPath(fond, color("#E9EBEF" if presse else "#FFFFFF"))
        if not actif:
            teinte = C.INK200
        else:
            teinte = C.ACCENT_INK if hover else C.INK300
        if zone.genre == "menu":
            nom, taille = _ICONE_MENU, TAILLE_ICONE
        elif zone.genre == "fleche":
            nom, taille = _ICONE_FLECHE, TAILLE_ICONE_FLECHE
        else:
            nom, taille = zone.bouton.icone, TAILLE_ICONE
        icone = icone_svg_teintee(icone_phosphor(nom), teinte, taille)
        cx = zone.rect.center().x() - taille / 2
        cy = zone.rect.center().y() - taille / 2
        icone.paint(painter, int(cx), int(cy), taille, taille)

    # ── Interaction ─────────────────────────────────────────────────────────────

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        # NB : le survol (MouseMove sans bouton) n'est PAS routé vers editorEvent par
        # Qt — seuls Press/Release/DblClick le sont. Le hover est donc géré dans
        # eventFilter (viewport, mouse tracking actif), comme TableAvecSurvolLigne.
        vue = option.widget
        ligne = self._fournisseur(index)
        if ligne is None or ligne.vide:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        zones = self._zones(option, ligne)
        if event.type() == QEvent.Type.MouseButtonPress:
            for num, zone in enumerate(zones):
                if self._zone_active(zone) and zone.rect.toRect().contains(pos):
                    self._presse_index = QPersistentModelIndex(index)
                    self._presse_num = num
                    if vue is not None:
                        vue.update()
                    break
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._presse_index = QPersistentModelIndex()
            self._presse_num = -1
            for zone in zones:
                if not zone.rect.toRect().contains(pos):
                    continue
                if not self._zone_active(zone):
                    break
                if zone.genre == "menu":
                    self._ouvrir_menu(ligne.menu, zone.rect, vue)
                elif zone.genre == "fleche":
                    self._ouvrir_menu(zone.bouton.menu_deroulant, zone.rect, vue)
                else:
                    zone.bouton.on_click()
                return True
            if vue is not None:
                vue.update()
        return False

    def _ouvrir_menu(self, specs: list[ActionSpec], rect: QRectF, vue) -> None:
        from debrief_meet.ui.actions_menu import construire_menu_actions

        menu = construire_menu_actions(specs, vue)
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
        ligne = self._fournisseur(index)
        if ligne is not None and not ligne.vide:
            for zone in self._zones(option, ligne):
                if not zone.rect.toRect().contains(event.pos()):
                    continue
                if zone.genre == "menu":
                    texte = "Actions"
                elif zone.genre == "fleche":
                    texte = zone.bouton.tooltip_fleche or zone.bouton.tooltip
                else:
                    texte = zone.bouton.tooltip
                QToolTip.showText(event.globalPos(), texte, view)
                return True
        QToolTip.hideText()
        return True

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        ligne = self._fournisseur(index)
        if ligne is None or ligne.vide:
            return QSize(largeur_colonne(0), TAILLE_BOUTON + 16)
        nb_fleches = sum(1 for b in ligne.boutons if b.menu_deroulant)
        return QSize(largeur_colonne(len(ligne.boutons), nb_fleches), TAILLE_BOUTON + 16)
