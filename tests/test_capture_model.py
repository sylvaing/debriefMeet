from __future__ import annotations

import wave
from datetime import datetime

import pytest
from PySide6.QtCore import Qt

from debrief_meet.core.fichiers import (
    MARQUEUR_EN_ATTENTE,
    EcrivainJournal,
    chemin_cr_mistral,
    chemin_reunion,
    definir_titre,
)
from debrief_meet.ui.capture_model import (
    COL_FICHIER_JOURNAL,
    COL_TITRE_REUNION,
    JOB_CR_MISTRAL,
    ROLE_CHEMIN,
    CaptureModel,
)
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.status_pill import HistoryState
from debrief_meet.ui.theme import C


def _creer_reunion(dossier, *, titre=None, avec_audio=False, avec_locuteurs=False):
    md = chemin_reunion(dossier, datetime(2026, 7, 4, 10, 30))
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("# Réunion — 2026-07-04 10:30\n\ntranscription\n", encoding="utf-8")
    if titre:
        definir_titre(md, titre)
    if avec_audio:
        with wave.open(str(md.with_name("moi.wav")), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 160)
    if avec_locuteurs:
        md.with_name("locuteurs.md").write_text("locuteurs", encoding="utf-8")
    return md


def test_reunion_colonnes_et_lignes(qapp, tmp_path):
    _creer_reunion(tmp_path, titre="Point équipe")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()

    assert modele.rowCount() == 1
    assert modele.columnCount() == 7
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


def test_etat_cr_disponible_prime(qapp, tmp_path):
    """Un CR généré (IA externe) prime sur l'état du pipeline (même avec locuteurs)."""
    md = _creer_reunion(tmp_path, avec_audio=True, avec_locuteurs=True)
    chemin_cr_mistral(md).write_text("# CR\n\nrésumé", encoding="utf-8")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert modele.data(modele.index(0, 4), Qt.ItemDataRole.UserRole) == HistoryState.CR_DISPONIBLE


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


# ── Ligne « en cours » (CHANGELOG_v2 §3) ─────────────────────────────────────

def test_ligne_en_cours_ajoute_une_ligne_en_tete(qapp, tmp_path):
    _creer_reunion(tmp_path, titre="Point équipe")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert modele.rowCount() == 1

    modele.definir_ligne_en_cours(True, 65)
    assert modele.rowCount() == 2
    assert modele.data(modele.index(0, COL_TITRE_REUNION)) == "Réunion en cours"
    assert modele.data(modele.index(0, 3)) == "01:05"
    assert modele.data(modele.index(0, 4), Qt.ItemDataRole.UserRole) == HistoryState.EN_COURS
    # la ligne réelle est décalée d'un cran
    assert modele.data(modele.index(1, COL_TITRE_REUNION)) == "Point équipe"


def test_ligne_en_cours_ignoree_hors_reunion(qapp, tmp_path):
    modele = CaptureModel(tmp_path, est_reunion=False)
    modele.recharger()
    modele.definir_ligne_en_cours(True, 10)
    assert modele.rowCount() == 0


def test_ligne_en_cours_retiree_a_l_arret(qapp, tmp_path):
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    modele.definir_ligne_en_cours(True, 10)
    assert modele.rowCount() == 1
    modele.definir_ligne_en_cours(False)
    assert modele.rowCount() == 0


def test_ligne_en_cours_n_a_pas_d_actions_ni_de_selection(qapp, tmp_path):
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    modele.definir_ligne_en_cours(True, 10)
    idx = modele.index(0, COL_TITRE_REUNION)
    assert not (modele.flags(idx) & Qt.ItemFlag.ItemIsSelectable)
    assert not (modele.flags(idx) & Qt.ItemFlag.ItemIsEditable)
    assert modele.chemin_a_la_ligne(0) is None
    assert modele.info_ligne(0).en_cours is True


def test_ligne_en_cours_decale_ligne_pour_chemin(qapp, tmp_path):
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    modele.definir_ligne_en_cours(True, 10)
    assert modele.ligne_pour_chemin(md) == 1


# ── Exclusion de la réunion active (pas de ligne en double) ───────────────────

def test_chemin_actif_exclu_du_listing(qapp, tmp_path):
    """La réunion en cours d'enregistrement a déjà son `transcription.md` sur disque,
    mais elle est représentée par la ligne « en cours » — sans exclusion elle
    apparaîtrait deux fois."""
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_chemin_actif(md)
    modele.recharger()
    modele.definir_ligne_en_cours(True, 9)

    assert modele.rowCount() == 1                       # la ligne « en cours » seule
    assert modele.data(modele.index(0, COL_TITRE_REUNION)) == "Réunion en cours"


def test_chemin_actif_remis_a_none_reaffiche_la_reunion(qapp, tmp_path):
    """Fin d'enregistrement : la réunion redevient une ligne normale du listing."""
    md = _creer_reunion(tmp_path, titre="Point équipe")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_chemin_actif(md)
    modele.recharger()
    assert modele.rowCount() == 0

    modele.definir_chemin_actif(None)
    modele.recharger()
    assert modele.rowCount() == 1
    assert modele.data(modele.index(0, COL_TITRE_REUNION)) == "Point équipe"


def test_chemin_actif_n_exclut_que_la_reunion_visee(qapp, tmp_path):
    """Les autres réunions restent listées pendant l'enregistrement."""
    from datetime import datetime as _dt

    from debrief_meet.core.fichiers import chemin_reunion as _chemin_reunion
    active = _creer_reunion(tmp_path)
    autre = _chemin_reunion(tmp_path, _dt(2026, 7, 5, 9, 0))
    autre.parent.mkdir(parents=True)
    autre.write_text("# Réunion — 2026-07-05 09:00\n", encoding="utf-8")

    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_chemin_actif(active)
    modele.recharger()

    assert modele.rowCount() == 1
    assert modele.chemin_a_la_ligne(0) == autre


# ── Colonne 0 : icône du traitement a posteriori en cours ────────────────────────

def _image_col0(modele, row=0):
    """Icône rendue de la colonne 0 (type). Comparer les IMAGES, pas les QIcon :
    ça fige à la fois la forme (donc QUELLE opération) et la teinte."""
    icone = modele.data(modele.index(row, 0), Qt.ItemDataRole.DecorationRole)
    return icone.pixmap(16, 16).toImage()


def _image_attendue(nom, couleur=C.JOB):
    return icone_svg_teintee(icone_phosphor(nom), couleur, 16).pixmap(16, 16).toImage()


def _infobulle_col0(modele, row=0):
    return modele.data(modele.index(row, 0), Qt.ItemDataRole.ToolTipRole)


@pytest.mark.parametrize("type_job,icone_attendue", [
    ("transcription", "file-text"),
    ("diarization", "users"),
    (JOB_CR_MISTRAL, "notebook"),
])
def test_icone_ligne_montre_le_job_a_posteriori_en_cours(qapp, tmp_path, type_job, icone_attendue):
    md = _creer_reunion(tmp_path, titre="Point équipe")
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert _image_col0(modele) == _image_attendue("users-three", C.INK400)  # repos

    modele.definir_job_en_cours(md, type_job)
    modele.recharger()
    assert _image_col0(modele) == _image_attendue(icone_attendue)


def test_fin_de_job_rend_l_icone_reunion(qapp, tmp_path):
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_job_en_cours(md, JOB_CR_MISTRAL)
    modele.recharger()
    assert _image_col0(modele) == _image_attendue("notebook")

    modele.definir_job_en_cours(None, None)
    modele.recharger()
    assert _image_col0(modele) == _image_attendue("users-three", C.INK400)


def test_icone_job_ne_touche_que_la_reunion_concernee(qapp, tmp_path):
    from datetime import datetime as _dt

    from debrief_meet.core.fichiers import chemin_reunion as _chemin_reunion
    cible = _creer_reunion(tmp_path)
    autre = _chemin_reunion(tmp_path, _dt(2026, 7, 5, 9, 0))
    autre.parent.mkdir(parents=True)
    autre.write_text("# Réunion — 2026-07-05 09:00\n", encoding="utf-8")

    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_job_en_cours(cible, "transcription")
    modele.recharger()
    lignes = {modele.chemin_a_la_ligne(r): r for r in range(modele.rowCount())}
    assert _image_col0(modele, lignes[cible]) == _image_attendue("file-text")
    assert _image_col0(modele, lignes[autre]) == _image_attendue("users-three", C.INK400)


def test_icone_job_de_type_inconnu_reste_visible(qapp, tmp_path):
    """Un job dont le type n'est pas dans la table : l'icône « réunion » mentirait sur
    l'inactivité, on peint le symbole générique — en orange comme les autres."""
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.definir_job_en_cours(md, "un-nouveau-job")
    modele.recharger()
    assert _image_col0(modele) == _image_attendue("arrows-clockwise")
    assert _infobulle_col0(modele) == "Traitement en cours…"


def test_ligne_en_cours_garde_le_micro_meme_si_un_job_porte_le_chemin_sentinelle(qapp, tmp_path):
    """Piège : la ligne « en cours » a `Path()` pour chemin (sentinelle). Un
    `_job_chemin` lui aussi vide serait `==` et lui collerait une icône de job, alors
    que c'est l'enregistrement LIVE — pas un traitement a posteriori."""
    from pathlib import Path as _Path
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    modele.definir_job_en_cours(_Path(), "transcription")
    modele.definir_ligne_en_cours(True, 5)

    assert modele.data(modele.index(0, COL_TITRE_REUNION)) == "Réunion en cours"
    assert _image_col0(modele) == _image_attendue("microphone", C.INK400)
    assert _infobulle_col0(modele) is None


def test_infobulle_colonne_type_nomme_l_operation(qapp, tmp_path):
    md = _creer_reunion(tmp_path)
    modele = CaptureModel(tmp_path, est_reunion=True)
    modele.recharger()
    assert _infobulle_col0(modele) is None            # au repos, pas d'infobulle parasite

    modele.definir_job_en_cours(md, "diarization")
    modele.recharger()
    assert _infobulle_col0(modele) == "Génération des locuteurs en cours…"
