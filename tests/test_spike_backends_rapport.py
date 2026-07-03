"""Tests de fumée — rapport.py du spike backends Windows."""
from __future__ import annotations

import json
import zipfile

from spike.backends_windows import rapport

CLES_ATTENDUES = {
    "version_spike", "horodatage", "machine", "libs", "accelerateurs",
    "audio", "resultats", "verdict_machine", "synthese",
}


def _res(backend, modele, statut="ok", rtf_moyen=0.5, rtf_fin=0.5,
         hallucination=False, wer=0.0):
    r = {"backend": backend, "modele": modele, "statut": statut,
         "rtf_moyen": rtf_moyen, "rtf_fin": rtf_fin,
         "hallucination": hallucination, "wer": wer, "device_reel": "cpu"}
    return r


def test_construire_rapport_cles():
    r = rapport.construire_rapport(
        materiel={"hostname": "Bastien", "os": "windows", "gpu": {}},
        libs={"python": "3.11"}, accelerateurs={},
        audio={"fichier": "a.wav", "duree_s": 60.0, "langue": "fr"},
        resultats=[_res("faster-whisper", "small")],
    )
    assert set(r) == CLES_ATTENDUES


def test_verdict_meilleur_modele():
    resultats = [
        _res("faster-whisper", "small", rtf_moyen=0.3, rtf_fin=0.3),
        _res("faster-whisper", "large-v3", rtf_moyen=1.5, rtf_fin=1.6),
    ]
    v = rapport.calculer_verdict_machine(resultats)
    assert v["backend"] == "faster-whisper"
    assert v["modele"] == "small"
    assert v["niveau"] in ("viable", "limite")


def test_verdict_exclut_hallucination():
    resultats = [
        _res("faster-whisper", "large-v3", rtf_moyen=0.4, hallucination=True),
        _res("faster-whisper", "small", rtf_moyen=0.6, hallucination=False),
    ]
    v = rapport.calculer_verdict_machine(resultats)
    assert v["modele"] == "small"


def test_verdict_insuffisant():
    resultats = [
        _res("faster-whisper", "small", rtf_moyen=1.2, rtf_fin=1.3),
    ]
    v = rapport.calculer_verdict_machine(resultats)
    assert v["niveau"] == "insuffisant"
    assert v["backend"] is None


def test_synthese_backends_embarquer():
    resultats = [
        _res("faster-whisper", "small", rtf_moyen=0.6),
        _res("openvino", "large-v3", rtf_moyen=0.4),
    ]
    s = rapport.construire_synthese(resultats)
    assert "faster-whisper" in s["backends_a_embarquer"]
    assert "openvino" in s["backends_a_embarquer"]
    assert "regle_selection" in s


def test_rendre_markdown_ne_plante_pas():
    r = rapport.construire_rapport(
        materiel={"hostname": "Alix", "os": "windows", "os_version": "Windows 11",
                  "arch": "AMD64", "cpu": "Intel i5", "cpu_cores": {"logiques": 10},
                  "ram_gb": 16.0, "gpu": {"fabricant": "intel", "name": "Intel UHD"},
                  "alimentation": {"source": "secteur"}},
        libs={}, accelerateurs={"vulkan": {"disponible": True, "gpus": [{"nom": "Intel UHD", "fabricant": "intel"}]}},
        audio={"fichier": "a.wav", "duree_s": 60.0, "langue": "fr"},
        resultats=[
            _res("faster-whisper", "small"),
            {"backend": "openvino", "modele": "small", "statut": "erreur", "erreur": "GPU indispo"},
        ],
    )
    md = rapport.rendre_markdown(r)
    assert "Verdict" in md
    assert "faster-whisper" in md
    assert "ÉCHEC" in md or "erreur" in md


def test_ecrire_et_emballer(tmp_path):
    dossier = tmp_path / "resultats"
    r = rapport.construire_rapport(
        materiel={"hostname": "Bastien Test", "os": "windows", "gpu": {}},
        libs={}, accelerateurs={},
        audio={"fichier": "a.wav", "duree_s": 10.0, "langue": "fr"},
        resultats=[_res("faster-whisper", "small")],
    )
    rapport.ecrire(r, dossier)
    (dossier / "journal.log").write_text("trace", encoding="utf-8")
    (dossier / "transcription_faster-whisper_small.txt").write_text("texte", encoding="utf-8")
    (dossier / "_temp.wav").write_bytes(b"\x00" * 100)

    archive = rapport.emballer(dossier, r["machine"])
    assert archive.exists()
    assert "Bastien-Test" in archive.name
    with zipfile.ZipFile(archive) as zf:
        noms = zf.namelist()
    assert "rapport.json" in noms
    assert "rapport.md" in noms
    assert "journal.log" in noms
    assert "_temp.wav" not in noms
    with zipfile.ZipFile(archive) as zf:
        data = json.loads(zf.read("rapport.json"))
    assert data["machine"]["hostname"] == "Bastien Test"
