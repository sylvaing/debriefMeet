from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCursor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QWidget,
    QWidgetAction,
)

from debrief_meet.core.config import Config
from debrief_meet.core.diagnostic import dossier_diagnostic_par_defaut, exporter_diagnostic
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat
from debrief_meet.ui.fenetre_principale import FenetrePrincipale
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C

logger = logging.getLogger(__name__)

_TAILLE_ICONE_MENU = 14

# Couleurs des lignes du menu tray (§8.8 debriefMeet-C) : exception à la palette
# maison, alignée sur les libellés système macOS (texte #1D1D1F, pas ink-900).
_TRAY_TEXT = "#1D1D1F"
_TRAY_HOVER_FG = "#FFFFFF"
_TRAY_HOVER_BG = "#0A6CFF"


def _icone_menu(nom: str, hex_color: str = _TRAY_TEXT) -> QIcon:
    """Icône de ligne de menu tray — blanche au survol via `QIcon.Mode.Selected`,
    que Qt applique automatiquement à l'item actif d'un `QMenu` stylé en QSS
    (§8.8 : plus de couleurs d'icônes variées, tout suit le texte de la ligne)."""
    chemin = icone_phosphor(nom)
    icone = QIcon()
    icone.addPixmap(
        icone_svg_teintee(chemin, hex_color, _TAILLE_ICONE_MENU).pixmap(_TAILLE_ICONE_MENU, _TAILLE_ICONE_MENU),
        QIcon.Mode.Normal)
    icone.addPixmap(
        icone_svg_teintee(chemin, _TRAY_HOVER_FG, _TAILLE_ICONE_MENU).pixmap(_TAILLE_ICONE_MENU, _TAILLE_ICONE_MENU),
        QIcon.Mode.Selected)
    return icone


class _LigneQuitter(QWidget):
    """Ligne « Quitter » en rouge permanent (`#FF3B30`, convention macOS) — un
    `QAction` standard ne peut pas recevoir une couleur de texte statique via
    `QMenu::item` en QSS (le sélecteur ne cible pas un item précis), d'où ce
    `QWidgetAction` custom plutôt qu'une action classique."""

    cliquee = Signal()

    _QSS_REPOS = "QWidget#trayQuitRow { background: transparent; border-radius: 5px; }"
    _QSS_SURVOL = f"QWidget#trayQuitRow {{ background: {_TRAY_HOVER_BG}; border-radius: 5px; }}"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trayQuitRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._QSS_REPOS)

        self._pixmap_repos = icone_svg_teintee(
            icone_phosphor("sign-out"), C.REC, _TAILLE_ICONE_MENU).pixmap(_TAILLE_ICONE_MENU, _TAILLE_ICONE_MENU)
        self._pixmap_survol = icone_svg_teintee(
            icone_phosphor("sign-out"), _TRAY_HOVER_FG, _TAILLE_ICONE_MENU).pixmap(_TAILLE_ICONE_MENU, _TAILLE_ICONE_MENU)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(9)
        self._icone = QLabel(self)
        self._icone.setPixmap(self._pixmap_repos)
        lay.addWidget(self._icone)
        self._label = QLabel("Quitter", self)
        self._label.setObjectName("trayQuitLabel")
        self._label.setStyleSheet(f"color: {C.REC};")
        lay.addWidget(self._label)
        lay.addStretch()

    def enterEvent(self, event) -> None:
        self.setStyleSheet(self._QSS_SURVOL)
        self._icone.setPixmap(self._pixmap_survol)
        self._label.setStyleSheet(f"color: {_TRAY_HOVER_FG};")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setStyleSheet(self._QSS_REPOS)
        self._icone.setPixmap(self._pixmap_repos)
        self._label.setStyleSheet(f"color: {C.REC};")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.cliquee.emit()
        super().mouseReleaseEvent(event)


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
        # (type, payload, expire_epoch_s) — messageClicked n'indique pas quelle
        # notification a été cliquée (§8) ; on mémorise la dernière émise pour
        # décider quoi faire au clic. Toute notification écrase la précédente.
        self._derniere_notif: tuple[str, object, float] | None = None
        self._evenement_pre_associe = None  # Evenement BlueMind en attente de _sur_reunion_demarree

        self._construire_menu()
        self._actualiser_icone(EtatVisuel.REPOS)
        self.rafraichir_raccourcis()

        machine.mode_change.connect(self._on_mode_change)
        machine.erreur.connect(self._on_erreur)
        self.activated.connect(self._on_activation)
        self.messageClicked.connect(self._on_notification_cliquee)

        # Notification macOS de fin de diarization + clic → ouvre l'Historique (doc 09 §5).
        if gestionnaire is not None:
            gestionnaire.termine.connect(self._on_diar_termine)
            gestionnaire.echoue.connect(self._on_diar_echoue)

        self.setToolTip("debriefMeet")

    def _construire_menu(self) -> None:
        # Pas de `setContextMenu()` : sur macOS, un menu attaché s'ouvre au clic
        # gauche ET droit (limite Qt documentée, cf. IMPLEMENTATION_SPEC §8). Le
        # menu est affiché manuellement sur clic droit (`_on_activation`).
        menu = QMenu()
        menu.setObjectName("trayMenu")
        self._menu = menu

        self._action_dictee = QAction(_icone_menu("microphone"), "Démarrer Dictée", menu)
        self._action_dictee.triggered.connect(self._machine.toggle_dictee)
        menu.addAction(self._action_dictee)

        self._action_reunion = QAction(_icone_menu("users-three"), "Démarrer Réunion", menu)
        self._action_reunion.triggered.connect(self._machine.toggle_reunion)
        menu.addAction(self._action_reunion)

        self._action_journal = QAction(_icone_menu("notebook"), "Démarrer Journal", menu)
        self._action_journal.triggered.connect(self._machine.toggle_journal)
        menu.addAction(self._action_journal)

        # Qt masque par défaut les raccourcis dans les menus contextuels
        # (`shortcutVisibleInContextMenu`) — notre QMenu s'affiche via popup()
        # comme un menu contextuel, donc invisible sans ce forçage explicite.
        for action in (self._action_dictee, self._action_reunion, self._action_journal):
            action.setShortcutVisibleInContextMenu(True)

        menu.addSeparator()

        action_ouvrir = QAction(_icone_menu("arrow-square-out"), "Ouvrir debriefMeet", menu)
        action_ouvrir.triggered.connect(self._afficher_fenetre_principale)
        menu.addAction(action_ouvrir)
        menu.setDefaultAction(action_ouvrir)  # mis en avant (ordre spec §8) : gras, plus de fond permanent

        action_prefs = QAction(_icone_menu("gear"), "Préférences…", menu)
        action_prefs.triggered.connect(self._ouvrir_preferences)
        menu.addAction(action_prefs)

        action_diagnostic = QAction(_icone_menu("bug"), "Exporter le diagnostic…", menu)
        action_diagnostic.triggered.connect(self._exporter_diagnostic)
        menu.addAction(action_diagnostic)

        menu.addSeparator()

        ligne_quitter = _LigneQuitter(menu)
        ligne_quitter.cliquee.connect(menu.close)
        ligne_quitter.cliquee.connect(QApplication.quit)
        action_quitter = QWidgetAction(menu)
        action_quitter.setText("Quitter")  # gardé pour les tests/accessibilité ; rendu via le widget custom
        action_quitter.setDefaultWidget(ligne_quitter)
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
        self._derniere_notif = None
        self.showMessage(
            "Locuteurs générés",
            f"« {nom} » — cliquez pour ouvrir l'Historique.",
            icone_wavemark_pour_etat(EtatVisuel.TERMINE), 8000)

    def _on_diar_echoue(self, md: object, _message: str) -> None:
        nom = getattr(md, "stem", str(md))
        self._derniere_notif = None
        self.showMessage(
            "Diarization échouée",
            f"La génération des locuteurs de « {nom} » a échoué.",
            icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    # ── Notifications micro (robustesse hot-plug, docs/25) ──────────────────────

    def notifier_micro_perdu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self._derniere_notif = None
        self.showMessage("Micro perdu", message, icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    def notifier_micro_retabli(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self._derniere_notif = None
        self.showMessage("Micro rétabli", message, icone_wavemark_pour_etat(EtatVisuel.TERMINE), 8000)

    # ── Notification « rien entendu » (dictée/journal muets, docs/27) ───────────

    def notifier_rien_entendu(self, message: str) -> None:
        if not self._config.get("notifications"):
            return
        self._derniere_notif = None
        self.showMessage("Rien entendu", message, icone_wavemark_pour_etat(EtatVisuel.ERREUR), 8000)

    # ── Notification F3 — début de réunion (docs/40 §8) ─────────────────────────

    def notifier_reunion_due(self, evt: object) -> None:
        if not self._config.get("notifications"):
            return
        avance = int(self._config.get("bluemind_notif_avance_min") or 5)
        expire = evt.debut_ms / 1000 + 600  # début + 10 min (§8)
        self._derniere_notif = ("reunion", evt, expire)
        self.showMessage(
            f"« {evt.titre} »",
            f"Commence dans {avance} min — cliquez pour enregistrer.",
            icone_wavemark_pour_etat(EtatVisuel.REPOS), 10_000)

    def _sur_reunion_demarree(self, fichier: object) -> None:
        """Câblée sur `OrchestrateurReunion.reunion_demarree` — pré-associe le
        fichier tout juste créé si l'enregistrement vient du clic sur une
        notification F3 (§8)."""
        evt = self._evenement_pre_associe
        self._evenement_pre_associe = None
        if evt is None:
            return
        from pathlib import Path

        from debrief_meet.core.bluemind.association import associer_evenement
        associer_evenement(Path(str(fichier)), evt)

    def _on_notification_cliquee(self) -> None:
        if self._derniere_notif is not None:
            type_notif, payload, expire = self._derniere_notif
            if type_notif == "reunion" and time.time() <= expire:
                self._demarrer_reunion_pre_associee(payload)
                return
        # Toute autre notification (ou une notif « reunion » expirée) : comportement
        # historique — cibler le dernier job de diarization/transcription terminé.
        cible = self._gestionnaire.dernier_termine() if self._gestionnaire else None
        self._fenetre_principale.selectionner_reunion(cible)
        self._afficher_fenetre_principale()

    def _demarrer_reunion_pre_associee(self, evt: object) -> None:
        if self._machine.est_actif:
            self.showMessage(
                "Réunion", "Un enregistrement est déjà en cours.",
                icone_wavemark_pour_etat(EtatVisuel.ERREUR), 6000)
            return
        self._evenement_pre_associe = evt
        if not self._machine.toggle_reunion():
            self._evenement_pre_associe = None
