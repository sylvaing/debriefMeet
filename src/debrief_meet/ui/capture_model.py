"""Modèle de table des captures (Historique, refonte design) — un par onglet
(Réunions / Journal), même classe paramétrée par `est_reunion`.

Les valeurs affichées sont précalculées à `recharger()` (une passe disque par
ligne), pas recalculées à chaque `data()` — cf. l'ancienne `FenetreHistorique`
qui construisait déjà les lignes une seule fois par rechargement.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from debrief_meet.core.fichiers import (
    apercu_journal,
    chemin_locuteurs,
    date_heure_reunion,
    definir_titre,
    duree_reunion,
    formater_duree,
    lister_enregistrements,
    pistes_audio_existantes,
    titre_reunion,
    transcription_en_attente,
)
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.status_pill import HistoryState
from debrief_meet.ui.theme import C

# Rôle custom : chemin du fichier associé à la ligne (toutes colonnes). `Qt.UserRole`
# reste réservé à `HistoryState` sur la colonne état (contrat de `StatusPillDelegate`).
ROLE_CHEMIN = Qt.ItemDataRole.UserRole + 1

COLS_REUNIONS = ("type", "titre", "date", "durée", "état", "actions")
COLS_JOURNAL = ("icône", "fichier", "note", "actions")

_ENTETES_REUNIONS = ("", "TITRE", "DATE", "DURÉE", "ÉTAT", "")
_ENTETES_JOURNAL = ("", "FICHIER", "NOTE", "")

COL_TITRE_REUNION = 1
COL_ACTIONS_REUNION = 5
COL_FICHIER_JOURNAL = 1
COL_ACTIONS_JOURNAL = 3


@dataclass
class _LigneReunion:
    chemin: Path
    titre_affiche: str
    titre_brut: str
    date_texte: str
    duree_texte: str
    etat: HistoryState
    audio: list[Path]
    locuteurs: bool
    en_attente: bool


@dataclass
class _LigneJournal:
    chemin: Path
    nom: str
    note: str


def _construire_ligne_reunion(chemin: Path) -> _LigneReunion:
    dh = date_heure_reunion(chemin)
    titre = titre_reunion(chemin)
    duree_secondes = duree_reunion(chemin)
    audio = pistes_audio_existantes(chemin)
    locuteurs = chemin_locuteurs(chemin).exists()
    en_attente = transcription_en_attente(chemin)

    if locuteurs:
        etat = HistoryState.LOCUTEURS
    elif en_attente:
        etat = HistoryState.AUDIO_SEUL
    else:
        etat = HistoryState.TRANSCRIT

    return _LigneReunion(
        chemin=chemin,
        titre_affiche=titre or (dh.strftime("%d/%m/%Y %H:%M") if dh else chemin.stem),
        titre_brut=titre or "",
        date_texte=dh.strftime("%d/%m/%Y") if dh else "—",
        duree_texte=formater_duree(duree_secondes),
        etat=etat,
        audio=audio,
        locuteurs=locuteurs,
        en_attente=en_attente,
    )


def _construire_ligne_journal(chemin: Path) -> _LigneJournal:
    return _LigneJournal(chemin=chemin, nom=chemin.name, note=apercu_journal(chemin))


class CaptureModel(QAbstractTableModel):
    """Table des enregistrements d'un dossier (Réunions ou Journal selon `est_reunion`)."""

    def __init__(self, dossier: Path, est_reunion: bool, parent=None) -> None:
        super().__init__(parent)
        self._dossier = dossier
        self._est_reunion = est_reunion
        self._lignes: list[_LigneReunion] | list[_LigneJournal] = []

    # ── API Qt ───────────────────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._lignes)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else (6 if self._est_reunion else 4)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        entetes = _ENTETES_REUNIONS if self._est_reunion else _ENTETES_JOURNAL
        return entetes[section]

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._est_reunion and index.column() == COL_TITRE_REUNION:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._lignes)):
            return None
        ligne = self._lignes[index.row()]
        col = index.column()

        if role == ROLE_CHEMIN:
            return ligne.chemin

        if self._est_reunion:
            return self._data_reunion(ligne, col, role)
        return self._data_journal(ligne, col, role)

    def _data_reunion(self, ligne: _LigneReunion, col: int, role: int):
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return icone_svg_teintee(icone_phosphor("users-three"), C.INK400, 16)
        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == COL_TITRE_REUNION:
                return ligne.titre_brut if role == Qt.ItemDataRole.EditRole else ligne.titre_affiche
            if col == 2:
                return ligne.date_texte
            if col == 3:
                return ligne.duree_texte
        if role == Qt.ItemDataRole.UserRole and col == 4:
            return ligne.etat
        return None

    def _data_journal(self, ligne: _LigneJournal, col: int, role: int):
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return icone_svg_teintee(icone_phosphor("notebook"), C.INK400, 16)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_FICHIER_JOURNAL:
                return ligne.nom
            if col == 2:
                return ligne.note
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if (not self._est_reunion or index.column() != COL_TITRE_REUNION
                or role != Qt.ItemDataRole.EditRole):
            return False
        ligne = self._lignes[index.row()]
        nouveau = str(value).strip()
        if nouveau == ligne.titre_brut:
            return False
        definir_titre(ligne.chemin, nouveau)
        self._lignes[index.row()] = _construire_ligne_reunion(ligne.chemin)
        self.dataChanged.emit(index, index)
        return True

    # ── Chargement ───────────────────────────────────────────────────────────

    def chemin_a_la_ligne(self, row: int) -> Path | None:
        if 0 <= row < len(self._lignes):
            return self._lignes[row].chemin
        return None

    def info_ligne(self, row: int) -> _LigneReunion | _LigneJournal | None:
        if 0 <= row < len(self._lignes):
            return self._lignes[row]
        return None

    def ligne_pour_chemin(self, chemin: Path) -> int | None:
        for i, ligne in enumerate(self._lignes):
            if ligne.chemin == chemin:
                return i
        return None

    def recharger(self) -> None:
        fichiers = lister_enregistrements(self._dossier)
        constructeur = _construire_ligne_reunion if self._est_reunion else _construire_ligne_journal
        self.beginResetModel()
        self._lignes = [constructeur(f) for f in fichiers]
        self.endResetModel()
