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


def test_sounddevice_qui_leve_devient_indisponible(monkeypatch, sounddevice_dispo):
    sd = sounddevice_dispo

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


def test_version_lib_replie_sur_le_version_du_module():
    """En app figée, PyInstaller n'embarque pas tous les `dist-info` : le diagnostic du
    terrain 2026-08-26 disait « indisponible » pour PySide6 ET sounddevice — les deux
    versions qu'on veut quand on débogue un plantage Qt ou une capture audio."""
    from debrief_meet.platform.infos_systeme import _version_lib
    assert _version_lib("nom-de-distribution-absent", module="PySide6")[0].isdigit()


def test_version_lib_sans_metadata_ni_module_reste_indisponible():
    from debrief_meet.platform.infos_systeme import _version_lib
    assert "indisponible" in _version_lib("absent", module="module_qui_n_existe_pas_xyz")


def test_pyside6_et_sounddevice_jamais_indisponibles_quand_importables(sounddevice_dispo):
    """Les deux rubriques que le terrain a perdues, sur l'appel réel (pas `_version_lib`
    en isolation) — c'est le dictionnaire final qui doit porter un numéro."""
    rubriques = collecter_infos_systeme()
    assert rubriques["pyside6"][0].isdigit()
    assert rubriques["sounddevice"][0].isdigit()


# ── Rubriques Linux (docs/49 §5.5) ───────────────────────────────────────────

def test_rubriques_linux_absentes_hors_linux(monkeypatch):
    """Ne pas allonger l'en-tête de session des autres OS avec des « non collecté »."""
    monkeypatch.setattr(sys, "platform", "darwin")
    infos = collecter_infos_systeme()
    for cle in ("distribution", "session", "serveur_audio"):
        assert cle not in infos


def test_rubriques_linux_presentes_et_sans_levee(monkeypatch):
    """Sur Mac, /proc/meminfo, /etc/os-release et pactl n'existent pas — les branches
    Linux doivent se replier sur "indisponible (...)" sans jamais faire échouer tout
    l'en-tête de session."""
    monkeypatch.setattr(sys, "platform", "linux")
    infos = collecter_infos_systeme()
    for cle in ("distribution", "session", "serveur_audio", "ram_go"):
        assert cle in infos
        assert isinstance(infos[cle], str) and infos[cle]


def test_ram_linux_lit_memtotal(monkeypatch, tmp_path):
    from debrief_meet.platform import infos_systeme

    faux = tmp_path / "meminfo"
    faux.write_text("MemTotal:       16316420 kB\nMemFree:  2000 kB\n", encoding="utf-8")
    ouvrir_reel = open
    monkeypatch.setattr("builtins.open",
                        lambda f, *a, **kw: ouvrir_reel(faux if f == "/proc/meminfo" else f,
                                                        *a, **kw))
    assert infos_systeme._ram_go_linux() == "15.6"


def test_session_linux_expose_wayland_ou_x11(monkeypatch):
    """Wayland vs X11 conditionne tray et raccourcis globaux (docs/49 L2) : l'info
    doit être dans tout diagnostic, pas à déduire."""
    from debrief_meet.platform import infos_systeme

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    assert infos_systeme._session_linux() == "wayland (ubuntu:GNOME)"


def test_session_linux_variables_absentes(monkeypatch):
    from debrief_meet.platform import infos_systeme

    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    assert infos_systeme._session_linux() == "inconnu (inconnu)"


def test_serveur_audio_sans_pactl(monkeypatch):
    from debrief_meet.platform import infos_systeme

    def _absent(*a, **kw):
        raise FileNotFoundError("pactl")

    monkeypatch.setattr("subprocess.run", _absent)
    assert "pactl absent" in infos_systeme._serveur_audio_linux()
