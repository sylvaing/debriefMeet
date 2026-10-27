"""Tests unitaires — transcription Voxtral (sans réseau, respx ; sans ffmpeg réel)."""
from __future__ import annotations

import httpx
import numpy as np
import pytest
import respx
from scipy.io import wavfile

from debrief_meet.core.mistral import transcription as t
from debrief_meet.core.mistral.client import (ClientMistral,
                                              ErreurModeleIndisponibleMistral)
from debrief_meet.core.mistral.silences import PlanCompaction

URL = "https://api.mistral.ai"


@pytest.fixture(autouse=True)
def _pas_de_vrai_sommeil(monkeypatch):
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", lambda _s: None)
    monkeypatch.setattr("debrief_meet.core.mistral.transcription._dormir", lambda _s: None)


def _wav_audible(tmp_path, nom="piste.wav", secondes=1.0):
    chemin = tmp_path / nom
    wavfile.write(chemin, 16000, np.full(int(16000 * secondes), 3000, dtype=np.int16))
    return chemin


def _wav_silencieux(tmp_path, nom="silence.wav"):
    chemin = tmp_path / nom
    wavfile.write(chemin, 16000, np.zeros(16000, dtype=np.int16))
    return chemin


# ── _construire_donnees ──────────────────────────────────────────────────────────

def test_construire_donnees_sans_langue_ni_contexte():
    data = t._construire_donnees("voxtral-mini-latest", None, [])
    assert data == {"model": "voxtral-mini-latest", "timestamp_granularities": "segment"}


def test_construire_donnees_avec_langue_et_contexte():
    data = t._construire_donnees("voxtral-mini-latest", "fr", ["Alice", "Bob"])
    assert data["language"] == "fr"
    assert data["context_bias"] == ["Alice", "Bob"]


def test_construire_donnees_limite_context_bias_a_100():
    noms = [f"nom{i}" for i in range(150)]
    data = t._construire_donnees("m", None, noms)
    assert len(data["context_bias"]) == 100


def test_construire_donnees_decoupe_les_noms_multi_mots():
    """Régression 2026-07-28 : Voxtral refuse un item avec espace/virgule (400 code 3051).
    Les noms complets des invités BlueMind sont découpés en jetons dédoublonnés."""
    data = t._construire_donnees("m", None, ["Sylvain Garcia", "Bastien Lenoir", "Sylvain Dupont"])
    assert data["context_bias"] == ["Sylvain", "Garcia", "Bastien", "Lenoir", "Dupont"]
    assert all(" " not in j and "," not in j for j in data["context_bias"])


def test_construire_donnees_ignore_les_entrees_vides():
    data = t._construire_donnees("m", None, ["", "   ", "Bob"])
    assert data["context_bias"] == ["Bob"]


# ── analyser_piste (§7.4) ─────────────────────────────────────────────────────────

def test_analyser_piste_audible(tmp_path):
    chemin = _wav_audible(tmp_path)
    a = t.analyser_piste(chemin)
    assert a.silencieuse is False
    assert a.duree_s == pytest.approx(1.0, abs=0.05)


def test_analyser_piste_silencieuse(tmp_path):
    chemin = _wav_silencieux(tmp_path)
    a = t.analyser_piste(chemin)
    assert a.silencieuse is True


def test_analyser_piste_faible_mais_parlee_non_silencieuse(tmp_path):
    """Régression : une piste faible (RMS brut ~0,005, SOUS le seuil anti-silence 0,008)
    mais contenant de la parole ne doit PAS être classée silencieuse — le vrai chemin de
    transcription la normalise d'abord (docs/27). Cas réel : micro discret à −42 dB."""
    chemin = tmp_path / "faible.wav"
    # 160/32768 ≈ 0,0049 → RMS brut < 0,008, mais normalisé (×~6) au-dessus.
    wavfile.write(chemin, 16000, np.full(16000, 160, dtype=np.int16))
    a = t.analyser_piste(chemin)
    assert a.silencieuse is False


def test_analyser_piste_fichier_illisible_ne_leve_pas(tmp_path):
    chemin = tmp_path / "corrompu.wav"
    chemin.write_bytes(b"pas un wav")
    a = t.analyser_piste(chemin)
    assert a.silencieuse is False
    assert a.duree_s == 0.0


# ── transcrire_fichier — chemin normal (piste entière, §7.1) ───────────────────────

@respx.mock
def test_transcrire_fichier_chemin_normal(tmp_path):
    chemin = tmp_path / "reunion_moi.opus"
    chemin.write_bytes(b"faux-opus")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(return_value=httpx.Response(
        200, json={
            "text": "bonjour tout le monde",
            "segments": [{"start": 0.0, "end": 2.0, "text": "bonjour tout le monde"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0},
        }))
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest", langue="fr")

    assert resultat.texte == "bonjour tout le monde"
    assert len(resultat.segments) == 1
    assert resultat.segments[0].debut == 0.0
    assert resultat.usage["prompt_tokens"] == 10


@respx.mock
def test_transcrire_fichier_sans_segments_construit_un_bloc_unique(tmp_path):
    chemin = tmp_path / "a.opus"
    chemin.write_bytes(b"x")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "juste du texte"}))
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert resultat.texte == "juste du texte"
    assert len(resultat.segments) == 1


@respx.mock
def test_transcrire_fichier_texte_vide_aucun_segment(tmp_path):
    """Piste silencieuse renvoyée par Voxtral (0 caractère) — cas réel du spike."""
    chemin = tmp_path / "systeme.opus"
    chemin.write_bytes(b"x")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "", "segments": []}))
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert resultat.texte == ""
    assert resultat.segments == []


# ── repli format refusé → transcodage WAV (§7.1) ──────────────────────────────────

@respx.mock
def test_repli_wav_si_format_refuse(tmp_path, monkeypatch):
    chemin = tmp_path / "reunion.opus"
    chemin.write_bytes(b"faux-opus")

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(400, text="format non supporté"),
        httpx.Response(200, json={"text": "transcrit via wav"}),
    ]

    monkeypatch.setattr("debrief_meet.core.fichiers.chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")

    def _faux_run(cmd, **kwargs):
        with open(cmd[-1], "wb") as f:
            f.write(b"faux-wav")

    monkeypatch.setattr("subprocess.run", _faux_run)

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert resultat.texte == "transcrit via wav"
    assert route.call_count == 2


# ── repli découpage sur échec réseau persistant (§10) ──────────────────────────────

@respx.mock
def test_repli_decoupage_si_reseau_persiste(tmp_path, monkeypatch):
    chemin = tmp_path / "longue_reunion.opus"
    chemin.write_bytes(b"faux-opus-long")

    # 3 tentatives réseau ratées (chemin normal) puis 2 segments transcrits avec succès.
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.ConnectError("broken pipe"),
        httpx.ConnectError("broken pipe"),
        httpx.ConnectError("broken pipe"),
        httpx.Response(200, json={"text": "premier segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "premier segment"}]}),
        httpx.Response(200, json={"text": "second segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "second segment"}]}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert "premier segment" in resultat.texte
    assert "second segment" in resultat.texte
    assert len(resultat.segments) == 2
    # Offset réappliqué : le 2e segment démarre à LIMITE_SEGMENT_S secondes.
    assert resultat.segments[1].debut == pytest.approx(t.LIMITE_SEGMENT_S)


# ── repli découpage sur erreur serveur 5xx (terrain 2026-08-31, poste Linux) ────────
#
# Un COMEX de 139 min parti d'un bloc a pris un 503, deux fois à 26 min d'écart. Le 5xx
# n'était rattrapé nulle part : ni reprise dans le client, ni branche dans cette
# cascade. Il remontait au pipeline et perdait le CR — alors que le découpage existait
# et aurait ramené l'envoi à des segments de 14 min, l'ordre de grandeur de tout ce qui
# passait sur ce poste.

@respx.mock
def test_repli_decoupage_si_erreur_serveur_persiste(tmp_path, monkeypatch):
    chemin = tmp_path / "comex.opus"
    chemin.write_bytes(b"faux-opus-long")

    # Les 2 tentatives du client sur l'envoi ENTIER échouent en 503, puis les 2 segments
    # du découpage passent — exactement le scénario que le terrain a perdu.
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"text": "premier segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "premier segment"}]}),
        httpx.Response(200, json={"text": "second segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "second segment"}]}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert "premier segment" in resultat.texte
    assert "second segment" in resultat.texte
    assert resultat.decoupee is True      # le pipeline découpera la piste suivante d'emblée
    assert resultat.segments[1].debut == pytest.approx(t.LIMITE_SEGMENT_S)


@respx.mock
def test_erreur_serveur_sur_les_segments_remonte(tmp_path, monkeypatch):
    """Le découpage est le DERNIER repli : si les segments eux-mêmes prennent des 5xx,
    il n'y a plus rien à tenter et l'échec doit remonter — surtout pas boucler."""
    from debrief_meet.core.mistral.client import ErreurServeurMistral

    chemin = tmp_path / "comex.opus"
    chemin.write_bytes(b"faux-opus-long")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(return_value=httpx.Response(503))

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1])

    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurServeurMistral):
        t.transcrire_fichier(client, chemin, "voxtral-mini-latest")


# ── modèle non servi : surtout PAS de découpage (terrain 2026-09-08, §10.7) ─────────

@respx.mock
def test_modele_non_servi_ne_declenche_aucun_decoupage(tmp_path, monkeypatch):
    """Un 429 à plafond nul est un refus DÉFINITIF, pas un quota momentané.

    Le découper reviendrait à multiplier le même refus par le nombre de segments —
    7 uploads inutiles pour une piste de 2 h. Test d'EFFET : faire de
    `ErreurModeleIndisponibleMistral` une sous-classe de `ErreurQuotaMistral` le fait
    échouer, alors que la seule vérification de la hiérarchie des classes resterait
    verte côté client."""
    chemin = tmp_path / "reunion.opus"
    chemin.write_bytes(b"faux-opus")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(return_value=httpx.Response(
        429, headers={"x-ratelimit-limit-req-minute": "0"},
        text='{"message":"Rate limit exceeded"}'))

    def _jamais(*_a, **_k):
        raise AssertionError("découpage tenté alors que le modèle n'est pas servi")

    monkeypatch.setattr(t, "decouper_piste", _jamais)

    client = ClientMistral(URL, "cle")
    with pytest.raises(ErreurModeleIndisponibleMistral, match="voxtral-mini-latest"):
        t.transcrire_fichier(client, chemin, "voxtral-mini-latest")


# ── repli découpage sur quota 429, sans retry (§10, vécu 74 min le 2026-08-05) ──────

@respx.mock
def test_repli_decoupage_immediat_si_quota(tmp_path, monkeypatch):
    chemin = tmp_path / "longue_reunion.opus"
    chemin.write_bytes(b"faux-opus-long")

    # 1 seul 429 sur la piste entière (pas de retry) puis 2 segments transcrits.
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={"text": "premier segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "premier segment"}]}),
        httpx.Response(200, json={"text": "second segment",
                                  "segments": [{"start": 0.0, "end": 5.0, "text": "second segment"}]}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert "premier segment" in resultat.texte
    assert "second segment" in resultat.texte
    # 3 appels exactement : le 429 de la piste entière n'a PAS été retenté.
    assert route.call_count == 3
    assert resultat.segments[1].debut == pytest.approx(t.LIMITE_SEGMENT_S)


# ── 429 informé par le sort de la piste précédente (vécu 2026-08-05 après-midi :
# moi.opus 74 min passait entier, systeme.opus prenait le 429 de fenêtre pleine) ────

@respx.mock
def test_429_apres_piste_entiere_attend_puis_retente_entier(tmp_path, monkeypatch):
    chemin = tmp_path / "systeme.opus"
    chemin.write_bytes(b"faux-opus-long")

    attentes: list[float] = []
    monkeypatch.setattr(t, "_dormir", attentes.append)

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429),                                     # fenêtre pleine
        httpx.Response(200, json={"text": "entier au 2e essai"}),  # fenêtre vidée
    ]

    monkeypatch.setattr(t, "decouper_piste",
                        lambda *a: pytest.fail("découpage inutile : l'entier devait repasser"))

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest",
                                    precedente_entiere=True)

    assert resultat.texte == "entier au 2e essai"
    assert resultat.decoupee is False
    assert route.call_count == 2
    assert attentes == [t._ATTENTE_FENETRE_S]


@respx.mock
def test_429_persistant_apres_piste_entiere_finit_en_decoupage(tmp_path, monkeypatch):
    chemin = tmp_path / "systeme.opus"
    chemin.write_bytes(b"faux-opus-long")

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429),                                    # entier, 1er essai
        httpx.Response(429),                                    # entier, après attente
        httpx.Response(200, json={"text": "premier segment"}),
        httpx.Response(200, json={"text": "second segment"}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest",
                                    precedente_entiere=True)

    assert "premier segment" in resultat.texte
    assert resultat.decoupee is True
    assert route.call_count == 4


@respx.mock
def test_piste_precedente_decoupee_decoupe_directement(tmp_path, monkeypatch):
    # La piste 1 a été découpée : l'envoi entier de la piste 2 échouerait pareil,
    # on ne le tente même pas (aucun appel avec le fichier complet).
    chemin = tmp_path / "systeme.opus"
    chemin.write_bytes(b"faux-opus-long")

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(200, json={"text": "premier segment"}),
        httpx.Response(200, json={"text": "second segment"}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest",
                                    precedente_entiere=False)

    assert "premier segment" in resultat.texte
    assert resultat.decoupee is True
    # 2 appels seulement : les segments — l'entier n'a jamais été envoyé.
    assert route.call_count == 2


@respx.mock
def test_segments_gardent_les_retries_429(tmp_path, monkeypatch):
    # Un 429 transitoire sur un SEGMENT (fenêtre pleine) est retenté, lui.
    chemin = tmp_path / "longue_reunion.opus"
    chemin.write_bytes(b"faux-opus-long")

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429),                                   # piste entière → découpage direct
        httpx.Response(429),                                   # segment 1, 1re tentative
        httpx.Response(200, json={"text": "premier segment"}),  # segment 1, retry OK
        httpx.Response(200, json={"text": "second segment"}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert "premier segment" in resultat.texte
    assert "second segment" in resultat.texte
    assert route.call_count == 4


# ── compaction des silences avant envoi (§10.2, terrain 2026-08-18) ─────────────

def _plan_utile():
    """Deux plages sonores dans une piste de 200 s (cas « réunion physique »)."""
    return PlanCompaction(plages=((10.0, 20.0), (100.0, 130.0)), duree_totale_s=200.0)


@respx.mock
def test_compaction_envoie_le_fichier_compacte_et_replace_les_horodatages(tmp_path, monkeypatch):
    chemin = _wav_audible(tmp_path, "systeme.wav")
    compacte = _wav_audible(tmp_path, "systeme_compacte.opus")
    monkeypatch.setattr(t, "compacter_piste", lambda src, dossier, plan: compacte)

    envoyes: list[str] = []

    def _reponse(requete):
        envoyes.append(requete.content.decode("utf-8", "replace"))
        return httpx.Response(200, json={"text": "salut",
                                         "segments": [{"start": 5.0, "end": 12.0, "text": "salut"}]})

    respx.post(f"{URL}/v1/audio/transcriptions").mock(side_effect=_reponse)
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest", plan=_plan_utile())

    assert "systeme_compacte.opus" in envoyes[0], "c'est la piste compactée qui part"
    # 5 s et 12 s dans la timeline compactée → 15 s et 102 s dans l'originale
    # (1re plage de 10 s, puis reprise à 100 s) : sans ce report, la fusion placerait
    # des propos de la 100e seconde au début de la réunion.
    assert resultat.segments[0].debut == pytest.approx(15.0)
    assert resultat.segments[0].fin == pytest.approx(102.0)


@respx.mock
def test_plan_inutile_envoie_la_piste_telle_quelle(tmp_path, monkeypatch):
    chemin = _wav_audible(tmp_path, "moi.wav")
    monkeypatch.setattr(t, "compacter_piste",
                        lambda *a, **k: pytest.fail("aucune compaction attendue"))
    plan_plein = PlanCompaction(plages=((0.0, 195.0),), duree_totale_s=200.0)

    envoyes: list[str] = []

    def _reponse(requete):
        envoyes.append(requete.content.decode("utf-8", "replace"))
        return httpx.Response(200, json={"text": "ok", "segments": [{"start": 1.0, "end": 2.0,
                                                                     "text": "ok"}]})

    respx.post(f"{URL}/v1/audio/transcriptions").mock(side_effect=_reponse)
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest", plan=plan_plein)

    assert "moi.wav" in envoyes[0]
    assert resultat.segments[0].debut == pytest.approx(1.0), "horodatages inchangés"


@respx.mock
def test_echec_de_compaction_retombe_sur_l_envoi_integral(tmp_path, monkeypatch):
    """La compaction est un confort : elle ne doit jamais faire perdre le CR."""
    chemin = _wav_audible(tmp_path, "systeme.wav")

    def _explose(*_a, **_k):
        raise OSError("ffmpeg indisponible")

    monkeypatch.setattr(t, "compacter_piste", _explose)

    envoyes: list[str] = []

    def _reponse(requete):
        envoyes.append(requete.content.decode("utf-8", "replace"))
        return httpx.Response(200, json={"text": "malgré tout"})

    respx.post(f"{URL}/v1/audio/transcriptions").mock(side_effect=_reponse)
    client = ClientMistral(URL, "cle")

    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest", plan=_plan_utile())

    assert resultat.texte == "malgré tout"
    assert "systeme.wav" in envoyes[0]


def test_analyser_piste_fournit_le_plan(tmp_path):
    analyse = t.analyser_piste(_wav_audible(tmp_path, secondes=3.0))
    assert analyse.plan is not None
    assert analyse.plan.duree_totale_s == pytest.approx(3.0, abs=0.1)


# ── cumul de l'usage dans le repli découpage (terrain 2026-09-07) ──────────────────
#
# Une réunion de 2 h a été perdue chez une utilisatrice Windows : 429 sur l'envoi
# entier → repli découpage → tous les segments transcrits et facturés → puis
# `TypeError: unsupported operand type(s) for +: 'int' and 'dict'` au moment
# d'additionner les `usage`. Mesuré le jour même sur l'API réelle : `usage` porte
# `prompt_tokens_details` (sous-dictionnaire) et `service_tier` (chaîne) à côté de
# ses compteurs. Aucun test ne pouvait le voir : tous les payloads de découpage
# ci-dessus sont mockés SANS clé `usage`, donc la boucle de cumul ne tournait jamais.

_USAGE_REEL = {                       # relevé de /v1/audio/transcriptions, 2026-09-07
    "prompt_audio_seconds": 2,
    "prompt_tokens": 4,
    "total_tokens": 380,
    "completion_tokens": 1,
    "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 375},
    "service_tier": "standard",
}


@respx.mock
def test_decoupage_survit_a_l_usage_reel_de_voxtral(tmp_path, monkeypatch):
    """Le découpage aboutit alors que `usage` mélange nombres, dict et chaîne."""
    chemin = tmp_path / "longue.opus"
    chemin.write_bytes(b"faux-opus-long")

    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(429, json={"message": "rate limit"}),      # envoi entier refusé
        httpx.Response(200, json={"text": "un", "usage": _USAGE_REEL}),
        httpx.Response(200, json={"text": "deux", "usage": _USAGE_REEL}),
    ]

    seg1 = tmp_path / "seg1.opus"
    seg1.write_bytes(b"x")
    seg2 = tmp_path / "seg2.opus"
    seg2.write_bytes(b"y")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg1, seg2])

    client = ClientMistral(URL, "cle")
    resultat = t.transcrire_fichier(client, chemin, "voxtral-mini-latest")

    assert resultat.texte == "un deux", "la transcription des 2 segments est rendue"
    assert resultat.decoupee is True
    # Les compteurs se cumulent, y compris dans le sous-dictionnaire ; la chaîne est
    # recopiée telle quelle plutôt que d'interrompre un découpage réussi.
    assert resultat.usage["total_tokens"] == 760
    assert resultat.usage["prompt_tokens_details"]["audio_tokens"] == 750
    assert resultat.usage["service_tier"] == "standard"


def test_cumuler_usage_ne_somme_que_les_nombres():
    total: dict = {}
    t._cumuler_usage(total, {"n": 1, "x": 1.5, "details": {"a": 2}, "tier": "standard",
                             "flag": True, "vide": None})
    t._cumuler_usage(total, {"n": 2, "x": 0.5, "details": {"a": 3, "b": 1}, "tier": "premier",
                             "flag": False, "vide": None})
    assert total["n"] == 3
    assert total["x"] == pytest.approx(2.0)
    assert total["details"] == {"a": 5, "b": 1}
    assert total["tier"] == "premier", "dernier segment gagne pour les non-nombres"
    assert total["flag"] is False, "un booléen n'est pas un compteur"
    assert total["vide"] is None


# ── Motif du 429 journalisé à la bascule en découpage (docs/42 §10.8) ────────────
# 71 % des transcriptions d'un poste passaient par le découpage sur un 429 dont le log
# ne disait pas la nature : quota (attendre suffirait) ou capacité côté Mistral.

_CORPS_CAPACITE = ('{"object":"error","message":"Not enough capacity available for this '
                   'request, please retry later.","type":"backend_out_of_capacity",'
                   '"code":"3505"}')


def _segments_factices(tmp_path, monkeypatch):
    seg = tmp_path / "seg1.opus"
    seg.write_bytes(b"x")
    monkeypatch.setattr(t, "decouper_piste", lambda chemin, dossier: [seg])


@respx.mock
def test_bascule_en_decoupage_journalise_le_motif_du_429(tmp_path, monkeypatch, caplog):
    chemin = tmp_path / "moi.opus"
    chemin.write_bytes(b"faux-opus-long")
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [httpx.Response(429, text=_CORPS_CAPACITE),
                         httpx.Response(200, json={"text": "segment"})]
    _segments_factices(tmp_path, monkeypatch)

    with caplog.at_level("WARNING", logger="debrief_meet.core.mistral.transcription"):
        t.transcrire_fichier(ClientMistral(URL, "cle"), chemin, "voxtral-mini-latest")

    ligne = next(r.getMessage() for r in caplog.records if "repli découpage sans retry" in r.getMessage())
    assert "backend_out_of_capacity (code 3505)" in ligne


@respx.mock
def test_429_persistant_apres_attente_journalise_aussi_le_motif(tmp_path, monkeypatch, caplog):
    chemin = tmp_path / "systeme.opus"
    chemin.write_bytes(b"faux-opus-long")
    route = respx.post(f"{URL}/v1/audio/transcriptions")
    route.side_effect = [httpx.Response(429, text=_CORPS_CAPACITE),
                         httpx.Response(429, text=_CORPS_CAPACITE),
                         httpx.Response(200, json={"text": "segment"})]
    _segments_factices(tmp_path, monkeypatch)

    with caplog.at_level("WARNING", logger="debrief_meet.core.mistral.transcription"):
        t.transcrire_fichier(ClientMistral(URL, "cle"), chemin, "voxtral-mini-latest",
                             precedente_entiere=True)

    lignes = [r.getMessage() for r in caplog.records if "Quota Mistral (429)" in r.getMessage()]
    assert len(lignes) == 2
    assert all("backend_out_of_capacity (code 3505)" in l for l in lignes)
