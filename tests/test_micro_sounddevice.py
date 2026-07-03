"""Tests unitaires — CaptureMicroSounddevice.

Couvre : le repli sur le périphérique par défaut, l'ouverture au taux natif du
périphérique (docs/20 — corrige le bug AirPods `-10851`), l'étiquetage/rééchan-
tillonnage vers 16 kHz canonique, et la résolution d'identité de périphérique
(anti-doublon du redémarrage à chaud). Tout est testé avec un faux module
`sounddevice` injecté — sans matériel audio réel.
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from debrief_meet.platform.commun.micro_sounddevice import (
    TAUX_CANONIQUE,
    CaptureMicroSounddevice,
)


class _FauxStream:
    def __init__(self, device, samplerate, evenements=None):
        self.device = device
        self.samplerate = samplerate
        self.started = False
        self.closed = False
        self._evenements = evenements

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True
        if self._evenements is not None:
            self._evenements.append("close")


class _FauxSounddevice:
    """Faux sounddevice : InputStream échoue si `device` n'est pas connu.

    `taux_par_index` mappe index → taux natif simulé du périphérique (défaut
    44 100 si absent de la table) — sert à simuler un micro Bluetooth verrouillé
    à un taux non standard (ex. AirPods à 24 000 Hz)."""

    def __init__(self, index_valide, taux_par_index=None):
        self._index_valide = index_valide
        self._taux_par_index = taux_par_index or {}
        self.streams_ouverts: list[_FauxStream] = []
        self.dernier_samplerate_demande = "non-demandé"
        # Traçabilité de l'ordre des opérations (refresh PortAudio, docs/25).
        self.evenements: list[str] = []
        self.appels_terminate = 0
        self.appels_initialize = 0

    def _connu(self, device):
        return device == self._index_valide or device in self._taux_par_index

    def _terminate(self):
        self.appels_terminate += 1
        self.evenements.append("terminate")

    def _initialize(self):
        self.appels_initialize += 1
        self.evenements.append("initialize")

    def InputStream(self, *, samplerate, channels, dtype, device, callback):
        self.dernier_samplerate_demande = samplerate
        self.evenements.append("open")
        if device is not None and not self._connu(device):
            raise RuntimeError(f"périphérique {device} introuvable")
        taux = self._taux_par_index.get(device, 44_100)
        s = _FauxStream(device, taux, evenements=self.evenements)
        self.streams_ouverts.append(s)
        return s

    def query_devices(self, device=None, kind=None):
        if device is not None:
            return {"index": device, "name": f"peripherique-{device}"}
        return {"index": self._index_valide, "name": "défaut"}


@pytest.fixture()
def micro_sans_warmup(monkeypatch):
    # Évite les 200 ms de sleep réels du warm-up.
    monkeypatch.setattr(CaptureMicroSounddevice, "WARMUP_S", 0.0)
    return CaptureMicroSounddevice()


def _pousser_bloc(micro, n_echantillons, valeur=1.0):
    bloc = (np.ones((n_echantillons, 1), dtype=np.float32) * valeur)
    micro._callback(bloc, n_echantillons, None, None)


# ── Repli sur le périphérique par défaut ─────────────────────────────────────

def test_demarrer_index_valide_ouvre_directement(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=2)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(2)

    assert len(faux.streams_ouverts) == 1
    assert faux.streams_ouverts[0].device == 2
    assert faux.streams_ouverts[0].started


def test_demarrer_index_invalide_repli_sur_defaut(micro_sans_warmup, monkeypatch):
    """Index configuré indisponible (ex. AirPods retirés) → repli sur device=None."""
    faux = _FauxSounddevice(index_valide=0)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(99)  # index qui n'existe plus

    # La 1re tentative (device=99) lève avant de créer un flux ; seul le repli
    # (device=None) ouvre effectivement un stream, et il est démarré.
    assert len(faux.streams_ouverts) == 1
    assert faux.streams_ouverts[0].device is None
    assert faux.streams_ouverts[0].started


def test_demarrer_sans_index_ne_replie_pas(micro_sans_warmup, monkeypatch):
    """Sans index demandé (device=None), un échec ne déclenche aucun repli — on propage."""
    faux = _FauxSounddevice(index_valide=0)

    def _input_stream_ko(*, samplerate, channels, dtype, device, callback):
        raise RuntimeError("aucun micro")

    faux.InputStream = _input_stream_ko
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    with pytest.raises(RuntimeError):
        micro_sans_warmup.demarrer(None)


# ── Taux natif à l'ouverture (docs/20 — bug AirPods `-10851`) ────────────────

def test_demarrer_ouvre_au_taux_natif_jamais_44100_impose(micro_sans_warmup, monkeypatch):
    """Un AirPods verrouillé à 24 kHz (mode mains-libres) ne doit plus provoquer -10851 :
    on demande samplerate=None (taux natif de PortAudio), jamais un taux fixe imposé."""
    faux = _FauxSounddevice(index_valide=3, taux_par_index={3: 24_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(3)

    assert faux.dernier_samplerate_demande is None
    assert faux.streams_ouverts[0].samplerate == 24_000       # taux natif effectivement ouvert
    assert micro_sans_warmup.taux_echantillonnage == TAUX_CANONIQUE == 16_000


def test_taux_echantillonnage_toujours_canonique_quel_que_soit_le_natif(
    micro_sans_warmup, monkeypatch
):
    faux = _FauxSounddevice(index_valide=1, taux_par_index={1: 48_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(1)

    assert micro_sans_warmup.taux_echantillonnage == 16_000


# ── Étiquetage + rééchantillonnage vers 16 kHz (docs/20 §5-6) ────────────────

def test_recuperer_echantillons_reechantillonne_vers_16k(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=1, taux_par_index={1: 48_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(1)

    _pousser_bloc(micro, 4800)  # 0,1 s à 48 kHz

    audio = micro.recuperer_echantillons()

    assert len(audio) == pytest.approx(1600, abs=5)  # 0,1 s à 16 kHz
    # `resample_poly` a des transitoires de filtre en bord de signal court —
    # on vérifie le niveau moyen plutôt qu'une égalité stricte échantillon par échantillon.
    assert np.mean(audio) == pytest.approx(1.0, abs=0.1)


def test_recuperer_echantillons_sans_rien_capte_renvoie_vide(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro_sans_warmup.demarrer(1)

    assert len(micro_sans_warmup.recuperer_echantillons()) == 0


def test_switch_en_cours_de_tranche_recolle_deux_taux_en_16k_homogene(
    micro_sans_warmup, monkeypatch
):
    """Docs/20 §4 : un switch de périphérique pendant une tranche produit deux
    suites de taux natifs différents (ex. 48k puis 24k), recollées en 16k homogène
    — jamais un seul taux appliqué à tort à tout le buffer."""
    faux = _FauxSounddevice(index_valide=1, taux_par_index={1: 48_000, 2: 24_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(1)
    _pousser_bloc(micro, 4800)          # 0,1 s à 48 kHz

    micro.redemarrer(2)
    _pousser_bloc(micro, 2400, valeur=2.0)  # 0,1 s à 24 kHz

    audio = micro.recuperer_echantillons()

    # 0,1 s@48k + 0,1 s@24k → 0,2 s à 16 kHz ≈ 3200 échantillons.
    assert len(audio) == pytest.approx(3200, abs=10)


# ── Redémarrage à chaud (Phase 3.5 / docs/20 §5) ─────────────────────────────

def test_redemarrer_preserve_le_buffer(micro_sans_warmup, monkeypatch):
    """Le redémarrage à chaud conserve l'audio déjà capté (pas de remise à zéro)."""
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(1)

    # Simule de l'audio capté depuis la dernière tranche, déjà au taux canonique
    # (isole ici la préservation du buffer du rééchantillonnage, testé à part).
    audio_capte = np.arange(1000, dtype=np.float32)
    micro._buffer = [(audio_capte, TAUX_CANONIQUE)]

    micro.redemarrer(1)

    restant = micro.recuperer_echantillons()
    assert np.array_equal(restant, audio_capte)  # audio préservé, sans altération


def test_redemarrer_ouvre_un_nouveau_flux_sur_lindex(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=2)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(2)

    micro.redemarrer(2)

    # Le dernier flux ouvert est démarré sur l'index demandé.
    assert faux.streams_ouverts[-1].device == 2
    assert faux.streams_ouverts[-1].started


def test_redemarrer_index_invalide_replie_sur_defaut(micro_sans_warmup, monkeypatch):
    """AirPods toujours absents au moment du redémarrage → repli sur le défaut."""
    faux = _FauxSounddevice(index_valide=0)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(0)

    micro.redemarrer(99)  # index préféré indisponible

    assert faux.streams_ouverts[-1].device is None
    assert faux.streams_ouverts[-1].started


# ── Double-start (docs/23 correctif 1 — fuite coreaudiod) ───────────────────

def test_demarrer_deux_fois_ferme_lancien_flux(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup

    micro.demarrer(1)
    micro.demarrer(1)  # double-start sans arreter() préalable

    assert len(faux.streams_ouverts) == 2
    premier, second = faux.streams_ouverts
    assert premier.closed is True
    assert second.started is True
    assert micro._stream is second


# ── Résolution d'identité de périphérique (docs/20 §6 étape B) ───────────────

def test_resoudre_peripherique_par_index(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=2)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    assert micro_sans_warmup.resoudre_peripherique(2) == "peripherique-2"


def test_resoudre_peripherique_defaut(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=2)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    assert micro_sans_warmup.resoudre_peripherique(None) == "défaut"


def test_resoudre_peripherique_echec_renvoie_none(micro_sans_warmup, monkeypatch):
    class _SDCasse:
        def query_devices(self, *a, **k):
            raise RuntimeError("aucun périphérique")

    monkeypatch.setitem(sys.modules, "sounddevice", _SDCasse())

    assert micro_sans_warmup.resoudre_peripherique(None) is None


# ── Refresh PortAudio (docs/25 correctif 1 — table figée à Pa_Initialize) ────

def test_demarrer_rafraichit_portaudio_avant_ouverture(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(1)

    assert faux.appels_terminate == 1
    assert faux.appels_initialize == 1
    assert faux.evenements == ["terminate", "initialize", "open"]


def test_redemarrer_ferme_lancien_flux_avant_le_refresh(micro_sans_warmup, monkeypatch):
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(1)
    faux.evenements.clear()  # ignore le refresh du demarrer() précédent

    micro.redemarrer(1)

    assert faux.evenements.index("close") < faux.evenements.index("terminate")


def test_demarrer_apres_arreter_attend_la_fermeture_differee_avant_refresh(
    micro_sans_warmup, monkeypatch
):
    """Séquence dangereuse du docs/25 : arreter() laisse le flux ouvert 300 ms
    (fermeture différée) — demarrer() doit attendre cette fermeture avant de
    rafraîchir PortAudio (Pa_Terminate avec un flux ouvert = état indéfini)."""
    faux = _FauxSounddevice(index_valide=1)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = micro_sans_warmup
    micro.demarrer(1)
    ancien = faux.streams_ouverts[-1]
    faux.evenements.clear()

    micro.arreter()   # arme la fermeture différée (thread, délai réel de 0,3 s)
    micro.demarrer(1)  # doit attendre la fermeture avant de rafraîchir

    assert ancien.closed is True
    assert faux.evenements.index("close") < faux.evenements.index("terminate")


def test_demarrer_sans_terminate_initialize_fonctionne_quand_meme(
    micro_sans_warmup, monkeypatch
):
    """Module sd sans API privée `_terminate`/`_initialize` (AttributeError) :
    le refresh est best-effort, la capture doit fonctionner quand même."""

    class _SDSansRefresh:
        def __init__(self):
            self.streams_ouverts = []

        def InputStream(self, *, samplerate, channels, dtype, device, callback):
            s = _FauxStream(device, 44_100)
            self.streams_ouverts.append(s)
            return s

    faux = _SDSansRefresh()
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    micro_sans_warmup.demarrer(1)

    assert faux.streams_ouverts[0].started
