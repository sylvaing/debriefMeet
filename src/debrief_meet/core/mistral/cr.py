"""Rédaction du CR via `/v1/chat/completions` (§4 étape 7, §5.2).

**Source-agnostique** : prend du texte en entrée, que la transcription vienne du
transcript local (défaut, §1) ou de Voxtral (repli) — même code dans les deux cas.
Modèle *texte* uniquement (`mistral_modele_cr`) — jamais un modèle Voxtral ici.
"""
from __future__ import annotations

from debrief_meet.core.mistral.client import ClientMistral


def generer_cr(client: ClientMistral, transcript: str, prompt: str, modele: str,
               sujet: str | None = None,
               participants: list[str] | None = None,
               date: str | None = None) -> tuple[str, dict]:
    """Retourne `(markdown_cr, usage)`. `usage` = `prompt_tokens`/`completion_tokens`.

    `sujet`, `date` et `participants` cadrent le CR : le prompt demande un titre
    « CR — [Sujet] — [Date] » que le modèle ne peut remplir sans qu'on les lui fournisse
    (le transcript seul ne les contient pas de façon fiable). `sujet`/`participants`
    viennent de l'association BlueMind quand elle existe ; `date` de la réunion elle-même
    (toujours disponible). Injectés quelle que soit la source du transcript (local/Voxtral)."""
    invite = prompt.rstrip()
    if sujet:
        invite = f"{invite}\n(Sujet de la réunion : {sujet})"
    if date:
        invite = f"{invite}\n(Date de la réunion : {date})"
    if participants:
        invite = f"{invite}\n(Participants prévus : {', '.join(participants)})"
    corps = {
        "model": modele,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": f"{invite}\n\n{transcript}"}],
    }
    r = client.post_json("v1/chat/completions", corps)
    payload = r.json()
    texte = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    return texte, usage
