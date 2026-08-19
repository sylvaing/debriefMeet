"""Générateur d'icône « WaveMark » (refonte design) — carré arrondi + 4 barres.

Motif de marque réutilisé par la toolbar (Étape 4) et le tray (Étape 8). Dessiné
dans un repère logique 100×100 (cf. `icones._ratio_ecran` pour le rendu Retina),
en plein (icône colorée) ou en contour (« template », s'adapte à la barre macOS).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from debrief_meet.ui.icones import _ratio_ecran

_S = 100.0  # repère logique de référence
_RAYON = 0.27 * _S
_LARGEUR_BARRE = 0.088 * _S
_GAP = 0.072 * _S
_EPAISSEUR = 0.06 * _S
_RAYON_BARRE = _LARGEUR_BARRE / 2
_HAUTEURS_BARRES = (0.29 * _S, 0.50 * _S, 0.235 * _S, 0.41 * _S)


def _cadre(filled: bool) -> QRectF:
    marge = 0.0 if filled else _EPAISSEUR / 2
    cote = _S - 2 * marge
    return QRectF(marge, marge, cote, cote)


def _dessiner_barres(painter: QPainter, couleur: QColor) -> None:
    largeur_totale = len(_HAUTEURS_BARRES) * _LARGEUR_BARRE + (len(_HAUTEURS_BARRES) - 1) * _GAP
    x = (_S - largeur_totale) / 2
    for hauteur in _HAUTEURS_BARRES:
        y = (_S - hauteur) / 2
        barre = QPainterPath()
        barre.addRoundedRect(QRectF(x, y, _LARGEUR_BARRE, hauteur), _RAYON_BARRE, _RAYON_BARRE)
        painter.fillPath(barre, couleur)
        x += _LARGEUR_BARRE + _GAP


def _dessiner(painter: QPainter, hex_color: str, filled: bool) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    couleur = QColor(hex_color)
    cadre = QPainterPath()
    cadre.addRoundedRect(_cadre(filled), _RAYON, _RAYON)

    if filled:
        painter.fillPath(cadre, couleur)
        _dessiner_barres(painter, QColor("#FFFFFF"))
    else:
        pen = QPen(couleur, _EPAISSEUR)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(cadre, pen)
        _dessiner_barres(painter, couleur)


def wavemark_icon(size: int, hex_color: str, filled: bool = True,
                  masque: bool | None = None) -> QIcon:
    """Icône WaveMark : carré arrondi plein (`filled`) ou en contour.

    ⚠️ En **plein**, les barres sont peintes en blanc sur le carré coloré : demander
    `filled=True` avec une couleur blanche produit donc un **carré blanc uni**, sans
    la marque (livré par erreur le 2026-08-18 sur la barre GNOME). Une icône
    monochrome claire s'obtient en **contour**, pas en plein.

    `masque` : force `setIsMask`, qui indique à macOS de reteindre l'icône selon sa
    barre de menus. Par défaut il suit `not filled` — le contour EST le template
    macOS. On le force à False pour un contour déjà à la bonne couleur (barre sombre
    Linux), afin que l'intention reste lisible même si le drapeau y est ignoré."""
    ratio = _ratio_ecran()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    echelle = size / _S
    painter.scale(echelle, echelle)
    _dessiner(painter, hex_color, filled)
    painter.end()

    icone = QIcon(pixmap)
    icone.setIsMask((not filled) if masque is None else masque)
    return icone
