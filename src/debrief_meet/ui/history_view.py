"""Vue Historique (refonte design) — table dense Réunions/Journal, recherche,
badges d'état. Remplace l'ancienne `FenetreHistorique` (QDialog + QListWidget) :
widget embarquable (Étape 4), pas de fenêtre autonome.

Porte à l'identique la logique métier de l'ancienne implémentation (actions,
diarization déléguée au gestionnaire persistant, rafraîchissement live) —
seule la présentation change (QTableView + délégués au lieu de lignes peintes
dans un QListWidget).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QModelIndex, QRectF, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import chemin_locuteurs, pistes_audio_existantes
from debrief_meet.platform.interfaces import PressePapiers
from debrief_meet.ui.actions_delegate import ActionSpec, ActionsDelegate
from debrief_meet.ui.capture_model import (
    COL_ACTIONS_JOURNAL,
    COL_ACTIONS_REUNION,
    COL_FICHIER_JOURNAL,
    COL_TITRE_REUNION,
    CaptureModel,
)
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.segmented import SegmentedControl
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


class HistoryView(QWidget):
    def __init__(
        self,
        config: Config,
        presse_papiers: PressePapiers | None = None,
        gestionnaire: GestionnaireDiarization | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._presse_papiers = presse_papiers
        self._gestionnaire = gestionnaire

        self._modele_reunions = CaptureModel(self._dossier(True), est_reunion=True, parent=self)
        self._modele_journal = CaptureModel(self._dossier(False), est_reunion=False, parent=self)

        self._proxy_reunions = self._creer_proxy(self._modele_reunions, COL_TITRE_REUNION)
        self._proxy_journal = self._creer_proxy(self._modele_journal, COL_FICHIER_JOURNAL)

        self._table_reunions = self._creer_table(self._proxy_reunions, est_reunion=True)
        self._table_journal = self._creer_table(self._proxy_journal, est_reunion=False)

        self._construire_ui()
        self._cabler_gestionnaire()
        self._installer_surveillance()
        self.recharger_tout()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _creer_proxy(self, modele: CaptureModel, colonne_filtre: int) -> QSortFilterProxyModel:
        proxy = QSortFilterProxyModel(self)
        proxy.setSourceModel(modele)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        proxy.setFilterKeyColumn(colonne_filtre)
        return proxy

    def _creer_table(self, proxy: QSortFilterProxyModel, est_reunion: bool) -> QTableView:
        table = QTableView(self)
        table.setModel(proxy)
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

        col_actions = COL_ACTIONS_REUNION if est_reunion else COL_ACTIONS_JOURNAL
        table.setItemDelegateForColumn(
            0, _BarreAccentDelegate(table))
        table.setItemDelegateForColumn(
            col_actions,
            ActionsDelegate(lambda idx, er=est_reunion: self._actions_pour_index(idx, er), table),
        )
        if est_reunion:
            table.setItemDelegateForColumn(4, StatusPillDelegate(table))

        entete = table.horizontalHeader()
        if est_reunion:
            table.setColumnWidth(0, 40)
            entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(2, 110)
            table.setColumnWidth(3, 74)
            table.setColumnWidth(4, 116)
            table.setColumnWidth(5, 200)
        else:
            table.setColumnWidth(0, 40)
            table.setColumnWidth(1, 200)
            entete.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(3, 150)

        raccourci = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), table)
        raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
        raccourci.activated.connect(lambda t=table, er=est_reunion: self._tout_supprimer(t, er, None))

        return table

    def _construire_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sous_entete = QWidget(self)
        sous_entete.setStyleSheet(f"background: {C.SURFACE}; border-bottom: 1px solid {C.BORDER_SOFT};")
        lay_entete = QHBoxLayout(sous_entete)
        lay_entete.setContentsMargins(20, 14, 20, 14)

        self._segmented = SegmentedControl(["Réunions", "Journal"], sous_entete)
        self._segmented.changed.connect(self._sur_segment_change)
        lay_entete.addWidget(self._segmented)
        lay_entete.addStretch()

        self._recherche = QLineEdit(sous_entete)
        self._recherche.setPlaceholderText("Rechercher une réunion…")
        self._recherche.setFixedWidth(260)
        self._recherche.textChanged.connect(self._sur_recherche_change)
        lay_entete.addWidget(self._recherche)

        layout.addWidget(sous_entete)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._table_reunions)
        self._pages.addWidget(self._table_journal)
        layout.addWidget(self._pages)

    def _sur_segment_change(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._recherche.setPlaceholderText(
            "Rechercher une réunion…" if index == 0 else "Rechercher dans le journal…")

    def _sur_recherche_change(self, texte: str) -> None:
        self._proxy_reunions.setFilterFixedString(texte)
        self._proxy_journal.setFilterFixedString(texte)

    # ── Chargement ───────────────────────────────────────────────────────────

    def _dossier(self, est_reunion: bool) -> Path:
        cle = "dossier_reunions" if est_reunion else "dossier_journal"
        return Path(self._config.get(cle))

    def recharger_tout(self) -> None:
        self._modele_reunions.recharger()
        self._modele_journal.recharger()

    # ── Actions par ligne (fournisseur du délégué) ──────────────────────────────

    def _actions_pour_index(self, index: QModelIndex, est_reunion: bool) -> list[ActionSpec]:
        proxy = index.model()
        source = proxy.mapToSource(index)
        modele = self._modele_reunions if est_reunion else self._modele_journal
        info = modele.info_ligne(source.row())
        if info is None:
            return []
        return self._actions_reunion(info) if est_reunion else self._actions_journal(info.chemin)

    def _actions_reunion(self, ligne) -> list[ActionSpec]:
        chemin = ligne.chemin
        job = self._gestionnaire.job_en_cours() if self._gestionnaire else None
        type_job = self._gestionnaire.type_job_en_cours() if self._gestionnaire else None
        en_cours = chemin == job
        un_job_tourne = job is not None

        actions = [ActionSpec(_ICONE_COPIER, "Copier la transcription", True,
                              lambda c=chemin: self._copier(c, True))]

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
            lambda c=chemin: self._tout_supprimer_un(c, True)))
        return actions

    def _actions_journal(self, chemin: Path) -> list[ActionSpec]:
        return [
            ActionSpec(_ICONE_COPIER, "Copier", True, lambda c=chemin: self._copier(c, False)),
            ActionSpec(_ICONE_OUVRIR, "Ouvrir", True, lambda c=chemin: self._ouvrir(c)),
            ActionSpec(_ICONE_REVELER, "Révéler dans le Finder", True, lambda c=chemin: self._reveler(c)),
            ActionSpec(_ICONE_TOUT_SUPPR, "Supprimer", True, lambda c=chemin: self._tout_supprimer_un(c, False)),
        ]

    # ── Sélection ──────────────────────────────────────────────────────────────

    def _chemins_selectionnes(self, table: QTableView, modele: CaptureModel) -> list[Path]:
        proxy = table.model()
        out: list[Path] = []
        lignes_vues = set()
        for proxy_idx in table.selectionModel().selectedIndexes():
            if proxy_idx.row() in lignes_vues:
                continue
            lignes_vues.add(proxy_idx.row())
            source = proxy.mapToSource(proxy_idx)
            chemin = modele.chemin_a_la_ligne(source.row())
            if chemin is not None:
                out.append(chemin)
        return out

    def _cibles(self, table: QTableView, modele: CaptureModel, chemin: Path | None) -> list[Path]:
        selection = self._chemins_selectionnes(table, modele)
        if chemin is None:
            return selection
        if chemin in selection and len(selection) > 1:
            return selection
        return [chemin]

    # ── Actions simples (mono-cible) ────────────────────────────────────────────

    def _copier(self, chemin: Path, est_reunion: bool) -> None:
        source = chemin
        if est_reunion:
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
        if chemin.exists():
            subprocess.Popen(["open", str(chemin)])

    def _reveler(self, chemin: Path) -> None:
        if chemin.exists():
            subprocess.Popen(["open", "-R", str(chemin)])

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
        self._modele_reunions.recharger()

    def _sur_diar_echoue(self, _md: object, message: str) -> None:
        self._modele_reunions.recharger()
        if self.isVisible():
            QMessageBox.warning(self, "Diarization — échec",
                                f"La génération des locuteurs a échoué :\n{message}")

    # ── Suppressions ────────────────────────────────────────────────────────────

    def _supprimer_audio_un(self, chemin: Path) -> None:
        cibles = [c for c in self._cibles(self._table_reunions, self._modele_reunions, chemin)
                  if pistes_audio_existantes(c)]
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
        self._modele_reunions.recharger()

    def _tout_supprimer_un(self, chemin: Path, est_reunion: bool) -> None:
        table = self._table_reunions if est_reunion else self._table_journal
        self._tout_supprimer(table, est_reunion, chemin)

    def _tout_supprimer(self, table: QTableView, est_reunion: bool, chemin: Path | None) -> None:
        modele = self._modele_reunions if est_reunion else self._modele_journal
        cibles = self._cibles(table, modele, chemin)
        if not cibles:
            return
        rep = QMessageBox.question(
            self, "Tout supprimer",
            f"Supprimer définitivement {len(cibles)} enregistrement(s) ?"
            + ("\n(Transcription + débrief locuteurs + audio retenu.)" if est_reunion else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        for c in cibles:
            self._supprimer_un(c, est_reunion)
        modele.recharger()

    def _supprimer_un(self, chemin: Path, est_reunion: bool) -> None:
        a_supprimer = [chemin]
        if est_reunion:
            a_supprimer.append(chemin_locuteurs(chemin))
            a_supprimer += pistes_audio_existantes(chemin)
        for p in a_supprimer:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    # ── Rafraîchissement live ────────────────────────────────────────────────────

    def _installer_surveillance(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        dossiers = {str(self._dossier(True)), str(self._dossier(False))}
        for d in dossiers:
            if Path(d).exists():
                self._watcher.addPath(d)
        self._watcher.directoryChanged.connect(self._sur_dossier_change)
        self._timer_refresh = QTimer(self)
        self._timer_refresh.setSingleShot(True)
        self._timer_refresh.setInterval(200)
        self._timer_refresh.timeout.connect(self.recharger_tout)

    def _sur_dossier_change(self, _chemin: str) -> None:
        self._timer_refresh.start()

    # ── Sélection programmatique (clic sur notification) ─────────────────────────

    def selectionner_reunion(self, chemin_md: Path | None) -> None:
        """Bascule sur l'onglet Réunions et sélectionne la ligne du `.md` donné."""
        self._segmented.definir_index(0)
        self._pages.setCurrentIndex(0)
        self._modele_reunions.recharger()
        if chemin_md is None:
            return
        row = self._modele_reunions.ligne_pour_chemin(Path(chemin_md))
        if row is None:
            return
        source_index = self._modele_reunions.index(row, 0)
        proxy_index = self._proxy_reunions.mapFromSource(source_index)
        self._table_reunions.selectionModel().clearSelection()
        self._table_reunions.selectRow(proxy_index.row())
        self._table_reunions.scrollTo(proxy_index)
