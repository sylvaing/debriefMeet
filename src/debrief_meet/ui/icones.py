"""Icône de tray : carré arrondi (bulle) + onde vocale.

La forme est constante ; la COULEUR encode l'état d'activité (cf. EtatVisuel) :
  - REPOS          → carré en contour, monochrome template (s'adapte à la barre macOS)
  - ENREGISTREMENT → carré plein rouge, ondes en réserve (blanches)
  - TRANSCRIPTION  → carré plein orange
  - TERMINE        → carré plein vert (bref)
  - ERREUR         → carré plein gris (bref)

Dessin programmatique (aucun asset requis), dans un repère logique 100×100.
L'artwork remplit presque tout le cadre (marge minimale) pour que l'icône occupe
la même hauteur que les autres icônes de la barre de menu. Rendu en haute
résolution (devicePixelRatio) pour rester net en Retina.

L'icône d'**application** (Dock/Finder, .icns) reprend le même motif en version
colorée avec un carré bleu de fond (cf. dessiner_icone_app / _SVG_ICONE_APP).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)

from debrief_meet.core.modes import EtatVisuel

# Couleurs système (palette Apple). REPOS n'a pas de couleur : rendu en template.
_COULEURS: dict[EtatVisuel, str] = {
    EtatVisuel.ENREGISTREMENT: "#FF3B30",  # rouge
    EtatVisuel.TRANSCRIPTION:  "#FF9500",  # orange
    EtatVisuel.TERMINE:        "#34C759",  # vert
    EtatVisuel.ERREUR:         "#8E8E93",  # gris (placeholder, ajustable)
}

# Couleur de l'icône d'application (Dock / barre des tâches) : bleu identité messagerie.
_COULEUR_APP = "#0A84FF"

# Barres de l'onde vocale en repère 100×100 : (x, y_haut, y_bas). Centrées (x,y) sur 50.
_BARRES = [
    (21, 38, 62),
    (35, 30, 70),
    (50, 24, 76),
    (65, 32, 68),
    (79, 36, 64),
]


def _ratio_ecran() -> float:
    app = QGuiApplication.instance()
    if app is not None:
        ecran = QGuiApplication.primaryScreen()
        if ecran is not None:
            return max(1.0, ecran.devicePixelRatio())
    return 2.0


def _chemin_bulle() -> QPainterPath:
    """Carré arrondi (sans queue) remplissant le cadre 100×100, marge pour le contour."""
    forme = QPainterPath()
    forme.addRoundedRect(QRectF(6, 6, 88, 88), 22, 22)
    return forme


def _dessiner_onde(painter: QPainter, couleur: QColor) -> None:
    pen = QPen(couleur, 7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for x, y0, y1 in _BARRES:
        painter.drawLine(x, y0, x, y1)


def icone_application(taille: int = 512) -> QIcon:
    """Icône de l'application (Dock macOS / barre des tâches) : carré bleu + bulle + onde.

    Même motif que l'icône `.app` (cf. dessiner_icone_app) : carré arrondi bleu plein +
    ondes **blanches** directement dessus. Remplit le cadre (≠ marges macOS du .icns) car
    elle sert d'icône de fenêtre en dev. Jamais un template (couleur conservée)."""
    ratio = _ratio_ecran()
    pixmap = QPixmap(round(taille * ratio), round(taille * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    echelle = taille / 100.0
    painter.scale(echelle, echelle)

    painter.setPen(Qt.PenStyle.NoPen)
    carre_bleu = QPainterPath()
    carre_bleu.addRoundedRect(QRectF(2, 2, 96, 96), 22, 22)
    painter.fillPath(carre_bleu, QColor(_COULEUR_APP))
    _dessiner_onde(painter, QColor("#FFFFFF"))
    painter.end()

    return QIcon(pixmap)


def icone_pour_etat(etat: EtatVisuel, taille: int = 22) -> QIcon:
    ratio = _ratio_ecran()
    pixmap = QPixmap(round(taille * ratio), round(taille * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # On dessine dans le repère logique 100×100 (Qt gère le facteur Retina).
    echelle = taille / 100.0
    painter.scale(echelle, echelle)

    bulle = _chemin_bulle()

    if etat == EtatVisuel.REPOS:
        # Contour seul, encre noire → rendu en template (cf. setIsMask plus bas)
        encre = QColor("#000000")
        pen = QPen(encre, 7)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bulle)
        _dessiner_onde(painter, encre)
    else:
        couleur = QColor(_COULEURS[etat])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(bulle, couleur)
        _dessiner_onde(painter, QColor("#FFFFFF"))

    painter.end()

    icone = QIcon(pixmap)
    # REPOS = template : macOS le recolore selon le thème de la barre de menu.
    icone.setIsMask(etat == EtatVisuel.REPOS)
    return icone


# ── Icônes Phosphor (refonte design) — SVG embarqués, référencés par nom logique ──
#
# Remplacent progressivement les glyphes Tabler ci-dessous au fil des étapes de la
# refonte (composants, Historique, Préférences, tray).

ICON_DIR = Path(__file__).parent / "assets" / "icons"
PHOSPHOR_DIR = ICON_DIR / "phosphor"


def icone_phosphor(nom: str) -> Path:
    """Chemin du SVG Phosphor `nom` (ex: "microphone" → .../phosphor/microphone.svg)."""
    return PHOSPHOR_DIR / f"{nom}.svg"


# ── Glyphes d'action (Historique) : fonte Tabler embarquée (outline, licence MIT) ──
#
# Décision (doc 09 §3) : rendu identique à l'aperçu validé → on peint les glyphes de la
# fonte Tabler outline embarquée (assets/tabler-icons.ttf). API inchangée : `icone_glyphe`
# (boutons, template recoloré clair/sombre + grisé si désactivé) et `pixmap_glyphe`
# (indicateurs de ligne, dans la couleur de texte du thème).

_FONTE_TABLER = Path(__file__).parent / "assets" / "tabler-icons.ttf"

# Nom logique → caractère (codepoint Tabler, cf. tabler-icons CSS).
_GLYPHES = {
    "micro":     "",   # ti-microphone
    "personnes": "",   # ti-users
    "copier":    "",   # ti-copy
    "note":      "",   # ti-file-text
    "dossier":   "﫷",   # ti-folder-open
    "muet":      "",   # ti-volume-off (haut-parleur barré)
    "corbeille": "",   # ti-trash
    "attente":   "",   # ti-loader-2 (spinner)
    "ecrire":    "",   # ti-writing (transcrire l'audio)
}

_famille_tabler: str | None = None


def _charger_fonte() -> str | None:
    """Charge la fonte Tabler une seule fois et renvoie sa famille (None si indisponible)."""
    global _famille_tabler
    if _famille_tabler is not None:
        return _famille_tabler
    fid = QFontDatabase.addApplicationFont(str(_FONTE_TABLER))
    if fid == -1:
        return None
    familles = QFontDatabase.applicationFontFamilies(fid)
    _famille_tabler = familles[0] if familles else None
    return _famille_tabler


def _peindre_glyphe(nom: str, taille: int, couleur: QColor, angle: float = 0.0) -> QPixmap:
    if nom not in _GLYPHES:
        raise ValueError(f"glyphe inconnu : {nom!r}")
    ratio = _ratio_ecran()
    pixmap = QPixmap(round(taille * ratio), round(taille * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    famille = _charger_fonte()
    if famille:
        police = QFont(famille)
        police.setPixelSize(taille)        # le glyphe remplit l'em (padding intégré Tabler)
        painter.setFont(police)
        painter.setPen(couleur)
        if angle:
            centre = taille / 2
            painter.translate(centre, centre)
            painter.rotate(angle)
            painter.translate(-centre, -centre)
        painter.drawText(QRectF(0, 0, taille, taille),
                         int(Qt.AlignmentFlag.AlignCenter), _GLYPHES[nom])
    painter.end()
    return pixmap


# Opacité de l'encre des icônes d'action : < 1 → trait perçu plus léger (cf. discussion 2026-06-26).
_INTENSITE_ACTION = 0.72


def _couleur_theme(alpha: float) -> QColor:
    """Couleur de texte du thème (clair/sombre) à l'opacité `alpha`. Repli noir hors app."""
    app = QGuiApplication.instance()
    couleur = (app.palette().color(QPalette.ColorRole.WindowText)
               if app is not None else QColor("#000000"))
    couleur.setAlphaF(alpha)
    return couleur


def icone_glyphe(nom: str, taille: int = 18, intensite: float = _INTENSITE_ACTION) -> QIcon:
    """Icône d'action (boutons de l'Historique), peinte dans la couleur de texte du thème.

    Encre atténuée (`intensite` < 1) pour un rendu **moins lourd** que le noir plein, tout en
    s'adaptant au thème clair/sombre. Pas de `isMask` (qui forcerait l'opacité pleine) ; Qt grise
    quand même l'état désactivé. La couleur est figée à la création (cf. note adaptation runtime)."""
    return QIcon(_peindre_glyphe(nom, taille, _couleur_theme(intensite)))


def pixmap_glyphe(nom: str, taille: int = 16, alpha: float = 0.55) -> QPixmap:
    """Pixmap d'un glyphe dans la couleur de texte du thème (indicateurs de ligne).

    `alpha` < 1 → rendu atténué (indicateur discret, pas un bouton)."""
    return _peindre_glyphe(nom, taille, _couleur_theme(alpha))


def icone_glyphe_pivotee(nom: str, taille: int = 18, angle: float = 0.0,
                         intensite: float = _INTENSITE_ACTION) -> QIcon:
    """Icône d'action peinte avec une rotation de `angle` degrés (pour un spinner animé)."""
    return QIcon(_peindre_glyphe(nom, taille, _couleur_theme(intensite), angle))


# ── Icône d'application (Dock / Finder, fichier .icns) ─────────────────────────
#
# Distincte de l'icône de tray : ici on suit les guidelines macOS (carré arrondi
# coloré, marges de sécurité ~80 %), pas un template monochrome. Motif validé :
# carré bleu système (dégradé) + ondes sonores **blanches** directement dessus.
# Repère logique 186×186 : le carré fait 150 centré (marge 18 → ~80,6 %, conforme au Dock).

_SVG_ICONE_APP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 186 186">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#5AB0FF"/><stop offset="1" stop-color="#0A74E6"/>'
    '</linearGradient></defs>'
    '<rect x="18" y="18" width="150" height="150" rx="34" fill="url(#g)"/>'
    '<rect x="52.5" y="78" width="9" height="30" rx="4.5" fill="#FFFFFF"/>'
    '<rect x="70.5" y="69" width="9" height="48" rx="4.5" fill="#FFFFFF"/>'
    '<rect x="88.5" y="61" width="9" height="64" rx="4.5" fill="#FFFFFF"/>'
    '<rect x="106.5" y="71" width="9" height="44" rx="4.5" fill="#FFFFFF"/>'
    '<rect x="124.5" y="76" width="9" height="34" rx="4.5" fill="#FFFFFF"/>'
    '</svg>'
)

# Tailles requises pour un .iconset macOS : (px de rendu, suffixe Apple).
_ICONSET_SPECS = [
    (16, "16x16"), (32, "16x16@2x"),
    (32, "32x32"), (64, "32x32@2x"),
    (128, "128x128"), (256, "128x128@2x"),
    (256, "256x256"), (512, "256x256@2x"),
    (512, "512x512"), (1024, "512x512@2x"),
]


def dessiner_icone_app(taille: int) -> QPixmap:
    """Rend l'icône d'application (carré arrondi + bulle + ondes) à `taille`×`taille`."""
    from PySide6.QtSvg import QSvgRenderer

    rendu = QSvgRenderer(QByteArray(_SVG_ICONE_APP.encode("utf-8")))
    image = QImage(taille, taille, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rendu.render(painter)
    painter.end()
    return QPixmap.fromImage(image)


def ecrire_iconset(dossier) -> list[Path]:
    """Écrit les PNG multi-résolution d'un `.iconset` macOS dans `dossier`.

    Renvoie les chemins écrits. `iconutil -c icns` (macOS) produit ensuite le .icns."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    ecrits: list[Path] = []
    for taille, suffixe in _ICONSET_SPECS:
        chemin = dossier / f"icon_{suffixe}.png"
        dessiner_icone_app(taille).save(str(chemin), "PNG")
        ecrits.append(chemin)
    return ecrits


_ICO_TAILLES = (16, 32, 48, 256)


def ecrire_ico(chemin) -> Path:
    """Écrit une icône Windows multi-résolution (.ico) — packaging/windows (docs/32 §3.2).

    Utilise Pillow (dépendance dev uniquement) : Qt n'expose pas d'API fiable pour
    combiner plusieurs résolutions dans un seul fichier .ico, alors que Pillow le
    fait nativement (`append_images` + `sizes`)."""
    import io
    from PIL import Image

    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    images = []
    for taille in _ICO_TAILLES:
        tampon = QByteArray()
        buf = QBuffer(tampon)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        dessiner_icone_app(taille).save(buf, "PNG")
        buf.close()
        images.append(Image.open(io.BytesIO(bytes(tampon))))

    images[-1].save(
        str(chemin), format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[:-1],
    )
    return chemin
