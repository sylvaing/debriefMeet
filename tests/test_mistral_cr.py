"""Tests unitaires — rédaction du CR via /v1/chat/completions (§4 étape 7, §5.2)."""
from __future__ import annotations

import httpx
import respx

from debrief_meet.core.mistral.client import ClientMistral
from debrief_meet.core.mistral.cr import generer_cr

URL = "https://api.mistral.ai"


@respx.mock
def test_generer_cr_construit_le_message_depuis_le_prompt():
    route = respx.post(f"{URL}/v1/chat/completions").mock(return_value=httpx.Response(
        200, json={"choices": [{"message": {"content": "# CR\n\nContenu."}}],
                   "usage": {"prompt_tokens": 5, "completion_tokens": 3}}))
    client = ClientMistral(URL, "cle")

    texte, usage = generer_cr(client, "voici la transcription", "Tu es un assistant CR.",
                              "mistral-small-latest")

    assert texte == "# CR\n\nContenu."
    assert usage == {"prompt_tokens": 5, "completion_tokens": 3}
    corps = route.calls.last.request.content
    assert b"mistral-small-latest" in corps
    assert b"Tu es un assistant CR." in corps
    assert b"voici la transcription" in corps


@respx.mock
def test_generer_cr_ajoute_le_sujet_si_fourni():
    route = respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "CR"}}]}))
    client = ClientMistral(URL, "cle")

    generer_cr(client, "transcript", "prompt", "mistral-small-latest", sujet="Point produit")

    assert b"Point produit" in route.calls.last.request.content


@respx.mock
def test_generer_cr_injecte_les_participants():
    """Éléments d'association BlueMind (docs/40) — les invités sont passés au CR."""
    route = respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "CR"}}]}))
    client = ClientMistral(URL, "cle")

    generer_cr(client, "transcript", "prompt", "mistral-small-latest",
               participants=["Alice Martin", "Bob Durand"])

    corps = route.calls.last.request.content
    assert b"Participants" in corps
    assert b"Alice Martin" in corps and b"Bob Durand" in corps


@respx.mock
def test_generer_cr_injecte_la_date():
    """La date de la réunion est fournie explicitement (le prompt demande « CR — … — [Date] »
    que le modèle ne peut remplir sans elle)."""
    route = respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "CR"}}]}))
    client = ClientMistral(URL, "cle")

    generer_cr(client, "transcript", "prompt", "mistral-small-latest", date="28/07/2026 10:31")

    corps = route.calls.last.request.content
    assert "Date de la réunion".encode() in corps
    assert b"28/07/2026 10:31" in corps


@respx.mock
def test_generer_cr_sans_usage_renvoie_dict_vide():
    respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "CR"}}]}))
    client = ClientMistral(URL, "cle")

    _texte, usage = generer_cr(client, "t", "p", "m")

    assert usage == {}
