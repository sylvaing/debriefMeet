"""Tests de fumée — materiel.py du spike backends Windows."""
from __future__ import annotations

from spike.backends_windows import materiel


def test_detecter_materiel_ne_plante_pas():
    m = materiel.detecter_materiel()
    cles_attendues = {"hostname", "os", "os_version", "arch", "cpu",
                      "cpu_cores", "cpu_freq_mhz", "ram_gb", "gpu", "alimentation"}
    assert cles_attendues <= set(m)


def test_detecter_materiel_gpu_a_fabricant():
    m = materiel.detecter_materiel()
    assert "fabricant" in m["gpu"]


def test_detecter_materiel_os_normalise():
    m = materiel.detecter_materiel()
    assert m["os"] in ("macos", "windows", "linux")


def test_versions_libs_ne_plante_pas():
    libs = materiel.versions_libs()
    assert "python" in libs
    assert libs["python"] is not None


def test_classer_gpu():
    assert materiel.classer_gpu("AMD Radeon RX 6600") == "amd"
    assert materiel.classer_gpu("Intel UHD Graphics 770") == "intel"
    assert materiel.classer_gpu("NVIDIA RTX 4090") == "nvidia"
    assert materiel.classer_gpu("Unknown GPU XYZ") == "autre"
    assert materiel.classer_gpu("") == "autre"
