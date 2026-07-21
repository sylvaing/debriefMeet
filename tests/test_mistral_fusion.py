"""Tests unitaires — fusion Moi + Participants par timestamp (§4 étape 6)."""
from __future__ import annotations

from debrief_meet.core.mistral.fusion import fusionner
from debrief_meet.core.mistral.transcription import Segment, TranscriptionMistral


def test_fusionner_entrelace_par_timestamp():
    moi = TranscriptionMistral(texte="bonjour", segments=[Segment(0.0, 1.0, "bonjour")])
    participants = TranscriptionMistral(
        texte="salut", segments=[Segment(2.0, 3.0, "salut")])

    resultat = fusionner(moi, participants)

    assert resultat.index("**Moi :** bonjour") < resultat.index("**Participants :** salut")


def test_fusionner_groupe_les_segments_consecutifs_du_meme_locuteur():
    moi = TranscriptionMistral(
        texte="a b", segments=[Segment(0.0, 1.0, "a"), Segment(1.0, 2.0, "b")])
    resultat = fusionner(moi, None)
    assert resultat.count("**Moi :**") == 1
    assert "a b" in resultat


def test_fusionner_piste_participants_absente():
    moi = TranscriptionMistral(texte="seul", segments=[Segment(0.0, 1.0, "seul")])
    resultat = fusionner(moi, None)
    assert "**Moi :** seul" in resultat
    assert "Participants" not in resultat


def test_fusionner_piste_moi_absente():
    participants = TranscriptionMistral(texte="eux", segments=[Segment(0.0, 1.0, "eux")])
    resultat = fusionner(None, participants)
    assert "**Participants :** eux" in resultat
    assert "Moi" not in resultat


def test_fusionner_deux_pistes_vides_ne_plante_pas():
    resultat = fusionner(None, None)
    assert resultat == ""


def test_fusionner_sans_segments_utilise_le_texte_brut():
    """Pas de `segments` renvoyés par l'API — repli sur le texte complet de chaque piste."""
    moi = TranscriptionMistral(texte="texte moi", segments=[])
    participants = TranscriptionMistral(texte="texte participants", segments=[])
    resultat = fusionner(moi, participants)
    assert "**Moi :** texte moi" in resultat
    assert "**Participants :** texte participants" in resultat
