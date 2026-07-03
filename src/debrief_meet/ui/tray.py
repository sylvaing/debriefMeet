from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from debrief_meet import __version__
from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.platform.interfaces import (
    DemarrageAuto,
    MoteurTranscription,
    PressePapiers,
)
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.historique import FenetreHistorique
from debrief_meet.ui.icones import icone_pour_etat
from debrief_meet.ui.preferences import FenetrePreferences

logger = logging.getLogger(__name__)


class IconeTray(QSystemTrayIcon):
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
        self._config = config
        self._demarrage_auto = demarrage_auto
        self._presse_papiers = presse_papiers
        self._gestionnaire = gestionnaire
        self._moteur = moteur
        self._reappliquer_raccourcis = reappliquer_raccourcis
        self._fenetre_prefs: FenetrePreferences | None = None
        self._fenetre_hist: FenetreHistorique | None = None

        self._etat_visuel = EtatVisuel.REPOS

        self._construire_menu()
        self._actualiser_icone(EtatVisuel.REPOS)
        self.rafraichir_raccourcis()

        machine.mode_change.connect(self._on_mode_change)
        machine.erreur.connect(self._on_erreur)
        self.activated.connect(self._on_activation)

        # Notification macOS de fin de diarization + clic → ouvre l'Historique (doc 09 §5).
        if gestionnaire is not None:
            gestionnaire.termine.connect(self._on_diar_termine)
            gestionnaire.echoue.connect(self._on_diar_echoue)
            self.messageClicked.connect(self._on_notification_cliquee)

        self.setToolTip("debriefMeet")

    def _construire_menu(self) -> None:
        menu = QMenu()

        self._action_dictee = QAction("Démarrer Dictée", menu)
        self._action_dictee.triggered.connect(self._machine.toggle_dictee)
        menu.addAction(self._action_dictee)

        self._action_reunion = QAction("Démarrer Réunion", menu)
        self._action_reunion.triggered.connect(self._machine.toggle_reunion)
        menu.addAction(self._action_reunion)

        self._action_journal = QAction("Démarrer Journal", menu)
        self._action_journal.triggered.connect(self._machine.toggle_journal)
        menu.addAction(self._action_journal)

        menu.addSeparator()

        action_hist = QAction("Historique…", menu)
        action_hist.triggered.connect(self._ouvrir_historique)
        menu.addAction(action_hist)

        action_prefs = QAction("Préférences…", menu)
        action_prefs.triggered.connect(self._ouvrir_preferences)
        menu.addAction(action_prefs)

        menu.addSeparator()

        action_about = QAction(f"debriefMeet {__version__}", menu)
        action_about.setEnabled(False)
        menu.addAction(action_about)

        action_quitter = QAction("Quitter", menu)
        action_quitter.triggered.connect(QApplication.quit)
        menu.addAction(action_quitter)

        self.setContextMenu(menu)

    def _on_mode_change(self, mode: Mode) -> None:
        self._actualiser_libelles(mode)
        logger.debug("Tray: mode → %s", mode.name)

    def definir_etat_visuel(self, etat: EtatVisuel) -> None:
        """Met à jour la couleur de l'icône selon l'état d'activité."""
        self._etat_visuel = etat
        self._actualiser_icone(etat)
        logger.debug("Tray: état visuel → %s", etat.name)

    def _on_erreur(self, message: str) -> None:
        logger.warning("Erreur mode : %s", message)

    def _on_activation(self, raison: QSystemTrayIcon.ActivationReason) -> None:
        if raison == QSystemTrayIcon.ActivationReason.Trigger:
            # Clic gauche : affiche le menu (comportement contextMenu par défaut sur macOS)
            pass

    def _actualiser_icone(self, etat: EtatVisuel) -> None:
        self.setIcon(icone_pour_etat(etat))

    def _actualiser_libelles(self, mode: Mode) -> None:
        configs = {
            Mode.IDLE:    ("Démarrer Dictée",   True,  "Démarrer Réunion",  True,  "Démarrer Journal",  True),
            Mode.DICTEE:  ("⏹ Arrêter Dictée",  True,  "Démarrer Réunion",  False, "Démarrer Journal",  False),
            Mode.REUNION: ("Démarrer Dictée",   False, "⏹ Arrêter Réunion", True,  "Démarrer Journal",  False),
            Mode.JOURNAL: ("Démarrer Dictée",   False, "Démarrer Réunion",  False, "⏹ Arrêter Journal", True),
        }
        td, ed, tr, er, tj, ej = configs[mode]
        self._action_dictee.setText(td);  self._action_dictee.setEnabled(ed)
        self._action_reunion.setText(tr); self._action_reunion.setEnabled(er)
        self._action_journal.setText(tj); self._action_journal.setEnabled(ej)

    def _ouvrir_preferences(self) -> None:
        if self._fenetre_prefs is None:
            self._fenetre_prefs = FenetrePreferences(
                self._config, self._demarrage_auto, moteur=self._moteur,
                reappliquer_raccourcis=self._reappliquer_et_rafraichir)
        self._fenetre_prefs.show()
        self._fenetre_prefs.raise_()
        self._fenetre_prefs.activateWindow()

    def _reappliquer_et_rafraichir(self) -> list[str]:
        echecs = self._reappliquer_raccourcis() if self._reappliquer_raccourcis else []
        self.rafraichir_raccourcis()
        return echecs

    def rafraichir_raccourcis(self) -> None:
        """Affiche les glyphes de raccourcis (⌃⌥⌘D…) dans le menu — purement décoratif,
        la capture réelle est faite par l'adaptateur Carbon (docs/28)."""
        self._action_dictee.setShortcut(QKeySequence.fromString(self._config.get("raccourci_dictee")))
        self._action_reunion.setShortcut(QKeySequence.fromString(self._config.get("raccourci_reunion")))
        self._action_journal.setShortcut(QKeySequence.fromString(self._config.get("raccourci_journal")))

    def _ouvrir_historique(self) -> FenetreHistorique:
        if self._fenetre_hist is None:
            self._fenetre_hist = FenetreHistorique(
                self._config, self._presse_papiers, gestionnaire=self._gestionnaire)
        self._fenetre_hist.show()
        self._fenetre_hist.raise_()
        self._fenetre_hist.activateWindow()
        return self._fenetre_hist

    # ── Notifications de diarization ────────────────────────────────────────────

    def _on_diar_termine(self, md: object, _sortie: object) -> None:
        nom = getattr(md, "stem", str(md))
        self.showMessage(
            "Locuteurs générés",
            f"« {nom} » — cliquez pour ouvrir l'Historique.",
            icone_pour_etat(EtatVisuel.TERMINE), 8000)

    def _on_diar_echoue(self, md: object, _message: str) -> None:
        nom = getattr(md, "stem", str(md))
        self.showMessage(
            "Diarization échouée",
            f"La génération des locuteurs de « {nom} » a échoué.",
            icone_pour_etat(EtatVisuel.ERREUR), 8000)

    # ── Notifications micro (robustesse hot-plug, docs/25) ──────────────────────

    def notifier_micro_perdu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Micro perdu", message, icone_pour_etat(EtatVisuel.ERREUR), 8000)

    def notifier_micro_retabli(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Micro rétabli", message, icone_pour_etat(EtatVisuel.TERMINE), 8000)

    # ── Notification « rien entendu » (dictée/journal muets, docs/27) ───────────

    def notifier_rien_entendu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Rien entendu", message, icone_pour_etat(EtatVisuel.ERREUR), 8000)

    def _on_notification_cliquee(self) -> None:
        # messageClicked n'indique pas quelle notif → on cible le dernier job terminé.
        fenetre = self._ouvrir_historique()
        cible = self._gestionnaire.dernier_termine() if self._gestionnaire else None
        fenetre.selectionner_reunion(cible)
