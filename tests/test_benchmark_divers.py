from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from benchmark import audio_io, chemins, diarisation, moteurs


# ── chemins ───────────────────────────────────────────────────────────────────

def test_chemins_surcharge_par_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCH_AUDIO", str(tmp_path / "a.wav"))
    monkeypatch.setenv("BENCH_MODELS", str(tmp_path / "m"))
    monkeypatch.setenv("BENCH_SORTIE", str(tmp_path / "out"))
    assert chemins.audio_canonique() == tmp_path / "a.wav"
    assert chemins.dossier_modeles() == tmp_path / "m"
    assert chemins.dossier_sortie() == tmp_path / "out"


# ── audio_io ──────────────────────────────────────────────────────────────────

def test_charger_wav_int16_mono(tmp_path):
    chemin = tmp_path / "m.wav"
    sig = (0.5 * np.sin(np.linspace(0, 100, 16000))).astype(np.float32)
    wavfile.write(chemin, 16000, (sig * 32767).astype(np.int16))
    audio, sr = audio_io.charger(chemin)
    assert sr == 16000
    assert audio.dtype == np.float32
    assert np.max(np.abs(audio)) <= 1.0  # normalisé


def test_charger_wav_stereo_reechantillonne(tmp_path):
    chemin = tmp_path / "s.wav"
    stereo = (np.random.rand(8000, 2) * 2 - 1).astype(np.float32)
    wavfile.write(chemin, 8000, (stereo * 32767).astype(np.int16))
    audio, sr = audio_io.charger(chemin)
    assert sr == 16000           # rééchantillonné de 8k → 16k
    assert audio.ndim == 1       # mixé en mono
    assert len(audio) == pytest.approx(16000, abs=50)


# ── diarisation (parties pures) ────────────────────────────────────────────────

def test_nb_locuteurs():
    segs = [(0, 1, "Locuteur 0"), (1, 2, "Locuteur 1"), (2, 3, "Locuteur 0")]
    assert diarisation.nb_locuteurs(segs) == 2
    assert diarisation.nb_locuteurs([]) == 0


def test_progress_sherpa_journalise_par_paliers():
    """Le callback de progression journalise par paliers de 10 % et renvoie 0 (continuer)."""
    class _Log:
        def __init__(self):
            self.messages = []
        def info(self, *a, **k):
            self.messages.append(a)
    log = _Log()
    cb = diarisation._progress_sherpa(log, pas=10.0)
    retours = [cb(t, 100) for t in (0, 5, 12, 50, 100)]
    assert retours == [0, 0, 0, 0, 0]          # 0 = continuer (jamais d'interruption)
    assert len(log.messages) == 4              # paliers 0, 12, 50, 100 (5 % sauté)


def test_ecrire_artefact(tmp_path):
    chemin = tmp_path / "diar.md"
    segs = [(0.0, 1.5, "Locuteur 0"), (1.5, 3.0, "Locuteur 1")]
    diarisation.ecrire_artefact(chemin, "Test", segs, dt=0.3, duree=3.0)
    contenu = chemin.read_text(encoding="utf-8")
    assert "Test" in contenu
    assert "Locuteurs détectés : 2" in contenu
    assert "Locuteur 0" in contenu


def test_token_hf_depuis_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test123")
    assert diarisation.token_hf() == "hf_test123"


# ── moteurs (sans backend) ──────────────────────────────────────────────────────

def test_moteur_liberer_sans_modele_ne_plante_pas():
    m = moteurs.MoteurBench({"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"})
    m.liberer()  # aucun modèle chargé → no-op, pas d'exception
    assert m._modele is None


def test_moteur_cpu_threads_par_defaut():
    m = moteurs.MoteurBench({"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"})
    assert m.cpu_threads >= 1


# ── materiel : parsing GPU (sans matériel, via _commande mocké) ─────────────────

def test_nvidia_smi_parse(monkeypatch):
    from benchmark import materiel
    monkeypatch.setattr(materiel, "_commande", lambda args: "NVIDIA GeForce RTX 4090, 24564\n")
    gpu = materiel._nvidia_smi()
    assert gpu["type"] == "nvidia"
    assert "RTX 4090" in gpu["name"]
    assert gpu["vram_mb"] == 24564


def test_nvidia_smi_absent(monkeypatch):
    from benchmark import materiel
    monkeypatch.setattr(materiel, "_commande", lambda args: None)
    assert materiel._nvidia_smi() is None


def test_gpu_systeme_linux(monkeypatch):
    from benchmark import materiel
    monkeypatch.setattr(materiel, "os_normalise", lambda: "linux")
    monkeypatch.setattr(materiel, "_commande",
                        lambda args: "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics\n")
    nom = materiel._gpu_systeme()
    assert nom and "Intel" in nom


# ── moteurs : transcription faster-whisper avec modèle injecté ──────────────────

def test_transcrire_faster_whisper_modele_injecte():
    class FauxSeg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class FauxInfo:
        language = "fr"

    class FauxModele:
        def transcribe(self, audio, language=None):
            return [FauxSeg(0.0, 1.0, " bonjour "), FauxSeg(1.0, 2.0, " le monde ")], FauxInfo()

    m = moteurs.MoteurBench({"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"})
    m._modele = FauxModele()
    res = m.transcrire(np.zeros(16000, dtype=np.float32), "fr")
    assert res.texte == "bonjour le monde"
    assert res.langue_detectee == "fr"
    assert len(res.segments) == 2
