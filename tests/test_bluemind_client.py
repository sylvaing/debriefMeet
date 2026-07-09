from __future__ import annotations

import httpx
import pytest
import respx

from debrief_meet.core.bluemind.client import (
    ClientBlueMind,
    ErreurAuthBlueMind,
    ErreurConfigurationBlueMind,
    ErreurIntrouvable,
    ErreurReseauBlueMind,
    ErreurServeurBlueMind,
    valider_url,
)

URL = "https://bm.example.com/api"


def test_valider_url_ok():
    assert valider_url(URL) == URL


def test_valider_url_retire_slash_final():
    assert valider_url(URL + "/") == URL


def test_valider_url_sans_api_refusee():
    with pytest.raises(ErreurConfigurationBlueMind):
        valider_url("https://bm.example.com")


@respx.mock
def test_get_ok():
    respx.get(f"{URL}/hello").mock(return_value=httpx.Response(200, json={"ok": True}))
    client = ClientBlueMind(URL, "token")
    r = client.get("hello")
    assert r.json() == {"ok": True}


@pytest.mark.parametrize("code", [401, 403])
@respx.mock
def test_erreur_auth(code):
    respx.get(f"{URL}/hello").mock(return_value=httpx.Response(code))
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurAuthBlueMind):
        client.get("hello")


@respx.mock
def test_erreur_introuvable():
    respx.get(f"{URL}/hello").mock(return_value=httpx.Response(404))
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurIntrouvable):
        client.get("hello")


@respx.mock
def test_erreur_serveur():
    respx.get(f"{URL}/hello").mock(return_value=httpx.Response(500))
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurServeurBlueMind):
        client.get("hello")


@respx.mock
def test_timeout_leve_erreur_reseau():
    respx.get(f"{URL}/hello").mock(side_effect=httpx.ConnectTimeout("timeout"))
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurReseauBlueMind):
        client.get("hello")


@respx.mock
def test_connexion_refusee_leve_erreur_reseau():
    respx.get(f"{URL}/hello").mock(side_effect=httpx.ConnectError("refused"))
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurReseauBlueMind):
        client.get("hello")


@respx.mock
def test_header_apikey_envoye():
    route = respx.get(f"{URL}/hello").mock(return_value=httpx.Response(200, json={}))
    client = ClientBlueMind(URL, "s3cr3t")
    client.get("hello")
    assert route.calls.last.request.headers["X-BM-ApiKey"] == "s3cr3t"


@respx.mock
def test_post_json():
    route = respx.post(f"{URL}/search").mock(return_value=httpx.Response(200, json={"values": []}))
    client = ClientBlueMind(URL, "token")
    client.post("search", json={"q": "x"})
    assert route.calls.last.request.content == httpx.Request(
        "POST", "https://x", json={"q": "x"}
    ).content
