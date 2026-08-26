"""Tests unitaires — CaptureMicroSounddevice.

Couvre : le repli sur le périphérique par défaut, l'ouverture au taux natif du
périphérique (docs/20 — corrige le bug AirPods `-10851`), l'étiquetage/rééchan-
tillonnage vers 16 kHz canonique, et la résolution d'identité de périphérique
(anti-doublon du redémarrage à chaud). Tout est testé avec un faux module
`sounddevice` injecté — sans matériel audio réel.
"""
from __future__ import annotations

import logging
import sys

import numpy as np
import pytest

from debrief_meet.platform.commun import micro_sounddevice as ms_module
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
        # hostapi=1 → « Windows WASAPI » dans la table `hostapis` ci-dessus (l'index
        # importe : c'est lui que `_logger_infos_flux` résout pour le log E-8).
        if device is not None:
            return {"index": device, "name": f"peripherique-{device}", "hostapi": 1}
        return {"index": self._index_valide, "name": "défaut", "hostapi": 1}

    # Vraie signature sounddevice : sans argument → LISTE des host API ; avec un index
    # → le dict de celui-là. `hostapis` permet de simuler un poste sans WASAPI.
    hostapis = [{"name": "MME", "default_input_device": 0},
                {"name": "Windows WASAPI", "default_input_device": 1}]

    def query_hostapis(self, index=None):
        if index is None:
            return list(self.hostapis)
        return self.hostapis[index] if index < len(self.hostapis) else {"name": "inconnu"}


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


# ── E-8 (docs/33 §2.1) : périphérique/host API/taux loggés à chaque (re)démarrage ──

def test_demarrer_logge_peripherique_host_api_et_taux(micro_sans_warmup, monkeypatch, caplog):
    faux = _FauxSounddevice(index_valide=2, taux_par_index={2: 48_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)

    with caplog.at_level(logging.INFO, logger="debrief_meet"):
        micro_sans_warmup.demarrer(2)

    messages = [r.message for r in caplog.records]
    assert any(
        "peripherique-2" in m and "Windows WASAPI" in m and "48000" in m and "16000" in m
        for m in messages
    )


def test_redemarrer_logge_aussi_les_infos_du_nouveau_flux(micro_sans_warmup, monkeypatch, caplog):
    faux = _FauxSounddevice(index_valide=2, taux_par_index={2: 48_000, 3: 44_100})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro_sans_warmup.demarrer(2)

    with caplog.at_level(logging.INFO, logger="debrief_meet"):
        micro_sans_warmup.redemarrer(3)

    messages = [r.message for r in caplog.records]
    assert any("peripherique-3" in m and "44100" in m for m in messages)


# ── Comblement des trous de capture (docs/48 §8) ─────────────────────────────
#
# PortAudio perd des échantillons quand le callback est affamé (GIL) ; chaque
# perte décale la piste micro par rapport à la piste système et désaligne l'AEC.
# Le trou est détecté par discontinuité d'horodatage ADC et comblé par du silence.

class _TimeInfo:
    def __init__(self, adc):
        self.inputBufferAdcTime = adc


class _Flags:
    def __init__(self, input_overflow=False):
        self.input_overflow = input_overflow


def _pousser_bloc_adc(micro, n_echantillons, adc, valeur=1.0, overflow=False):
    bloc = np.ones((n_echantillons, 1), dtype=np.float32) * valeur
    micro._callback(bloc, n_echantillons, _TimeInfo(adc), _Flags(overflow))


@pytest.fixture()
def micro_16k(micro_sans_warmup, monkeypatch):
    """Micro démarré sur un périphérique natif 16 kHz : pas de rééchantillonnage,
    les comptes d'échantillons des tests sont exacts."""
    faux = _FauxSounddevice(index_valide=1, taux_par_index={1: TAUX_CANONIQUE})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro_sans_warmup.demarrer(1)
    return micro_sans_warmup


def test_trou_adc_comble_par_du_silence(micro_16k):
    """0,1 s captée, 50 ms perdues, 0,1 s captée → 0,25 s rendues, silence au milieu."""
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.15)  # attendu 10.1 → trou de 50 ms

    audio = micro_16k.recuperer_echantillons()

    assert len(audio) == 1600 + 800 + 1600
    assert np.all(audio[:1600] == 1.0)
    assert np.all(audio[1600:2400] == 0.0)  # le trou, comblé
    assert np.all(audio[2400:] == 1.0)


def test_blocs_contigus_aucun_comblement(micro_16k):
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.1)  # exactement contigu

    assert len(micro_16k.recuperer_echantillons()) == 3200


def test_gigue_sous_le_seuil_ignoree(micro_16k):
    """Un écart de 5 ms est de la gigue d'horodatage, pas une perte — rien d'inséré."""
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.105)

    assert len(micro_16k.recuperer_echantillons()) == 3200


def test_trou_aberrant_resynchronise_sans_combler(micro_16k):
    """Un saut de 60 s est un horodatage aberrant : on ne fabrique pas une minute
    de silence, mais la continuité repart du nouvel horodatage."""
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=70.0)   # aberrant → pas de comblement
    _pousser_bloc_adc(micro_16k, 1600, adc=70.1)   # contigu au précédent

    assert len(micro_16k.recuperer_echantillons()) == 4800


def test_horodatage_indisponible_pas_de_comblement(micro_16k):
    """Host API sans horodatage ADC (0.0) ou time_info absent : jamais de
    comblement à l'aveugle — comportement d'avant docs/48 §8, inchangé."""
    _pousser_bloc_adc(micro_16k, 1600, adc=0.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=0.0)
    micro_16k._callback(np.ones((1600, 1), dtype=np.float32), 1600, None, None)

    assert len(micro_16k.recuperer_echantillons()) == 4800


def test_redemarrage_reinitialise_la_continuite_adc(micro_16k, monkeypatch):
    """Nouveau flux = nouvelle horloge PortAudio : le premier bloc du nouveau flux
    ne doit pas être comparé à l'horodatage de l'ancien (comblement fantôme)."""
    _pousser_bloc_adc(micro_16k, 1600, adc=100.0)

    micro_16k.redemarrer(1)
    _pousser_bloc_adc(micro_16k, 1600, adc=0.5)  # horloge repartie de ~zéro

    assert len(micro_16k.recuperer_echantillons()) == 3200


def test_incidents_journalises_en_warning_par_tranche(micro_16k, caplog):
    """Docs/48 : « l'échec était dans les logs, mais en DEBUG » — plus jamais ça.
    Une seule ligne par tranche, avec trous, durée comblée et overflows."""
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.15, overflow=True)  # trou de 50 ms

    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        micro_16k.recuperer_echantillons()

    (msg,) = [r.message for r in caplog.records if "trou(s) de capture" in r.message]
    assert "1 trou(s)" in msg and "50 ms" in msg and "1 overflow(s)" in msg


def test_pas_de_journal_sans_incident(micro_16k, caplog):
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.1)

    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        micro_16k.recuperer_echantillons()

    assert not [r for r in caplog.records if "trou(s) de capture" in r.message]


def test_overflow_sans_horodatage_compte_quand_meme(micro_16k, caplog):
    """paInputOverflow levé mais ADC indisponible : impossible de dimensionner le
    trou (rien d'inséré), mais l'incident est journalisé — la perte reste visible."""
    micro_16k._callback(np.ones((1600, 1), dtype=np.float32), 1600,
                        _TimeInfo(0.0), _Flags(input_overflow=True))

    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        audio = micro_16k.recuperer_echantillons()

    assert len(audio) == 1600
    (msg,) = [r.message for r in caplog.records if "trou(s) de capture" in r.message]
    assert "0 trou(s)" in msg and "1 overflow(s)" in msg


def test_compteurs_remis_a_zero_entre_tranches(micro_16k, caplog):
    """Les incidents d'une tranche ne fuient pas dans la suivante."""
    _pousser_bloc_adc(micro_16k, 1600, adc=10.0)
    _pousser_bloc_adc(micro_16k, 1600, adc=10.15)
    micro_16k.recuperer_echantillons()

    _pousser_bloc_adc(micro_16k, 1600, adc=10.35)  # contigu (attendu 10.25+0.1)… non : trou !
    _pousser_bloc_adc(micro_16k, 1600, adc=10.45)  # contigu au précédent
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        micro_16k.recuperer_echantillons()

    (msg,) = [r.message for r in caplog.records if "trou(s) de capture" in r.message]
    assert "1 trou(s)" in msg  # celui de CETTE tranche seulement, pas 2


# ── Host API préféré : WASAPI plutôt que le défaut global (MME) sous Windows ──────
#
# Terrain 2026-08-26 : `micro_index = None` menait au défaut de PortAudio, soit MME
# sous Windows, dont l'horodatage ADC ne permet pas de détecter les pertes
# d'échantillons — le comblement de docs/48 §8 y est hors service.

def _micro(host_api_prefere):
    micro = CaptureMicroSounddevice(host_api_prefere=host_api_prefere)
    micro.WARMUP_S = 0.0
    return micro


def test_sans_index_vise_le_defaut_du_host_api_prefere(monkeypatch):
    faux = _FauxSounddevice(index_valide=None, taux_par_index={1: 48_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("WASAPI")

    micro.demarrer(None)

    # default_input_device de « Windows WASAPI » = 1, pas le défaut global (None).
    assert faux.streams_ouverts[-1].device == 1


def test_index_demande_explicitement_n_est_jamais_remplace(monkeypatch):
    """La préférence ne vaut QUE pour « aucun périphérique demandé » : un choix
    utilisateur (Préférences › Audio) doit être respecté tel quel."""
    faux = _FauxSounddevice(index_valide=7)
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("WASAPI")

    micro.demarrer(7)

    assert faux.streams_ouverts[-1].device == 7


def test_host_api_prefere_absent_retombe_sur_le_defaut_global(monkeypatch):
    faux = _FauxSounddevice(index_valide=None)
    faux.hostapis = [{"name": "MME", "default_input_device": 0}]   # pas de WASAPI
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("WASAPI")

    micro.demarrer(None)

    assert faux.streams_ouverts[-1].device is None


def test_host_api_prefere_sans_entree_par_defaut_retombe_sur_le_global(monkeypatch):
    """PortAudio met -1 quand l'host API n'a aucune entrée par défaut — pas un index."""
    faux = _FauxSounddevice(index_valide=None)
    faux.hostapis = [{"name": "Windows WASAPI", "default_input_device": -1}]
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("WASAPI")

    micro.demarrer(None)

    assert faux.streams_ouverts[-1].device is None


def test_preference_vide_conserve_le_comportement_portaudio(monkeypatch):
    faux = _FauxSounddevice(index_valide=None, taux_par_index={1: 48_000})
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("")

    micro.demarrer(None)

    assert faux.streams_ouverts[-1].device is None


def test_defaut_prefere_qui_refuse_de_s_ouvrir_replie_sur_le_global(monkeypatch):
    """L'index WASAPI existe dans la table mais l'ouverture échoue (périphérique
    fantôme) : le repli de `_ouvrir_flux` doit ramener au défaut global, pas propager."""
    faux = _FauxSounddevice(index_valide=None)          # aucun index n'est ouvrable...
    faux.hostapis = [{"name": "Windows WASAPI", "default_input_device": 42}]
    monkeypatch.setitem(sys.modules, "sounddevice", faux)
    micro = _micro("WASAPI")

    micro.demarrer(None)

    # Deux tentatives d'ouverture (42 refusé, puis le défaut global), et seul le second
    # flux existe — `InputStream` lève avant de créer quoi que ce soit.
    assert faux.evenements.count("open") == 2
    assert [s.device for s in faux.streams_ouverts] == [None]


def test_host_api_prefere_defaut_selon_l_os(monkeypatch):
    """Le défaut est dérivé de `sys.platform` (idiome de `surveillant_peripheriques`) :
    WASAPI sous Windows, aucune préférence ailleurs — et le paramètre explicite garde
    les tests déterministes sur les deux OS, la gate de build tournant sur la VM."""
    monkeypatch.setattr("debrief_meet.platform.commun.micro_sounddevice.sys.platform", "win32")
    assert (CaptureMicroSounddevice()._host_api_prefere
            == CaptureMicroSounddevice.HOST_API_PREFERE_DEFAUT)
    monkeypatch.setattr("debrief_meet.platform.commun.micro_sounddevice.sys.platform", "darwin")
    assert CaptureMicroSounddevice()._host_api_prefere == ""


# ── Comblement de trous HORS SERVICE : le dire au lieu de le taire ────────────────
#
# Terrain 2026-08-26 : le log portait « 0 trou(s) comblé(s), 1 overflow(s) signalé(s) »
# et rien d'autre — il a fallu remonter l'offset de l'AEC pour comprendre que les pertes
# n'étaient pas compensées. Le déclencheur est le DÉFICIT d'horloge murale : ni les
# overflows (zéro le jour du décrochage) ni l'horodatage ne sont fiables pour ça.


class _Horloge:
    """Horloge murale contrôlée — `avancer()` simule le temps qui passe sans dormir."""

    def __init__(self):
        self.t = 1_000.0

    def monotonic(self):
        return self.t

    def sleep(self, _secondes):
        pass

    def avancer(self, secondes):
        self.t += secondes


@pytest.fixture()
def horloge(monkeypatch):
    h = _Horloge()
    monkeypatch.setattr(ms_module, "time", h)
    return h


def _alertes_aveugles(caplog):
    return [r.getMessage() for r in caplog.records if "HORS SERVICE" in r.getMessage()]


def _livrer(micro, horloge, secondes_livrees, secondes_ecoulees, adc=0.0, overflow=False):
    """Livre `secondes_livrees` d'échantillons pendant que l'horloge avance de
    `secondes_ecoulees` — l'écart est la perte non compensée."""
    n = int(secondes_livrees * TAUX_CANONIQUE)
    horloge.avancer(secondes_ecoulees)
    _pousser_bloc_adc(micro, n, adc, overflow=overflow)


def test_deficit_declare_le_comblement_hors_service(micro_16k, horloge, caplog):
    """10 s d'horloge murale pour 5 s d'échantillons livrés : 5 s ont été perdues et
    personne ne les a comblées. Aucun overflow n'est nécessaire pour le voir — c'est
    tout l'intérêt, le poste du terrain n'en signalait aucun."""
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 0.0)        # pose t0 sur l'horloge contrôlée
        _livrer(micro_16k, horloge, secondes_livrees=5.0, secondes_ecoulees=10.0)
        micro_16k.recuperer_echantillons()

    alertes = _alertes_aveugles(caplog)
    assert len(alertes) == 1
    assert "5000 ms d'échantillons manquants" in alertes[0]
    assert "ne fournit pas d'horodatage ADC" in alertes[0]   # adc=0 → explique le déficit


def test_flux_sain_n_alerte_jamais_meme_sans_horodatage(micro_16k, horloge, caplog):
    """NON-RÉGRESSION Linux/macOS : un host API qui ne fournit AUCUN horodatage (adc=0)
    mais ne perd rien ne doit produire aucun WARNING. Sans cette garde, tout poste dont
    PortAudio ne remplit pas `inputBufferAdcTime` en récolterait un par réunion."""
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 0.0)
        for _ in range(20):
            _livrer(micro_16k, horloge, secondes_livrees=1.0, secondes_ecoulees=1.0)
            micro_16k.recuperer_echantillons()

    assert _alertes_aveugles(caplog) == []


def test_deficit_sous_le_seuil_reste_silencieux(micro_16k, horloge, caplog):
    """Gigue d'ordonnancement : sous le seuil, on se taît (la dérive d'horloge légitime
    est 3 ordres de grandeur plus petite, elle ne peut jamais y arriver)."""
    manque = ms_module.CaptureMicroSounddevice.DEFICIT_ALERTE_S / 2
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 0.0)
        _livrer(micro_16k, horloge, secondes_livrees=5.0, secondes_ecoulees=5.0 + manque)
        micro_16k.recuperer_echantillons()

    assert _alertes_aveugles(caplog) == []


def test_trou_comble_ne_creuse_aucun_deficit(micro_16k, horloge, caplog):
    """Comblement OPÉRANT : le trou est détecté par l'horodatage et remplacé par du
    silence, qui compte comme livré — donc pas de déficit, donc pas d'alerte, alors que
    le temps mural, lui, a bien avancé pendant le trou."""
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        horloge.avancer(1.0)
        _pousser_bloc_adc(micro_16k, 16_000, 1.0)          # 1 s livrée, adc à 1.0
        horloge.avancer(2.0)                               # 2 s murales…
        _pousser_bloc_adc(micro_16k, 16_000, 3.0)          # …dont 1 s de trou comblé
        micro_16k.recuperer_echantillons()

    assert micro_16k._trous_combles_flux == 1
    assert _alertes_aveugles(caplog) == []


def test_alerte_deficit_emise_une_seule_fois_par_flux(micro_16k, horloge, caplog):
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 0.0)
        for _ in range(3):
            _livrer(micro_16k, horloge, secondes_livrees=1.0, secondes_ecoulees=5.0)
            micro_16k.recuperer_echantillons()

    assert len(_alertes_aveugles(caplog)) == 1


def test_overflows_cites_en_explication_du_deficit(micro_16k, horloge, caplog):
    """Quand PortAudio DAIGNE signaler l'overflow, il est cité — mais il n'est jamais le
    déclencheur : le poste du terrain n'en a signalé aucun le jour du décrochage."""
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 1.0)               # horodatage présent (adc > 0)
        # adc CONTIGU au bloc précédent (1 échantillon plus tard) : l'horodatage jure que
        # rien n'a été perdu — la signature MME — alors que 4 s ont disparu du mur.
        _livrer(micro_16k, horloge, secondes_livrees=1.0, secondes_ecoulees=5.0,
                adc=1.0 + 1 / TAUX_CANONIQUE, overflow=True)
        micro_16k.recuperer_echantillons()

    alertes = _alertes_aveugles(caplog)
    assert len(alertes) == 1
    assert "aucune discontinuité" in alertes[0]            # adc > 0 → l'autre explication
    assert "1 overflow(s) non compensé(s)" in alertes[0]


def test_redemarrage_rearme_le_verdict_d_aveuglement(micro_16k, horloge, caplog):
    """Un nouveau flux peut viser un autre host API : le verdict précédent ne le
    concerne pas, et la comptabilité murale repart de zéro."""
    _pousser_bloc_adc(micro_16k, 1, 0.0)
    _livrer(micro_16k, horloge, secondes_livrees=1.0, secondes_ecoulees=5.0)
    micro_16k.recuperer_echantillons()
    assert micro_16k._alerte_aveugle_emise

    micro_16k.redemarrer(1)
    assert micro_16k._alerte_aveugle_emise is False
    assert micro_16k._t0_flux is None
    assert micro_16k._echantillons_livres == 0

    caplog.clear()   # sinon la 1ʳᵉ alerte, déjà capturée, compterait pour la seconde
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        _pousser_bloc_adc(micro_16k, 1, 0.0)
        _livrer(micro_16k, horloge, secondes_livrees=1.0, secondes_ecoulees=5.0)
        micro_16k.recuperer_echantillons()
    assert len(_alertes_aveugles(caplog)) == 1
