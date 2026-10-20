"""Tests unitaires — pipeline bout-en-bout (§4). Décision adaptative (§1) : transcript
local par défaut, repli Voxtral si absent, forçage possible. Aucun réseau réel (respx)."""
from __future__ import annotations

import httpx
import numpy as np
import pytest
import respx
from scipy.io import wavfile

from debrief_meet.core.fichiers import (
    MARQUEUR_EN_ATTENTE,
    chemin_cr_mistral,
    chemin_locuteurs,
    renommer_dossier_reunion,
)
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


def _piste(tmp_path, suffixe, silencieuse=False, duree_s=1.0):
    n = int(16000 * duree_s)
    valeurs = np.zeros(n, dtype=np.int16) if silencieuse else np.full(n, 3000, dtype=np.int16)
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


def test_piste_systeme_informee_du_sort_de_la_piste_moi(tmp_path, config_tmp, monkeypatch):
    # Le sort de la 1re piste (entière ou découpée) est transmis à la 2e via
    # `precedente_entiere` — c'est lui qui décide du sens d'un éventuel 429.
    from debrief_meet.core.mistral.transcription import TranscriptionMistral

    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme")
    _configurer(config_tmp)

    appels: list[tuple[str, bool | None]] = []

    def _faux_transcrire(client, piste, modele, langue, context_bias, precedente_entiere=None,
                         plan=None):
        appels.append((piste.stem, precedente_entiere))
        return TranscriptionMistral(texte=f"texte {piste.stem}", decoupee=(piste.stem == "moi"))

    monkeypatch.setattr(pipeline, "transcrire_fichier", _faux_transcrire)
    pipeline._transcrire_via_voxtral(md, client=None, config=config_tmp, context_bias=[])

    # moi : aucune info (1re piste) ; systeme : informée que moi a été DÉCOUPÉE.
    assert appels == [("moi", None), ("systeme", False)]


def test_piste_systeme_sait_que_moi_est_passee_entiere(tmp_path, config_tmp, monkeypatch):
    from debrief_meet.core.mistral.transcription import TranscriptionMistral

    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme")
    _configurer(config_tmp)

    appels: list[tuple[str, bool | None]] = []

    def _faux_transcrire(client, piste, modele, langue, context_bias, precedente_entiere=None,
                         plan=None):
        appels.append((piste.stem, precedente_entiere))
        return TranscriptionMistral(texte=f"texte {piste.stem}")

    monkeypatch.setattr(pipeline, "transcrire_fichier", _faux_transcrire)
    pipeline._transcrire_via_voxtral(md, client=None, config=config_tmp, context_bias=[])

    assert appels == [("moi", None), ("systeme", True)]


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


@respx.mock
def test_garde_fou_mesure_la_reunion_et_non_la_somme_des_pistes(tmp_path, config_tmp):
    """Régression du 2026-08-18 : les deux pistes étant enregistrées SIMULTANÉMENT,
    les additionner divisait par deux la limite réelle — une réunion de 98 min était
    refusée comme « 197 min »."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi", duree_s=60.0)
    _piste(tmp_path, "systeme", duree_s=60.0)
    # 1 min par piste : la réunion dure 1 min (limite atteinte, pas dépassée), alors
    # que la somme des deux ferait 2 min et déclencherait le refus.
    _configurer(config_tmp, mistral_duree_max_min=1)

    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    chemin_cr = pipeline.generer_cr_reunion(md, config_tmp)

    assert chemin_cr.exists()


@respx.mock
def test_message_du_garde_fou_designe_le_reglage_reel(tmp_path, config_tmp):
    """Le message renvoyait l'utilisateur vers un réglage absent de l'interface."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp, mistral_duree_max_min=0)

    with pytest.raises(ErreurMistral, match="IA en ligne"):
        pipeline.generer_cr_reunion(md, config_tmp)


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
    """En repli Voxtral, les noms d'invités (tous) servent de context_bias (orthographe).
    Chaque nom est découpé en jetons (Voxtral refuse les espaces/virgules, code 3051) :
    3 invités « Prénom Nom » → 6 jetons. Lexique désactivé pour isoler les invités
    (sa contribution au biais est couverte par les tests lexique ci-dessous)."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _ecrire_association(md)
    _configurer(config_tmp, lexique_actif=False)
    route_t = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_t.calls.last.request.content
    assert corps.count(b'name="context_bias"') == 6   # 3 invités × 2 mots (tous, même non cochés)
    for jeton in (b"Alice", b"Martin", b"Carol", b"Absente"):
        assert jeton in corps
    # jamais d'item avec espace (ce qui provoquait le 400 côté Voxtral)
    assert b"Alice Martin" not in corps


@respx.mock
def test_association_injecte_la_date_dans_le_cr(tmp_path, config_tmp):
    """La date de l'événement associé est injectée dans le CR (le prompt demande
    « CR — [Sujet] — [Date] »). Débriefe depuis le transcript local."""
    md = _md_avec_transcript(tmp_path)
    _ecrire_association(md)                     # sidecar debut = 2026-01-01T10:00:00
    _configurer(config_tmp)
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert b"01/01/2026 10:00" in route_cr.calls.last.request.content


# ── Lexique de corrections (docs/46) ─────────────────────────────────────────────

@respx.mock
def test_lexique_injecte_le_bloc_dans_le_prompt_cr(tmp_path, config_tmp):
    """Lexique actif par défaut + une ligne saisie → le bloc de corrections suit le
    prompt résolu, quel que soit son chemin d'entrée (docs/46 §5.1)."""
    md = _md_avec_transcript(tmp_path)
    _configurer(config_tmp, lexique_corrections=[
        {"entendu": "Seppning Club", "ecrire": "SecNumCloud"}])
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_cr.calls.last.request.content
    assert b"Corrections de transcription" in corps
    assert b"SecNumCloud" in corps                    # ligne du tableau saisi


@respx.mock
def test_lexique_complete_aussi_le_prompt_ponctuel(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    _configurer(config_tmp, lexique_corrections=[{"entendu": "Mappy", "ecrire": "MAPI"}])
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp, prompt="Prompt ponctuel choisi.")

    corps = route_cr.calls.last.request.content
    assert b"Prompt ponctuel choisi." in corps
    assert b"Corrections de transcription" in corps


@respx.mock
def test_lexique_inactif_prompt_intact(tmp_path, config_tmp):
    md = _md_avec_transcript(tmp_path)
    _configurer(config_tmp, lexique_actif=False)
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert b"Corrections de transcription" not in route_cr.calls.last.request.content


@respx.mock
def test_lexique_alimente_le_context_bias_voxtral(tmp_path, config_tmp):
    """Sans association BlueMind, le biais = les termes « à écrire » du lexique,
    parenthèses retirées (docs/46 §5.3)."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp, lexique_corrections=[
        {"entendu": "Acmé", "ecrire": "ACME (société fictive)"},
        {"entendu": "Seppning Club", "ecrire": "SecNumCloud"},
    ])
    route_t = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_t.calls.last.request.content
    assert corps.count(b'name="context_bias"') == 2
    assert b"ACME" in corps and b"SecNumCloud" in corps
    assert b"fictive" not in corps                    # précision parenthèses exclue


@respx.mock
def test_invites_prioritaires_devant_le_lexique_dans_le_biais(tmp_path, config_tmp):
    """Invités BlueMind en tête du biais : prioritaires dans la coupe à 100 jetons."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _ecrire_association(md)
    _configurer(config_tmp, lexique_corrections=[{"entendu": "Blue Moon", "ecrire": "BlueMind"}])
    route_t = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    corps = route_t.calls.last.request.content
    assert corps.count(b'name="context_bias"') == 7   # 3 invités × 2 mots + 1 terme lexique
    assert corps.index(b"Alice") < corps.index(b"BlueMind")


@respx.mock
def test_lexique_inactif_pas_de_biais_lexique(tmp_path, config_tmp):
    """Même interrupteur pour le prompt et le biais (docs/46 §5.3) — inactif, seuls
    les invités restent."""
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp, lexique_actif=False)
    route_t = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    assert b'name="context_bias"' not in route_t.calls.last.request.content


@respx.mock
def test_voxtral_reinsere_le_cartouche_invites(tmp_path, config_tmp):
    """Après réécriture Voxtral du `.md`, le cartouche invités BlueMind (effacé par la
    réécriture) est ré-inséré depuis le sidecar — cohérence + portabilité (docs/42 §7.5)."""
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT

    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _ecrire_association(md)                     # écrit le sidecar (pas le bloc dans le .md)
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "bonjour"}))
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    pipeline.generer_cr_reunion(md, config_tmp)

    contenu = md.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in contenu            # cartouche ré-inséré
    assert "Alice Martin" in contenu            # invité coché
    assert "Carol Absente" not in contenu       # invité non coché exclu
    assert "bonjour" in contenu                 # transcription Voxtral bien écrite


# ── Renommage du dossier PENDANT le job (docs/43 §6) ───────────────────────────
#
# Le job dure des minutes ; pendant ce temps l'utilisateur peut associer la réunion à
# un événement BlueMind ou éditer son titre — les deux renomment le dossier. Deux
# échecs réels le 2026-08-26 (CR perdu, à relancer à la main) : l'un à l'écriture de
# `transcription.md` juste après l'upload Voxtral, l'autre à l'écriture de `CR.md`.


def _reunion_en_dossier(tmp_path, contenu, nom="2026-08-26_16-20-54"):
    dossier = tmp_path / nom
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text(contenu, encoding="utf-8")
    return md


@respx.mock
def test_cr_ecrit_dans_le_dossier_renomme_pendant_la_redaction(tmp_path, config_tmp):
    """Cas du 2026-08-26 16:26 : lecture passée, `CR.md` écrit dans un dossier qui
    n'existait plus. Le renommage survient ici pendant l'appel de rédaction."""
    md = _reunion_en_dossier(
        tmp_path, "# Réunion — 2026-08-26 16:20\n\n---\n\n**Moi :** Bonjour.\n")
    _configurer(config_tmp)
    apres = {}

    def _renomme_puis_repond(request):
        apres["md"] = renommer_dossier_reunion(md, "Point Acme")
        return _REP_CR

    respx.post(f"{URL}/v1/chat/completions").mock(side_effect=_renomme_puis_repond)

    chemin_cr = pipeline.generer_cr_reunion(md, config_tmp)

    assert chemin_cr == apres["md"].with_name("CR.md")
    assert chemin_cr.read_text(encoding="utf-8").strip() == "# CR généré"
    assert not (tmp_path / "2026-08-26_16-20-54").exists()      # l'ancien dossier n'a pas repoussé


@respx.mock
def test_transcription_recuperee_dans_le_dossier_renomme_pendant_voxtral(tmp_path, config_tmp):
    """Cas du 2026-08-26 16:19 : échec 347 ms après la fin de l'upload Voxtral, au moment
    de réécrire `transcription.md` (récupération de la transcription en local)."""
    md = _reunion_en_dossier(
        tmp_path, f"# Réunion — 2026-08-26 16:20\n\n> {MARQUEUR_EN_ATTENTE}\n",
        nom="2026-08-26_15-53-44")
    _piste(md.parent, "moi")
    _configurer(config_tmp)
    apres = {}

    def _renomme_puis_repond(request):
        apres["md"] = renommer_dossier_reunion(md, "Point Marseille")
        return httpx.Response(200, json={"text": "compte rendu de la réunion"})

    respx.post(f"{URL}/v1/audio/transcriptions").mock(side_effect=_renomme_puis_repond)
    respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    chemin_cr = pipeline.generer_cr_reunion(md, config_tmp)

    nouveau_md = apres["md"]
    contenu = nouveau_md.read_text(encoding="utf-8")
    assert MARQUEUR_EN_ATTENTE not in contenu                    # transcription récupérée
    assert "compte rendu de la réunion" in contenu
    assert chemin_cr == nouveau_md.with_name("CR.md")


@respx.mock
def test_dossier_supprime_pendant_le_job_echoue_comme_avant(tmp_path, config_tmp):
    """Garde-fou : la re-résolution répare un renommage, elle n'invente pas une réunion.
    Un dossier supprimé doit toujours faire échouer le job (et non écrire ailleurs)."""
    import shutil

    md = _reunion_en_dossier(
        tmp_path, "# Réunion\n\n---\n\n**Moi :** Bonjour.\n")
    _configurer(config_tmp)

    def _supprime_puis_repond(request):
        shutil.rmtree(md.parent)
        return _REP_CR

    respx.post(f"{URL}/v1/chat/completions").mock(side_effect=_supprime_puis_repond)

    with pytest.raises(FileNotFoundError):
        pipeline.generer_cr_reunion(md, config_tmp)


# ── transcrire_reunion : transcription distante SEULE (sans CR) ─────────────────

@respx.mock
def test_transcrire_reunion_ecrit_le_md_et_ne_produit_aucun_cr(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp)
    route_transcription = respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "texte voxtral"}))
    route_cr = respx.post(f"{URL}/v1/chat/completions").mock(return_value=_REP_CR)

    sortie = pipeline.transcrire_reunion(md, config_tmp)

    assert sortie == md
    assert "texte voxtral" in md.read_text(encoding="utf-8")
    assert route_transcription.call_count == 1
    # Le point de la tâche : aucun appel de rédaction, aucun CR sur le disque.
    assert route_cr.call_count == 0
    assert not chemin_cr_mistral(md).exists()


@respx.mock
def test_transcrire_reunion_mentionne_voxtral_dans_le_md(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "texte voxtral"}))

    pipeline.transcrire_reunion(md, config_tmp)

    assert "Voxtral" in md.read_text(encoding="utf-8")


@respx.mock
def test_transcrire_reunion_supprime_le_debrief_locuteurs_perime(tmp_path, config_tmp):
    """Garder `locuteurs.md` ferait rédiger le prochain CR sur le texte REMPLACÉ :
    `_lire_transcript_local` lui donne la priorité sur `transcription.md`."""
    md = _md_avec_transcript(tmp_path)
    chemin_locuteurs(md).write_text("**Alice :** ancien texte", encoding="utf-8")
    _piste(tmp_path, "moi")
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "nouveau texte voxtral"}))

    pipeline.transcrire_reunion(md, config_tmp)

    assert not chemin_locuteurs(md).exists()
    assert "nouveau texte voxtral" in md.read_text(encoding="utf-8")


@respx.mock
def test_transcrire_reunion_sans_locuteurs_ne_leve_pas(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _configurer(config_tmp)
    respx.post(f"{URL}/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "t"}))

    assert pipeline.transcrire_reunion(md, config_tmp) == md


def test_transcrire_reunion_leve_sans_cle_api(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi")
    with pytest.raises(ErreurMistral):
        pipeline.transcrire_reunion(md, config_tmp)


def test_transcrire_reunion_leve_si_aucune_piste(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _configurer(config_tmp)
    with pytest.raises(FileNotFoundError):
        pipeline.transcrire_reunion(md, config_tmp)


@respx.mock
def test_transcrire_reunion_respecte_la_duree_max(tmp_path, config_tmp):
    md = _md_placeholder(tmp_path)
    _piste(tmp_path, "moi", duree_s=120)
    _configurer(config_tmp, mistral_duree_max_min=1)
    with pytest.raises(ErreurMistral, match="trop longue"):
        pipeline.transcrire_reunion(md, config_tmp)


@respx.mock
def test_transcrire_reunion_ecrit_dans_le_dossier_renomme_pendant_le_job(tmp_path, config_tmp):
    """docs/43 §16 : le renommage est déclenché DEPUIS le mock, donc pendant l'upload.

    Posé avant l'appel, il testerait un cas plus facile que le code d'entrée gère déjà
    (`resoudre_chemin_reunion` en tête de fonction) et resterait vert en cas de
    régression sur la re-résolution d'APRÈS transcription."""
    dossier = tmp_path / "2026-05-05_14-00-00"
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text(f"# Réunion\n\n> {MARQUEUR_EN_ATTENTE}\n", encoding="utf-8")
    _piste(dossier, "moi")
    _configurer(config_tmp)
    nouveau: dict = {}

    def _renommer_puis_repondre(_request):
        nouveau["md"] = renommer_dossier_reunion(md, "Point hebdo")
        return httpx.Response(200, json={"text": "texte apres renommage"})

    respx.post(f"{URL}/v1/audio/transcriptions").mock(side_effect=_renommer_puis_repondre)

    sortie = pipeline.transcrire_reunion(md, config_tmp)

    assert nouveau["md"] != md                      # le renommage a bien eu lieu
    assert sortie == nouveau["md"]
    assert "texte apres renommage" in nouveau["md"].read_text(encoding="utf-8")
    assert not md.exists()                          # rien écrit à l'ancien chemin
