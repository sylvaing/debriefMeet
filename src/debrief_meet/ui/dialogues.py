"""Gabarit unifié des boîtes de dialogue (DESIGN.md §8.9) — remplace toute
`QMessageBox`/`QInputDialog`/`QDialog` par défaut : overlay + carte + en-tête
(tuile icône + titre + description) + pied (Annuler + action colorée selon
l'intention — jamais de « Yes/OK » générique).

`CarteFlottante` porte la coquille nue (overlay + carte blanche arrondie +
ombre) — utilisée directement par les dialogues à contenu libre (assistant de
diarization). `DialogueGabarit` y ajoute l'en-tête + le pied communs, pour les
confirmations et les dialogues de formulaire (association BlueMind, mapping
des locuteurs).

Deux garanties structurelles, ajoutées par docs/50 après le blocage constaté sur
un événement BlueMind à ~34 invités :

1. **La carte ne déborde jamais de sa fenêtre hôte** — sa hauteur est plafonnée
   (`_ajuster_hauteur_carte`) et, dans `DialogueGabarit`, seul le corps défile :
   l'en-tête et le pied restent fixes, donc les boutons sont **toujours**
   atteignables quel que soit le contenu. Sans ça, une liste trop longue poussait
   « Annuler / Associer » hors de l'écran et le dialogue n'avait plus de sortie
   que la touche Échap.
2. **L'overlay est un widget enfant de la fenêtre hôte** (et non une fenêtre de
   premier niveau recopiant sa géométrie une seule fois) : déplacer ou
   redimensionner la fenêtre emporte le voile et la carte avec elle, sans code de
   suivi. Le chemin « fenêtre centrée sur l'écran » subsiste pour `parent=None`
   (aucun hôte où se greffer). ⚠️ Conséquence assumée (docs/50 §3.3) : la
   modalité devient **fenêtre** au lieu d'**application** — une autre fenêtre de
   l'app reste cliquable pendant qu'un dialogue est ouvert.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Callable

from PySide6.QtCore import QEvent, QEventLoop, QObject, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, SANS

_COULEUR_OVERLAY = QColor(16, 24, 40, 115)  # rgba(16,24,40,.45)
_FOND_CARTE = "#FFFFFF"


class Intention(Enum):
    DESTRUCTIF = auto()
    ACCENT = auto()


class _Palette:
    def __init__(self, tuile_bg: str, tuile_bordure: str, icone: str, bouton: str, bouton_survol: str) -> None:
        self.tuile_bg = tuile_bg
        self.tuile_bordure = tuile_bordure
        self.icone = icone
        self.bouton = bouton
        self.bouton_survol = bouton_survol


_PALETTES = {
    Intention.DESTRUCTIF: _Palette(C.DANGER_BG, "#F4C9C7", C.DANGER, C.DANGER, "#96190F"),
    Intention.ACCENT: _Palette(C.ACCENT_SOFT, C.ACCENT_SOFT, C.ACCENT_INK, C.ACCENT, C.ACCENT_INK),
}


def _centrer_sur_ecran(widget: QWidget) -> None:
    ecran = QGuiApplication.primaryScreen()
    if ecran is None:
        return
    geo = ecran.availableGeometry()
    widget.move(geo.center() - widget.rect().center())


class _ZoneDefilante(QScrollArea):
    """`QScrollArea` qui **ne rétrécit pas** les dialogues courts.

    Le `sizeHint` d'un `QScrollArea` standard est arbitraire et petit : l'employer
    tel quel raboterait tous les dialogues du gabarit (`confirmer`, `informer`…).
    En renvoyant le `sizeHint` du contenu, la carte garde sa taille naturelle tant
    qu'elle tient dans la fenêtre ; le `minimumSizeHint`, lui, reste petit — c'est
    ce qui autorise le layout à la comprimer, et donc la barre de défilement à
    apparaître, quand la fenêtre est trop courte."""

    def __init__(self, contenu: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Fond laissé à la carte blanche. La feuille de style est posée sur le **viewport
        # seul** : sur celui du QScrollArea elle basculerait tout le sous-arbre — barre de
        # défilement comprise — sur le rendu « stylesheet », qui lui donne une glissière
        # fantôme. Et une palette blanche ne suffirait pas : la feuille de style globale
        # (`QWidget { … }`) prime sur la palette, d'où un rectangle gris dans la carte —
        # invisible sur macOS, bien réel sous Fusion (Linux, et le rendu des tests).
        self.viewport().setStyleSheet("background: transparent;")
        self.setWidget(contenu)

    def sizeHint(self) -> QSize:  # noqa: N802 — override Qt
        contenu = self.widget()
        return super().sizeHint() if contenu is None else contenu.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — override Qt
        """Aucun plancher : celui de `QAbstractScrollArea` (~70 px, prévu pour une vue
        autonome) creusait un trou vertical dans les dialogues **sans corps** — un
        `confirmer()` gagnait 70 px de blanc entre sa description et ses boutons — et
        empêchait le layout de comprimer le corps autant que nécessaire."""
        return QSize(0, 0)


class CarteFlottante(QDialog):
    """Coquille commune (§8.9) : overlay + carte blanche arrondie centrée, ombre
    portée. Les sous-classes peuplent `corps` (`QVBoxLayout`, dans la carte).

    Avec un parent : **widget enfant** de la fenêtre hôte, couvrant tout son
    rectangle — il la suit donc naturellement quand elle bouge. Sans parent :
    fenêtre sans cadre centrée sur l'écran (aucun hôte, aucun overlay)."""

    #: Marge minimale laissée autour de la carte dans la fenêtre hôte.
    MARGE_HAUTEUR = 48
    #: Hauteur en deçà de laquelle on cesse de comprimer (fenêtre minuscule).
    HAUTEUR_PLANCHER = 220

    def __init__(self, parent: QWidget | None, *, largeur_carte: int = 380) -> None:
        hote = parent.window() if parent is not None else None
        super().__init__(hote)
        self._hote = hote
        self._boucle: QEventLoop | None = None
        self._avec_overlay = hote is not None

        if hote is None:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setModal(True)
        else:
            # Widget enfant : `Qt.WindowType.Widget` retire le drapeau `Dialog` posé
            # par `QDialog`, sinon Qt en referait une fenêtre indépendante.
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setObjectName("overlayDialogue")
            # La feuille de style globale pose `QDialog { background: #FFFFFF }` :
            # sélecteur nominatif obligatoire, sinon le voile serait un aplat blanc.
            self.setStyleSheet("QDialog#overlayDialogue { background: transparent; }")
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            hote.installEventFilter(self)

        self._carte = QFrame(self)
        self._carte.setObjectName("carteDialogue")
        self._carte.setFixedWidth(largeur_carte)
        self._carte.setStyleSheet(
            f"QFrame#carteDialogue {{ background: {_FOND_CARTE}; border-radius: 12px; }}")
        ombre = QGraphicsDropShadowEffect(self._carte)
        ombre.setBlurRadius(44)
        ombre.setOffset(0, 10)
        ombre.setColor(QColor(16, 24, 40, 100))
        self._carte.setGraphicsEffect(ombre)

        self.corps = QVBoxLayout(self._carte)
        self.corps.setContentsMargins(22, 22, 22, 22)
        self.corps.setSpacing(18)

        grille = QGridLayout(self)
        grille.setContentsMargins(0, 0, 0, 0)
        grille.addWidget(self._carte, 0, 0, Qt.AlignmentFlag.AlignCenter)

    # ── Débordement ─────────────────────────────────────────────────────────────

    def _ajuster_hauteur_carte(self, hauteur_disponible: int) -> None:
        """Plafonne la hauteur de la carte. Indispensable : l'alignement `AlignCenter`
        fait servir au layout le `sizeHint` de l'item **sans le comprimer** — c'est
        la taille maximale du widget, et elle seule, qui le borne."""
        self._carte.setMaximumHeight(
            max(self.HAUTEUR_PLANCHER, hauteur_disponible - self.MARGE_HAUTEUR))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 — override Qt
        """L'overlay épouse la fenêtre hôte à chaque redimensionnement (le déplacement,
        lui, est gratuit : la géométrie d'un enfant est relative à son parent).

        `getattr` et non `self._hote` : à la fermeture de l'application, l'hôte est
        détruit alors que le filtre est encore posé et que les attributs Python de
        l'overlay ont déjà été purgés — Qt appellerait alors cette surcharge sur une
        coquille vide (`AttributeError` crachée sur stderr à chaque quit)."""
        hote = getattr(self, "_hote", None)
        if hote is not None and obj is hote and event.type() == QEvent.Type.Resize:
            self.setGeometry(hote.rect())
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:  # noqa: N802 — override Qt
        if self._avec_overlay:
            painter = QPainter(self)
            painter.fillRect(self.rect(), _COULEUR_OVERLAY)
        super().paintEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 — override Qt
        super().showEvent(event)
        if self._hote is not None:
            self.setGeometry(self._hote.rect())
            self._ajuster_hauteur_carte(self._hote.height())
            self.raise_()
            self.setFocus()
        else:
            ecran = QGuiApplication.primaryScreen()
            if ecran is not None:
                self._ajuster_hauteur_carte(ecran.availableGeometry().height())
            self.adjustSize()
            _centrer_sur_ecran(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 — override Qt
        super().resizeEvent(event)
        if self._hote is not None:
            self._ajuster_hauteur_carte(self.height())

    # ── Cycle de vie ────────────────────────────────────────────────────────────

    def exec(self) -> int:
        """Même contrat que `QDialog.exec()` (bloque, renvoie `DialogCode`), émulé par
        une boucle d'événements imbriquée quand le dialogue est un widget enfant —
        `QDialog.exec()` exige une fenêtre."""
        if self._hote is None:
            return super().exec()
        self.show()
        self.raise_()
        self.setFocus()
        boucle = QEventLoop()
        self._boucle = boucle
        self.finished.connect(boucle.quit)
        try:
            boucle.exec()
        finally:
            self._boucle = None
            self.finished.disconnect(boucle.quit)
        return self.result()

    def done(self, code: int) -> None:
        """Sortie unique des deux chemins (`accept`/`reject` y passent) : on en profite
        pour déposer le filtre sur l'hôte — un overlay fermé ne doit plus rien suivre."""
        if self._hote is not None:
            self._hote.removeEventFilter(self)
        super().done(code)


class DialogueGabarit(CarteFlottante):
    """Confirmation/formulaire simple : en-tête (tuile + titre + description) +
    `zone_corps` (contenu libre, **défilant**) + pied (Annuler + action)."""

    def __init__(
        self, parent: QWidget | None, *, titre: str, description: str, icone: str,
        intention: Intention = Intention.ACCENT, largeur_carte: int = 380,
    ) -> None:
        super().__init__(parent, largeur_carte=largeur_carte)
        palette = _PALETTES[intention]

        entete = QHBoxLayout()
        entete.setSpacing(14)
        tuile = QLabel()
        tuile.setFixedSize(40, 40)
        tuile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tuile.setStyleSheet(
            f"background: {palette.tuile_bg}; border: 1px solid {palette.tuile_bordure};"
            f" border-radius: 10px;")
        icone_qt = icone_svg_teintee(icone_phosphor(icone), palette.icone, 19)
        tuile.setPixmap(icone_qt.pixmap(19, 19))
        entete.addWidget(tuile, 0, Qt.AlignmentFlag.AlignTop)

        colonne = QVBoxLayout()
        colonne.setSpacing(5)
        lab_titre = QLabel(titre)
        lab_titre.setFont(QFont(SANS, 15, QFont.Weight.Bold))
        lab_titre.setStyleSheet(f"color: {C.INK900};")
        lab_titre.setWordWrap(True)
        colonne.addWidget(lab_titre)
        lab_desc = QLabel(description)
        lab_desc.setFont(QFont(SANS, 13))
        lab_desc.setStyleSheet(f"color: {C.INK500};")
        lab_desc.setWordWrap(True)
        colonne.addWidget(lab_desc)
        entete.addLayout(colonne, 1)
        self.corps.addLayout(entete)

        # Corps **défilant** : seul lui est comprimé quand la fenêtre est trop courte,
        # l'en-tête et le pied restant fixes — c'est ce qui garantit que les boutons
        # sont toujours atteignables (docs/50 §3.1).
        self._contenu_corps = QWidget()
        self.zone_corps = QVBoxLayout(self._contenu_corps)
        self.zone_corps.setContentsMargins(0, 0, 0, 0)
        self.zone_corps.setSpacing(12)
        self._defilement = _ZoneDefilante(self._contenu_corps)
        self.corps.addWidget(self._defilement)

        self._pied = QHBoxLayout()
        pied = self._pied
        pied.addStretch()
        self._bouton_annuler = QPushButton("Annuler")
        self._bouton_annuler.setObjectName("secondary")
        self._bouton_annuler.clicked.connect(self.reject)
        pied.addWidget(self._bouton_annuler)
        self._bouton_action = QPushButton()
        self._bouton_action.setStyleSheet(
            f"QPushButton {{ background: {palette.bouton}; color: #fff; border: none;"
            f" border-radius: 9px; padding: 9px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {palette.bouton_survol}; }}")
        pied.addWidget(self._bouton_action)
        self.corps.addLayout(pied)

    def showEvent(self, event) -> None:  # noqa: N802 — override Qt
        """Corps vide (confirmations, `informer`/`avertir`) : la zone défilante est
        **masquée** et non simplement vide — un item de hauteur nulle laisserait quand
        même l'espacement du layout, soit 18 px de blanc gagnés par ces dialogues."""
        self._defilement.setVisible(self.zone_corps.count() > 0)
        super().showEvent(event)

    def definir_action(self, label: str, on_click: Callable[[], None] | None = None) -> None:
        self._bouton_action.setText(label)
        self._bouton_action.clicked.connect(on_click if on_click is not None else self.accept)

    def ajouter_bouton_secondaire(self, label: str, on_click: Callable[[], None]) -> QPushButton:
        """Troisième voie, insérée **avant** « Annuler » (même style secondaire) — pour un
        choix qui n'est ni l'action principale ni un renoncement (p. ex. « Sans
        association » : on continue, mais sans faire ce que le dialogue propose)."""
        bouton = QPushButton(label)
        bouton.setObjectName("secondary")
        bouton.clicked.connect(on_click)
        self._pied.insertWidget(self._pied.indexOf(self._bouton_annuler), bouton)
        return bouton

    def masquer_annuler(self) -> None:
        self._bouton_annuler.hide()

    def bouton_action(self) -> QPushButton:
        return self._bouton_action

    def bouton_annuler(self) -> QPushButton:
        return self._bouton_annuler


# ── Fonctions de convenance (remplacent QMessageBox.question/information/warning) ──

def confirmer(
    parent: QWidget | None, *, titre: str, description: str,
    label_action: str = "Supprimer", icone: str = "trash",
    intention: Intention = Intention.DESTRUCTIF,
) -> bool:
    """Remplace `QMessageBox.question(...) == Yes` — deux boutons, action décrite."""
    dlg = DialogueGabarit(parent, titre=titre, description=description, icone=icone, intention=intention)
    dlg.definir_action(label_action)
    return dlg.exec() == QDialog.DialogCode.Accepted


def informer(
    parent: QWidget | None, *, titre: str, description: str,
    icone: str = "check-circle", label_fermer: str = "Fermer",
) -> None:
    """Remplace `QMessageBox.information(...)` — acquittement neutre/positif."""
    dlg = DialogueGabarit(parent, titre=titre, description=description, icone=icone,
                          intention=Intention.ACCENT)
    dlg.masquer_annuler()
    dlg.definir_action(label_fermer)
    dlg.exec()


def avertir(
    parent: QWidget | None, *, titre: str, description: str,
    icone: str = "warning-circle", label_fermer: str = "Fermer",
) -> None:
    """Remplace `QMessageBox.warning`/`.critical(...)` — acquittement d'erreur/blocage."""
    dlg = DialogueGabarit(parent, titre=titre, description=description, icone=icone,
                          intention=Intention.DESTRUCTIF)
    dlg.masquer_annuler()
    dlg.definir_action(label_fermer)
    dlg.exec()
