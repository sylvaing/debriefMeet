"""Tests unitaires — client HTTP Mistral (sans réseau, respx)."""
from __future__ import annotations

import httpx
import pytest
import respx

from debrief_meet.core.mistral.client import (
    _TENTATIVES_5XX,
    ClientMistral,
    ErreurAuthMistral,
    ErreurFormatMistral,
    ErreurMistral,
    ErreurModeleIndisponibleMistral,
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


@respx.mock
def test_erreur_auth_inclut_le_corps_de_la_reponse():
    """Le corps porte la vraie cause (cas réel du 2026-08-31 : 403 tier_not_allowed
    que le statut seul faisait passer pour une clé invalide)."""
    corps = '{"message":"This model is not available in your subscription tier","code":"1910"}'
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(403, text=corps))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurAuthMistral, match="subscription tier"):
        client.get("v1/models")


@respx.mock
def test_erreur_auth_tronque_le_corps():
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(401, text="x" * 1000))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurAuthMistral) as exc:
        client.get("v1/models")
    assert len(str(exc.value)) < 400


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


# ── reprise sur 5xx (terrain 2026-08-31 : 503 sur un envoi de 139 min) ──────────────

@respx.mock
def test_5xx_est_rejoue_puis_leve():
    """Un 5xx est transitoire par nature : on rejoue avant d'abandonner. Le budget est
    volontairement court — au-delà, c'est à la cascade de replis de découper."""
    route = respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(503))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurServeurMistral):
        client.get("v1/models")
    # Valeur en dur ET constante : comparer à la seule constante laisserait passer un
    # budget ramené à 1, c'est-à-dire la suppression pure et simple de la reprise.
    assert route.call_count == 2 == _TENTATIVES_5XX


@respx.mock
def test_5xx_suivi_d_un_succes_rend_la_reponse():
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"data": []})]
    client = ClientMistral(URL, "cle")

    reponse = client.get("v1/models")

    assert reponse.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_5xx_puis_429_recoit_le_traitement_du_429():
    """La reprise 5xx passe AVANT les autres classifications, donc une reprise qui
    retombe sur un 429 doit recevoir l'attente du quota — pas être maquillée en erreur
    serveur par le `>= 400` final."""
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [httpx.Response(503)] + [httpx.Response(429)] * 8
    client = ClientMistral(URL, "cle")

    with pytest.raises(ErreurQuotaMistral):
        client.get("v1/models")


@respx.mock
def test_5xx_puis_4xx_recoit_le_traitement_du_4xx():
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [httpx.Response(502), httpx.Response(401)]
    client = ClientMistral(URL, "cle")

    with pytest.raises(ErreurAuthMistral):
        client.get("v1/models")


@respx.mock
def test_5xx_honore_retry_after(monkeypatch):
    attentes = []
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", attentes.append)
    route = respx.get(f"{URL}/v1/models")
    route.side_effect = [httpx.Response(503, headers={"Retry-After": "7"}),
                         httpx.Response(200, json={})]
    client = ClientMistral(URL, "cle")

    client.get("v1/models")

    assert attentes == [7.0]


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


@respx.mock
def test_429_backoff_traverse_une_fenetre_minute(monkeypatch):
    # Sans Retry-After, le cumul des attentes avant la dernière tentative doit
    # dépasser 60 s : un gros appel réussi juste avant laisse la fenêtre
    # tokens/minute pleine (vécu 2026-08-05, 1er segment du repli découpage).
    attentes: list[float] = []
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", attentes.append)
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(429))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurQuotaMistral):
        client.get("v1/models")
    # Chaque attente précède sa tentative : la dernière tentative part à
    # sum(attentes) secondes du premier 429 — elle doit être hors fenêtre.
    assert sum(attentes) > 60.0


@respx.mock
def test_429_sans_retry_leve_immediatement_si_desactive():
    # retries_429=False (envoi d'une piste entière) : le premier 429 lève sans réessai.
    route = respx.post(f"{URL}/v1/audio/transcriptions").mock(return_value=httpx.Response(429))
    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurQuotaMistral):
        client.poster_transcription("v1/audio/transcriptions", {"model": "m"},
                                    "a.opus", b"x", "audio/ogg", retries_429=False)
    assert route.call_count == 1


@respx.mock
def test_429_retries_conserves_par_defaut_sur_transcription():
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={"text": "ok"}),
    ]
    client = ClientMistral(URL, "cle")
    r = client.poster_transcription("v1/audio/transcriptions", {"model": "m"},
                                    "a.opus", b"x", "audio/ogg")
    assert r.json() == {"text": "ok"}
    assert route.call_count == 2


# ── 429 à plafond nul : le modèle n'est pas servi (terrain 2026-09-08, §10.7) ────
#
# Chez une utilisatrice : « Quota dépassé (429) sur v1/chat/completions », 4 fois en
# 1 h 35, chaque fois après 20 + 40 + 60 s d'attente. Mesuré ensuite sur l'API réelle :
# `mistral-medium-latest` répond 429 avec `x-ratelimit-limit-req-minute: 0` — allocation
# NULLE, pas épuisée. Aucune attente ne pouvait aboutir, et le message envoyait
# l'utilisatrice réessayer plus tard.

_PLAFOND_NUL = {"x-ratelimit-limit-req-minute": "0"}
#: Corps réel renvoyé par Mistral dans ce cas.
_CORPS_429 = '{"object":"error","message":"Rate limit exceeded","type":"rate_limited","code":"1300"}'


@respx.mock
def test_429_a_plafond_nul_leve_sans_aucune_attente(monkeypatch):
    dormi: list[float] = []
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", dormi.append)
    route = respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers=_PLAFOND_NUL, text=_CORPS_429))

    with pytest.raises(ErreurModeleIndisponibleMistral) as excinfo:
        ClientMistral(URL, "k").post_json("/v1/chat/completions",
                                          {"model": "mistral-medium-latest"})

    assert dormi == [], "un plafond à 0 ne se résorbe pas : ne jamais attendre"
    assert route.call_count == 1
    message = str(excinfo.value)
    assert "mistral-medium-latest" in message
    assert "0 requête/minute" in message
    assert "Préférences" in message


@respx.mock
def test_429_a_plafond_nul_n_est_pas_une_erreur_de_quota():
    """`transcription.py` rattrape `ErreurQuotaMistral` pour découper la piste :
    hériter d'elle ferait multiplier un refus définitif par le nombre de segments."""
    respx.post(f"{URL}/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers=_PLAFOND_NUL, text=_CORPS_429))

    with pytest.raises(ErreurMistral) as excinfo:
        ClientMistral(URL, "k").post_json("/v1/chat/completions", {"model": "m"})

    assert not isinstance(excinfo.value, ErreurQuotaMistral)


@respx.mock
def test_429_a_plafond_nul_detecte_aussi_sur_une_reprise():
    """Le premier 429 peut être un vrai rate-limit et la reprise révéler le plafond nul."""
    respx.get(f"{URL}/v1/models").mock(side_effect=[
        httpx.Response(429),
        httpx.Response(429, headers=_PLAFOND_NUL, text=_CORPS_429),
    ])

    with pytest.raises(ErreurModeleIndisponibleMistral):
        ClientMistral(URL, "k").get("/v1/models")


@respx.mock
def test_429_a_plafond_nul_sur_transcription_nomme_le_modele():
    """Le modèle vit dans `data` (multipart), pas dans `json`."""
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(429, headers=_PLAFOND_NUL, text=_CORPS_429))

    with pytest.raises(ErreurModeleIndisponibleMistral, match="voxtral-mini-latest"):
        ClientMistral(URL, "k").poster_transcription(
            "/v1/audio/transcriptions", {"model": "voxtral-mini-latest"},
            "a.opus", b"x", "audio/ogg")


@respx.mock
def test_plafond_non_nul_reste_un_quota_ordinaire(monkeypatch):
    """Un vrai rate-limit garde ses reprises : ne pas transformer tout 429 en verdict."""
    dormi: list[float] = []
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", dormi.append)
    respx.get(f"{URL}/v1/models").mock(
        return_value=httpx.Response(429, headers={"x-ratelimit-limit-req-minute": "188"}))

    with pytest.raises(ErreurQuotaMistral):
        ClientMistral(URL, "k").get("/v1/models")
    assert dormi, "un quota ordinaire doit continuer à patienter"


@respx.mock
def test_en_tete_absent_ou_illisible_reste_un_quota_ordinaire():
    """Aucun en-tête (proxy, passerelle) : on ne peut rien conclure, donc on retente."""
    respx.get(f"{URL}/v1/models").mock(
        return_value=httpx.Response(429, headers={"x-ratelimit-limit-req-minute": "n/a"}))

    with pytest.raises(ErreurQuotaMistral):
        ClientMistral(URL, "k").get("/v1/models")


@respx.mock
def test_message_de_quota_porte_le_corps_de_la_reponse():
    """Le corps porte la vraie cause — c'est déjà ce que font les branches 401/403 et
    400/422. Sans lui, le diagnostic du 2026-09-08 a demandé de rejouer l'appel à la
    main pour découvrir la limite à 0."""
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(429, text=_CORPS_429))

    with pytest.raises(ErreurQuotaMistral, match="Rate limit exceeded"):
        ClientMistral(URL, "k").get("/v1/models")


@respx.mock
def test_message_de_quota_sans_retry_porte_aussi_le_corps():
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(429, text=_CORPS_429))

    with pytest.raises(ErreurQuotaMistral, match="Rate limit exceeded"):
        ClientMistral(URL, "k").poster_transcription(
            "/v1/audio/transcriptions", {"model": "voxtral-mini-latest"},
            "a.opus", b"x", "audio/ogg", retries_429=False)
