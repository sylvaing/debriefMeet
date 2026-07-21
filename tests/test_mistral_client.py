"""Tests unitaires — client HTTP Mistral (sans réseau, respx)."""
from __future__ import annotations

import httpx
import pytest
import respx

from debrief_meet.core.mistral.client import (
    ClientMistral,
    ErreurAuthMistral,
    ErreurFormatMistral,
    ErreurMistral,
    ErreurQuotaMistral,
    ErreurReseauMistral,
    ErreurServeurMistral,
    valider_url,
)

URL = "https://api.mistral.ai"


@pytest.fixture(autouse=True)
def _pas_de_vrai_sommeil(monkeypatch):
    """Les tests de reprise ne doivent jamais vraiment dormir."""
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", lambda _s: None)


def test_valider_url_ok():
    assert valider_url(URL) == URL


def test_valider_url_retire_slash_final():
    assert valider_url(URL + "/") == URL


def test_valider_url_vide_refusee():
    with pytest.raises(ErreurMistral):
        valider_url("   ")


@respx.mock
def test_get_ok():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"ok": True}))
    client = ClientMistral(URL, "cle")
    r = client.get("v1/models")
    assert r.json() == {"ok": True}


@respx.mock
def test_header_bearer_envoye():
    route = respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={}))
    client = ClientMistral(URL, "s3cr3t")
    client.get("v1/models")
    assert route.calls.last.request.headers["Authorization"] == "Bearer s3cr3t"


@respx.mock
def test_post_json():
    route = respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []}))
    client = ClientMistral(URL, "cle")
    client.post_json("v1/chat/completions", {"model": "mistral-small-latest"})
    assert b'"model":"mistral-small-latest"' in route.calls.last.request.content or \
        b'"model": "mistral-small-latest"' in route.calls.last.request.content


@respx.mock
def test_poster_transcription_multipart():
    route = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    client = ClientMistral(URL, "cle")
    r = client.poster_transcription(
        "v1/audio/transcriptions", {"model": "voxtral-mini-latest"},
        "reunion.opus", b"contenu-audio-factice", "audio/ogg")
    assert r.json() == {"text": "bonjour"}
    corps = route.calls.last.request.content
    assert b'name="model"' in corps
    assert b"voxtral-mini-latest" in corps
    assert b'filename="reunion.opus"' in corps
    assert b"contenu-audio-factice" in corps


@respx.mock
def test_context_bias_en_champs_repetes():
    """`data` en dict avec valeur-liste => champs répétés (pas une liste de tuples,
    piège rencontré par le spike — cf. docs/42)."""
    route = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": ""}))
    client = ClientMistral(URL, "cle")
    client.poster_transcription(
        "v1/audio/transcriptions",
        {"model": "voxtral-mini-latest", "context_bias": ["Alice", "Bob"]},
        "a.opus", b"x", "audio/ogg")
    corps = route.calls.last.request.content
    assert corps.count(b'name="context_bias"') == 2
    assert b"Alice" in corps and b"Bob" in corps


@pytest.mark.parametrize("code", [401, 403])
@respx.mock
def test_erreur_auth(code):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(code))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurAuthMistral):
        client.get("v1/models")


@pytest.mark.parametrize("code", [400, 415, 422])
@respx.mock
def test_erreur_format(code):
    respx.post(f"{URL}/v1/audio/transcriptions").mock(return_value=httpx.Response(code, text="bad"))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurFormatMistral):
        client.poster_transcription("v1/audio/transcriptions", {"model": "m"}, "a.opus", b"x", "audio/ogg")


@respx.mock
def test_erreur_serveur():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(500))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurServeurMistral):
        client.get("v1/models")


@respx.mock
def test_timeout_leve_erreur_reseau_apres_reprises():
    route = respx.get(f"{URL}/v1/models").mock(side_effect=httpx.ReadTimeout("timeout"))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurReseauMistral):
        client.get("v1/models")
    assert route.call_count == 3  # 3 tentatives (§7.3)


@respx.mock
def test_reprise_reussit_apres_une_coupure():
    """Une première coupure réseau (broken pipe simulé) suivie d'un succès — reprise
    validée en réel par le spike."""
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [httpx.ConnectError("broken pipe"), httpx.Response(200, json={"ok": True})]
    client = ClientMistral(URL, "cle")
    r = client.get("v1/models")
    assert r.json() == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_429_respecte_retry_after_puis_reussit():
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = ClientMistral(URL, "cle")
    r = client.get("v1/models")
    assert r.json() == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_429_persistant_leve_erreur_quota():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(429))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurQuotaMistral):
        client.get("v1/models")
