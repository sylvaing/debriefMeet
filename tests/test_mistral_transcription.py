"""Tests unitaires — transcription Voxtral (sans réseau, respx ; sans ffmpeg réel)."""
from __future__ import annotations

import httpx
import numpy as np
import pytest
import respx
from scipy.io import wavfile

from debrief_meet.core.mistral import transcription as t
from debrief_meet.core.mistral.client import ClientMistral

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
