from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from debrief_meet.core import diarization as diar
from debrief_meet.core.audio import decoder_audio_16k
from debrief_meet.platform.interfaces import ResultatTranscription, Segment


# ── Fonctions pures : etiqueter ───────────────────────────────────────────────

def test_etiqueter_micro_une_voix_est_moi():
    segs = [(0.0, 1.0, "SPK0"), (1.0, 2.0, "SPK0")]
    r = diar.etiqueter(segs, "micro")
    assert {s[2] for s in r} == {"Moi"}


def test_etiqueter_micro_plusieurs_voix_present():
    segs = [(0.0, 1.0, "A"), (1.0, 2.0, "B"), (2.0, 3.0, "A"), (3.0, 4.0, "C")]
    r = diar.etiqueter(segs, "micro")
    # Ordre de 1ʳᵉ apparition : A→Présent 1, B→Présent 2, C→Présent 3.
    assert r[0][2] == "Présent 1"
    assert r[1][2] == "Présent 2"
    assert r[2][2] == "Présent 1"   # A réapparaît → label stable
    assert r[3][2] == "Présent 3"


def test_etiqueter_systeme_distant():
    segs = [(0.0, 1.0, "X"), (1.0, 2.0, "Y")]
    r = diar.etiqueter(segs, "systeme")
    assert [s[2] for s in r] == ["Distant 1", "Distant 2"]


def test_etiqueter_liste_vide():
    assert diar.etiqueter([], "micro") == []


# ── attribuer ─────────────────────────────────────────────────────────────────

def test_attribuer_chevauchement_majoritaire():
    whisper = [Segment(0.0, 2.0, "bonjour"), Segment(2.0, 4.0, "salut")]
    diar_segs = [(0.0, 1.8, "Moi"), (2.1, 4.0, "Distant 1")]
    r = diar.attribuer(whisper, diar_segs)
    assert r[0] == (0.0, 2.0, "Moi", "bonjour")
    assert r[1] == (2.0, 4.0, "Distant 1", "salut")


def test_attribuer_sans_recouvrement():
    whisper = [Segment(10.0, 11.0, "perdu")]
    diar_segs = [(0.0, 1.0, "Moi")]
    r = diar.attribuer(whisper, diar_segs)
    assert r[0][2] == "—"          # aucun locuteur attribué


def test_attribuer_diar_vide():
    whisper = [Segment(0.0, 1.0, "x")]
    assert diar.attribuer(whisper, [])[0][2] == "—"


# ── fusionner ─────────────────────────────────────────────────────────────────

def test_fusionner_tri_et_regroupement():
    micro = [(0.0, 1.0, "Moi", "un"), (1.0, 2.0, "Moi", "deux")]
    systeme = [(0.5, 1.5, "Distant 1", "trois")]
    tours = diar.fusionner(micro, systeme)
    # Tri par début : Moi(0.0) → Distant(0.5) → Moi(1.0). Pas de regroupement (alterne).
    assert [t[1] for t in tours] == ["Moi", "Distant 1", "Moi"]


def test_fusionner_regroupe_consecutifs():
    micro = [(0.0, 1.0, "Moi", "un"), (1.0, 2.0, "Moi", "deux")]
    tours = diar.fusionner(micro)
    assert len(tours) == 1
    assert tours[0] == (0.0, "Moi", "un deux")


def test_fusionner_ignore_texte_vide():
    assert diar.fusionner([(0.0, 1.0, "Moi", "   ")]) == []


# ── rendre_locuteurs_md ───────────────────────────────────────────────────────

def test_rendre_locuteurs_md(tmp_path):
    chemin = tmp_path / "r_locuteurs.md"
    diar.rendre_locuteurs_md(chemin, "Réunion — test — locuteurs",
                             [(0.0, "Moi", "bonjour"), (65.0, "Distant 1", "salut")])
    contenu = chemin.read_text(encoding="utf-8")
    assert "# Réunion — test — locuteurs" in contenu
    assert "**Moi** [00:00] bonjour" in contenu
    assert "**Distant 1** [01:05] salut" in contenu


# ── decoder_audio_16k ─────────────────────────────────────────────────────────

def test_decoder_audio_16k_wav_mono(tmp_path):
    chemin = tmp_path / "a.wav"
    sig = (0.3 * np.sin(np.linspace(0, 200, 16000))).astype(np.float32)
    wavfile.write(chemin, 16000, (sig * 32767).astype(np.int16))
    audio = decoder_audio_16k(chemin)
    assert audio.dtype == np.float32
    assert np.max(np.abs(audio)) <= 1.0          # normalisé
    assert len(audio) == pytest.approx(16000, abs=10)


def test_decoder_audio_16k_wav_stereo_reechantillonne(tmp_path):
    chemin = tmp_path / "s.wav"
    stereo = (np.random.rand(8000, 2) * 2 - 1).astype(np.float32)
    wavfile.write(chemin, 8000, (stereo * 32767).astype(np.int16))
    audio = decoder_audio_16k(chemin)
    assert audio.ndim == 1                         # mixé mono
    assert len(audio) == pytest.approx(16000, abs=50)  # 8k → 16k


# ── DiarizationPyannote (pipeline injecté, sans pyannote réel) ─────────────────

class _FauxTrack:
    def __init__(self, start, end):
        self.start, self.end = start, end


class _FauxAnnotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, lbl in self._tracks:
            yield _FauxTrack(start, end), None, lbl


class _FauxPipeline:
    def __init__(self, tracks):
        self._tracks = tracks

    def __call__(self, entree):
        assert "waveform" in entree and entree["sample_rate"] == diar.SR
        return _FauxAnnotation(self._tracks)


def test_diarization_pyannote_pipeline_injecte():
    # `diariser()` importe torch même avec un pipeline injecté — torch n'est pas
    # installé sur la VM Windows (diarization hors périmètre v1, docs/30 §3).
    pytest.importorskip("torch")
    moteur = diar.DiarizationPyannote(token="factice")
    moteur._pipeline = _FauxPipeline([(0.0, 1.0, "SPK0"), (1.0, 2.0, "SPK1")])
    segs = moteur.diariser(np.zeros(diar.SR, dtype=np.float32))
    assert segs == [(0.0, 1.0, "SPK0"), (1.0, 2.0, "SPK1")]


class _FauxPipelineGenerateur:
    """Pipeline dont `__call__` est une fonction génératrice — pyannote.audio 4.0.6.

    Reproduit le piège réel : l'appel rend un générateur sans exécuter le corps, et
    seul `apply()` (sur un fichier passé par `prepare_one`) rend le vrai résultat."""

    def __init__(self, tracks):
        self._tracks = tracks
        self.prepare = []

    def __call__(self, entree):
        yield entree, _FauxAnnotation(self._tracks)   # jamais atteint : générateur

    def prepare_one(self, fichier, preload=False):
        self.prepare.append(fichier)
        return {**fichier, "uri": "en-memoire"}

    def apply(self, fichier):
        assert fichier["uri"] == "en-memoire", "apply() exige un fichier préparé"
        return _FauxSortie(_FauxAnnotation(self._tracks))


class _FauxSortie:
    """`DiarizeOutput` de pyannote 4.x : l'annotation est sous `speaker_diarization`."""

    def __init__(self, annotation):
        self.speaker_diarization = annotation


def test_diarization_contourne_le_call_generateur():
    # Régression : en 4.0.6, `pipeline(...)` rendait un générateur → 'generator'
    # object has no attribute 'itertracks' sur les 2 pistes, aucun locuteurs.md.
    pytest.importorskip("torch")
    moteur = diar.DiarizationPyannote(token="factice")
    pipeline = _FauxPipelineGenerateur([(0.0, 1.0, "SPK0")])
    moteur._pipeline = pipeline
    assert moteur.diariser(np.zeros(diar.SR, dtype=np.float32)) == [(0.0, 1.0, "SPK0")]
    assert pipeline.prepare, "le fichier doit passer par prepare_one avant apply"


def test_diarization_sortie_inattendue_message_explicite():
    # Une future incompatibilité doit dire « version incompatible », pas AttributeError.
    pytest.importorskip("torch")
    moteur = diar.DiarizationPyannote(token="factice")
    moteur._pipeline = type("P", (), {"__call__": lambda self, _: object()})()
    with pytest.raises(diar.ErreurDiarization, match="incompatible"):
        moteur.diariser(np.zeros(diar.SR, dtype=np.float32))


def test_token_hf_depuis_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_xyz")
    assert diar._token_hf() == "hf_xyz"


def test_token_hf_repli_cache(monkeypatch):
    # Sans HF_TOKEN, on retombe sur le cache huggingface_hub.get_token().
    monkeypatch.delenv("HF_TOKEN", raising=False)
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "get_token", lambda: "hf_cache")
    assert diar._token_hf() == "hf_cache"


def test_moteur_diarization_base_abstrait():
    with pytest.raises(NotImplementedError):
        diar.MoteurDiarization().diariser(np.zeros(16, dtype=np.float32))


# ── normaliser_asr (non-régression : RMS retenu juste sous le seuil) ──────────

def test_normaliser_asr_remonte_audio_faible():
    # Cas réel du bug : RMS ~0.008 (juste sous le seuil moteur) → doit être remonté.
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(16000).astype(np.float32)) * 0.008  # RMS ≈ 0.008
    out = diar.normaliser_asr(audio, cible_rms=0.03)
    rms = float(np.sqrt(np.mean(out**2)))
    assert rms > 0.008 and rms == pytest.approx(0.03, abs=0.005)


def test_normaliser_asr_laisse_silence_pur():
    silence = np.zeros(16000, dtype=np.float32)
    assert float(np.max(np.abs(diar.normaliser_asr(silence)))) == 0.0


def test_normaliser_asr_natenue_pas_audio_fort():
    fort = (np.sin(np.linspace(0, 100, 16000)) * 0.5).astype(np.float32)
    rms_avant = float(np.sqrt(np.mean(fort**2)))
    out = diar.normaliser_asr(fort, cible_rms=0.03)
    assert float(np.sqrt(np.mean(out**2))) == pytest.approx(rms_avant, abs=1e-6)


def test_normaliser_asr_gain_plafonne():
    tres_faible = (np.sin(np.linspace(0, 100, 16000)) * 0.0001).astype(np.float32)
    out = diar.normaliser_asr(tres_faible, cible_rms=0.03, gain_max=20.0)
    # Gain plafonné à 20× → ne remonte pas jusqu'à la cible (évite d'amplifier du bruit).
    assert float(np.max(np.abs(out))) <= float(np.max(np.abs(tres_faible))) * 20.0 + 1e-6


# ── Orchestration : generer_locuteurs (moteurs fakes) ──────────────────────────

class FauxTranscription:
    """Renvoie des segments préprogrammés, un jeu par appel (micro puis système)."""

    def __init__(self, jeux: list[list[Segment]]):
        self._jeux = jeux
        self._appel = 0

    def transcrire(self, audio, langue=None):
        segs = self._jeux[self._appel]
        self._appel += 1
        return ResultatTranscription(" ".join(s.texte for s in segs), "fr", segs)


class FauxDiar(diar.MoteurDiarization):
    def __init__(self, jeux: list[list[tuple[float, float, str]]]):
        self._jeux = jeux
        self._appel = 0

    def diariser(self, audio_16k):
        segs = self._jeux[self._appel]
        self._appel += 1
        return segs


def _ecrire_wav(chemin, duree_s=2.0):
    n = int(duree_s * 16000)
    wavfile.write(chemin, 16000, np.zeros(n, dtype=np.int16))


def test_generer_locuteurs_deux_pistes(tmp_path):
    md = tmp_path / "transcription.md"
    md.write_text("# brouillon", encoding="utf-8")
    _ecrire_wav(tmp_path / "moi.wav")
    _ecrire_wav(tmp_path / "systeme.wav")

    transcription = FauxTranscription([
        [Segment(0.0, 1.0, "bonjour à tous")],            # micro
        [Segment(1.0, 2.0, "ici les distants")],          # système
    ])
    diarisation = FauxDiar([
        [(0.0, 1.0, "SPK0")],                              # micro : 1 voix → Moi
        [(1.0, 2.0, "D0")],                                # système → Distant 1
    ])

    sortie = diar.generer_locuteurs(md, transcription, diarisation)
    assert sortie.name == "locuteurs.md"
    contenu = sortie.read_text(encoding="utf-8")
    assert "**Moi** [00:00] bonjour à tous" in contenu
    assert "**Distant 1** [00:01] ici les distants" in contenu


def test_generer_locuteurs_systeme_absent_degrade(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("#", encoding="utf-8")
    _ecrire_wav(tmp_path / "moi.wav")            # pas de piste système

    transcription = FauxTranscription([[Segment(0.0, 1.0, "seul au micro")]])
    diarisation = FauxDiar([[(0.0, 1.0, "SPK0")]])
    sortie = diar.generer_locuteurs(md, transcription, diarisation)
    contenu = sortie.read_text(encoding="utf-8")
    assert "Moi" in contenu and "Distant" not in contenu


def test_generer_locuteurs_une_piste_echoue_lautre_passe(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("#", encoding="utf-8")
    _ecrire_wav(tmp_path / "moi.wav")
    _ecrire_wav(tmp_path / "systeme.wav")

    class TranscriptionMicroKO(FauxTranscription):
        def transcrire(self, audio, langue=None):
            if self._appel == 0:                  # 1er appel = micro → échec
                self._appel += 1
                raise RuntimeError("micro illisible")
            return super().transcrire(audio, langue)

    transcription = TranscriptionMicroKO([
        [],                                        # micro (jamais utilisé : lève)
        [Segment(0.0, 1.0, "les distants parlent")],
    ])
    diarisation = FauxDiar([[(0.0, 1.0, "D0")]])   # un seul jeu : seul le système diarize
    sortie = diar.generer_locuteurs(md, transcription, diarisation)
    contenu = sortie.read_text(encoding="utf-8")
    assert "Distant 1" in contenu                  # le système est passé
    assert "les distants parlent" in contenu


def test_generer_locuteurs_aucune_piste(tmp_path):
    md = tmp_path / "vide.md"
    md.write_text("#", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        diar.generer_locuteurs(md, FauxTranscription([]), FauxDiar([]))


# ── Onboarding : détection cache (modele_telecharge / configuree) ───────────────

def test_modele_telecharge_vrai(monkeypatch):
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, fichier: "/cache/config.yaml")
    assert diar.modele_telecharge() is True
    assert diar.configuree() is True


def test_modele_telecharge_faux(monkeypatch):
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache",
                        lambda repo, fichier: None)            # absent du cache
    assert diar.modele_telecharge() is False
    assert diar.configuree() is False


# ── Onboarding : téléchargement (erreurs typées, token jamais stocké) ───────────

def test_telecharger_token_vide_leve_erreur_token():
    with pytest.raises(diar.ErreurToken):
        diar.telecharger("   ")


def test_verifier_acces_gated_leve_erreur_licence(monkeypatch):
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.utils import GatedRepoError

    def _raise(*a, **k):
        raise GatedRepoError.__new__(GatedRepoError)   # bypass ctor (response requis)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _raise)
    with pytest.raises(diar.ErreurLicence):
        diar._verifier_acces("hf_x")


def test_verifier_acces_repo_introuvable_leve_erreur_token(monkeypatch):
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.utils import RepositoryNotFoundError

    def _raise(*a, **k):
        raise RepositoryNotFoundError.__new__(RepositoryNotFoundError)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _raise)
    with pytest.raises(diar.ErreurToken):
        diar._verifier_acces("hf_x")


def test_verifier_acces_reseau_leve_erreur_reseau(monkeypatch):
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub

    def _raise(*a, **k):
        raise ConnectionError("pas de réseau")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _raise)
    with pytest.raises(diar.ErreurReseau):
        diar._verifier_acces("hf_x")


def test_telecharger_succes_appelle_progression(monkeypatch):
    # pyannote/réseau évités : on stubbe les deux étapes internes.
    monkeypatch.setattr(diar, "_verifier_acces", lambda token: None)
    monkeypatch.setattr(diar, "_peupler_cache", lambda token: None)
    progres = []
    diar.telecharger("hf_abc", progression=progres.append)
    assert progres == [1.0]


def test_charger_force_offline_sans_token(monkeypatch):
    """_charger() lit le cache local en forçant HF_HUB_OFFLINE, sans token ni
    `local_files_only` (supprimé en pyannote 4.x — cf. docs/29)."""
    import sys, types
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    from huggingface_hub import constants

    appels = {}

    class _FakePipeline:
        @staticmethod
        def from_pretrained(repo, **kw):
            appels["repo"], appels["kw"] = repo, kw
            # Capture l'état offline AU MOMENT de l'appel (doit être True).
            appels["offline_pendant_appel"] = constants.HF_HUB_OFFLINE
            return object()

    faux_audio = types.ModuleType("pyannote.audio"); faux_audio.Pipeline = _FakePipeline
    faux_pyannote = types.ModuleType("pyannote"); faux_pyannote.audio = faux_audio
    faux_torch = types.ModuleType("torch")
    faux_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    faux_torch.backends = types.SimpleNamespace(mps=None)
    faux_torch.device = lambda x: x
    monkeypatch.setitem(sys.modules, "pyannote", faux_pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", faux_audio)
    monkeypatch.setitem(sys.modules, "torch", faux_torch)
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False)   # état de départ réaliste

    pipe = diar.DiarizationPyannote()._charger()

    assert pipe is not None
    assert "local_files_only" not in appels["kw"]            # supprimé en v4
    assert "token" not in appels["kw"]                        # plus de token au chargement
    assert appels["offline_pendant_appel"] is True            # offline forcé pendant l'appel
    assert constants.HF_HUB_OFFLINE is False                  # restauré après le bloc


class MoteurDiarizationErreur(diar.MoteurDiarization):
    """Simule une incompatibilité de chargement (modèle absent, API incompatible…)."""

    def precharger(self) -> None:
        raise diar.ErreurDiarization("modèle non téléchargé")

    def diariser(self, audio_16k):
        raise AssertionError("ne doit pas être appelé si precharger() a déjà échoué")


def test_precharger_propage_erreur_diarization_claire():
    with pytest.raises(diar.ErreurDiarization, match="modèle non téléchargé"):
        MoteurDiarizationErreur().precharger()


def test_generer_locuteurs_remonte_erreur_de_chargement_avant_la_boucle(tmp_path):
    """Une incompatibilité de chargement remonte via `precharger`, avant la boucle par
    piste — message clair, pas « toutes les pistes en échec » (cf. docs/29)."""
    md = tmp_path / "r.md"
    md.write_text("#", encoding="utf-8")
    _ecrire_wav(tmp_path / "moi.wav")

    with pytest.raises(diar.ErreurDiarization, match="modèle non téléchargé"):
        diar.generer_locuteurs(md, FauxTranscription([]), MoteurDiarizationErreur())


def test_mode_offline_hf_restaure_meme_si_exception():
    # `huggingface_hub` peut manquer dans l'environnement (clone partiel, docs/44) :
    # ce test porte sur du code qui en dépend, il se saute plutôt que de casser.
    pytest.importorskip("huggingface_hub")
    from huggingface_hub import constants

    constants.HF_HUB_OFFLINE = False
    with pytest.raises(ValueError):
        with diar._mode_offline_hf():
            assert constants.HF_HUB_OFFLINE is True
            raise ValueError("boum")
    assert constants.HF_HUB_OFFLINE is False
