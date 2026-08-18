"""Coquille de la fenêtre principale (refonte design v2, CHANGELOG_v2 §1) —
Toolbar (3 onglets de type + engrenage Préférences) + zone de contenu
empilée (Réunion / Dictée / Journal / Préférences). Chaque page de type porte
son propre historique et son propre bouton Démarrer/Arrêter (§2) — il n'y a
plus d'onglet « Historique » global ni d'écran d'enregistrement plein écran
(§6, `RecordingView` supprimée).
"""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QSize, Qt
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
from debrief_meet.core.bluemind.store import StoreCalendrier
from debrief_meet.core.bluemind.sync import SynchroCalendrier
from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats
from debrief_meet.platform.interfaces import DemarrageAuto, MoteurTranscription, PressePapiers
from debrief_meet.ui.dictee_view import DicteeView
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.generateur_cr_mistral import GestionnaireCRMistral
from debrief_meet.ui.icones import icone_bascule
from debrief_meet.ui.journal_view import JournalView
from debrief_meet.ui.preferences_view import PreferencesView
from debrief_meet.ui.recording_controller import RecordingController
from debrief_meet.core import mode_transcription
from debrief_meet.ui.reunion_view import ReunionView
from debrief_meet.ui.theme import C, M, MONO, SANS
from debrief_meet.ui.wavemark import wavemark_icon

# Identifiants **stables** des pages (ids du QButtonGroup) — et non des positions dans
# la pile : en édition lite les pages Dictée et Journal n'existent pas (docs/44), donc
# `_index_pages` traduit l'identifiant en index réel rendu par `addWidget()`.
PAGE_REUNION, PAGE_DICTEE, PAGE_JOURNAL, PAGE_PREFERENCES = range(4)

# Liseré autour de la fenêtre : nécessaire seulement là où le gestionnaire de
# fenêtres n'apporte pas d'ombre portée (Wayland/GNOME, cf. `_construire`). macOS et
# Windows dessinent la leur, un liseré y ferait doublon.
_BORDURE_FENETRE = sys.platform.startswith("linux")


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
        bluemind_reinitialiser_sync: Callable[[], None] | None = None,
        bluemind_declencher_sync: Callable[[], None] | None = None,
        bluemind_sur_ouverture: Callable[[], None] | None = None,
        bluemind_store: StoreCalendrier | None = None,
        bluemind_synchro: SynchroCalendrier | None = None,
        gestionnaire_cr_mistral: GestionnaireCRMistral | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._machine = machine
        self._bluemind_sur_ouverture = bluemind_sur_ouverture
        self.setWindowTitle("debriefMeet")
        self.resize(1000, 660)

        self._reunion_view = ReunionView(
            config, machine, presse_papiers, gestionnaire, bluemind_store, gestionnaire_cr_mistral,
            bluemind_synchro, self)
        self._dictee_view = DicteeView(config, machine, self) \
            if mode_transcription.avec_dictee_journal() else None
        self._journal_view = JournalView(config, machine, presse_papiers, self) \
            if mode_transcription.avec_dictee_journal() else None
        self._preferences_view = PreferencesView(
            config, demarrage_auto, moteur, reappliquer_raccourcis,
            bluemind_reinitialiser_sync, bluemind_declencher_sync, self)

        self._pages = QStackedWidget(self)
        self._index_pages: dict[int, int] = {}
        self._ajouter_page(PAGE_REUNION, self._reunion_view)
        self._ajouter_page(PAGE_DICTEE, self._dictee_view)
        self._ajouter_page(PAGE_JOURNAL, self._journal_view)
        self._ajouter_page(PAGE_PREFERENCES, self._preferences_view)

        toolbar = self._construire_toolbar()

        centre = QWidget(self)
        centre.setObjectName("fenetreCentre")
        layout = QVBoxLayout(centre)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._pages, 1)
        self.setCentralWidget(centre)
        if _BORDURE_FENETRE:
            # Sous Wayland, GNOME impose les décorations côté client et le plugin Qt
            # `adwaita` ne dessine AUCUNE ombre portée, contrairement aux applications
            # GTK natives : notre fenêtre blanche devient alors indiscernable d'un
            # fond blanc (constaté chez le premier utilisateur Linux). On trace donc
            # notre propre liseré — indépendant du plugin de décoration, donc valable
            # sous Wayland comme sous X11.
            centre.setStyleSheet(
                f"#fenetreCentre {{ border: 1px solid {C.BORDER}; }}")

        # Référence conservée : un RecordingController sans propriétaire est
        # éligible au GC (cf. sa docstring), ce qui couperait ses connexions.
        self._recording_controller = RecordingController(
            machine, self._reunion_view, self._dictee_view, self._journal_view, self)

        self.definir_etat_visuel(EtatVisuel.REPOS)

    def _ajouter_page(self, id_page: int, vue: QWidget | None) -> None:
        """`addWidget()` rend l'index réel : les constantes PAGE_* restent des
        identifiants stables, jamais des positions dans la pile."""
        if vue is None:
            return
        self._index_pages[id_page] = self._pages.addWidget(vue)

    # ── Toolbar ────────────────────────────────────────────────────────────────

    def _construire_toolbar(self) -> QWidget:
        barre = QWidget(self)
        barre.setObjectName("toolbar")
        barre.setFixedHeight(M.TOOLBAR_H)
        lay = QHBoxLayout(barre)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        marque = QLabel(barre)
        marque.setPixmap(wavemark_icon(26, C.ACCENT, filled=True).pixmap(26, 26))
        lay.addWidget(marque)

        nom = QLabel("debriefMeet", barre)
        nom.setFont(QFont(SANS, 15, QFont.Weight.Bold))
        lay.addWidget(nom)

        version = QLabel(__version__, barre)
        version.setStyleSheet(
            f"color: {C.INK300}; border: 1px solid {C.BORDER}; border-radius: 5px; padding: 1px 5px;"
            f" font-family: '{MONO}'; font-size: 10.5px;")
        lay.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)

        lay.addSpacing(16)

        self._groupe_nav = QButtonGroup(barre)
        self._groupe_nav.setExclusive(True)

        # Un onglet par page réellement construite (Dictée/Journal absentes en lite).
        self._nav_reunion = self._creer_bouton_nav("Réunion", "users-three", barre)
        self._nav_dictee = self._creer_bouton_nav("Dictée", "microphone", barre) \
            if PAGE_DICTEE in self._index_pages else None
        self._nav_journal = self._creer_bouton_nav("Journal", "notebook", barre) \
            if PAGE_JOURNAL in self._index_pages else None
        for bouton, page in (
            (self._nav_reunion, PAGE_REUNION),
            (self._nav_dictee, PAGE_DICTEE),
            (self._nav_journal, PAGE_JOURNAL),
        ):
            if bouton is None:
                continue
            self._groupe_nav.addButton(bouton, page)
            lay.addWidget(bouton)
        self._nav_reunion.setChecked(True)

        lay.addStretch()

        self._bouton_prefs = QToolButton(barre)
        self._bouton_prefs.setObjectName("gearBtn")
        self._bouton_prefs.setToolTip("Préférences")
        self._bouton_prefs.setAutoRaise(True)
        self._bouton_prefs.setFixedSize(34, 34)
        self._bouton_prefs.setIconSize(QSize(18, 18))
        self._bouton_prefs.setIcon(icone_bascule("gear", C.INK400, C.ACCENT_INK, 18))
        self._bouton_prefs.setCheckable(True)
        self._groupe_nav.addButton(self._bouton_prefs, PAGE_PREFERENCES)
        lay.addWidget(self._bouton_prefs)

        self._groupe_nav.idClicked.connect(self._sur_nav_change)

        self._icone_etat = QLabel(barre)
        lay.addWidget(self._icone_etat)

        return barre

    def _creer_bouton_nav(self, label: str, icone: str, parent: QWidget) -> QToolButton:
        bouton = QToolButton(parent)
        bouton.setObjectName("navTab")
        bouton.setText(label)
        bouton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bouton.setAutoRaise(True)
        bouton.setFixedHeight(M.TOOLBAR_H)
        bouton.setIconSize(QSize(16, 16))
        bouton.setIcon(icone_bascule(icone, C.INK400, C.ACCENT_INK, 16))
        bouton.setCheckable(True)
        return bouton

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _sur_nav_change(self, page: int) -> None:
        self._pages.setCurrentIndex(self._index_pages[page])

    def afficher_reunion(self) -> None:
        self._nav_reunion.setChecked(True)
        self._pages.setCurrentIndex(self._index_pages[PAGE_REUNION])

    def afficher_preferences(self) -> None:
        self._bouton_prefs.setChecked(True)
        self._pages.setCurrentIndex(self._index_pages[PAGE_PREFERENCES])

    def selectionner_reunion(self, chemin_md) -> None:
        """Relais pour le clic sur une notification (cf. tray) — ouvre la page
        Réunion et sélectionne la ligne visée."""
        self.afficher_reunion()
        self._reunion_view.selectionner_reunion(chemin_md)

    def definir_reunion_active(self, chemin_md) -> None:
        """Relais de `OrchestrateurReunion.reunion_demarree` (docs/43 §9) — la page
        Réunion doit surveiller le sous-dossier de la réunion en cours."""
        self._reunion_view.definir_reunion_active(chemin_md)

    def showEvent(self, event) -> None:
        # Déclencheur de sync BlueMind « ouverture de la fenêtre » (docs/40 §5) —
        # no-op si l'interco n'est pas configurée ou si une sync tourne déjà.
        if self._bluemind_sur_ouverture is not None:
            self._bluemind_sur_ouverture()
        super().showEvent(event)

    # ── État visuel (icône toolbar) ──────────────────────────────────────────────

    def definir_etat_visuel(self, etat: EtatVisuel) -> None:
        self._icone_etat.setPixmap(icone_wavemark_pour_etat(etat, taille=24).pixmap(24, 24))
