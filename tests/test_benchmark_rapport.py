from __future__ import annotations

import json
import zipfile

from benchmark import rapport

CLES_ATTENDUES = {
    "schema_version", "horodatage", "machine", "mode", "audio",
    "transcription", "diarisation", "openvino", "capture", "accelerateurs",
    "verdict", "observations",
}


def _transc(modele, moyen, fin=None, wer=0.0):
    return {"modele": modele, "rtf_moyen": moyen, "rtf_fin": fin, "wer": wer}


def test_verdict_large_v3_viable():
    v = rapport.calculer_verdict([
        _transc("small", 0.2), _transc("medium", 0.4), _transc("large-v3", 0.45),
    ])
    assert v["modele_max_viable"] == "large-v3"
    assert v["niveau"] == "viable"


def test_verdict_limite_medium():
    v = rapport.calculer_verdict([
        _transc("small", 0.3), _transc("medium", 0.8), _transc("large-v3", 1.4),
    ])
    assert v["modele_max_viable"] == "medium"
    assert v["niveau"] == "limite"


def test_verdict_insuffisant():
    v = rapport.calculer_verdict([
        _transc("small", 1.1), _transc("medium", 2.0), _transc("large-v3", 3.5),
    ])
    assert v["modele_max_viable"] is None
    assert v["niveau"] == "insuffisant"


def test_verdict_utilise_rtf_soutenu_pire():
    # RTF moyen OK mais fin > 1.0 (throttling) → large-v3 NON viable.
    v = rapport.calculer_verdict([
        _transc("small", 0.3, 0.35), _transc("medium", 0.6, 0.7),
        _transc("large-v3", 0.9, 1.3),
    ])
    assert v["modele_max_viable"] == "medium"


def test_verdict_ignore_modeles_en_echec():
    v = rapport.calculer_verdict([
        {"modele": "small", "erreur": "OOM"}, _transc("medium", 0.5),
    ])
    assert v["modele_max_viable"] == "medium"


def test_construire_rapport_cles():
    r = rapport.construire_rapport(
        materiel={"hostname": "pc", "os": "windows", "gpu": {}},
        mode={"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"},
        audio={"fichier": "a.wav", "duree_s": 1800},
        transcription=[_transc("small", 0.3)],
        diarisation=[{"moteur": "sherpa", "rtf": 0.2, "n_locuteurs": 2}],
        capture={"youtube": {"realise": False}},
        accelerateurs={"cuda": {"disponible": False}},
        observations="rien à signaler",
    )
    assert set(r) == CLES_ATTENDUES
    assert r["verdict"]["modele_max_viable"] == "small"


def test_rendre_markdown_ne_plante_pas():
    r = rapport.construire_rapport(
        materiel={"hostname": "pc", "os": "linux", "gpu": {"type": "none"},
                  "cpu_cores": {"logiques": 4}, "alimentation": {"source": "secteur"}},
        mode={"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"},
        audio={"fichier": "a.wav", "duree_s": 1800},
        transcription=[_transc("small", 0.3, 0.3, 0.1), {"modele": "medium", "erreur": "OOM"}],
        diarisation=[{"moteur": "sherpa", "rtf": 0.2, "n_locuteurs": 2},
                     {"moteur": "pyannote", "erreur": "pas de token"}],
        capture={"youtube": {"realise": True, "son_capte": True},
                 "lecture_voix": {"realise": True, "wer_avant_aec": 0.2, "wer_apres_aec": 0.15,
                                  "attenuation_echo_db": -30.0},
                 "aec_livekit": {"disponible": True, "version": "1.1", "plateforme_wheel": "linux"}},
        accelerateurs={"cuda": {"disponible": False}, "vulkan": {"disponible": True}},
    )
    md = rapport.rendre_markdown(r)
    assert "Verdict" in md and "Transcription" in md and "small" in md


def test_openvino_defaut_liste_vide():
    # Sans GPU Intel, l'argument openvino est omis → liste vide, pas absente.
    r = rapport.construire_rapport(
        materiel={"hostname": "pc", "os": "windows", "gpu": {}},
        mode={"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"},
        audio={"fichier": "a.wav", "duree_s": 1800},
        transcription=[_transc("small", 0.3)],
        diarisation=[], capture={}, accelerateurs={},
    )
    assert r["openvino"] == []


def test_rendre_markdown_table_openvino():
    r = rapport.construire_rapport(
        materiel={"hostname": "pc", "os": "windows", "gpu": {"type": "intel"},
                  "cpu_cores": {"logiques": 8}, "alimentation": {"source": "secteur"}},
        mode={"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"},
        audio={"fichier": "a.wav", "duree_s": 1800},
        transcription=[_transc("large-v3", 1.2, 1.3, 0.0)],   # CPU lent
        diarisation=[],
        openvino=[{"moteur": "openvino", "modele": "large-v3", "device": "GPU",
                   "rtf_moyen": 0.4, "rtf_fin": 0.42, "wer": 0.0,
                   "ram_pic_mb": 900, "vram_pic_mb": None},
                  {"moteur": "openvino", "modele": "medium", "erreur": "device GPU indispo"}],
        capture={}, accelerateurs={},
    )
    md = rapport.rendre_markdown(r)
    assert "Transcription OpenVINO (GPU Intel)" in md
    assert "ÉCHEC : device GPU indispo" in md
    # ligne comparative RTF OpenVINO-GPU vs CPU
    assert "OpenVINO-GPU 0.4 vs CPU 1.2" in md


def test_ecrire_et_emballer(tmp_path):
    dossier = tmp_path / "resultats"
    r = rapport.construire_rapport(
        materiel={"hostname": "PC Test", "os": "windows", "gpu": {}},
        mode={"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"},
        audio={"fichier": "a.wav", "duree_s": 10},
        transcription=[_transc("small", 0.3)],
        diarisation=[], capture={}, accelerateurs={},
    )
    rapport.ecrire(r, dossier)
    (dossier / "journal.log").write_text("trace", encoding="utf-8")
    (dossier / "transcription_small.txt").write_text("texte", encoding="utf-8")

    (dossier / "_diar_pyannote.wav").write_bytes(b"\x00" * 1000)  # temp non nettoyé

    archive = rapport.emballer(dossier, r["machine"])
    assert archive.exists()
    assert archive.name.startswith("bench_PC-Test_windows_")
    with zipfile.ZipFile(archive) as zf:
        noms = zf.namelist()
    assert "rapport.json" in noms
    assert "rapport.md" in noms
    assert "journal.log" in noms
    assert "transcription_small.txt" in noms
    # Filet de sécurité : les fichiers temporaires `_*` ne sont jamais emballés.
    assert "_diar_pyannote.wav" not in noms
    # le rapport.json embarqué est valide
    with zipfile.ZipFile(archive) as zf:
        data = json.loads(zf.read("rapport.json"))
    assert data["machine"]["hostname"] == "PC Test"
