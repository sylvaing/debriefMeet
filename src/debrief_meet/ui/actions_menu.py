"""Popover de menu d'actions (⋯) — DESIGN.md §8.6.3. Chaque item est un
`QWidgetAction` avec un widget custom (icône + libellé), sur le même principe
que `_LigneQuitter` (tray.py) : un `QAction` standard ne permet pas de fixer
une couleur de texte/icône statique par item (item destructif en rouge
permanent, item indisponible grisé) ni un survol qui recolore icône+texte
ensemble (fond accent-soft + texte/icône accent-ink)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget, QWidgetAction

from debrief_meet.ui.actions_delegate import ActionSpec
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, SANS

_TAILLE_ICONE = 16
_LARGEUR_MIN = 238
# Marges de la ligne (contentsMargins 10 g/d + spacing 11 + icône 16) + padding/bordure
# du menu (5×2 + 1×2) — largeur d'un item = _CHROME_LIGNE + largeur du texte.
_CHROME_LIGNE = 10 + _TAILLE_ICONE + 11 + 10 + 12


class _LigneMenuAction(QWidget):
    cliquee = Signal()

    def __init__(self, spec: ActionSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if spec.actif else Qt.CursorShape.ArrowCursor)

        if not spec.actif:
            self._couleur_texte = C.INK200
            self._couleur_icone = C.INK200
        elif spec.danger:
            self._couleur_texte = C.DANGER
            self._couleur_icone = C.DANGER
        else:
            self._couleur_texte = C.INK900
            self._couleur_icone = C.INK300
        self._fond_survol = "#FEF3F2" if spec.danger else C.ACCENT_SOFT
        self._couleur_survol = C.DANGER if spec.danger else C.ACCENT_INK

        self.setObjectName("ligneMenuAction")
        self.setStyleSheet("QWidget#ligneMenuAction { background: transparent; border-radius: 7px; }")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(11)
        self._pix_repos = icone_svg_teintee(
            icone_phosphor(spec.icone), self._couleur_icone, _TAILLE_ICONE
        ).pixmap(_TAILLE_ICONE, _TAILLE_ICONE)
        self._icone = QLabel(self)
        self._icone.setPixmap(self._pix_repos)
        lay.addWidget(self._icone)
        self._label = QLabel(spec.tooltip, self)
        self._label.setStyleSheet(f"color: {self._couleur_texte}; font-size: 13px; font-weight: 500;")
        lay.addWidget(self._label)
        lay.addStretch()

        if spec.actif:
            self._pix_survol = icone_svg_teintee(
                icone_phosphor(spec.icone), self._couleur_survol, _TAILLE_ICONE
            ).pixmap(_TAILLE_ICONE, _TAILLE_ICONE)

    def enterEvent(self, event) -> None:  # noqa: N802 — override Qt
        if self._spec.actif:
            self.setStyleSheet(
                f"QWidget#ligneMenuAction {{ background: {self._fond_survol}; border-radius: 7px; }}")
            self._icone.setPixmap(self._pix_survol)
            self._label.setStyleSheet(f"color: {self._couleur_survol}; font-size: 13px; font-weight: 500;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — override Qt
        self.setStyleSheet("QWidget#ligneMenuAction { background: transparent; border-radius: 7px; }")
        self._icone.setPixmap(self._pix_repos)
        self._label.setStyleSheet(f"color: {self._couleur_texte}; font-size: 13px; font-weight: 500;")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — override Qt
        if self._spec.actif and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.cliquee.emit()
        super().mouseReleaseEvent(event)


def construire_menu_actions(specs: list[ActionSpec], parent: QWidget | None = None) -> QMenu:
    """Construit le popover pour `specs` (déjà privées de l'action Copier, portée
    par le bouton dédié — cf. `ActionsDelegate`). `spec.separateur_avant` insère
    un filet avant l'item ; `spec.danger` le rend rouge (Tout supprimer)."""
    menu = QMenu(parent)
    menu.setObjectName("actionsMenu")
    # Largeur = max(238, plus long libellé) pour ne jamais tronquer un item
    # (ex. « Supprimer l'audio (garde le débrief) », plus long que 238 px).
    police = QFont(SANS)
    police.setPixelSize(13)
    police.setWeight(QFont.Weight.Medium)
    metriques = QFontMetrics(police)
    largeur_texte = max((metriques.horizontalAdvance(s.tooltip) for s in specs), default=0)
    menu.setFixedWidth(max(_LARGEUR_MIN, _CHROME_LIGNE + largeur_texte))
    for spec in specs:
        if spec.separateur_avant:
            menu.addSeparator()
        ligne = _LigneMenuAction(spec, parent=menu)
        action = QWidgetAction(menu)
        action.setDefaultWidget(ligne)
        menu.addAction(action)
        if spec.actif:
            ligne.cliquee.connect(menu.close)
            ligne.cliquee.connect(spec.on_click)
    return menu
