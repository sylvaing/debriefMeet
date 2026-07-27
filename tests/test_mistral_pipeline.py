"""Tests unitaires — pipeline bout-en-bout (§4). Décision adaptative (§1) : transcript
local par défaut, repli Voxtral si absent, forçage possible. Aucun réseau réel (respx)."""
from __future__ import annotations

import httpx
import numpy as np
import pytest
import respx
from scipy.io import wavfile

from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE
from debrief_meet.core.mistral import pipeline
from debrief_meet.core.mistral.client import ErreurMistral

URL = "https://api.mistral.ai"
_REP_CR = httpx.Response(200, json={"choices": [{"message": {"content": "# CR généré"}}],
                                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}})


@pytest.fixture(autouse=True)
def _pas_de_vrai_sommeil(monkeypatch):
    monkeypatch.setattr("debrief_meet.core.mistral.client._dormir", lambda _s: None)


def _md_avec_transcript(tmp_path, nom="2026-01-01_10-00-00"):
    md = tmp_path / f"{nom}.md"
    md.write_text(
        "# Réunion — 2026-01-01 10:00\n\n---\n\n**Moi :** Bonjour à tous.\n\n"
        "**Participants :** Salut !\n\n", encoding="utf-8")
    return md


def _md_placeholder(tmp_path, nom="2026-01-01_11-00-00"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion — 2026-01-01 11:00\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    return md


def _configurer(config_tmp, **overrides):
    config_tmp.set("mistral_cle_api", "cle-de-test")
    config_tmp.set("mistral_base_url", URL)
    for cle, valeur in overrides.items():
        config_tmp.set(cle, valeur)
    return config_tmp


def _piste(tmp_path, suffixe, silencieuse=False):
    valeurs = np.zeros(16000, dtype=np.int16) if silencieuse else np.full(16000, 3000, dtype=np.int16)
    wavfile.write(tmp_path / f"{suffixe}.wav", 16000, valeurs)


# ── disponible() ───────────────────────────────────────────────────────────────

def test_disponible_faux_sans_cle(config_tmp):
    assert pipeline.disponible(config_tmp) is False


def test_disponible_vrai_avec_cle(config_tmp):
    config_tmp.set("mistral_cle_api", "x")
    assert pipeline.disponible(config_tmp) is True


# ── Défaut adaptatif : transcript local ─────────────────────────────────────────

@respx.mock
def test_utilise_le_transcript_local_par_defaut(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    _configurer(config_tmp)
    route_transcription = respx.post(f"{URL}/v1/audio/transcriptions")
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    chemin_cr = pipeline.generer_cr_reunion(md, config_tmp)

    assert chemin_cr.name == "CR.md"
    assert chemin_cr.read_text(encoding="utf-8").strip() == "# CR généré"
    assert route_transcription.call_count == 0        # aucun upload audio (§1)
    assert route_cr.call_count == 1
    assert b"Bonjour" in route_cr.calls.last.request.content


@respx.mock
def test_transcript_local_utilise_le_fichier_locuteurs_si_present(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    locuteurs = md.with_name("locuteurs.md")
    locuteurs.write_text("**SPEAKER_00 :** Contenu locuteurs.", encoding="utf-8")
    _configurer(config_tmp)
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert b"Contenu locuteurs" in route_cr.calls.last.request.content


# ── Repli Voxtral (pas de transcript local exploitable) ─────────────────────────

@respx.mock
def test_repli_voxtral_si_placeholder_audio_seul(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme", silencieuse=True)  # ignorée (§7.4)
    _configurer(config_tmp)

    route_transcription = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "transcription voxtral"}))
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    chemin_cr = pipeline.generer_cr_reunion(md, config_tmp)

    assert chemin_cr.exists()
    assert route_transcription.call_count == 1     # 1 seule piste envoyée (l'autre silencieuse)
    assert b"transcription voxtral" in route_cr.calls.last.request.content


@respx.mock
def test_voxtral_reecrit_le_transcript_local_avec_mention(tmp_path, config_tmp):
    """Placeholder « audio seul » → la transcription Voxtral est récupérée dans le .md
    local, avec la mention Voxtral et sans le marqueur d'attente."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "compte rendu de la réunion"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    contenu = md.read_text(encoding="utf-8")
    assert MARQUEUR_EN_ATTENTE not in contenu           # placeholder remplacé
    assert "Voxtral" in contenu                          # mention de la source
    assert "compte rendu de la réunion" in contenu       # transcription récupérée
    assert "**Moi :**" in contenu


@respx.mock
def test_forcer_voxtral_n_ecrase_pas_le_transcript_local_existant(tmp_path, config_tmp):
    """Si un transcript local existe déjà (pas un placeholder) et qu'on force Voxtral,
    le .md local ne doit PAS être écrasé — on ne détruit pas la transcription locale."""
    md = _md_avec_transcript(tmp_path)
    original = md.read_text(encoding="utf-8")
    _piste(tmp_path, "moi")
    _configurer(config_tmp, mistral_source_transcription="voxtral")
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "voxtral"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert md.read_text(encoding="utf-8") == original    # transcript local intact


def test_repli_voxtral_leve_si_aucune_piste(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _configurer(config_tmp)
    with pytest.raises(FileNotFoundError):
        pipeline.generer_cr_reunion(md, config_tmp)


@respx.mock
def test_repli_voxtral_leve_si_toutes_pistes_silencieuses(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi", silencieuse=True)
    _configurer(config_tmp)
    with pytest.raises(ErreurMistral):
        pipeline.generer_cr_reunion(md, config_tmp)


# ── Forçage Voxtral (option avancée, §9) ────────────────────────────────────────

@respx.mock
def test_forcer_voxtral_ignore_le_transcript_local(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp, mistral_source_transcription="voxtral")

    route_transcription = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "forcé via voxtral"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert route_transcription.call_count == 1


# ── Garde-fou durée (§13) ────────────────────────────────────────────────────────

@respx.mock
def test_garde_fou_duree_max_leve_avant_tout_appel_reseau(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp, mistral_duree_max_min=0)  # 1s d'audio > 0 min autorisée

    route_transcription = respx.post(f"{URL}/v1/audio/transcriptions")

    with pytest.raises(ErreurMistral):
        pipeline.generer_cr_reunion(md, config_tmp)

    assert route_transcription.call_count == 0


# ── Erreurs — pas de fichier partiel ─────────────────────────────────────────────

def test_sans_cle_api_leve_et_n_ecrit_rien(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    with pytest.raises(ErreurMistral):
        pipeline.generer_cr_reunion(md, config_tmp)
    assert not md.with_name("CR.md").exists()


@respx.mock
def test_echec_cr_n_ecrit_rien(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=httpx.Response(500))

    with pytest.raises(ErreurMistral):
        pipeline.generer_cr_reunion(md, config_tmp)

    assert not md.with_name("CR.md").exists()


# ── Association BlueMind exploitée (docs/40, §7.5) ───────────────────────────────

def _ecrire_association(md, titre="Point produit hebdo",
                        invites=(("Alice Martin", True), ("Bob Durand", True), ("Carol Absente", False))):
    from debrief_meet.core.bluemind import association
    asso = association.Association(
        event_uid="evt-1", cal_uid="cal-1", titre=titre, debut="2026-01-01T10:00:00",
        invites=[association.InviteAssocie(nom=nom, email=f"{nom}@x.fr", part_status="accepted",
                                           organisateur=False, coche=coche)
                 for nom, coche in invites])
    association.ecrire(md, asso)


@respx.mock
def test_association_injecte_sujet_et_participants_dans_le_cr(tmp_path, config_tmp):
    """Titre de l'événement + invités cochés → passés au CR (indépendant de la source)."""
    md = _md_avec_transcript(tmp_path)
    _ecrire_association(md)
    _configurer(config_tmp)
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_cr.calls.last.request.content
    assert b"Point produit hebdo" in corps           # sujet = titre de l'événement
    assert b"Alice Martin" in corps and b"Bob Durand" in corps
    assert b"Carol Absente" not in corps             # invité NON coché exclu des participants


@respx.mock
def test_association_alimente_le_context_bias_de_la_transcription(tmp_path, config_tmp):
    """En repli Voxtral, les noms d'invités (tous) servent de context_bias (orthographe)."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _ecrire_association(md)
    _configurer(config_tmp)
    route_t = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_t.calls.last.request.content
    assert corps.count(b'name="context_bias"') == 3   # tous les invités (même non cochés)
    assert b"Alice Martin" in corps and b"Carol Absente" in corps
