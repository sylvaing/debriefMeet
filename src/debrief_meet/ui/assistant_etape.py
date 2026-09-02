"""Pièces communes aux assistants guidés (diarization docs/13, Mistral docs/42 §9.4).

Les deux assistants ont la même anatomie d'étape : une maquette SVG de l'écran visé,
un titre, un paragraphe, et — pour les étapes qui envoient l'utilisateur sur un site
tiers — un bouton qui ouvre le navigateur. Ce module tient cette anatomie une seule
fois ; il vivait dans `assistant_diarization.py`, donc l'assistant Mistral ne pouvait
pas s'en servir sans duplication (et est resté sans illustration jusqu'ici).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C

DOSSIER_ASSETS = Path(__file__).parent / "assets"

#: Largeur de rendu des maquettes. Tient dans une carte de 520 px
#: (`CarteFlottante` retire 22 px de marge de chaque côté).
LARGEUR_ILLUSTRATION = 460

_TAILLE_ICONE_LIEN = 15


def pixmap_svg(chemin: Path, largeur: int = LARGEUR_ILLUSTRATION, dpr: int = 2) -> QPixmap:
    """Rend un SVG d'asset en QPixmap à `largeur` (ratio préservé, net en Retina via dpr)."""
    from PySide6.QtSvg import QSvgRenderer

    rendu = QSvgRenderer(str(chemin))
    taille = rendu.defaultSize()
    if not taille.isValid() or taille.width() <= 0:
        return QPixmap()
    hauteur = round(largeur * taille.height() / taille.width())
    image = QImage(largeur * dpr, hauteur * dpr, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    peintre = QPainter(image)
    peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
    rendu.render(peintre)
    peintre.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def illustration(fichier: str, largeur: int = LARGEUR_ILLUSTRATION) -> QLabel:
    """Illustration de l'étape (SVG d'asset). Repli discret si l'asset manque."""
    lab = QLabel()
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chemin = DOSSIER_ASSETS / fichier
    pixmap = pixmap_svg(chemin, largeur) if chemin.exists() else QPixmap()
    if pixmap.isNull():
        lab.setText("(illustration indisponible)")
        lab.setStyleSheet("color:gray;")
    else:
        lab.setPixmap(pixmap)
    return lab


def titre_etape(texte: str) -> QLabel:
    lab = QLabel(texte)
    lab.setStyleSheet("font-weight:bold;font-size:15px;")
    return lab


def bouton_lien(libelle: str, url: str) -> QPushButton:
    """Bouton qui ouvre `url` dans le navigateur.

    `objectName` obligatoire : la feuille de style ne donne fond et bordure qu'aux
    boutons nommés (`theme.qss`), un bouton anonyme se peignait donc en gras noir sur
    blanc — indiscernable d'un paragraphe, et les deux assistants n'offraient aucune
    autre affordance de clic. L'icône « sortir du cadre » dit en plus ce que fait le
    clic (quitter l'app pour le navigateur), ce qu'aucune couleur ne porte ; le bleu
    reste réservé à « Suivant », seule sortie de l'étape.
    """
    btn = QPushButton(libelle)
    btn.setObjectName("secondary")
    chemin = icone_phosphor("arrow-square-out")
    icone = QIcon(icone_svg_teintee(chemin, C.INK700, _TAILLE_ICONE_LIEN).pixmap(
        _TAILLE_ICONE_LIEN, _TAILLE_ICONE_LIEN))
    # Le style natif passe l'icône en mode `Active` au focus clavier, où la feuille de
    # style recolore aussi le texte : sans ce pixmap, l'icône y resterait grise.
    icone.addPixmap(
        icone_svg_teintee(chemin, C.ACCENT_INK, _TAILLE_ICONE_LIEN).pixmap(
            _TAILLE_ICONE_LIEN, _TAILLE_ICONE_LIEN),
        QIcon.Mode.Active, QIcon.State.Off)
    btn.setIcon(icone)
    btn.setIconSize(QSize(_TAILLE_ICONE_LIEN, _TAILLE_ICONE_LIEN))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
    return btn


def page_etape(fichier: str, titre: str, texte: str, url: str,
               libelle_lien: str) -> QWidget:
    """Étape « va sur ce site » : maquette, titre, explication, bouton d'ouverture."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.addWidget(illustration(fichier))
    lay.addWidget(titre_etape(titre))
    corps = QLabel(texte)
    corps.setWordWrap(True)
    lay.addWidget(corps)
    lay.addWidget(bouton_lien(libelle_lien, url), alignment=Qt.AlignmentFlag.AlignLeft)
    lay.addStretch()
    return w
