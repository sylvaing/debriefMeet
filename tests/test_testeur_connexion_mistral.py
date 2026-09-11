"""Tests — worker « Tester la connexion » Remote IA (docs/42 §9.1). Sans réseau (respx).

Porte autant sur les **signaux** que sur le **log** : le verdict du bouton ne vivait que
dans un label des Préférences, perdu à la fermeture de la fenêtre, donc invisible à un
diagnostic terrain. Même traitement que le jumeau BlueMind.
"""
from __future__ import annotations

import logging

import httpx
import respx

from debrief_meet.ui.testeur_connexion_mistral import TesteurConnexionMistral

URL = "https://api.mistral.ai"
LOGGER = "debrief_meet.ui.testeur_connexion_mistral"


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


# ── Journalisation ───────────────────────────────────────────────────────────────

@respx.mock
def test_succes_journalise_en_info_avec_le_nombre_de_modeles(caplog):
    """Le compte vient du corps déjà reçu. C'est la mesure qui a démêlé docs/42 §10.7 :
    une clé parfaitement valide qui ne se voit servir presque aucun modèle."""
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(
        200, json={"data": [{"id": "ministral-14b-latest"}, {"id": "voxtral-mini-latest"}]}))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        TesteurConnexionMistral(URL, "cle").executer()

    assert [r.levelno for r in caplog.records] == [logging.INFO]
    message = caplog.records[0].getMessage()
    assert "réussi" in message
    assert URL in message
    assert "2 modèle(s)" in message, message


@respx.mock
def test_corps_inattendu_ne_casse_pas_le_succes(caplog):
    """Le compte est un agrément de log, jamais une décision : une réponse 200 dont le
    corps n'a pas la forme attendue reste un test RÉUSSI, avec un compte inconnu."""
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(
        200, content=b"pas du json", headers={"content-type": "text/plain"}))
    reussites = []
    w = TesteurConnexionMistral(URL, "cle")
    w.reussi.connect(reussites.append)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        w.executer()

    assert len(reussites) == 1, "un corps illisible ne doit pas transformer un succès en échec"
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert "? modèle(s)" in caplog.records[0].getMessage()


@respx.mock
def test_echec_journalise_un_warning_nommant_l_url(caplog):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(
        401, json={"message": "Unauthorized"}))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        TesteurConnexionMistral(URL, "mauvaise-cle").executer()

    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    message = caplog.records[0].getMessage()
    assert "échoué" in message
    assert URL in message, "l'URL testée doit figurer au log"


@respx.mock
def test_aucun_log_ne_contient_la_cle_api(caplog):
    """La clé ne voyage qu'en en-tête `Authorization` et les erreurs du client ne
    reprennent que des corps de réponse serveur — le log ne doit pas rouvrir la brèche,
    ni sur le chemin du succès ni sur celui de l'échec."""
    secret = "cle-tres-secrete-42"
    with caplog.at_level(logging.INFO, logger=LOGGER):
        respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
        TesteurConnexionMistral(URL, secret).executer()
        respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(
            401, json={"message": "Unauthorized"}))
        TesteurConnexionMistral(URL, secret).executer()

    assert len(caplog.records) == 2, "un succès puis un échec attendus"
    assert secret not in caplog.text
