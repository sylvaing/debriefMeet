"""Tests sans matériel de l'adaptateur de capture système Linux (docs/49 §5.1).

`sounddevice` et `pactl` sont entièrement bouchonnés : ces tests tournent sur le Mac
comme sur le conteneur LXC headless, où `import sounddevice` lève (cf. la fixture
`sounddevice_dispo` du conftest — ici on n'importe jamais le vrai module).

Les cas couverts sont ceux **mesurés** par le spike sur le poste cible, pas des cas
imaginés : bascule de sortie (le flux livre des zéros sans rien signaler) et
disparition du sink (le flux gèle, `active` reste True, aucune exception).
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
import pytest

from debrief_meet.platform.linux import capture_systeme_monitor as mod
from debrief_meet.platform.linux.capture_systeme_monitor import (
    CaptureAudioSystemeMonitor,
    TAUX,
    index_moniteur,
    sink_par_defaut,
)

SINK_A = "alsa_output.pci-0000_00_1f.3.HiFi__HDMI1__sink"
SINK_B = "bluez_output.A0:0C:E2:8B:A6:29"


# ── Doubles ──────────────────────────────────────────────────────────────────────

class _FauxFlux:
    """Flux PortAudio bouchonné : un thread pousse des blocs dans le rappel.

    `active` reste **True** même après un gel, exactement comme le vrai (docs/49 Q6) —
    c'est ce qui interdit de s'en servir comme indicateur de santé."""

    def __init__(self, rappel, blocs_par_seconde=200):
        self._rappel = rappel
        self._periode = 1.0 / blocs_par_seconde
        self._arret = threading.Event()
        self._thread: threading.Thread | None = None
        self.active = False
        self.gele = False
        self.ferme = False

    def start(self):
        self.active = True
        self._thread = threading.Thread(target=self._pousser, daemon=True)
        self._thread.start()

    def _pousser(self):
        while not self._arret.wait(self._periode):
            if self.gele:
                continue   # plus aucune trame — mais `active` reste True
            self._rappel(np.full((64, 2), 0.5, dtype=np.float32), 64, None, None)

    def stop(self):
        self._arret.set()

    def close(self):
        self.ferme = True
        self._arret.set()


class _FauxSd:
    def __init__(self, sinks=(SINK_A,)):
        self.definir_sinks(sinks)
        self.flux_crees: list[_FauxFlux] = []
        self.leve_a_l_ouverture = False

    def definir_sinks(self, sinks):
        """Une entrée moniteur par sink, sous le hostapi PulseAudio."""
        self._devices = [
            {"name": "default", "max_input_channels": 128, "hostapi": 0},
        ] + [
            {"name": f"{s}.monitor", "max_input_channels": 2, "hostapi": 1} for s in sinks
        ]

    def query_hostapis(self):
        return [{"name": "ALSA"}, {"name": "PulseAudio"}]

    def query_devices(self):
        return self._devices

    def InputStream(self, **kwargs):  # noqa: N802 — nom imposé par sounddevice
        if self.leve_a_l_ouverture:
            raise RuntimeError("ouverture refusée")
        flux = _FauxFlux(kwargs["callback"])
        self.flux_crees.append(flux)
        return flux


@pytest.fixture
def sd_faux(monkeypatch):
    faux = _FauxSd()
    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    return faux


@pytest.fixture
def pactl_faux(monkeypatch):
    """Contrôle la sortie par défaut vue par l'adaptateur."""
    etat = {"sink": SINK_A}
    monkeypatch.setattr(mod, "sink_par_defaut", lambda: etat["sink"])
    return etat


def _attendre(predicat, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if predicat():
            return True
        time.sleep(0.02)
    return False


# ── Résolution du moniteur ───────────────────────────────────────────────────────

def test_moniteur_resolu_sur_le_hostapi_pulseaudio(sd_faux):
    assert index_moniteur(sd_faux, SINK_A) == 1


def test_moniteur_ignore_les_entrees_hors_pulseaudio(sd_faux, caplog):
    """Les moniteurs ne sont visibles que sous PulseAudio : une entrée ALSA portant le
    même nom ne doit pas être retenue (mesuré au spike — ALSA n'expose que
    `default`/`sysdefault`/`pipewire`, qui n'identifient aucun sink)."""
    sd_faux._devices = [{"name": f"{SINK_A}.monitor", "max_input_channels": 2, "hostapi": 0}]
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        assert index_moniteur(sd_faux, SINK_A) is None
    assert any("introuvable" in r.getMessage() for r in caplog.records)


def test_aucun_repli_sur_un_autre_moniteur(sd_faux, caplog):
    """LE test de contrat de la résolution : avec 4 sorties, prendre « le premier
    moniteur venu » capturerait une sortie inactive — piste système muette et
    silencieuse. Mieux vaut None et un WARNING."""
    sd_faux.definir_sinks([SINK_B])   # le sink demandé n'est pas là
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        assert index_moniteur(sd_faux, SINK_A) is None


def test_enumeration_qui_leve_ne_propage_pas(sd_faux):
    def _leve():
        raise RuntimeError("PortAudio cassé")

    sd_faux.query_devices = _leve
    assert index_moniteur(sd_faux, SINK_A) is None


def test_sink_par_defaut_absent_de_pactl(monkeypatch):
    monkeypatch.setattr(mod, "_pactl", lambda *a: None)
    assert sink_par_defaut() is None


def test_sink_par_defaut_vide_vaut_none(monkeypatch):
    monkeypatch.setattr(mod, "_pactl", lambda *a: "")
    assert sink_par_defaut() is None


# ── disponible() ─────────────────────────────────────────────────────────────────

def test_disponible_vrai_quand_le_moniteur_existe(sd_faux, pactl_faux):
    assert CaptureAudioSystemeMonitor().disponible() is True


def test_disponible_faux_et_loggé_sans_pactl(sd_faux, monkeypatch, caplog):
    monkeypatch.setattr(mod, "sink_par_defaut", lambda: None)
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        assert CaptureAudioSystemeMonitor().disponible() is False
    # La cause décide d'une réunion sans piste système : elle doit être dans les logs.
    assert any("pactl" in r.getMessage() for r in caplog.records)


# ── Capture nominale ─────────────────────────────────────────────────────────────

def test_capture_alimente_le_buffer_en_mono(sd_faux, pactl_faux):
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        assert _attendre(lambda: len(capture.recuperer_echantillons()) > 0)
    finally:
        capture.arreter()


def test_downmix_stereo_vers_mono(sd_faux, pactl_faux):
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        _attendre(lambda: sd_faux.flux_crees and sd_faux.flux_crees[0].active)
        time.sleep(0.2)
        audio = capture.recuperer_echantillons()
    finally:
        capture.arreter()
    assert audio.ndim == 1 and audio.dtype == np.float32
    assert np.allclose(audio[audio != 0], 0.5)   # moyenne des 2 canaux à 0,5


def test_demarrer_deux_fois_est_un_no_op_logge(sd_faux, pactl_faux, caplog):
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        with caplog.at_level(logging.WARNING, logger="debrief_meet"):
            capture.demarrer()
        assert any("déjà en cours" in r.getMessage() for r in caplog.records)
    finally:
        capture.arreter()


def test_arreter_sans_demarrer_ne_leve_pas():
    CaptureAudioSystemeMonitor().arreter()


def test_arreter_ferme_le_flux(sd_faux, pactl_faux):
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    _attendre(lambda: bool(sd_faux.flux_crees))
    capture.arreter()
    assert sd_faux.flux_crees[0].ferme is True


def test_taux_echantillonnage_est_48k():
    assert CaptureAudioSystemeMonitor().taux_echantillonnage == TAUX


# ── Q4 : la sortie par défaut change ─────────────────────────────────────────────

def test_changement_de_sortie_rouvre_sur_le_nouveau_moniteur(sd_faux, pactl_faux, monkeypatch):
    """Mesuré au spike : quand le son part ailleurs, le flux continue de livrer des
    zéros sans rien signaler. Seule la surveillance de `pactl` peut le détecter."""
    monkeypatch.setattr(mod, "_INTERVALLE_SURVEILLANCE_S", 0.2)
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        assert _attendre(lambda: bool(sd_faux.flux_crees))
        sd_faux.definir_sinks([SINK_A, SINK_B])
        pactl_faux["sink"] = SINK_B
        assert _attendre(lambda: len(sd_faux.flux_crees) == 2), "aucune réouverture"
    finally:
        capture.arreter()
    assert sd_faux.flux_crees[0].ferme is True


def test_sortie_inchangee_ne_rouvre_pas(sd_faux, pactl_faux, monkeypatch):
    monkeypatch.setattr(mod, "_INTERVALLE_SURVEILLANCE_S", 0.1)
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        _attendre(lambda: bool(sd_faux.flux_crees))
        time.sleep(0.8)   # 8 cycles de surveillance : largement de quoi rouvrir à tort
        assert len(sd_faux.flux_crees) == 1
    finally:
        capture.arreter()


# ── Q6 : le sink disparaît — le flux gèle sans rien dire ────────────────────────

def test_flux_gele_est_detecte_et_rouvert(sd_faux, pactl_faux, monkeypatch, caplog):
    """LE test du comportement mesuré en phase 4 : sink détruit ⇒ plus aucune trame,
    `active` reste True, aucune exception. Le chien de garde est le seul recours."""
    monkeypatch.setattr(mod, "_GRACE_APRES_OUVERTURE_S", 0.2)
    monkeypatch.setattr(mod, "_SILENCE_AVANT_REOUVERTURE_S", 0.3)

    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        assert _attendre(lambda: bool(sd_faux.flux_crees))
        premier = sd_faux.flux_crees[0]
        with caplog.at_level(logging.WARNING, logger="debrief_meet"):
            premier.gele = True          # le sink a disparu : plus une seule trame
            assert _attendre(lambda: len(sd_faux.flux_crees) == 2), "gel non détecté"
    finally:
        capture.arreter()

    assert premier.active is True, "le double doit refléter le vrai : `active` ment"
    assert any("aucune trame" in r.getMessage() for r in caplog.records)


def test_pas_de_reouverture_pendant_le_delai_de_grace(sd_faux, pactl_faux, monkeypatch):
    """Sans délai de grâce, un flux qui vient d'être ouvert (donc sans trame encore)
    serait aussitôt jugé mort — boucle de réouverture infinie."""
    monkeypatch.setattr(mod, "_SILENCE_AVANT_REOUVERTURE_S", 0.01)
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        _attendre(lambda: bool(sd_faux.flux_crees))
        time.sleep(1.0)
        assert len(sd_faux.flux_crees) == 1
    finally:
        capture.arreter()


# ── Repli silence : l'horloge de la piste ne s'arrête jamais ────────────────────

def test_silence_injecte_quand_aucun_moniteur(sd_faux, monkeypatch):
    """Sans piste système, `core/reunion` mesurerait un temps plus court que le micro :
    les deux pistes se décaleraient de la durée de la panne (docs/48)."""
    monkeypatch.setattr(mod, "sink_par_defaut", lambda: None)
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        assert _attendre(lambda: len(capture.recuperer_echantillons()) > 0, delai=3.0)
    finally:
        capture.arreter()


def test_silence_comble_la_duree_reelle(sd_faux, pactl_faux, monkeypatch):
    capture = CaptureAudioSystemeMonitor()
    capture._t_derniere_trame = time.monotonic() - 2.0
    capture._combler_silence(time.monotonic(), "test")
    audio = capture.recuperer_echantillons()
    assert 1.8 * TAUX <= len(audio) <= 2.2 * TAUX
    assert not audio.any()


def test_silence_borne_pour_ne_pas_exploser_la_memoire(sd_faux, pactl_faux, caplog):
    """Une mise en veille de la machine créerait un trou de plusieurs heures :
    combler à l'identique allouerait des gigaoctets."""
    capture = CaptureAudioSystemeMonitor()
    capture._t_derniere_trame = time.monotonic() - 7200.0   # 2 h
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        capture._combler_silence(time.monotonic(), "veille")
    audio = capture.recuperer_echantillons()
    assert len(audio) == int(mod._COMBLEMENT_MAX_S * TAUX)
    assert any("décalé" in r.getMessage() for r in caplog.records)


def test_panne_durable_ne_noie_pas_le_journal(sd_faux, monkeypatch, caplog):
    """Le comblement tourne à chaque tick (2/s) : tout journaliser produirait ~7 000
    lignes/h dans un fichier rotatif de 5 Mo et chasserait l'historique utile
    (docs/31). Le silence doit bien être injecté, mais résumé périodiquement."""
    monkeypatch.setattr(mod, "sink_par_defaut", lambda: None)
    monkeypatch.setattr(mod, "_INTERVALLE_TICK_S", 0.02)

    capture = CaptureAudioSystemeMonitor()
    with caplog.at_level(logging.INFO, logger="debrief_meet"):
        capture.demarrer()
        time.sleep(1.0)          # ≈ 50 ticks, donc 50 comblements
        capture.arreter()
        echantillons = len(capture.recuperer_echantillons())

    lignes_silence = [r for r in caplog.records if "silence" in r.getMessage()]
    assert echantillons > 0, "le silence doit être injecté malgré la limitation des logs"
    assert len(lignes_silence) <= 2, f"journal noyé : {len(lignes_silence)} lignes"


def test_jitter_normal_ne_declenche_pas_de_comblement(sd_faux, pactl_faux):
    capture = CaptureAudioSystemeMonitor()
    capture._t_derniere_trame = time.monotonic() - 0.01
    capture._combler_silence(time.monotonic(), "jitter")
    assert len(capture.recuperer_echantillons()) == 0


# ── Robustesse : jamais de crash de réunion ─────────────────────────────────────

def test_ouverture_qui_leve_ne_tue_pas_le_thread(sd_faux, pactl_faux, caplog):
    """docs/33 E-3 : la capture système ne doit jamais faire tomber la réunion."""
    sd_faux.leve_a_l_ouverture = True
    capture = CaptureAudioSystemeMonitor()
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        capture.demarrer()
        time.sleep(1.2)
        actif = capture._thread is not None and capture._thread.is_alive()
        capture.arreter()
    assert actif, "le thread doit survivre et continuer d'essayer"
    assert any("ouverture impossible" in r.getMessage() for r in caplog.records)


def test_sortie_revenue_est_reprise(sd_faux, pactl_faux):
    """Le flux ne se rétablit pas tout seul quand on a dû fermer : il faut rouvrir."""
    sd_faux.leve_a_l_ouverture = True
    capture = CaptureAudioSystemeMonitor()
    capture.demarrer()
    try:
        time.sleep(0.8)
        sd_faux.leve_a_l_ouverture = False
        assert _attendre(lambda: bool(sd_faux.flux_crees), delai=3.0)
    finally:
        capture.arreter()
