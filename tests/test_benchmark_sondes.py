from __future__ import annotations

import subprocess

import numpy as np

from benchmark import sondes_accel, sondes_capture, vulkan_probe


# ── Sondes accélérateurs ──────────────────────────────────────────────────────

def test_sonder_tout_structure():
    res = sondes_accel.sonder_tout()
    for cle in ("cuda", "intel_openvino", "intel_directml", "amd_rocm", "vulkan"):
        assert cle in res
        assert "disponible" in res[cle]
        assert isinstance(res[cle]["disponible"], bool)


def test_sonde_intel_openvino_absente_degrade():
    # OpenVINO n'est pas installé ici → disponible False, jamais d'exception.
    r = sondes_accel.sonde_intel_openvino()
    assert r["disponible"] is False


# ── Sonde Vulkan (loader via sous-processus isolé) ─────────────────────────────

def _faux_proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_vulkan_loader_gpu_detecte(monkeypatch):
    gpus = [{"nom": "Intel Iris Xe", "type": "integrated", "fabricant": "intel",
             "api_version": "1.3.0"}]
    monkeypatch.setattr(sondes_accel.subprocess, "run",
                        lambda *a, **k: _faux_proc(0, __import__("json").dumps(gpus)))
    r = sondes_accel.sonde_vulkan()
    assert r["disponible"] is True
    assert r["methode"] == "loader"
    assert r["gpus"][0]["fabricant"] == "intel"


def test_vulkan_enfant_crashe_ne_propage_pas(monkeypatch):
    # L'enfant segfault (code négatif) → pas de stdout exploitable → repli puis False.
    appels = {"n": 0}

    def run(cmd, *a, **k):
        appels["n"] += 1
        if "vulkan_probe" in " ".join(map(str, cmd)):
            return _faux_proc(-11, "")          # SIGSEGV simulé, stdout vide
        raise FileNotFoundError("vulkaninfo absent")  # repli CLI indisponible

    monkeypatch.setattr(sondes_accel.subprocess, "run", run)
    r = sondes_accel.sonde_vulkan()
    assert r["disponible"] is False             # aucune exception propagée
    assert r["methode"] is None
    assert appels["n"] >= 1


def test_vulkan_timeout_ne_propage_pas(monkeypatch):
    def run(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd, 20)
    monkeypatch.setattr(sondes_accel.subprocess, "run", run)
    r = sondes_accel.sonde_vulkan()
    assert r["disponible"] is False             # timeout absorbé, run continue


def test_vulkan_repli_vulkaninfo(monkeypatch):
    # Loader KO (stdout vide) mais vulkaninfo présent → repli CLI.
    def run(cmd, *a, **k):
        joint = " ".join(map(str, cmd))
        if "vulkan_probe" in joint:
            return _faux_proc(1, "")            # loader échoue
        return _faux_proc(0, "GPU0:\n\tdeviceName = AMD Radeon RX 6700 XT\n")
    monkeypatch.setattr(sondes_accel.subprocess, "run", run)
    r = sondes_accel.sonde_vulkan()
    assert r["methode"] == "vulkaninfo"
    assert r["disponible"] is True
    assert "AMD Radeon RX 6700 XT" in r["gpus"][0]["nom"]


def test_vulkan_probe_mappings():
    # vendorID → fabricant, deviceType → libellé.
    assert vulkan_probe.FABRICANTS[0x8086] == "intel"
    assert vulkan_probe.FABRICANTS[0x1002] == "amd"
    assert vulkan_probe.FABRICANTS[0x10DE] == "nvidia"
    assert vulkan_probe.TYPES[2] == "discrete"
    assert vulkan_probe.TYPES[1] == "integrated"


def test_vulkan_probe_version_format():
    # encodage Vulkan : (major<<22)|(minor<<12)|patch
    assert vulkan_probe._version((1 << 22) | (3 << 12) | 275) == "1.3.275"


# ── Sondes capture ────────────────────────────────────────────────────────────

def test_scenario_auto_skip_ne_plante_pas():
    res = sondes_capture.scenario(auto_skip=True)
    assert res["youtube"]["realise"] is False
    assert res["lecture_voix"]["realise"] is False
    assert "bluetooth" not in res  # étape Bluetooth retirée (trop d'interactions)
    assert isinstance(res["peripheriques"], list)
    assert "disponible" in res["aec_livekit"]


def test_scenario_dit_arreter_youtube(monkeypatch):
    # Mode interactif (mocké) : un message doit inviter à arrêter YouTube après la capture.
    monkeypatch.setattr(sondes_capture, "demander", lambda *a, **k: "n")  # on saute chaque étape
    monkeypatch.setattr(sondes_capture, "lister_peripheriques", lambda: [])
    monkeypatch.setattr(sondes_capture, "sonde_livekit", lambda: {"disponible": False})

    messages: list[str] = []

    class FauxLog:
        def info(self, msg, *a):
            messages.append(msg % a if a else msg)

        def debug(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

    monkeypatch.setattr(sondes_capture, "journal", lambda: FauxLog())
    sondes_capture.scenario(auto_skip=False, duree=0.1)
    joint = " ".join(messages)
    assert "ARRÊTER" in joint and "YouTube" in joint


def test_etape_youtube_son_capte(monkeypatch):
    monkeypatch.setattr(sondes_capture, "demander", lambda *a, **k: "")  # on procède

    def faux_systeme(duree):
        sr = 48_000
        t = np.linspace(0, duree, int(duree * sr), endpoint=False)
        return {"audio": (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32),
                "sr": sr, "canaux": 2, "methode": "test", "dtype": "float32"}

    monkeypatch.setattr(sondes_capture, "_enregistrer_systeme", faux_systeme)
    res = sondes_capture.etape_youtube(auto_skip=False, duree=0.2)
    assert res["realise"] is True
    assert res["son_capte"] is True
    assert res["format_capte"]["sample_rate"] == 48_000


def test_etape_youtube_echec_capture_capturee(monkeypatch):
    monkeypatch.setattr(sondes_capture, "demander", lambda *a, **k: "")

    def systeme_ko(duree):
        raise RuntimeError("loopback indisponible")

    monkeypatch.setattr(sondes_capture, "_enregistrer_systeme", systeme_ko)
    res = sondes_capture.etape_youtube(auto_skip=False, duree=0.2)
    assert res["realise"] is True
    assert "erreur" in res  # l'échec est consigné, pas propagé


def _faux_capture(sr):
    def fn(duree):
        t = np.linspace(0, duree, int(duree * sr), endpoint=False)
        return {"audio": (0.2 * np.sin(2 * np.pi * 300 * t)).astype(np.float32),
                "sr": sr, "canaux": 1, "methode": "test", "dtype": "float32"}
    return fn


def test_etape_lecture_voix_aec_et_wer(monkeypatch):
    monkeypatch.setattr(sondes_capture, "demander", lambda *a, **k: "")
    monkeypatch.setattr(sondes_capture, "_enregistrer_micro", _faux_capture(44_100))
    monkeypatch.setattr(sondes_capture, "_enregistrer_systeme", _faux_capture(48_000))

    res = sondes_capture.etape_lecture_voix(
        auto_skip=False, duree=1.5, transcrire_fn=lambda audio16k: "transcription simulée")
    assert res["realise"] is True
    # AEC exécutée (atténuation présente) et WER calculé avant/après.
    assert "attenuation_echo_db" in res
    assert "wer_avant_aec" in res


# ── Capture loopback Windows via soundcard ─────────────────────────────────────
#
# sounddevice/PortAudio ne sait pas faire le loopback WASAPI → on passe par soundcard.
# On mocke le module `soundcard` (injecté dans sys.modules) car la lib n'est pas
# installée sur le poste de dev (macOS/Linux) et ouvre du matériel réel.

def _faux_soundcard(audio, nom_hp="Haut-parleurs", hp=object()):
    """Faux module `soundcard` : un HP par défaut + un micro loopback qui rend `audio`."""
    import sys
    import types

    class FauxMic:
        def __init__(self, nom):
            self.nom = nom

        def record(self, samplerate, numframes):
            return audio

    mod = types.ModuleType("soundcard")
    mod.default_speaker = lambda: (types.SimpleNamespace(name=nom_hp) if hp is not None else None)
    mod.get_microphone = lambda nom, include_loopback=False: (
        FauxMic(nom) if include_loopback else None)
    return mod, sys


def test_capturer_loopback_windows_ok(monkeypatch):
    sr = 48_000
    t = np.linspace(0, 0.2, int(0.2 * sr), endpoint=False)
    stereo = np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    mod, sys = _faux_soundcard(stereo)
    monkeypatch.setitem(sys.modules, "soundcard", mod)

    cap = sondes_capture._capturer_loopback_windows(0.2, sr=sr)
    assert cap["methode"] == "wasapi-loopback(soundcard)"
    assert cap["sr"] == sr and cap["canaux"] == 2
    assert cap["audio"].ndim == 1            # downmixé en mono
    assert sondes_capture._rms(cap["audio"]) > sondes_capture.SEUIL_SON


def test_capturer_loopback_windows_sans_hp(monkeypatch):
    # Pas de haut-parleur par défaut → RuntimeError explicite (consigné par l'étape).
    mod, sys = _faux_soundcard(np.zeros((10, 2), np.float32), hp=None)
    monkeypatch.setitem(sys.modules, "soundcard", mod)
    import pytest

    with pytest.raises(RuntimeError, match="haut-parleur"):
        sondes_capture._capturer_loopback_windows(0.1)


def test_etape_youtube_windows_loopback_via_soundcard(monkeypatch):
    # Bout-à-bout : sur Windows, etape_youtube passe par soundcard et capte le son.
    sr = 48_000
    t = np.linspace(0, 0.2, int(0.2 * sr), endpoint=False)
    stereo = np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    mod, sys = _faux_soundcard(stereo)
    monkeypatch.setitem(sys.modules, "soundcard", mod)
    monkeypatch.setattr(sondes_capture.materiel, "os_normalise", lambda: "windows")
    monkeypatch.setattr(sondes_capture, "demander", lambda *a, **k: "")

    res = sondes_capture.etape_youtube(auto_skip=False, duree=0.2)
    assert res["realise"] is True
    assert res["son_capte"] is True
    assert res["methode"] == "wasapi-loopback(soundcard)"


def test_lister_peripheriques_sans_sounddevice(monkeypatch):
    import builtins

    vrai_import = builtins.__import__

    def import_ko(nom, *a, **k):
        if nom.split(".")[0] == "sounddevice":
            raise ImportError("simulé")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", import_ko)
    assert sondes_capture.lister_peripheriques() == []


# ── Capture Linux via pactl + parec (fonctions pures) ──────────────────────────

def test_monitor_depuis_pactl_prefere_sink_defaut():
    default_sink = "alsa_output.pci-0000_00_1f.3.analog-stereo\n"
    sources = (
        "0\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tmodule\ts16le\tIDLE\n"
        "1\talsa_input.pci-0000_00_1f.3.analog-stereo\tmodule\ts16le\tSUSPENDED\n"
        "2\talsa_output.usb-Dock.analog-stereo.monitor\tmodule\ts16le\tRUNNING\n"
    )
    mon = sondes_capture._monitor_depuis_pactl(default_sink, sources)
    assert mon == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"


def test_monitor_depuis_pactl_repli_premier_monitor():
    # default sink sans monitor listé → on prend le 1er .monitor disponible
    mon = sondes_capture._monitor_depuis_pactl(
        "sink_absent",
        "7\talsa_output.hdmi.monitor\tm\ts16le\tIDLE\n8\talsa_input.mic\tm\ts16le\tIDLE\n")
    assert mon == "alsa_output.hdmi.monitor"


def test_monitor_depuis_pactl_aucune():
    assert sondes_capture._monitor_depuis_pactl("", "1\talsa_input.mic\tm\ts16le\tIDLE\n") is None
    assert sondes_capture._monitor_depuis_pactl("", "") is None


def test_cmd_parec_construit_les_args():
    cmd = sondes_capture._cmd_parec("alsa_output.x.monitor", 48000, 2)
    assert cmd[0] == "parec"
    assert "--device=alsa_output.x.monitor" in cmd
    assert "--format=float32le" in cmd
    assert "--rate=48000" in cmd and "--channels=2" in cmd


def test_decoder_pcm_f32_stereo_et_mono():
    src = np.array([0.1, -0.2, 0.3, -0.4], dtype="<f4")
    stereo = sondes_capture._decoder_pcm_f32(src.tobytes(), 2)
    assert stereo.shape == (2, 2) and stereo.dtype == np.float32
    mono = sondes_capture._decoder_pcm_f32(src.tobytes(), 1)
    assert mono.shape == (4,)
    # octets tronqués (pas un multiple de canaux) → on rogne proprement
    tronque = sondes_capture._decoder_pcm_f32(src[:3].tobytes(), 2)
    assert tronque.shape == (1, 2)


def test_capturer_via_parec_absent_renvoie_none(monkeypatch):
    # parec/pactl absents → None (déclenche le repli sounddevice), jamais d'exception
    monkeypatch.setattr("shutil.which", lambda _c: None)
    assert sondes_capture._capturer_via_parec(1.0) is None
