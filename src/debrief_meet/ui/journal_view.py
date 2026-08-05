"""Page Journal (refonte design v2, CHANGELOG_v2 §2/§5) — barre d'action
(bouton Démarrer/Arrêter + recherche) au-dessus de la liste des notes.

Porte la logique métier journal de l'ancienne `HistoryView` (v1, disparue).
Contrairement à Réunion, pas de ligne « en cours » ici (CHANGELOG_v2 §5).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.platform.interfaces import PressePapiers
from debrief_meet.ui import dialogues
from debrief_meet.ui.actions_delegate import (
    ActionsDelegate,
    ActionsLigne,
    ActionSpec,
    BoutonSpec,
    largeur_colonne,
)
from debrief_meet.ui.capture_action_bar import CaptureActionBar
from debrief_meet.ui.capture_model import COL_ACTIONS_JOURNAL, COL_FICHIER_JOURNAL, CaptureModel
from debrief_meet.ui.icon_delegate import IconeColonneDelegate
from debrief_meet.ui.survol_ligne import TableAvecSurvolLigne
from debrief_meet.ui.texte_delegate import TexteLigneDelegate
from debrief_meet.ui.theme import M

_ICONE_COPIER = "copy"
_ICONE_OUVRIR = "arrow-square-out"
_ICONE_REVELER = "folder"
_ICONE_TOUT_SUPPR = "trash"


class JournalView(QWidget):
    def __init__(
        self,
        config: Config,
        machine: MachineEtats,
        presse_papiers: PressePapiers | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._presse_papiers = presse_papiers

        self._modele = CaptureModel(self._dossier(), est_reunion=False, parent=self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._modele)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(COL_FICHIER_JOURNAL)

        self._table = self._creer_table()

        self._construire_ui(machine)
        self._installer_surveillance()
        self.recharger()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _creer_table(self) -> TableAvecSurvolLigne:
        table = TableAvecSurvolLigne(self)
        table.setModel(self._proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setFrameShape(TableAvecSurvolLigne.Shape.NoFrame)
        table.setSortingEnabled(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(M.ROW_H)
        table.setMouseTracking(True)

        table.setItemDelegate(TexteLigneDelegate(table))
        table.setItemDelegateForColumn(0, IconeColonneDelegate(table))
        table.setItemDelegateForColumn(
            COL_ACTIONS_JOURNAL, ActionsDelegate(self._actions_pour_index, table))

        entete = table.horizontalHeader()
        entete.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setColumnWidth(0, 40)
        table.setColumnWidth(1, 200)
        entete.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # Bouton Copier + ⋯ (§8.6.1) — cf. ActionsDelegate.sizeHint
        table.setColumnWidth(3, largeur_colonne(1))

        raccourci = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), table)
        raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
        raccourci.activated.connect(lambda: self._tout_supprimer(None))

        return table

    def _construire_ui(self, machine: MachineEtats) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._action_bar = CaptureActionBar(
            Mode.JOURNAL, avec_recherche=True, placeholder_recherche="Rechercher dans le journal…",
            actions_masse=True, avec_ignorer_audio=False, parent=self)
        self._action_bar.demande_bascule.connect(machine.toggle_journal)
        self._action_bar.recherche_change.connect(self._proxy.setFilterFixedString)
        # Actions en masse (§8.6.4) — Journal : suppression seule (pas d'« Ignorer l'audio »).
        self._action_bar.demande_supprimer_masse.connect(lambda: self._tout_supprimer(None))
        self._action_bar.demande_deselection.connect(self._table.clearSelection)
        self._table.selectionModel().selectionChanged.connect(self._sur_selection_change)
        self._modele.modelReset.connect(self._sur_selection_change)
        layout.addWidget(self._action_bar)

        layout.addWidget(self._table, 1)

    def _sur_selection_change(self, *_args) -> None:
        self._action_bar.definir_compte_selection(len(self._chemins_selectionnes()))

    # ── Machine à états (RecordingController) ───────────────────────────────────

    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None:
        self._action_bar.definir_etat(mode_actif, secondes)

    # ── Chargement ───────────────────────────────────────────────────────────

    def _dossier(self) -> Path:
        return Path(self._config.get("dossier_journal"))

    def recharger(self) -> None:
        self._modele.recharger()

    # ── Actions par ligne (fournisseur du délégué) ──────────────────────────────

    def _actions_pour_index(self, index: QModelIndex) -> ActionsLigne:
        proxy = index.model()
        source = proxy.mapToSource(index)
        info = self._modele.info_ligne(source.row())
        if info is None:
            return ActionsLigne()
        chemin = info.chemin
        return ActionsLigne(
            boutons=[BoutonSpec(_ICONE_COPIER, "Copier", True, lambda c=chemin: self._copier(c))],
            menu=[
                ActionSpec(_ICONE_COPIER, "Copier", True, lambda c=chemin: self._copier(c)),
                ActionSpec(_ICONE_OUVRIR, "Ouvrir", True, lambda c=chemin: self._ouvrir(c)),
                ActionSpec(_ICONE_REVELER, "Révéler dans le dossier", True,
                           lambda c=chemin: self._reveler(c)),
                ActionSpec(_ICONE_TOUT_SUPPR, "Supprimer", True,
                           lambda c=chemin: self._tout_supprimer_un(c),
                           danger=True, separateur_avant=True),
            ])

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

    # ── Actions simples ──────────────────────────────────────────────────────────

    def _copier(self, chemin: Path) -> None:
        if not chemin.exists():
            return
        texte = chemin.read_text(encoding="utf-8")
        if self._presse_papiers:
            self._presse_papiers.copier(texte)
        else:
            try:
                subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)
            except Exception:
                pass

    def _ouvrir(self, chemin: Path) -> None:
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

    # ── Suppressions ────────────────────────────────────────────────────────────

    def _tout_supprimer_un(self, chemin: Path) -> None:
        self._tout_supprimer(chemin)

    def _tout_supprimer(self, chemin: Path | None) -> None:
        cibles = self._cibles(chemin)
        if not cibles:
            return
        n = len(cibles)
        noun = "entrées" if n > 1 else "entrée"
        verbe = "seront supprimées" if n > 1 else "sera supprimée"
        confirme = dialogues.confirmer(
            self, titre=f"Supprimer {n} {noun} ?",
            description=f"{n} {noun} {verbe} définitivement (notes et audio inclus).",
            label_action="Supprimer", icone="trash")
        if not confirme:
            return
        for c in cibles:
            try:
                if c.exists():
                    c.unlink()
            except OSError:
                pass
        self._modele.recharger()

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
