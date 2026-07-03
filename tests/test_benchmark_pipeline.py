from __future__ import annotations

import numpy as np
import pytest

from benchmark import pipeline
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

MODE = {"moteur": "faux", "device": "cpu", "compute_type": "int8"}


class MoteurFauxBench:
    """Imite MoteurBench : renvoie un texte dépendant de la taille (qualité simulée)."""

    TEXTES = {
        "small": "le chien dormait sur le tapis",       # 2 substitutions vs large-v3
        "medium": "le chat dort sur le tapis rouge",    # 1 insertion
        "large-v3": "le chat dort sur le tapis",        # référence
    }

    def __init__(self, mode, cpu_threads=None):
        self.mode = mode
        self.taille = None

    def charger(self, taille):
        self.taille = taille

    def transcrire(self, audio, langue=None):
        txt = self.TEXTES.get(self.taille, "texte")
        return ResultatTranscription(txt, "fr", [Segment(0.0, 1.0, txt)])

    def liberer(self):
        pass


class MoteurQuiPlante(MoteurFauxBench):
    def charger(self, taille):
        if taille == "medium":
            raise RuntimeError("OOM simulé")
        super().charger(taille)


@pytest.fixture
def audio_court():
    # 3 s à 16 kHz → ~1 tranche (DUREE_TRANCHE_S = 30 s).
    return np.zeros(3 * pipeline.SR, dtype=np.float32)


def test_tronquer():
    audio = np.zeros(60 * pipeline.SR, dtype=np.float32)  # 60 s
    assert len(pipeline.tronquer(audio, pipeline.SR, 10)) == 10 * pipeline.SR
    assert len(pipeline.tronquer(audio, pipeline.SR, 0)) == len(audio)        # 0 = tout
    assert len(pipeline.tronquer(audio, pipeline.SR, 999)) == len(audio)      # plafond > durée


def test_decouper_nombre_de_tranches():
    audio = np.zeros(65 * pipeline.SR, dtype=np.float32)  # 65 s
    tranches = pipeline.decouper(audio, pipeline.SR, duree_tranche_s=30.0)
    assert len(tranches) == 3  # 30 + 30 + 5


def test_transcrire_modele_mesure(monkeypatch, tmp_path, audio_court):
    monkeypatch.setattr(pipeline.moteurs, "MoteurBench", MoteurFauxBench)
    r = pipeline.transcrire_modele(MODE, "small", pipeline.decouper(audio_court),
                                   pipeline.SR, "fr", tmp_path)
    assert r["modele"] == "small"
    assert r["rtf_moyen"] is not None
    assert isinstance(r["rtf_tranches"], list) and r["rtf_tranches"]
    assert r["n_mots"] > 0
    assert (tmp_path / r["artefact_txt"]).exists()


def test_executer_sweep_wer_relatif(monkeypatch, tmp_path, audio_court):
    monkeypatch.setattr(pipeline.moteurs, "MoteurBench", MoteurFauxBench)
    res = pipeline.executer_sweep(MODE, ["small", "medium", "large-v3"],
                                  audio_court, pipeline.SR, "fr", tmp_path)
    par_modele = {r["modele"]: r for r in res}
    # large-v3 est la référence → WER 0 ; small > medium.
    assert par_modele["large-v3"]["wer"] == 0.0
    assert par_modele["small"]["wer"] > par_modele["medium"]["wer"] > 0
    assert all(r.get("wer_reference") == "large-v3" for r in res)
    assert all("_texte" not in r for r in res)  # champ interne retiré


def test_executer_sweep_un_modele_echoue_continue(monkeypatch, tmp_path, audio_court):
    monkeypatch.setattr(pipeline.moteurs, "MoteurBench", MoteurQuiPlante)
    res = pipeline.executer_sweep(MODE, ["small", "medium", "large-v3"],
                                  audio_court, pipeline.SR, "fr", tmp_path)
    par_modele = {r["modele"]: r for r in res}
    assert "erreur" in par_modele["medium"]          # échec consigné
    assert par_modele["small"].get("rtf_moyen") is not None  # le run continue
    assert par_modele["large-v3"].get("rtf_moyen") is not None


def test_mesure_memoire_ne_plante_pas():
    with pipeline.MesureMemoire(intervalle=0.01) as mem:
        _ = [i * i for i in range(10000)]
    # ram_pic_mb renseigné si psutil dispo, sinon None — jamais d'exception.
    assert mem.ram_pic_mb is None or mem.ram_pic_mb > 0


class MoteurOpenVINOFaux:
    """Imite MoteurOpenVINO : texte dépendant de la taille (qualité simulée)."""

    TEXTES = {
        "small": "le chien dormait sur le tapis",       # 2 substitutions vs large-v3
        "medium": "le chat dort sur le tapis rouge",    # 1 insertion
        "large-v3": "le chat dort sur le tapis",        # référence
    }

    def __init__(self, device="GPU"):
        self.device = device
        self.taille = None

    def charger(self, taille):
        self.taille = taille

    def transcrire(self, audio, langue=None):
        txt = self.TEXTES.get(self.taille, "texte")
        return ResultatTranscription(txt, "fr", [Segment(0.0, 1.0, txt)])

    def liberer(self):
        pass


def test_appliquer_wer_relatif():
    resultats = [
        {"modele": "small", "_texte": "le chien dormait sur le tapis"},
        {"modele": "large-v3", "_texte": "le chat dort sur le tapis"},
        {"modele": "medium", "erreur": "OOM"},   # échec : inchangé
    ]
    pipeline._appliquer_wer_relatif(resultats)
    par = {r["modele"]: r for r in resultats}
    assert par["large-v3"]["wer"] == 0.0
    assert par["large-v3"]["wer_reference"] == "large-v3"
    assert par["small"]["wer"] > 0
    assert all("_texte" not in r for r in resultats)
    assert "wer" not in par["medium"]


def test_executer_comparatif_openvino(monkeypatch, tmp_path, audio_court):
    monkeypatch.setattr("benchmark.moteur_openvino.MoteurOpenVINO", MoteurOpenVINOFaux)
    res = pipeline.executer_comparatif_openvino(
        ["small", "medium", "large-v3"], audio_court, pipeline.SR, "fr", tmp_path)
    par = {r["modele"]: r for r in res}
    assert all(r["moteur"] == "openvino" for r in res)
    assert all(r.get("device") == "GPU" for r in res)
    assert par["large-v3"]["wer"] == 0.0
    assert par["small"]["wer"] > par["medium"]["wer"] > 0
    assert (tmp_path / "transcription_openvino_small.txt").exists()
    assert all("_texte" not in r for r in res)


def test_executer_comparatif_openvino_echec_isole(monkeypatch, tmp_path, audio_court):
    class OVQuiPlante(MoteurOpenVINOFaux):
        def charger(self, taille):
            if taille == "medium":
                raise RuntimeError("device GPU indisponible")
            super().charger(taille)

    monkeypatch.setattr("benchmark.moteur_openvino.MoteurOpenVINO", OVQuiPlante)
    res = pipeline.executer_comparatif_openvino(
        ["small", "medium", "large-v3"], audio_court, pipeline.SR, "fr", tmp_path)
    par = {r["modele"]: r for r in res}
    assert "erreur" in par["medium"]                          # échec consigné
    assert par["small"].get("rtf_moyen") is not None          # le run continue
    assert par["large-v3"].get("rtf_moyen") is not None


def test_executer_diarisation_comparatif(monkeypatch, tmp_path):
    segs = [(0.0, 1.0, "Locuteur 0"), (1.0, 2.0, "Locuteur 1")]
    monkeypatch.setattr(pipeline.diarisation, "diariser_sherpa", lambda audio: (segs, 0.5))

    def pyannote_ko(wav, token):
        raise RuntimeError("pas de token")

    monkeypatch.setattr(pipeline.diarisation, "diariser_pyannote", pyannote_ko)
    audio = np.zeros(2 * pipeline.SR, dtype=np.float32)
    res = pipeline.executer_diarisation(audio, pipeline.SR, tmp_path, token=None)
    par_moteur = {r["moteur"]: r for r in res}
    # sherpa réussit (RTF + locuteurs + artefact), pyannote échoue proprement.
    assert par_moteur["sherpa"]["n_locuteurs"] == 2
    assert (tmp_path / par_moteur["sherpa"]["artefact_md"]).exists()
    assert "erreur" in par_moteur["pyannote"]
    # Le WAV temporaire est nettoyé MÊME quand pyannote échoue (sinon il alourdit le zip).
    assert not (tmp_path / "_diar_pyannote.wav").exists()
