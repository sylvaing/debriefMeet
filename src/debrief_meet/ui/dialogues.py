"""Gabarit unifié des boîtes de dialogue (DESIGN.md §8.9) — remplace toute
`QMessageBox`/`QInputDialog`/`QDialog` par défaut : overlay + carte + en-tête
(tuile icône + titre + description) + pied (Annuler + action colorée selon
l'intention — jamais de « Yes/OK » générique).

`CarteFlottante` porte la coquille nue (overlay + carte blanche arrondie +
ombre) — utilisée directement par les dialogues à contenu libre (assistant de
diarization). `DialogueGabarit` y ajoute l'en-tête + le pied communs, pour les
confirmations et les dialogues de formulaire (association BlueMind, mapping
des locuteurs).
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, SANS

_COULEUR_OVERLAY = QColor(16, 24, 40, 115)  # rgba(16,24,40,.45)


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


class CarteFlottante(QDialog):
    """Coquille commune (§8.9) : overlay (si parent visible) + carte blanche
    arrondie centrée, ombre portée. Les sous-classes peuplent `corps`
    (`QVBoxLayout`, dans la carte)."""

    def __init__(self, parent: QWidget | None, *, largeur_carte: int = 380) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._avec_overlay = parent is not None

        self._carte = QFrame(self)
        self._carte.setObjectName("carteDialogue")
        self._carte.setFixedWidth(largeur_carte)
        self._carte.setStyleSheet(
            "QFrame#carteDialogue { background: #FFFFFF; border-radius: 12px; }")
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

    def paintEvent(self, event) -> None:  # noqa: N802 — override Qt
        if self._avec_overlay:
            painter = QPainter(self)
            painter.fillRect(self.rect(), _COULEUR_OVERLAY)
        super().paintEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 — override Qt
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.window().geometry())
        else:
            self.adjustSize()
            _centrer_sur_ecran(self)


class DialogueGabarit(CarteFlottante):
    """Confirmation/formulaire simple : en-tête (tuile + titre + description) +
    `zone_corps` (contenu libre) + pied (Annuler + action)."""

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

        self.zone_corps = QVBoxLayout()
        self.zone_corps.setSpacing(12)
        self.corps.addLayout(self.zone_corps)

        pied = QHBoxLayout()
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

    def definir_action(self, label: str, on_click: Callable[[], None] | None = None) -> None:
        self._bouton_action.setText(label)
        self._bouton_action.clicked.connect(on_click if on_click is not None else self.accept)

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
