from __future__ import annotations

import pytest

from benchmark import modeles, moteurs


@pytest.mark.parametrize(
    "materiel, attendu",
    [
        ({"os": "macos", "arch": "arm64", "gpu": {"type": "metal", "cuda": None}},
         {"moteur": "mlx", "device": "metal"}),
        ({"os": "windows", "arch": "AMD64", "gpu": {"type": "nvidia", "cuda": "12.4"}},
         {"moteur": "faster-whisper", "device": "cuda"}),
        ({"os": "windows", "arch": "AMD64", "gpu": {"type": "intel", "cuda": None}},
         {"moteur": "faster-whisper", "device": "cpu"}),
        ({"os": "linux", "arch": "x86_64", "gpu": {"type": "none", "cuda": None}},
         {"moteur": "faster-whisper", "device": "cpu"}),
        # NVIDIA détecté mais sans version CUDA (driver/runtime KO) → repli CPU.
        ({"os": "linux", "arch": "x86_64", "gpu": {"type": "nvidia", "cuda": None}},
         {"moteur": "faster-whisper", "device": "cpu"}),
    ],
)
def test_choisir_mode(materiel, attendu):
    mode = moteurs.choisir_mode(materiel)
    assert mode["moteur"] == attendu["moteur"]
    assert mode["device"] == attendu["device"]
    assert mode["compute_type"] in {"float16", "int8"}


def test_resoudre_faster_whisper_repo_par_defaut():
    # Sans dossier local, on retombe sur le repo HF.
    assert modeles.resoudre_faster_whisper("small") == "Systran/faster-whisper-small"


def test_resoudre_faster_whisper_local_si_present(tmp_path, monkeypatch):
    (tmp_path / "faster-whisper-medium").mkdir()
    monkeypatch.setenv("BENCH_MODELS", str(tmp_path))
    assert modeles.resoudre_faster_whisper("medium") == str(tmp_path / "faster-whisper-medium")


def test_resoudre_faster_whisper_taille_inconnue():
    with pytest.raises(ValueError):
        modeles.resoudre_faster_whisper("gigantesque")


def test_transcrire_sans_charger_leve():
    m = moteurs.MoteurBench({"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"})
    import numpy as np

    with pytest.raises(RuntimeError):
        m.transcrire(np.zeros(16000, dtype=np.float32))
