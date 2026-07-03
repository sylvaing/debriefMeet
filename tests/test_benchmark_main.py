from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.io import wavfile

from benchmark import __main__ as cli
from benchmark import pipeline


@pytest.fixture
def audio_wav(tmp_path):
    chemin = tmp_path / "test.wav"
    wavfile.write(chemin, 16_000, np.zeros(16_000, dtype=np.int16))  # 1 s de silence
    return chemin


def test_main_orchestration_produit_zip(monkeypatch, tmp_path, audio_wav):
    # On neutralise les étapes lourdes : on teste le câblage, pas les modèles.
    monkeypatch.setattr(pipeline, "executer_sweep",
                        lambda *a, **k: [{"modele": "small", "rtf_moyen": 0.3,
                                          "rtf_fin": 0.3, "wer": 0.0}])

    sortie = tmp_path / "out"
    code = cli.main([
        "--audio", str(audio_wav), "--sortie", str(sortie),
        "--auto-skip", "--sans-diarisation", "--sans-accel",
    ])
    assert code == 0
    assert (sortie / "rapport.json").exists()
    assert (sortie / "rapport.md").exists()
    assert (sortie / "journal.log").exists()

    rapport = json.loads((sortie / "rapport.json").read_text(encoding="utf-8"))
    assert rapport["verdict"]["modele_max_viable"] == "small"
    assert rapport["audio"]["fichier"] == "test.wav"

    # Un unique zip a été produit à côté du dossier de sortie.
    zips = list(tmp_path.glob("bench_*.zip"))
    assert len(zips) == 1
