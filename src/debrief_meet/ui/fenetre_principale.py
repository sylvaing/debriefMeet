"""Coquille de la fenêtre principale (refonte design) — Toolbar + zone de contenu
empilée (Historique / Préférences / Enregistrement). Remplace la navigation par
dialogues indépendants (anciennes FenetreHistorique/FenetrePreferences) : une
seule fenêtre, la sélection d'onglet ne change pas quand un enregistrement
s'affiche par-dessus (cf. RecordingController).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from debrief_meet import __version__
from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats
from debrief_meet.platform.interfaces import DemarrageAuto, MoteurTranscription, PressePapiers
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.history_view import HistoryView
from debrief_meet.ui.preferences_view import PreferencesView
from debrief_meet.ui.recording_controller import RecordingController
from debrief_meet.ui.recording_view import RecordingView
from debrief_meet.ui.start_group import StartButtonGroup
from debrief_meet.ui.theme import C, M, MONO, SANS
from debrief_meet.ui.wavemark import wavemark_icon

PAGE_HISTORIQUE, PAGE_PREFERENCES, PAGE_ENREGISTREMENT = range(3)


class FenetrePrincipale(QMainWindow):
    def __init__(
        self,
        machine: MachineEtats,
        config: Config,
        demarrage_auto: DemarrageAuto | None = None,
        presse_papiers: PressePapiers | None = None,
        gestionnaire: GestionnaireDiarization | None = None,
        moteur: MoteurTranscription | None = None,
        reappliquer_raccourcis: Callable[[], list[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._machine = machine
        self.setWindowTitle("debriefMeet")
        self.resize(1000, 660)

        self._history_view = HistoryView(config, presse_papiers, gestionnaire, self)
        self._preferences_view = PreferencesView(
            config, demarrage_auto, moteur, reappliquer_raccourcis, self)
        self._recording_view = RecordingView(machine, self)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._history_view)      # PAGE_HISTORIQUE
        self._pages.addWidget(self._preferences_view)   # PAGE_PREFERENCES
        self._pages.addWidget(self._recording_view)     # PAGE_ENREGISTREMENT

        toolbar = self._construire_toolbar()

        centre = QWidget(self)
        layout = QVBoxLayout(centre)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._pages, 1)
        self.setCentralWidget(centre)

        # Référence conservée : un RecordingController sans propriétaire est
        # éligible au GC (cf. sa docstring), ce qui couperait ses connexions.
        self._recording_controller = RecordingController(machine, self._start_group, self)
        self._recording_controller.showRequested.connect(self._afficher_enregistrement)

        self.definir_etat_visuel(EtatVisuel.REPOS)

    # ── Toolbar ────────────────────────────────────────────────────────────────

    def _construire_toolbar(self) -> QWidget:
        barre = QWidget(self)
        barre.setFixedHeight(M.TOOLBAR_H)
        barre.setStyleSheet(f"background: {C.SURFACE}; border-bottom: 1px solid {C.BORDER};")
        lay = QHBoxLayout(barre)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        marque = QLabel(barre)
        marque.setPixmap(wavemark_icon(26, C.ACCENT, filled=True).pixmap(26, 26))
        lay.addWidget(marque)

        nom = QLabel("debriefMeet", barre)
        nom.setFont(QFont(SANS, 15, QFont.Weight.Bold))
        lay.addWidget(nom)

        version = QLabel(f"v{__version__}", barre)
        version.setFont(QFont(MONO, 10))
        version.setStyleSheet(
            f"color: {C.INK500}; border: 1px solid {C.BORDER}; border-radius: 5px; padding: 1px 6px;")
        lay.addWidget(version)

        lay.addSpacing(16)

        self._nav_historique = QToolButton(barre)
        self._nav_historique.setObjectName("navTab")
        self._nav_historique.setText("Historique")
        self._nav_historique.setCheckable(True)
        self._nav_preferences = QToolButton(barre)
        self._nav_preferences.setObjectName("navTab")
        self._nav_preferences.setText("Préférences")
        self._nav_preferences.setCheckable(True)

        self._groupe_nav = QButtonGroup(barre)
        self._groupe_nav.setExclusive(True)
        self._groupe_nav.addButton(self._nav_historique, PAGE_HISTORIQUE)
        self._groupe_nav.addButton(self._nav_preferences, PAGE_PREFERENCES)
        self._groupe_nav.idClicked.connect(self._sur_nav_change)
        self._nav_historique.setChecked(True)

        lay.addWidget(self._nav_historique)
        lay.addWidget(self._nav_preferences)

        lay.addStretch()

        self._start_group = StartButtonGroup(barre)
        lay.addWidget(self._start_group)

        self._icone_etat = QLabel(barre)
        lay.addWidget(self._icone_etat)

        return barre

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _sur_nav_change(self, page: int) -> None:
        self._pages.setCurrentIndex(page)

    def _afficher_enregistrement(self) -> None:
        """Affiche RecordingView sans changer l'onglet coché (cf. IMPLEMENTATION_SPEC §7)."""
        self._pages.setCurrentIndex(PAGE_ENREGISTREMENT)

    def afficher_historique(self) -> None:
        self._nav_historique.setChecked(True)
        self._pages.setCurrentIndex(PAGE_HISTORIQUE)

    def afficher_preferences(self) -> None:
        self._nav_preferences.setChecked(True)
        self._pages.setCurrentIndex(PAGE_PREFERENCES)

    def selectionner_reunion(self, chemin_md) -> None:
        """Relais pour le clic sur une notification (cf. tray) — ouvre l'Historique
        et sélectionne la ligne visée."""
        self.afficher_historique()
        self._history_view.selectionner_reunion(chemin_md)

    # ── État visuel (icône toolbar) ──────────────────────────────────────────────

    def definir_etat_visuel(self, etat: EtatVisuel) -> None:
        self._icone_etat.setPixmap(icone_wavemark_pour_etat(etat, taille=24).pixmap(24, 24))
