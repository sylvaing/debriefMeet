"""Tests de fumée — correctifs modeles.py / assembler.py / moteur_directml.py.

Cf. docs/18-spike-backends-windows.md §13.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

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


def test_convertir_openvino_turbo_complete_le_tokenizer_lent(monkeypatch, tmp_path):
    """§1.4 doc 39 — après l'export optimum-cli, vocab.json/merges.txt doivent être
    ajoutés (tokenizer lent, exigé par use_fast=False dans moteur_openvino.py).

    Téléchargés directement depuis le repo source (hf_hub_download), pas via
    WhisperTokenizer.save_pretrained() : transformers >=5 ne réécrit plus ces
    fichiers pour la classe "lente" (vérifié transformers 5.0.0 en session)."""
    from spike.backends_windows import assembler

    appels: list[tuple[str, str]] = []

    def faux_hf_hub_download(repo_id, filename, local_dir):
        assert repo_id == assembler.OV_TURBO_MODEL_ID
        appels.append((repo_id, filename))
        Path(local_dir, filename).write_text("{}" if filename.endswith(".json") else "", encoding="utf-8")

    faux_hf = types.ModuleType("huggingface_hub")
    faux_hf.hf_hub_download = faux_hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", faux_hf)
    monkeypatch.setattr(assembler.subprocess, "run", lambda *a, **k: None)

    dest = tmp_path / "openvino-whisper-large-v3-turbo"
    assembler.convertir_openvino_turbo(dest)

    assert (dest / "vocab.json").is_file()
    assert (dest / "merges.txt").is_file()
    assert appels == [
        (assembler.OV_TURBO_MODEL_ID, "vocab.json"),
        (assembler.OV_TURBO_MODEL_ID, "merges.txt"),
    ]


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


# ── §2.2/2.6 doc 39 — filtre --backends générique ─────────────────────────────

def test_telecharger_modeles_backends_openvino_seulement(monkeypatch, tmp_path):
    """§2.2 — backends=["openvino"] ne doit préparer que les artefacts openvino."""
    from spike.backends_windows import assembler

    def faux_convertir_turbo(dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "openvino_model.xml").write_text("<xml/>", encoding="utf-8")

    monkeypatch.setattr(assembler, "convertir_openvino_turbo", faux_convertir_turbo)

    def snapshot_interdit(*a, **k):
        raise AssertionError("snapshot_download ne doit pas être appelé pour large-v3-turbo")

    faux_hf = types.ModuleType("huggingface_hub")
    faux_hf.snapshot_download = snapshot_interdit
    monkeypatch.setitem(sys.modules, "huggingface_hub", faux_hf)

    assembler.telecharger_modeles(tmp_path, ["large-v3-turbo"], backends=["openvino"])

    assert (tmp_path / "openvino-whisper-large-v3-turbo").is_dir()
    assert not (tmp_path / "faster-whisper-large-v3-turbo").exists()
    assert not (tmp_path / "directml-whisper-large-v3-turbo").exists()
    assert not (tmp_path / "ggml").exists()


def test_generer_lanceur_injecte_args_backends():
    """§2.2 — les args (--backends/--modeles) sont injectés avant %*, qui reste disponible."""
    from spike.backends_windows import assembler

    contenu = assembler.generer_lanceur("--backends openvino --modeles large-v3-turbo")
    assert "-m spike.backends_windows --backends openvino --modeles large-v3-turbo %*" in contenu


def test_generer_lanceur_sans_args_retrocompatible():
    from spike.backends_windows import assembler

    contenu = assembler.generer_lanceur()
    assert "-m spike.backends_windows %*" in contenu


def test_suffixe_et_args_lanceur_vides_par_defaut():
    """Rétrocompatibilité : backends=None + sweep complet → aucun suffixe/args (cf.
    scripts/build_spike_backends_vm.sh qui attend spike-backends-windows.zip)."""
    from spike.backends_windows import assembler, modeles as mdl

    assert assembler._suffixe_bundle(None, mdl.SWEEP) == ""
    assert assembler._args_lanceur(None, mdl.SWEEP) == ""


def test_assembler_backends_filtre_produit_bundle_reduit(monkeypatch, tmp_path):
    """§2.6 — --backends openvino --modeles large-v3-turbo : bundle sans faster-whisper,
    ggml, whisper-cli.exe ni directml, contenant le modèle openvino turbo complété."""
    import zipfile

    from spike.backends_windows import assembler

    # Ne jamais toucher au vrai cache prebuild (modèles réels, plusieurs Go, sur ce Mac).
    monkeypatch.setattr(assembler.chemins, "dossier_modeles", lambda: tmp_path / "cache_vide")
    monkeypatch.setattr(assembler, "telecharger_wheels",
                        lambda libs, natif=False: libs.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(assembler, "copier_sources", lambda libs: None)
    monkeypatch.setattr(assembler, "copier_audio", lambda libs: None)
    monkeypatch.setattr(assembler, "telecharger_python_embeddable",
                        lambda bundle, version=assembler.PY_EMBED_VERSION:
                            (bundle / "python").mkdir(parents=True, exist_ok=True))

    def faux_convertir_turbo(dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "openvino_model.xml").write_text("<xml/>", encoding="utf-8")

    monkeypatch.setattr(assembler, "convertir_openvino_turbo", faux_convertir_turbo)

    appels_whisper_cli = []
    monkeypatch.setattr(assembler, "copier_whisper_cli", lambda libs: appels_whisper_cli.append(libs))

    archive = assembler.assembler(tmp_path, tailles=["large-v3-turbo"], backends=["openvino"])

    assert archive.name == "spike-backends-windows-openvino-large-v3-turbo.zip"
    assert appels_whisper_cli == []

    with zipfile.ZipFile(archive) as zf:
        noms = zf.namelist()
        lanceur_nom = next(n for n in noms if n.endswith("lancer.bat"))
        contenu_lanceur = zf.read(lanceur_nom).decode("utf-8")

    assert any("openvino-whisper-large-v3-turbo" in n for n in noms)
    assert not any("faster-whisper" in n for n in noms)
    assert not any("ggml" in n for n in noms)
    assert not any("whisper-cli.exe" in n for n in noms)
    assert not any("directml-whisper" in n for n in noms)
    assert "--backends openvino --modeles large-v3-turbo" in contenu_lanceur
