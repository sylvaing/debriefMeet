"""Tests sans matériel — `soundcard` est entièrement mocké via `sys.modules`
(docs/34 §2.4). Les blocs simulés sont produits sans délai réel (juste un léger
sleep pour éviter une boucle folle), donc les tests restent rapides."""
from __future__ import annotations

import logging
import sys
import time
import types

import numpy as np
import pytest

from debrief_meet.platform.windows import capture_systeme_wasapi as mod
from debrief_meet.platform.windows.capture_systeme_wasapi import TAUX, CaptureAudioSystemeWasapi


class _FakeRecorder:
    def __init__(self, comportement):
        self._comportement = comportement

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        time.sleep(0.002)   # pace la boucle — évite un busy-loop qui affame le GIL
        return self._comportement()


class _FakeMicrophone:
    def __init__(self, comportement):
        self._comportement = comportement

    def recorder(self, samplerate, channels, blocksize):
        return _FakeRecorder(self._comportement)


class _FakeSpeaker:
    def __init__(self, name):
        self.name = name


class _FakeSoundcard:
    def __init__(self, bloc_defaut=None):
        self.nom_defaut = "Haut-parleurs (Realtek)"
        self.appels_get_microphone: list[str] = []
        self.leve_get_microphone: Exception | None = None
        self.echecs_restants: int | None = None   # None = échoue toujours
        self.delai_get_microphone = 0.0
        self._bloc_defaut = (
            bloc_defaut if bloc_defaut is not None
            else np.zeros((1024, 2), dtype=np.float32)
        )
        self._comportement_record = lambda: self._bloc_defaut

    def default_speaker(self):
        return _FakeSpeaker(self.nom_defaut)

    def get_microphone(self, name, include_loopback=True):
        self.appels_get_microphone.append(name)
        if self.delai_get_microphone:
            time.sleep(self.delai_get_microphone)
        if self.leve_get_microphone is not None:
            if self.echecs_restants is None or self.echecs_restants > 0:
                if self.echecs_restants is not None:
                    self.echecs_restants -= 1
                raise self.leve_get_microphone
        return _FakeMicrophone(self._comportement_record)


@pytest.fixture
def fake_sc(monkeypatch):
    fake = _FakeSoundcard()
    monkeypatch.setitem(sys.modules, "soundcard", fake)
    return fake


def _attendre(condition, timeout=2.0):
    debut = time.monotonic()
    while time.monotonic() - debut < timeout:
        if condition():
            return True
        time.sleep(0.005)
    return False


# ── Contrat de base ───────────────────────────────────────────────────────────

def test_disponible_true_avec_haut_parleur(fake_sc):
    assert CaptureAudioSystemeWasapi().disponible() is True


def test_disponible_false_si_soundcard_leve(monkeypatch):
    def _leve(*a, **kw):
        raise RuntimeError("pas de soundcard ici")
    fake = types.SimpleNamespace(default_speaker=_leve)
    monkeypatch.setitem(sys.modules, "soundcard", fake)
    assert CaptureAudioSystemeWasapi().disponible() is False


def test_recuperer_echantillons_vide_sans_capture():
    capture = CaptureAudioSystemeWasapi()
    assert capture.recuperer_echantillons().shape == (0,)


# ── E-2 : idempotence du démarrage ───────────────────────────────────────────

def test_demarrer_deux_fois_ne_double_pas_le_flux(fake_sc, caplog):
    capture = CaptureAudioSystemeWasapi()
    try:
        capture.demarrer()
        with caplog.at_level(logging.WARNING, logger="debrief_meet"):
            capture.demarrer()
        assert any("déjà en cours" in r.message for r in caplog.records)
        assert len(fake_sc.appels_get_microphone) <= 1
    finally:
        capture.arreter()


# ── E-3 : arrêt joint le thread ───────────────────────────────────────────────

def test_arreter_joint_le_thread(fake_sc):
    capture = CaptureAudioSystemeWasapi()
    capture.demarrer()
    time.sleep(0.05)   # laisse le thread démarrer réellement avant de l'arrêter
    capture.arreter()
    assert capture._thread is None


def test_arreter_sans_demarrer_ne_leve_pas():
    CaptureAudioSystemeWasapi().arreter()


# ── Downmix stéréo → mono ────────────────────────────────────────────────────

def test_downmix_stereo_vers_mono(fake_sc):
    bloc = np.zeros((1024, 2), dtype=np.float32)
    bloc[:, 0] = 1.0
    bloc[:, 1] = 3.0
    fake_sc._bloc_defaut = bloc

    capture = CaptureAudioSystemeWasapi()
    capture.demarrer()
    try:
        # Attend qu'au moins un bloc soit capté.
        echantillons = np.zeros(0, dtype=np.float32)
        debut = time.monotonic()
        while time.monotonic() - debut < 1.0 and len(echantillons) == 0:
            time.sleep(0.01)
            with capture._verrou:
                if capture._buffer:
                    echantillons = np.concatenate(capture._buffer)
        assert len(echantillons) > 0
        assert np.allclose(echantillons, 2.0)
    finally:
        capture.arreter()


# ── Bascule de sortie en cours de réunion (§2.3) ─────────────────────────────

def test_bascule_de_sortie_reouvre_sur_le_nouveau_haut_parleur(fake_sc, monkeypatch):
    import debrief_meet.platform.windows.capture_systeme_wasapi as mod
    monkeypatch.setattr(mod, "_INTERVALLE_SURVEILLANCE_S", 0.0)

    capture = CaptureAudioSystemeWasapi()
    capture.demarrer()
    try:
        assert _attendre(lambda: len(fake_sc.appels_get_microphone) >= 1)
        fake_sc.nom_defaut = "Casque Bluetooth"
        assert _attendre(lambda: "Casque Bluetooth" in fake_sc.appels_get_microphone, timeout=2.0)
    finally:
        capture.arreter()


# ── 3 échecs consécutifs → mode silence, jamais de crash ─────────────────────

def test_trois_echecs_consecutifs_passe_en_mode_silence(fake_sc, caplog):
    fake_sc.leve_get_microphone = RuntimeError("WASAPI indisponible")

    capture = CaptureAudioSystemeWasapi()
    with caplog.at_level(logging.ERROR, logger="debrief_meet"):
        capture.demarrer()
        assert _attendre(lambda: capture._silence is True, timeout=2.0)
    capture.arreter()

    assert any("mode silence" in r.message for r in caplog.records)
    # NB : plus d'assertion « piste vide » ici — c'était le défaut, pas le contrat.
    # `_silence = True` était posé et lu par personne, la piste cessait de grandir et
    # finissait courte de tout le reste de la réunion. Le comblement continu est
    # vérifié par test_mode_silence_comble_jusqu_a_l_arret ci-dessous.


# ── Comblement du silence (docs/48) : la piste système garde sa durée réelle ──────
#
# Port de `platform/linux/capture_systeme_monitor`, qui l'avait appris le premier.
# Toute seconde sans livraison RACCOURCIT la piste système et décale les deux pistes
# d'autant — l'AEC décroche, l'attribution des locuteurs devient fausse.

def test_silence_comble_la_duree_reelle(fake_sc):
    capture = CaptureAudioSystemeWasapi()
    capture._t_derniere_trame = time.monotonic() - 2.0
    capture._combler_silence(time.monotonic(), "test")
    audio = capture.recuperer_echantillons()
    assert 1.8 * TAUX <= len(audio) <= 2.2 * TAUX
    assert not audio.any()


def test_silence_borne_pour_ne_pas_exploser_la_memoire(fake_sc, caplog):
    """Une mise en veille créerait un trou de plusieurs heures : combler à l'identique
    allouerait des gigaoctets. On borne, et on DIT que les pistes resteront décalées."""
    capture = CaptureAudioSystemeWasapi()
    capture._t_derniere_trame = time.monotonic() - 7200.0
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        capture._combler_silence(time.monotonic(), "veille")
    audio = capture.recuperer_echantillons()
    assert len(audio) == int(mod._COMBLEMENT_MAX_S * TAUX)
    assert any("décalé" in r.getMessage() for r in caplog.records)


def test_gigue_sous_le_seuil_non_comblee(fake_sc):
    capture = CaptureAudioSystemeWasapi()
    capture._t_derniere_trame = time.monotonic() - mod._COMBLEMENT_MIN_S / 2
    capture._combler_silence(time.monotonic(), "gigue")
    assert capture.recuperer_echantillons().shape == (0,)


def test_mode_silence_comble_jusqu_a_l_arret(fake_sc, monkeypatch):
    """LE défaut corrigé : après 3 échecs, `_silence = True` était posé puis le thread
    faisait `return` — la piste cessait de grandir jusqu'à la fin de la réunion, et
    `_silence` n'était lu par personne. Elle doit maintenant continuer de grandir."""
    monkeypatch.setattr(mod, "_PERIODE_COMBLEMENT_S", 0.02)
    fake_sc.leve_get_microphone = RuntimeError("WASAPI indisponible")

    capture = CaptureAudioSystemeWasapi()
    try:
        capture.demarrer()
        assert _attendre(lambda: capture._silence is True, timeout=2.0)
        assert _attendre(lambda: len(capture.recuperer_echantillons()) > 0, timeout=2.0)
    finally:
        capture.arreter()
    assert capture._silence_cumule_s > 0


def test_reouverture_comble_le_temps_perdu(fake_sc, caplog):
    """Le trou de la réinit WASAPI (ici 150 ms simulées) doit être comblé au retour,
    sinon chaque cycle échec→réouverture raccourcit la piste."""
    fake_sc.leve_get_microphone = RuntimeError("panne passagère")
    fake_sc.echecs_restants = 1              # échoue une fois, puis marche
    fake_sc.delai_get_microphone = 0.15      # le temps réellement perdu

    capture = CaptureAudioSystemeWasapi()
    try:
        with caplog.at_level(logging.INFO, logger="debrief_meet"):
            capture.demarrer()
            assert _attendre(lambda: capture._silence_cumule_s > 0, timeout=3.0)
    finally:
        capture.arreter()

    messages = [r.getMessage() for r in caplog.records]
    assert any("silence injectées" in m and "en échec" in m for m in messages)
