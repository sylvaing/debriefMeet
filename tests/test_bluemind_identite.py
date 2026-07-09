from __future__ import annotations

import httpx
import pytest
import respx

from debrief_meet.core.bluemind.client import ClientBlueMind
from debrief_meet.core.bluemind.identite import (
    ErreurIdentiteIntrouvable,
    resoudre_identite,
)

URL = "https://bm.example.com/api"
EMAIL = "sylvain.garcia@bluemind.net"


@respx.mock
def test_resolution_directe_byemail():
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "user-uid-1", "value": {"displayName": "Sylvain Garcia"}})
    )
    client = ClientBlueMind(URL, "token")
    identite = resoudre_identite(client, EMAIL)
    assert identite.domain_uid == "bluemind.net"
    assert identite.user_uid == "user-uid-1"
    assert identite.nom_affiche == "Sylvain Garcia"


@pytest.mark.parametrize("code", [401, 403, 404])
@respx.mock
def test_fallback_directory_search_sur_refus(code):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(return_value=httpx.Response(code))
    respx.post(f"{URL}/directory/bluemind.net/_search").mock(
        return_value=httpx.Response(200, json={
            "values": [{"uid": "user-uid-2", "value": {
                "path": "reel.internal/users/user-uid-2", "displayName": "Sylvain Garcia"}}]
        })
    )
    client = ClientBlueMind(URL, "token")
    identite = resoudre_identite(client, EMAIL)
    # Le domain_uid réel vient de value.path, PAS de la partie droite de l'email.
    assert identite.domain_uid == "reel.internal"
    assert identite.user_uid == "user-uid-2"


@respx.mock
def test_fallback_directory_search_sur_204():
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(return_value=httpx.Response(204))
    respx.post(f"{URL}/directory/bluemind.net/_search").mock(
        return_value=httpx.Response(200, json={
            "values": [{"uid": "u3", "value": {"path": "bluemind.net/users/u3"}}]
        })
    )
    client = ClientBlueMind(URL, "token")
    identite = resoudre_identite(client, EMAIL)
    assert identite.user_uid == "u3"


@respx.mock
def test_aucun_resultat_leve_erreur():
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(return_value=httpx.Response(404))
    respx.post(f"{URL}/directory/bluemind.net/_search").mock(
        return_value=httpx.Response(200, json={"values": []})
    )
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurIdentiteIntrouvable):
        resoudre_identite(client, EMAIL)


def test_email_invalide_leve_erreur():
    client = ClientBlueMind(URL, "token")
    with pytest.raises(ErreurIdentiteIntrouvable):
        resoudre_identite(client, "pas-un-email")


@respx.mock
def test_nom_affiche_repli_sur_login():
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {"login": "sgarcia"}})
    )
    client = ClientBlueMind(URL, "token")
    identite = resoudre_identite(client, EMAIL)
    assert identite.nom_affiche == "sgarcia"
