"""Tests de fumée — correctifs modeles.py / assembler.py / moteur_directml.py.

Cf. docs/18-spike-backends-windows.md §13.
"""
from __future__ import annotations

import sys
import types

from spike.backends_windows import modeles


def test_ggml_small_resout_q5_1():
    """§13.1 — ggml-small-q5_0.bin n'existe pas (404), q5_1 est la bonne variante."""
    assert modeles.TABLE_VULKAN_GGML["small"] == "ggml-small-q5_1.bin"


def test_assembler_ggml_small_coherent_avec_modeles():
    from spike.backends_windows import assembler
    assert assembler.GGML_FICHIERS["small"] == modeles.TABLE_VULKAN_GGML["small"]


def test_directml_allow_patterns_filtrent_fp16_seulement():
    """§13.2 — ne récupérer que les .onnx fp16 + fichiers hors onnx/."""
    assert modeles.DIRECTML_ALLOW_PATTERNS == ["onnx/*_fp16.onnx", "*.json", "*.txt"]


def test_moteur_directml_charge_la_variante_fp16(monkeypatch, tmp_path):
    """§13.2 — charger() doit passer les noms de fichiers fp16 explicites."""
    appels: dict = {}

    class FauxModele:
        pass

    class FauxORTModel:
        @staticmethod
        def from_pretrained(chemin, **kwargs):
            appels["chemin"] = chemin
            appels["kwargs"] = kwargs
            return FauxModele()

    class FauxProcessor:
        @staticmethod
        def from_pretrained(chemin):
            return object()

    faux_optimum = types.ModuleType("optimum")
    faux_optimum_onnxruntime = types.ModuleType("optimum.onnxruntime")
    faux_optimum_onnxruntime.ORTModelForSpeechSeq2Seq = FauxORTModel
    faux_transformers = types.ModuleType("transformers")
    faux_transformers.AutoProcessor = FauxProcessor

    monkeypatch.setitem(sys.modules, "optimum", faux_optimum)
    monkeypatch.setitem(sys.modules, "optimum.onnxruntime", faux_optimum_onnxruntime)
    monkeypatch.setitem(sys.modules, "transformers", faux_transformers)

    dest = tmp_path / "directml-whisper-small"
    (dest / "onnx").mkdir(parents=True)
    monkeypatch.setenv("SPIKE_MODELS", str(tmp_path))

    from spike.backends_windows.moteur_directml import MoteurDirectML
    moteur = MoteurDirectML()
    moteur.charger("small")

    assert appels["kwargs"]["encoder_file_name"] == "encoder_model_fp16.onnx"
    assert appels["kwargs"]["decoder_file_name"] == "decoder_model_fp16.onnx"
    assert appels["kwargs"]["decoder_with_past_file_name"] == "decoder_with_past_model_fp16.onnx"
    assert appels["kwargs"]["subfolder"] == "onnx"


def test_modeles_prets_detecte_manquants(tmp_path):
    from spike.backends_windows import assembler
    manquants = assembler.modeles_prets(tmp_path, ["small"])
    assert "faster-whisper-small" in manquants
    assert "openvino-whisper-small" in manquants
    assert "directml-whisper-small" in manquants
    assert "ggml/ggml-small-q5_1.bin" in manquants


def test_modeles_prets_turbo_attend_conversion_openvino(tmp_path):
    from spike.backends_windows import assembler
    manquants = assembler.modeles_prets(tmp_path, ["large-v3-turbo"])
    assert "openvino-whisper-large-v3-turbo" in manquants


def test_whisper_cli_manquants_detecte_absence(tmp_path):
    """§13.6 — aucun fichier présent : tout doit être signalé manquant."""
    from spike.backends_windows import assembler
    manquants = assembler.whisper_cli_manquants(tmp_path)
    assert set(manquants) == set(assembler.WHISPER_CLI_FICHIERS)


def test_whisper_cli_manquants_vide_si_complet(tmp_path):
    from spike.backends_windows import assembler
    for nom in assembler.WHISPER_CLI_FICHIERS:
        (tmp_path / nom).write_bytes(b"")
    assert assembler.whisper_cli_manquants(tmp_path) == []


def test_telecharger_whisper_cli_rejette_mauvaise_empreinte(monkeypatch, tmp_path):
    """§13.6 — un zip altéré (empreinte SHA256 différente) doit être rejeté, pas installé silencieusement."""
    import io
    import urllib.request
    import zipfile

    from spike.backends_windows import assembler

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nom in assembler.WHISPER_CLI_FICHIERS:
            zf.writestr(nom, b"contenu factice")
    data = buf.getvalue()

    class FauxReponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return data

    monkeypatch.setattr(urllib.request, "urlopen", lambda url: FauxReponse())

    try:
        assembler.telecharger_whisper_cli(tmp_path)
        raise AssertionError("devrait avoir levé ValueError sur empreinte incorrecte")
    except ValueError as exc:
        assert "empreinte" in str(exc)
    assert assembler.whisper_cli_manquants(tmp_path) == assembler.WHISPER_CLI_FICHIERS
