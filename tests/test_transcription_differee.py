"""Tests unitaires — transcription différée (depuis l'audio retenu)."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE
from debrief_meet.core.transcription_differee import transcrire_reunion
from debrief_meet.platform.interfaces import ResultatTranscription, Segment
from tests.fakes.adapters import MoteurFake


def _placeholder(tmp_path, nom="2026-01-01_10-00"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion — 2026-01-01 10:00\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    return md


def _piste(tmp_path, suffixe):
    # Constante audible (pas du silence) : depuis docs/27, le moteur applique la porte
    # anti-silence en interne (héritée par MoteurFake) — un WAV muet serait ignoré.
    wavfile.write(tmp_path / f"{suffixe}.wav", 16000, np.full(16000, 3000, dtype=np.int16))


def test_transcrit_les_deux_pistes_et_reecrit_le_md(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme")
    moteur = MoteurFake()

    resultat = transcrire_reunion(md, moteur)

    assert resultat == md
    contenu = md.read_text(encoding="utf-8")
    assert MARQUEUR_EN_ATTENTE not in contenu          # placeholder remplacé
    assert "**Moi :**" in contenu
    assert "**Participants :**" in contenu
    assert "transcription de test" in contenu
    assert len(moteur.appels_transcrire) == 2           # 2 pistes transcrites


def test_une_seule_piste_presente(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")          # pas de système
    moteur = MoteurFake()

    transcrire_reunion(md, moteur)

    contenu = md.read_text(encoding="utf-8")
    assert "**Moi :**" in contenu
    assert "Audio système non disponible" in contenu     # warning piste manquante
    assert len(moteur.appels_transcrire) == 1


def test_aucune_piste_leve(tmp_path):
    md = _placeholder(tmp_path)
    with pytest.raises(FileNotFoundError):
        transcrire_reunion(md, MoteurFake())


def test_titre_conserve_depuis_le_md(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    assert md.read_text(encoding="utf-8").startswith("# Réunion — 2026-01-01 10:00")


def test_titre_custom_conserve(tmp_path):
    md = _placeholder(tmp_path)
    md.write_text(md.read_text(encoding="utf-8").replace(
        "# Réunion — 2026-01-01 10:00", "# Budget Q3"), encoding="utf-8")
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    from debrief_meet.core.fichiers import titre_reunion
    assert titre_reunion(md) == "Budget Q3"             # le titre custom survit à la réécriture


def test_duree_conservee_apres_reecriture(tmp_path):
    from debrief_meet.core.fichiers import definir_duree, duree_reunion
    md = _placeholder(tmp_path)
    definir_duree(md, 900)                               # durée posée en fin de captation
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    assert duree_reunion(md) == 900                      # préservée malgré la réécriture du .md
