"""Modèle de table des captures (Historique, refonte design) — un par onglet
(Réunions / Journal), même classe paramétrée par `est_reunion`.

Les valeurs affichées sont précalculées à `recharger()` (une passe disque par
ligne), pas recalculées à chaque `data()` — cf. l'ancienne `FenetreHistorique`
qui construisait déjà les lignes une seule fois par rechargement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from debrief_meet.core.fichiers import (
    apercu_journal,
    chemin_cr_mistral,
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
from debrief_meet.ui.chrono import formater_chrono
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.status_pill import HistoryState
from debrief_meet.ui.theme import C, MONO, SANS

# Polices/couleurs des colonnes texte (CHANGELOG_v2 §1, « polices des lignes
# d'historique ») — lues par `TexteLigneDelegate` (Qt.FontRole/Qt.ForegroundRole).
_FONT_TITRE = QFont(SANS, 13.5, QFont.Weight.Bold)
_FONT_MONO = QFont(MONO, 12)
_FONT_FICHIER = QFont(MONO, 13, QFont.Weight.Medium)
_FONT_NOTE = QFont(SANS, 12.5)
_COULEUR_SECONDAIRE = QColor(C.INK500)

# Rôle custom : chemin du fichier associé à la ligne (toutes colonnes). `Qt.UserRole`
# reste réservé à `HistoryState` sur la colonne état (contrat de `StatusPillDelegate`).
ROLE_CHEMIN = Qt.ItemDataRole.UserRole + 1

COLS_REUNIONS = ("type", "titre", "date", "durée", "état", "calendrier", "actions")
COLS_JOURNAL = ("icône", "fichier", "note", "actions")

_ENTETES_REUNIONS = ("", "TITRE", "DATE", "DURÉE", "ÉTAT", "", "")
_ENTETES_JOURNAL = ("", "FICHIER", "NOTE", "")

COL_TITRE_REUNION = 1
COL_CALENDRIER_REUNION = 5  # DESIGN.md §8.6.2 — colonne dédiée, sortie de la rangée d'actions
COL_ACTIONS_REUNION = 6
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
    cr_disponible: bool = False  # CR généré par une IA externe (Mistral) — <stem>_CR.md
    en_cours: bool = False  # ligne live insérée en tête pendant l'enregistrement (pas de fichier réel)


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
    cr_disponible = chemin_cr_mistral(chemin).exists()

    # Priorité : le CR (livrable final d'une IA externe) prime sur l'état du pipeline
    # de transcription/locuteurs.
    if cr_disponible:
        etat = HistoryState.CR_DISPONIBLE
    elif locuteurs:
        etat = HistoryState.LOCUTEURS
    elif en_attente:
        etat = HistoryState.AUDIO_SEUL
    else:
        etat = HistoryState.TRANSCRIT

    return _LigneReunion(
        chemin=chemin,
        titre_affiche=titre or (dh.strftime("%d/%m/%Y %H:%M") if dh else chemin.stem),
        titre_brut=titre or "",
        date_texte=dh.strftime("%d/%m/%Y · %H:%M") if dh else "—",
        duree_texte=formater_duree(duree_secondes),
        etat=etat,
        audio=audio,
        locuteurs=locuteurs,
        en_attente=en_attente,
        cr_disponible=cr_disponible,
    )


def _construire_ligne_journal(chemin: Path) -> _LigneJournal:
    return _LigneJournal(chemin=chemin, nom=chemin.name, note=apercu_journal(chemin))


def _construire_ligne_en_cours(secondes: int) -> _LigneReunion:
    """Ligne « Réunion en cours » (CHANGELOG_v2 §3) — pas de fichier réel, chemin
    sentinelle jamais déréférencé (actions désactivées, ligne non sélectionnable)."""
    return _LigneReunion(
        chemin=Path(),
        titre_affiche="Réunion en cours",
        titre_brut="",
        date_texte=datetime.now().strftime("%d/%m/%Y · %H:%M"),
        duree_texte=formater_chrono(secondes),
        etat=HistoryState.EN_COURS,
        audio=[],
        locuteurs=False,
        en_attente=False,
        en_cours=True,
    )


class CaptureModel(QAbstractTableModel):
    """Table des enregistrements d'un dossier (Réunions ou Journal selon `est_reunion`)."""

    def __init__(self, dossier: Path, est_reunion: bool, parent=None) -> None:
        super().__init__(parent)
        self._dossier = dossier
        self._est_reunion = est_reunion
        self._lignes: list[_LigneReunion] | list[_LigneJournal] = []
        self._ligne_en_cours: _LigneReunion | None = None  # Réunion uniquement (CHANGELOG_v2 §3)

    # ── API Qt ───────────────────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._lignes) + (1 if self._ligne_en_cours is not None else 0)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else (7 if self._est_reunion else 4)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        entetes = _ENTETES_REUNIONS if self._est_reunion else _ENTETES_JOURNAL
        return entetes[section]

    def _ligne_a_index(self, row: int) -> _LigneReunion | _LigneJournal | None:
        if self._ligne_en_cours is not None:
            if row == 0:
                return self._ligne_en_cours
            row -= 1
        if 0 <= row < len(self._lignes):
            return self._lignes[row]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        ligne = self._ligne_a_index(index.row()) if index.isValid() else None
        if isinstance(ligne, _LigneReunion) and ligne.en_cours:
            return Qt.ItemFlag.ItemIsEnabled  # ni sélectionnable ni éditable
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._est_reunion and index.column() == COL_TITRE_REUNION:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        ligne = self._ligne_a_index(index.row())
        if ligne is None:
            return None
        col = index.column()

        if role == ROLE_CHEMIN:
            return ligne.chemin

        if self._est_reunion:
            return self._data_reunion(ligne, col, role)
        return self._data_journal(ligne, col, role)

    def _data_reunion(self, ligne: _LigneReunion, col: int, role: int):
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            icone = "microphone" if ligne.en_cours else "users-three"
            return icone_svg_teintee(icone_phosphor(icone), C.INK400, 16)
        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == COL_TITRE_REUNION:
                return ligne.titre_brut if role == Qt.ItemDataRole.EditRole else ligne.titre_affiche
            if col == 2:
                return ligne.date_texte
            if col == 3:
                return ligne.duree_texte
        if role == Qt.ItemDataRole.FontRole:
            if col == COL_TITRE_REUNION:
                return _FONT_TITRE
            if col in (2, 3):
                return _FONT_MONO
        if role == Qt.ItemDataRole.ForegroundRole and col in (2, 3):
            return _COULEUR_SECONDAIRE
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
        if role == Qt.ItemDataRole.FontRole:
            if col == COL_FICHIER_JOURNAL:
                return _FONT_FICHIER
            if col == 2:
                return _FONT_NOTE
        if role == Qt.ItemDataRole.ForegroundRole and col == 2:
            return _COULEUR_SECONDAIRE
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if (not self._est_reunion or index.column() != COL_TITRE_REUNION
                or role != Qt.ItemDataRole.EditRole):
            return False
        ligne = self._ligne_a_index(index.row())
        if ligne is None or ligne.en_cours:
            return False
        nouveau = str(value).strip()
        if nouveau == ligne.titre_brut:
            return False
        definir_titre(ligne.chemin, nouveau)
        offset = 1 if self._ligne_en_cours is not None else 0
        self._lignes[index.row() - offset] = _construire_ligne_reunion(ligne.chemin)
        self.dataChanged.emit(index, index)
        return True

    # ── Ligne « en cours » (Réunion, CHANGELOG_v2 §3) ───────────────────────────

    def definir_ligne_en_cours(self, active: bool, secondes: int = 0) -> None:
        """Insère/retire/actualise la ligne « Réunion en cours » en tête de table."""
        if not self._est_reunion:
            return
        if not active:
            if self._ligne_en_cours is not None:
                self.beginRemoveRows(QModelIndex(), 0, 0)
                self._ligne_en_cours = None
                self.endRemoveRows()
            return
        if self._ligne_en_cours is None:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._ligne_en_cours = _construire_ligne_en_cours(secondes)
            self.endInsertRows()
        else:
            self._ligne_en_cours = _construire_ligne_en_cours(secondes)
            self.dataChanged.emit(self.index(0, 2), self.index(0, 3))

    # ── Chargement ───────────────────────────────────────────────────────────

    def chemin_a_la_ligne(self, row: int) -> Path | None:
        ligne = self._ligne_a_index(row)
        if ligne is None or (isinstance(ligne, _LigneReunion) and ligne.en_cours):
            return None
        return ligne.chemin

    def info_ligne(self, row: int) -> _LigneReunion | _LigneJournal | None:
        return self._ligne_a_index(row)

    def ligne_pour_chemin(self, chemin: Path) -> int | None:
        offset = 1 if self._ligne_en_cours is not None else 0
        for i, ligne in enumerate(self._lignes):
            if ligne.chemin == chemin:
                return i + offset
        return None

    def recharger(self) -> None:
        fichiers = lister_enregistrements(self._dossier)
        constructeur = _construire_ligne_reunion if self._est_reunion else _construire_ligne_journal
        self.beginResetModel()
        self._lignes = [constructeur(f) for f in fichiers]
        self.endResetModel()
