"""Page Réunion (refonte design v2, CHANGELOG_v2 §2/§3) — barre d'action
(bouton Démarrer/Arrêter + recherche) au-dessus du tableau des réunions, avec
une ligne « en cours » insérée en tête pendant l'enregistrement.

Porte la logique métier réunion de l'ancienne `HistoryView` (v1, disparue) —
actions, diarization déléguée au gestionnaire persistant, rafraîchissement
live. La partie Journal vit désormais dans `journal_view.py`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QModelIndex, QRectF, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import chemin_locuteurs, pistes_audio_existantes
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.platform.interfaces import PressePapiers
from debrief_meet.ui.actions_delegate import ActionSpec, ActionsDelegate
from debrief_meet.ui.capture_action_bar import CaptureActionBar
from debrief_meet.ui.capture_model import COL_ACTIONS_REUNION, COL_TITRE_REUNION, CaptureModel
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.status_pill import StatusPillDelegate
from debrief_meet.ui.theme import C, M, color

_ICONE_COPIER = "copy"
_ICONE_TRANSCRIRE = "file-text"
_ICONE_GENERER = "users"
_ICONE_EN_COURS = "clock-counter-clockwise"
_ICONE_OUVRIR = "arrow-square-out"
_ICONE_REVELER = "folder"
_ICONE_SUPPR_AUDIO = "microphone-slash"
_ICONE_TOUT_SUPPR = "trash"


class _BarreAccentDelegate(QStyledItemDelegate):
    """Colonne 0 : rendu standard (icône type) + barre d'accent 3px si sélectionnée."""

    LARGEUR = 3

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            rect = QRectF(option.rect.left(), option.rect.top(), self.LARGEUR, option.rect.height())
            painter.fillRect(rect, color(C.ACCENT))
            painter.restore()


class ReunionView(QWidget):
    def __init__(
        self,
        config: Config,
        machine: MachineEtats,
        presse_papiers: PressePapiers | None = None,
        gestionnaire: GestionnaireDiarization | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._presse_papiers = presse_papiers
        self._gestionnaire = gestionnaire

        self._modele = CaptureModel(self._dossier(), est_reunion=True, parent=self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._modele)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(COL_TITRE_REUNION)

        self._table = self._creer_table()

        self._construire_ui(machine)
        self._cabler_gestionnaire()
        self._installer_surveillance()
        self.recharger()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _creer_table(self) -> QTableView:
        table = QTableView(self)
        table.setModel(self._proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setFrameShape(QTableView.Shape.NoFrame)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(M.ROW_H)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        table.setMouseTracking(True)

        table.setItemDelegateForColumn(0, _BarreAccentDelegate(table))
        table.setItemDelegateForColumn(
            COL_ACTIONS_REUNION, ActionsDelegate(self._actions_pour_index, table))
        table.setItemDelegateForColumn(4, StatusPillDelegate(table))

        entete = table.horizontalHeader()
        table.setColumnWidth(0, 40)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(2, 110)
        table.setColumnWidth(3, 74)
        table.setColumnWidth(4, 116)
        table.setColumnWidth(5, 200)

        raccourci = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), table)
        raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
        raccourci.activated.connect(lambda: self._tout_supprimer(None))

        return table

    def _construire_ui(self, machine: MachineEtats) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._action_bar = CaptureActionBar(
            Mode.REUNION, avec_recherche=True, placeholder_recherche="Rechercher une réunion…", parent=self)
        self._action_bar.demande_bascule.connect(machine.toggle_reunion)
        self._action_bar.recherche_change.connect(self._proxy.setFilterFixedString)
        layout.addWidget(self._action_bar)

        layout.addWidget(self._table, 1)

    # ── Machine à états (RecordingController) ───────────────────────────────────

    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None:
        self._action_bar.definir_etat(mode_actif, secondes)
        self._modele.definir_ligne_en_cours(mode_actif is Mode.REUNION, secondes)

    # ── Chargement ───────────────────────────────────────────────────────────

    def _dossier(self) -> Path:
        return Path(self._config.get("dossier_reunions"))

    def recharger(self) -> None:
        self._modele.recharger()

    # ── Actions par ligne (fournisseur du délégué) ──────────────────────────────

    def _actions_pour_index(self, index: QModelIndex) -> list[ActionSpec]:
        proxy = index.model()
        source = proxy.mapToSource(index)
        info = self._modele.info_ligne(source.row())
        if info is None or info.en_cours:
            return []
        return self._actions_reunion(info)

    def _actions_reunion(self, ligne) -> list[ActionSpec]:
        chemin = ligne.chemin
        job = self._gestionnaire.job_en_cours() if self._gestionnaire else None
        type_job = self._gestionnaire.type_job_en_cours() if self._gestionnaire else None
        en_cours = chemin == job
        un_job_tourne = job is not None

        actions = [ActionSpec(_ICONE_COPIER, "Copier la transcription", True,
                              lambda c=chemin: self._copier(c))]

        if ligne.en_attente:
            if en_cours and type_job == "transcription":
                actions.append(ActionSpec(_ICONE_EN_COURS, "Transcription en cours…", False, lambda: None))
            else:
                dispo = self._gestionnaire is not None and self._gestionnaire.disponible()
                actif = dispo and bool(ligne.audio) and not un_job_tourne
                tooltip = "Transcrire la réunion"
                if not ligne.audio:
                    tooltip = "Aucun audio à transcrire"
                elif not dispo:
                    tooltip = "Moteur de transcription indisponible"
                elif un_job_tourne:
                    tooltip = "Une tâche est déjà en cours"
                actions.append(ActionSpec(_ICONE_TRANSCRIRE, tooltip, actif,
                                          lambda c=chemin: self._transcrire(c)))
        else:
            if en_cours and type_job == "diarization":
                actions.append(
                    ActionSpec(_ICONE_EN_COURS, "Génération des locuteurs en cours…", False, lambda: None))
            else:
                prete = self._gestionnaire is not None and self._gestionnaire.diarization_prete()
                actif = prete and bool(ligne.audio) and not ligne.locuteurs and not un_job_tourne
                tooltip = "Générer les locuteurs"
                if ligne.locuteurs:
                    tooltip = "Locuteurs déjà générés"
                elif not ligne.audio:
                    tooltip = "Aucun audio retenu"
                elif not prete:
                    tooltip = "Diarization non configurée — Préférences › Audio"
                elif un_job_tourne:
                    tooltip = "Une génération est déjà en cours"
                actions.append(ActionSpec(_ICONE_GENERER, tooltip, actif,
                                          lambda c=chemin: self._generer(c)))

        actions.append(ActionSpec(_ICONE_OUVRIR, "Ouvrir la transcription", True,
                                  lambda c=chemin: self._ouvrir(c)))
        actions.append(ActionSpec(_ICONE_REVELER, "Révéler dans le Finder", True,
                                  lambda c=chemin: self._reveler(c)))
        actions.append(ActionSpec(
            _ICONE_SUPPR_AUDIO, "Supprimer l'audio (garde le débrief)", bool(ligne.audio),
            lambda c=chemin: self._supprimer_audio_un(c)))
        actions.append(ActionSpec(
            _ICONE_TOUT_SUPPR, "Tout supprimer (transcription + locuteurs + audio)", True,
            lambda c=chemin: self._tout_supprimer_un(c)))
        return actions

    # ── Sélection ──────────────────────────────────────────────────────────────

    def _chemins_selectionnes(self) -> list[Path]:
        out: list[Path] = []
        lignes_vues = set()
        for proxy_idx in self._table.selectionModel().selectedIndexes():
            if proxy_idx.row() in lignes_vues:
                continue
            lignes_vues.add(proxy_idx.row())
            source = self._proxy.mapToSource(proxy_idx)
            chemin = self._modele.chemin_a_la_ligne(source.row())
            if chemin is not None:
                out.append(chemin)
        return out

    def _cibles(self, chemin: Path | None) -> list[Path]:
        selection = self._chemins_selectionnes()
        if chemin is None:
            return selection
        if chemin in selection and len(selection) > 1:
            return selection
        return [chemin]

    # ── Actions simples (mono-cible) ────────────────────────────────────────────

    def _copier(self, chemin: Path) -> None:
        source = chemin
        loc = chemin_locuteurs(chemin)
        if loc.exists():
            source = loc
        if not source.exists():
            return
        texte = source.read_text(encoding="utf-8")
        from debrief_meet.core import prompts as _prompts
        contenu = _prompts.contenu_actif(self._config.get("prompts"), self._config.get("prompt_actif"))
        if contenu:
            texte = _prompts.prefixer(texte, contenu)
        if self._presse_papiers:
            self._presse_papiers.copier(texte)
        else:
            try:
                subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)
            except Exception:
                pass

    def _ouvrir(self, chemin: Path) -> None:
        # `open` (macOS) n'existe pas sur Windows — trouvé en test interactif réel
        # sur la VM (2026-07-04) : crash FileNotFoundError [WinError 2] ailleurs
        # dans les Préférences pour ce même motif.
        if not chemin.exists():
            return
        if sys.platform == "win32":
            os.startfile(str(chemin))  # noqa: S606 — ouverture explicite demandée par l'utilisateur
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin)])

    def _reveler(self, chemin: Path) -> None:
        if not chemin.exists():
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(chemin)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin.parent)])

    # ── Diarization (déléguée au gestionnaire persistant) ───────────────────────

    def _generer(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.diarization_prete():
            return
        if not pistes_audio_existantes(chemin):
            QMessageBox.information(
                self, "Diarization",
                f"Aucun audio retenu pour « {chemin.name} ».\n"
                "Activez la rétention audio dans les Préférences avant la réunion.")
            return
        if not self._gestionnaire.lancer(chemin):
            QMessageBox.information(self, "Diarization", "Une génération est déjà en cours.")

    def _transcrire(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.disponible():
            return
        if not pistes_audio_existantes(chemin):
            QMessageBox.information(self, "Transcription", f"Aucun audio retenu pour « {chemin.name} ».")
            return
        if not self._gestionnaire.lancer_transcription(chemin):
            QMessageBox.information(self, "Transcription", "Une tâche est déjà en cours.")

    def _cabler_gestionnaire(self) -> None:
        if self._gestionnaire is None:
            return
        self._gestionnaire.demarre.connect(self._sur_diar_change)
        self._gestionnaire.termine.connect(self._sur_diar_change)
        self._gestionnaire.echoue.connect(self._sur_diar_echoue)

    def _sur_diar_change(self, *_args) -> None:
        self._modele.recharger()

    def _sur_diar_echoue(self, _md: object, message: str) -> None:
        self._modele.recharger()
        if self.isVisible():
            QMessageBox.warning(self, "Diarization — échec",
                                f"La génération des locuteurs a échoué :\n{message}")

    # ── Suppressions ────────────────────────────────────────────────────────────

    def _supprimer_audio_un(self, chemin: Path) -> None:
        cibles = [c for c in self._cibles(chemin) if pistes_audio_existantes(c)]
        if not cibles:
            QMessageBox.information(self, "Audio retenu", "Aucun audio retenu à supprimer.")
            return
        rep = QMessageBox.question(
            self, "Supprimer l'audio retenu",
            f"Supprimer l'audio retenu de {len(cibles)} réunion(s) ?\n"
            "(Le débrief reste ; la diarization ne sera plus regénérable.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        for c in cibles:
            for p in pistes_audio_existantes(c):
                try:
                    p.unlink()
                except OSError:
                    pass
        self._modele.recharger()

    def _tout_supprimer_un(self, chemin: Path) -> None:
        self._tout_supprimer(chemin)

    def _tout_supprimer(self, chemin: Path | None) -> None:
        cibles = self._cibles(chemin)
        if not cibles:
            return
        rep = QMessageBox.question(
            self, "Tout supprimer",
            f"Supprimer définitivement {len(cibles)} enregistrement(s) ?"
            "\n(Transcription + débrief locuteurs + audio retenu.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        for c in cibles:
            self._supprimer_un(c)
        self._modele.recharger()

    def _supprimer_un(self, chemin: Path) -> None:
        a_supprimer = [chemin, chemin_locuteurs(chemin), *pistes_audio_existantes(chemin)]
        for p in a_supprimer:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    # ── Rafraîchissement live ────────────────────────────────────────────────────

    def _installer_surveillance(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        dossier = str(self._dossier())
        if Path(dossier).exists():
            self._watcher.addPath(dossier)
        self._watcher.directoryChanged.connect(self._sur_dossier_change)
        self._timer_refresh = QTimer(self)
        self._timer_refresh.setSingleShot(True)
        self._timer_refresh.setInterval(200)
        self._timer_refresh.timeout.connect(self.recharger)

    def _sur_dossier_change(self, _chemin: str) -> None:
        self._timer_refresh.start()

    # ── Sélection programmatique (clic sur notification) ─────────────────────────

    def selectionner_reunion(self, chemin_md: Path | None) -> None:
        """Sélectionne la ligne du `.md` donné."""
        self._modele.recharger()
        if chemin_md is None:
            return
        row = self._modele.ligne_pour_chemin(Path(chemin_md))
        if row is None:
            return
        source_index = self._modele.index(row, 0)
        proxy_index = self._proxy.mapFromSource(source_index)
        self._table.selectionModel().clearSelection()
        self._table.selectRow(proxy_index.row())
        self._table.scrollTo(proxy_index)
