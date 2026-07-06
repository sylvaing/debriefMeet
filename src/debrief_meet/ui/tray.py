from __future__ import annotations

import logging

from PySide6.QtGui import QAction, QCursor, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from debrief_meet.core.config import Config
from debrief_meet.core.diagnostic import dossier_diagnostic_par_defaut, exporter_diagnostic
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat
from debrief_meet.ui.fenetre_principale import FenetrePrincipale
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C

logger = logging.getLogger(__name__)

_TAILLE_ICONE_MENU = 15


def _icone_menu(nom: str, hex_color: str) -> QIcon:
    return icone_svg_teintee(icone_phosphor(nom), hex_color, _TAILLE_ICONE_MENU)


class IconeTray(QSystemTrayIcon):
    def __init__(
        self,
        machine: MachineEtats,
        config: Config,
        fenetre_principale: FenetrePrincipale,
        gestionnaire: GestionnaireDiarization | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._machine = machine
        self._config = config
        self._fenetre_principale = fenetre_principale
        self._gestionnaire = gestionnaire

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
        # Pas de `setContextMenu()` : sur macOS, un menu attaché s'ouvre au clic
        # gauche ET droit (limite Qt documentée, cf. IMPLEMENTATION_SPEC §8). Le
        # menu est affiché manuellement sur clic droit (`_on_activation`).
        menu = QMenu()
        menu.setObjectName("trayMenu")
        self._menu = menu

        self._action_dictee = QAction(_icone_menu("microphone", C.INK500), "Démarrer Dictée", menu)
        self._action_dictee.triggered.connect(self._machine.toggle_dictee)
        menu.addAction(self._action_dictee)

        self._action_reunion = QAction(_icone_menu("users-three", C.INK500), "Démarrer Réunion", menu)
        self._action_reunion.triggered.connect(self._machine.toggle_reunion)
        menu.addAction(self._action_reunion)

        self._action_journal = QAction(_icone_menu("notebook", C.INK500), "Démarrer Journal", menu)
        self._action_journal.triggered.connect(self._machine.toggle_journal)
        menu.addAction(self._action_journal)

        # Qt masque par défaut les raccourcis dans les menus contextuels
        # (`shortcutVisibleInContextMenu`) — notre QMenu s'affiche via popup()
        # comme un menu contextuel, donc invisible sans ce forçage explicite.
        for action in (self._action_dictee, self._action_reunion, self._action_journal):
            action.setShortcutVisibleInContextMenu(True)

        menu.addSeparator()

        action_ouvrir = QAction(
            _icone_menu("arrow-square-out", C.ACCENT_INK), "Ouvrir debriefMeet", menu)
        action_ouvrir.triggered.connect(self._afficher_fenetre_principale)
        menu.addAction(action_ouvrir)
        menu.setDefaultAction(action_ouvrir)  # mis en avant (ordre spec §8)

        action_prefs = QAction(_icone_menu("gear", C.INK500), "Préférences…", menu)
        action_prefs.triggered.connect(self._ouvrir_preferences)
        menu.addAction(action_prefs)

        action_diagnostic = QAction(_icone_menu("bug", C.INK500), "Exporter le diagnostic…", menu)
        action_diagnostic.triggered.connect(self._exporter_diagnostic)
        menu.addAction(action_diagnostic)

        menu.addSeparator()

        action_quitter = QAction(_icone_menu("sign-out", C.DANGER), "Quitter", menu)
        action_quitter.triggered.connect(QApplication.quit)
        menu.addAction(action_quitter)

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
            self._afficher_fenetre_principale()
        elif raison == QSystemTrayIcon.ActivationReason.Context:
            self._menu.popup(QCursor.pos())

    def _actualiser_icone(self, etat: EtatVisuel) -> None:
        self.setIcon(icone_wavemark_pour_etat(etat))

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
        self._fenetre_principale.afficher_preferences()
        self._afficher_fenetre_principale()

    def _afficher_fenetre_principale(self) -> None:
        self._fenetre_principale.show()
        self._fenetre_principale.raise_()
        self._fenetre_principale.activateWindow()

    def rafraichir_raccourcis(self) -> None:
        """Affiche les glyphes de raccourcis (⌃⌥⌘D…) dans le menu — purement décoratif,
        la capture réelle est faite par l'adaptateur Carbon (docs/28)."""
        self._action_dictee.setShortcut(QKeySequence.fromString(self._config.get("raccourci_dictee")))
        self._action_reunion.setShortcut(QKeySequence.fromString(self._config.get("raccourci_reunion")))
        self._action_journal.setShortcut(QKeySequence.fromString(self._config.get("raccourci_journal")))

    def _exporter_diagnostic(self) -> None:
        """Doit marcher même quand tout le reste est cassé (docs/31 §3.6) : code
        trivial, sans dépendance au moteur, erreurs affichées plutôt que loguées
        silencieusement."""
        try:
            from debrief_meet.platform.infos_systeme import collecter_infos_systeme
            chemin = exporter_diagnostic(dossier_diagnostic_par_defaut(), collecter_infos_systeme())
            QMessageBox.information(
                None, "Diagnostic exporté",
                f"Diagnostic exporté sur le Bureau : {chemin.name}\n"
                "Envoyez ce fichier à Sylvain.",
            )
        except Exception as exc:
            logger.error("Export diagnostic impossible (%s)", exc, exc_info=True)
            QMessageBox.critical(None, "Erreur", f"Impossible d'exporter le diagnostic :\n{exc}")

    # ── Notifications de diarization ────────────────────────────────────────────

    def _on_diar_termine(self, md: object, _sortie: object) -> None:
        nom = getattr(md, "stem", str(md))
        self.showMessage(
            "Locuteurs générés",
            f"« {nom} » — cliquez pour ouvrir l'Historique.",
            icone_wavemark_pour_etat(EtatVisuel.TERMINE), 8000)

    def _on_diar_echoue(self, md: object, _message: str) -> None:
        nom = getattr(md, "stem", str(md))
        self.showMessage(
            "Diarization échouée",
            f"La génération des locuteurs de « {nom} » a échoué.",
            icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    # ── Notifications micro (robustesse hot-plug, docs/25) ──────────────────────

    def notifier_micro_perdu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Micro perdu", message, icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    def notifier_micro_retabli(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Micro rétabli", message, icone_wavemark_pour_etat(EtatVisuel.TERMINE), 8000)

    # ── Notification « rien entendu » (dictée/journal muets, docs/27) ───────────

    def notifier_rien_entendu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self.showMessage("Rien entendu", message, icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    def _on_notification_cliquee(self) -> None:
        # messageClicked n'indique pas quelle notif → on cible le dernier job terminé.
        cible = self._gestionnaire.dernier_termine() if self._gestionnaire else None
        self._fenetre_principale.selectionner_reunion(cible)
        self._afficher_fenetre_principale()
