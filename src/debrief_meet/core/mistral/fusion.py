"""Fusion Moi + Participants (§4 étape 6, branche Voxtral uniquement).

Réutilise l'entrelacement de `core/fichiers.py::_entrelaces` (même logique déjà
utilisée par la transcription différée, `core/transcription_differee.py`) : trie les
segments des deux pistes par timestamp et groupe les prises de parole consécutives
du même locuteur.
"""
from __future__ import annotations

from debrief_meet.core.fichiers import _entrelaces
from debrief_meet.core.mistral.transcription import TranscriptionMistral


def fusionner(moi: TranscriptionMistral | None,
             participants: TranscriptionMistral | None) -> str:
    """Transcript étiqueté `**Moi :**` / `**Participants :**`, entrelacé par timestamp.

    Une piste absente (`None`, non retenue ou silencieuse — §7.4) est traitée comme
    vide, sans planter."""
    moi = moi or TranscriptionMistral(texte="")
    participants = participants or TranscriptionMistral(texte="")
    segs_moi = [(s.debut, s.texte) for s in moi.segments]
    segs_participants = [(s.debut, s.texte) for s in participants.segments]
    blocs = _entrelaces(moi.texte.strip(), participants.texte.strip(), segs_moi, segs_participants)
    return "\n\n".join(f"**{locuteur} :** {texte}" for locuteur, texte in blocs)
