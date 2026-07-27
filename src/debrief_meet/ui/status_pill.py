"""Badge d'état (pilule) — Historique (refonte design).

Rendu par délégué (`StatusPillDelegate`), pas par widget : plus léger dans un
tableau et cohérent avec la barre d'accent de ligne (Étape 5).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate

from debrief_meet.ui.fond_ligne import peindre_fond_ligne
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, SANS, color

# Rendu pilule (cf. IMPLEMENTATION_SPEC.md §3b)
_RAYON_PILULE = 20
_PADDING = (3, 9, 3, 7)  # haut, droite, bas, gauche
_GAP = 6
_TAILLE_ICONE = 13
_TAILLE_TEXTE = 12


class HistoryState(Enum):
    EN_COURS = auto()
    TRANSCRIT = auto()
    AUDIO_SEUL = auto()
    LOCUTEURS = auto()
    CR_DISPONIBLE = auto()


@dataclass(frozen=True)
class Badge:
    label: str
    fg: str
    bg: str
    icone: str  # nom logique Phosphor


_BADGES: dict[HistoryState, Badge] = {
    HistoryState.EN_COURS: Badge("En cours", C.REC, C.REC_BG, "record-fill"),
    HistoryState.TRANSCRIT: Badge("Transcrit", C.SUCCESS, C.SUCCESS_BG, "check-circle"),
    HistoryState.AUDIO_SEUL: Badge("Audio seul", C.NEUTRAL, C.NEUTRAL_BG, "waveform"),
    HistoryState.LOCUTEURS: Badge("Locuteurs", C.INFO, C.INFO_BG, "users-three"),
    HistoryState.CR_DISPONIBLE: Badge("CR disponible", C.SUCCESS, C.SUCCESS_BG, "notebook"),
}


def badge_pour_etat(etat: HistoryState) -> Badge:
    return _BADGES[etat]


class StatusPillDelegate(QStyledItemDelegate):
    """Peint une pilule à partir d'un `HistoryState` stocké en `Qt.ItemDataRole.UserRole`."""

    def paint(self, painter: QPainter, option, index) -> None:
        etat = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(etat, HistoryState):
            super().paint(painter, option, index)
            return

        badge = badge_pour_etat(etat)
        haut, droite, bas, gauche = _PADDING
        font = QFont(SANS, _TAILLE_TEXTE)
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        largeur_texte = metrics.horizontalAdvance(badge.label)
        largeur = gauche + _TAILLE_ICONE + _GAP + largeur_texte + droite
        hauteur = haut + _TAILLE_ICONE + bas

        rect = option.rect
        x = rect.left() + (rect.width() - largeur) / 2
        y = rect.top() + (rect.height() - hauteur) / 2

        peindre_fond_ligne(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fond = QPainterPath()
        fond.addRoundedRect(QRectF(x, y, largeur, hauteur), _RAYON_PILULE, _RAYON_PILULE)
        painter.fillPath(fond, color(badge.bg))

        icone = icone_svg_teintee(icone_phosphor(badge.icone), badge.fg, taille=_TAILLE_ICONE)
        icone.paint(painter, int(x + gauche), int(y + haut), _TAILLE_ICONE, _TAILLE_ICONE)

        painter.setFont(font)
        painter.setPen(color(badge.fg))
        texte_x = x + gauche + _TAILLE_ICONE + _GAP
        painter.drawText(
            QRectF(texte_x, y, largeur_texte, hauteur), Qt.AlignmentFlag.AlignVCenter, badge.label
        )

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        etat = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(etat, HistoryState):
            return super().sizeHint(option, index)
        badge = badge_pour_etat(etat)
        haut, droite, bas, gauche = _PADDING
        metrics = QFontMetrics(QFont(SANS, _TAILLE_TEXTE))
        largeur_texte = metrics.horizontalAdvance(badge.label)
        largeur = gauche + _TAILLE_ICONE + _GAP + largeur_texte + droite
        hauteur = haut + _TAILLE_ICONE + bas
        return QSize(int(largeur), int(hauteur))
