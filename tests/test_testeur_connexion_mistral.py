"""Tests — worker « Tester la connexion » Remote IA (docs/42 §9.1). Sans réseau (respx)."""
from __future__ import annotations

import httpx
import respx

from debrief_meet.ui.testeur_connexion_mistral import TesteurConnexionMistral

URL = "https://api.mistral.ai"


@respx.mock
def test_executer_succes():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    reussites = []
    w = TesteurConnexionMistral(URL, "cle")
    w.reussi.connect(reussites.append)
    w.executer()
    assert len(reussites) == 1


@respx.mock
def test_executer_echec_cle_invalide():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(401))
    echecs = []
    w = TesteurConnexionMistral(URL, "mauvaise-cle")
    w.echec.connect(echecs.append)
    w.executer()
    assert len(echecs) == 1
    assert "401" in echecs[0] or "authentification" in echecs[0].lower()
