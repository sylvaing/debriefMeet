from __future__ import annotations

import wave
from datetime import datetime

import pytest
from PySide6.QtCore import Qt

from debrief_meet.core.fichiers import (
    MARQUEUR_EN_ATTENTE,
    EcrivainJournal,
    chemin_reunion,
    definir_titre,
)
from debrief_meet.ui.capture_model import (
    COL_FICHIER_JOURNAL,
    COL_TITRE_REUNION,
    ROLE_CHEMIN,
    CaptureModel,
)
from debrief_meet.ui.status_pill import HistoryState


def _creer_reunion(dossier, *, titre=None, avec_audio=False, avec_locuteurs=False):
    md = chemin_reunion(dossier, datetime(2026, 7, 4, 10, 30))
    md.write_text("# Réunion — 2026-07-04 10:30\n\ntranscription\n", encoding="utf-8")
    if titre:
        definir_titre(md, titre)
    if avec_audio:
        with wave.open(str(dossier / f"{md.stem}_moi.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 160)
    if avec_locuteurs:
        (dossier / f"{md.stem}_locuteurs.md").write_text("locuteurs", encoding="utf-8")
    return md


def test_reunion_colonnes_et_lignes(qapp, tmp_path):
    _creer_reunion(tmp_path, titre="Point équipe")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()

    assert modele.rowCount() == 1
    assert modele.columnCount() == 6
    idx_titre = modele.index(0, COL_TITRE_REUNION)
    assert modele.data(idx_titre) == "Point équipe"
    assert modele.data(idx_titre, ROLE_CHEMIN) is not None


@pytest.mark.parametrize(
    "avec_audio, avec_locuteurs, etat_attendu",
    [
        (False, False, HistoryState.TRANSCRIT),
        (True, True, HistoryState.LOCUTEURS),
    ],
)
def test_etat_priorite(qapp, tmp_path, avec_audio, avec_locuteurs, etat_attendu):
    _creer_reunion(tmp_path, avec_audio=avec_audio, avec_locuteurs=avec_locuteurs)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    idx_etat = modele.index(0, 4)
    assert modele.data(idx_etat, Qt.ItemDataRole.UserRole) == etat_attendu


def test_etat_audio_seul_en_attente(qapp, tmp_path):
    md = _creer_reunion(tmp_path, avec_audio=True)
    md.write_text(md.read_text(encoding="utf-8") + f"\n> {MARQUEUR_EN_ATTENTE}\n", encoding="utf-8")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert modele.data(modele.index(0, 4), Qt.ItemDataRole.UserRole) == HistoryState.AUDIO_SEUL


def test_titre_editable_et_pas_les_autres_colonnes(qapp, tmp_path):
    _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert modele.flags(modele.index(0, COL_TITRE_REUNION)) & Qt.ItemFlag.ItemIsEditable
    assert not (modele.flags(modele.index(0, 2)) & Qt.ItemFlag.ItemIsEditable)


def test_set_data_renomme_et_persiste(qapp, tmp_path):
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    idx = modele.index(0, COL_TITRE_REUNION)
    ok = modele.setData(idx, "Nouveau titre", Qt.ItemDataRole.EditRole)
    assert ok is True
    assert modele.data(idx) == "Nouveau titre"

    relu = CaptureModel(tmp_path, est_reunion=True)
    relu.recharger()
    assert relu.data(relu.index(0, COL_TITRE_REUNION)) == "Nouveau titre"


def test_set_data_meme_valeur_ne_reecrit_pas(qapp, tmp_path):
    _creer_reunion(tmp_path, titre="Titre stable")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    idx = modele.index(0, COL_TITRE_REUNION)
    assert modele.setData(idx, "Titre stable", Qt.ItemDataRole.EditRole) is False


def test_journal_colonnes(qapp, tmp_path):
    EcrivainJournal(tmp_path).ajouter_entree("Une note importante")
    modele = CaptureModel(tmp_path, est_reunion=False, parent=None)
    modele.recharger()
    assert modele.columnCount() == 4
    idx_nom = modele.index(0, COL_FICHIER_JOURNAL)
    assert modele.data(idx_nom).endswith(".md")
    idx_note = modele.index(0, 2)
    assert modele.data(idx_note) == "Une note importante"


def test_ligne_pour_chemin(qapp, tmp_path):
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert modele.ligne_pour_chemin(md) == 0
    assert modele.ligne_pour_chemin(tmp_path / "absent.md") is None


def test_recharger_vide_si_dossier_absent(qapp, tmp_path):
    modele = CaptureModel(tmp_path / "n_existe_pas", est_reunion=True)
    modele.recharger()
    assert modele.rowCount() == 0
