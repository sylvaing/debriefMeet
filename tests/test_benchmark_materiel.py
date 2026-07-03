from __future__ import annotations

import pytest

from benchmark import materiel


def test_os_normalise_valeur_connue():
    assert materiel.os_normalise() in {"macos", "windows", "linux"}


@pytest.mark.parametrize(
    "nom, attendu",
    [
        ("NVIDIA GeForce RTX 3080", "nvidia"),
        ("Tesla T4", "nvidia"),
        ("AMD Radeon RX 6800", "amd"),
        ("Intel(R) UHD Graphics 770", "intel"),
        ("Apple M2", "autre"),
        ("", "autre"),
    ],
)
def test_classer_gpu(nom, attendu):
    assert materiel.classer_gpu(nom) == attendu


def test_detecter_materiel_cles_presentes():
    m = materiel.detecter_materiel()
    for cle in (
        "hostname", "os", "os_version", "arch", "cpu", "cpu_cores",
        "cpu_freq_mhz", "ram_gb", "gpu", "alimentation",
    ):
        assert cle in m, f"clé manquante : {cle}"
    assert m["os"] in {"macos", "windows", "linux"}
    assert set(m["gpu"]) == {"type", "name", "vram_mb", "cuda"}
    assert set(m["alimentation"]) == {"source", "niveau_pct"}
    assert set(m["cpu_cores"]) == {"physiques", "logiques"}


def test_detecter_materiel_ne_leve_pas_sans_deps(monkeypatch):
    """Même si psutil/cpuinfo/torch sont absents, la détection ne plante pas."""
    import builtins

    vrai_import = builtins.__import__

    def import_ko(nom, *args, **kwargs):
        if nom.split(".")[0] in {"psutil", "cpuinfo", "torch"}:
            raise ImportError(f"simulé : {nom}")
        return vrai_import(nom, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_ko)
    m = materiel.detecter_materiel()
    assert m["os"] in {"macos", "windows", "linux"}
    # GPU dégradé proprement (pas de torch) : type renseigné, jamais d'exception.
    assert m["gpu"]["type"] in {"nvidia", "amd", "intel", "autre", "none", "metal"}


def test_versions_libs_contient_python():
    v = materiel.versions_libs()
    assert "python" in v and v["python"]
    # numpy est une dépendance du projet → présent
    assert "numpy" in v
