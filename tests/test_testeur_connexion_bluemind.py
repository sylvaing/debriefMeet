"""Tests — worker « Tester la connexion » BlueMind (docs/40 §4). Sans réseau (respx).

Porte autant sur les **signaux** que sur le **log** : le bouton est le seul geste par
lequel l'utilisateur interroge l'interco, et son verdict ne vivait jusqu'ici que dans un
label des Préférences (perdu à la fermeture de la fenêtre). Un diagnostic terrain doit
pouvoir lire ce verdict — cf. le poste du 2026-09-11, URL saisie sans `/api`.
"""
from __future__ import annotations

import logging

import httpx
import respx

from debrief_meet.ui.testeur_connexion_bluemind import TesteurConnexionBlueMind

URL = "https://bm.example.com/api"
EMAIL = "sylvain.garcia@bluemind.net"
LOGGER = "debrief_meet.ui.testeur_connexion_bluemind"


def _route_identite(display_name="Sylvain Garcia"):
    return respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {"displayName": display_name}}))


@respx.mock
def test_succes_emet_reussi_et_journalise_en_info(caplog):
    _route_identite()
    reussites = []
    w = TesteurConnexionBlueMind(URL, "token", EMAIL, True)
    w.reussi.connect(lambda nom, mail: reussites.append((nom, mail)))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        w.executer()

    assert reussites == [("Sylvain Garcia", EMAIL)]
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    message = caplog.records[0].getMessage()
    assert "réussi" in message
    assert URL in message, "l'URL testée doit figurer au log — c'est le champ le plus souvent faux"
    assert "Sylvain Garcia" in message


@respx.mock
def test_url_sans_api_journalise_un_warning_nommant_l_url(caplog):
    """Cas réel du 2026-09-11 : `ClientBlueMind` refuse l'URL AVANT tout appel réseau.
    Le log doit nommer et la cause et la valeur fautive — sans quoi le diagnostic ne dit
    ni que le bouton a été cliqué, ni ce qui avait été saisi."""
    mauvaise = "https://bm.example.com"     # /api manquant
    echecs = []
    w = TesteurConnexionBlueMind(mauvaise, "token", EMAIL, True)
    w.echec.connect(echecs.append)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        w.executer()

    assert len(echecs) == 1 and "/api" in echecs[0]
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    message = caplog.records[0].getMessage()
    assert "échoué" in message
    assert mauvaise in message, "la valeur saisie doit être lisible au log"
    assert "/api" in message


@respx.mock
def test_token_invalide_emet_echec_et_journalise_un_warning(caplog):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(return_value=httpx.Response(403))
    respx.post(f"{URL}/directory/bluemind.net/_search").mock(return_value=httpx.Response(403))
    echecs = []
    w = TesteurConnexionBlueMind(URL, "mauvais-token", EMAIL, True)
    w.echec.connect(echecs.append)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        w.executer()

    assert len(echecs) == 1
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


@respx.mock
def test_aucun_log_ne_contient_le_token(caplog):
    """Le token est le seul secret de la saisie — il ne voyage qu'en en-tête et
    l'export de diagnostic le caviarde dans la config ; il ne doit pas ressortir par
    le log, ni sur le chemin du succès ni sur celui de l'échec."""
    secret = "tok-tres-secret-42"
    _route_identite()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        TesteurConnexionBlueMind(URL, secret, EMAIL, True).executer()
        respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
            return_value=httpx.Response(500))
        respx.post(f"{URL}/directory/bluemind.net/_search").mock(
            return_value=httpx.Response(500))
        TesteurConnexionBlueMind(URL, secret, EMAIL, True).executer()

    assert len(caplog.records) == 2, "un succès puis un échec attendus"
    assert secret not in caplog.text
