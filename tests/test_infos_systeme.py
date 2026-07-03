from __future__ import annotations

import sys

from debrief_meet.platform.infos_systeme import collecter_infos_systeme


def test_ne_leve_jamais_et_rubriques_attendues_presentes():
    infos = collecter_infos_systeme()
    for cle in (
        "os", "machine", "processeur", "coeurs", "ram_go", "gpu", "python",
        "pyside6", "sounddevice", "numpy", "faster_whisper", "soundcard",
        "peripheriques_audio_entree", "peripheriques_audio_sortie",
    ):
        assert cle in infos


def test_sounddevice_qui_leve_devient_indisponible(monkeypatch):
    import sounddevice as sd

    def _leve(*a, **kw):
        raise RuntimeError("PortAudio cassé")

    monkeypatch.setattr(sd, "query_devices", _leve)
    infos = collecter_infos_systeme()
    assert "indisponible" in infos["peripheriques_audio_entree"]
    assert "indisponible" in infos["peripheriques_audio_sortie"]


def test_rubriques_ram_gpu_non_collectees_hors_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    infos = collecter_infos_systeme()
    assert infos["ram_go"] == "non collecté"
    assert infos["gpu"] == "non collecté"


def test_rubriques_windows_ne_levent_pas_meme_sans_windll(monkeypatch):
    """Sur Mac, ctypes.windll et powershell n'existent pas — la branche Windows doit
    quand même se replier proprement sur "indisponible (...)" sans lever."""
    monkeypatch.setattr(sys, "platform", "win32")
    infos = collecter_infos_systeme()
    assert "indisponible" in infos["ram_go"] or infos["ram_go"] != ""
    assert "indisponible" in infos["gpu"] or infos["gpu"] != ""


def test_version_lib_inconnue_indisponible():
    from debrief_meet.platform.infos_systeme import _version_lib
    assert "indisponible" in _version_lib("ce-paquet-n-existe-pas-du-tout")
