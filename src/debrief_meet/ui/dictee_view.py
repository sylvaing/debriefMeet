"""Page Dictée (refonte design v2, CHANGELOG_v2 §2/§4) — barre d'action (bouton
Démarrer/Arrêter, sans recherche) + état explicatif centré. Pas d'historique :
le texte transcrit est copié dans le presse-papiers à l'arrêt (déjà câblé côté
capture, cf. `core/dictee.py`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.capture_action_bar import CaptureActionBar
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, MONO, SANS


class DicteeView(QWidget):
    def __init__(self, config: Config, machine: MachineEtats, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._action_bar = CaptureActionBar(Mode.DICTEE, avec_recherche=False, parent=self)
        self._action_bar.demande_bascule.connect(machine.toggle_dictee)
        layout.addWidget(self._action_bar)

        layout.addWidget(self._construire_etat_vide(config), 1)

    def _construire_etat_vide(self, config: Config) -> QWidget:
        conteneur = QWidget(self)
        lay = QVBoxLayout(conteneur)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(16)
        lay.setContentsMargins(30, 30, 30, 30)

        tuile = QLabel(conteneur)
        tuile.setFixedSize(60, 60)
        tuile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tuile.setStyleSheet(f"background: {C.ACCENT_SOFT}; border-radius: 16px;")
        tuile.setPixmap(icone_svg_teintee(icone_phosphor("microphone"), C.ACCENT_INK, 28).pixmap(28, 28))
        lay.addWidget(tuile, 0, Qt.AlignmentFlag.AlignHCenter)

        titre = QLabel("Dictée vocale", conteneur)
        titre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titre.setFont(QFont(SANS, 16, QFont.Weight.Bold))
        lay.addWidget(titre)

        raccourci = QKeySequence.fromString(config.get("raccourci_dictee")).toString(
            QKeySequence.SequenceFormat.NativeText) or "—"
        texte = QLabel(conteneur)
        texte.setTextFormat(Qt.TextFormat.RichText)
        texte.setWordWrap(True)
        texte.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texte.setMaximumWidth(380)
        texte.setFont(QFont(SANS, 13))
        texte.setStyleSheet(f"color: {C.INK350}; line-height: 1.7;")
        texte.setText(
            "Le texte transcrit est copié dans le presse-papiers. Cliquez sur "
            f"<b style=\"color:{C.INK600};\">Démarrer la dictée</b> ou utilisez le raccourci "
            f"<span style=\"font-family:'{MONO}'; color:{C.INK600};\">{raccourci}</span>."
        )
        lay.addWidget(texte, 0, Qt.AlignmentFlag.AlignHCenter)

        return conteneur

    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None:
        self._action_bar.definir_etat(mode_actif, secondes)
