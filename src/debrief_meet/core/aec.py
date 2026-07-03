"""
Annulation d'écho acoustique (AEC) — Phase A, étape 1.

`ProcesseurAEC` nettoie le micro avec l'audio système comme référence, pour en
retirer l'écho des participants distants (haut-parleurs sans casque). Il encapsule
l'AEC3 (SDK LiveKit) validée par le spike (cf. `docs/05-spike-aec-webrtc.md` et le
cadrage `docs/06-integration-aec.md`).

Caractéristiques (validées au spike) :
- moteur **LiveKit AEC3**, débruitage (NS) **désactivé** (dégrade la voix) ;
- la référence doit **précéder** l'écho (filtre causal) → **marge de lead ~40 ms** ;
- objet **à état** : on l'alimente par tranche via `pousser()`, l'état de l'AEC et
  l'alignement sont conservés d'une tranche à l'autre (la dérive d'horloge est
  absorbée par l'estimateur interne d'AEC3, cf. spike Étape 2).

Ce module ne touche pas à l'app (le câblage `factory`/`reunion` est l'étape 2).
"""
from __future__ import annotations

import logging
import os
import sys

import numpy as np

from debrief_meet.core.audio import SEUIL_RMS_SILENCE as SEUIL_RMS, reechantillonner

logger = logging.getLogger(__name__)

# Trace de diagnostic vers stderr si DEBRIEF_AEC_DEBUG est défini (étape 3, validation).
_DEBUG = bool(os.environ.get("DEBRIEF_AEC_DEBUG"))


def _trace(msg: str) -> None:
    if _DEBUG:
        sys.stderr.write(f"[AEC] {msg}\n")
        sys.stderr.flush()
    logger.debug("AEC %s", msg)

SR_AEC = 16_000                       # 16 kHz mono, comme ce qu'on envoie à Whisper
TRAME = SR_AEC * 10 // 1000           # 160 échantillons = 10 ms (imposé par WebRTC)
MARGE_LEAD_MS_DEFAUT = 40             # réf précède l'écho (cf. spike : plateau 20-60 ms)
DELAI_MAX_MS = 600                    # délai HP→micro plausible : au-delà = faux verrou
CALIB_FENETRE_S = 12.0                # fenêtre de cross-corrélation pour caler le délai
REF_RMS_MIN = 0.005                   # en deçà, le système est silencieux → pas d'écho à caler
QUALITE_CORR_MIN = 10.0               # pic/médiane mini pour un délai FIABLE (sinon on diffère)


# ── Estimation du délai (cross-corrélation bornée) ───────────────────────────

def _meilleur_lag(a: np.ndarray, b: np.ndarray, delai_max: int) -> int:
    """Lag maximisant |cross-corrélation| dans [-delai_max, +delai_max] (échantillons)."""
    from scipy import signal

    corr = np.abs(signal.correlate(a, b, mode="full"))
    lags = signal.correlation_lags(len(a), len(b), mode="full")
    corr = np.where(np.abs(lags) <= delai_max, corr, -1.0)
    return int(lags[np.argmax(corr)])


def estimer_delai(mic: np.ndarray, ref: np.ndarray,
                  delai_max_ms: int = DELAI_MAX_MS, fenetre_s: float = 3.0) -> int | None:
    """Délai entier (échantillons, 16 kHz) entre micro et référence, ou None si
    pas assez d'audio. Borné à ±`delai_max_ms` pour éviter les faux verrous."""
    n = min(len(mic), len(ref), int(fenetre_s * SR_AEC))
    if n < SR_AEC // 2:               # < 0,5 s : insuffisant pour caler
        return None
    a = mic[:n] - mic[:n].mean()
    b = ref[:n] - ref[:n].mean()
    return _meilleur_lag(a, b, int(delai_max_ms / 1000 * SR_AEC))


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def _caler_delai(mic: np.ndarray, ref: np.ndarray, delai_max: int) -> tuple[int, float]:
    """Retourne (délai, qualité) où qualité = pic / médiane de la cross-corrélation.

    Une qualité élevée = pic franc = écho réellement corrélé ; une qualité faible
    = pas d'écho exploitable (on ne calera pas dessus)."""
    from scipy import signal

    a = mic - mic.mean()
    b = ref - ref.mean()
    corr = np.abs(signal.correlate(a, b, mode="full"))
    lags = signal.correlation_lags(len(a), len(b), mode="full")
    plausible = np.abs(lags) <= delai_max
    corr_borne = np.where(plausible, corr, 0.0)
    idx = int(np.argmax(corr_borne))
    pic = corr_borne[idx]
    mediane = float(np.median(corr[corr > 0])) if np.any(corr > 0) else 0.0
    qualite = pic / mediane if mediane > 0 else 0.0
    return int(lags[idx]), qualite


# ── Moteur AEC (injectable pour les tests) ───────────────────────────────────

class MoteurAEC:
    """Interface d'un moteur d'AEC trame à trame (10 ms, int16 mono 16 kHz)."""

    def traiter_trame(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        """near = micro, far = référence (système). Retourne le micro nettoyé."""
        raise NotImplementedError

    def terminer(self) -> None:
        pass


class _MoteurAECLiveKit(MoteurAEC):
    """AEC3 via le SDK LiveKit (APM WebRTC de production)."""

    def __init__(self, ns: bool = False) -> None:
        from livekit import rtc

        self._rtc = rtc
        self._apm = rtc.AudioProcessingModule(
            echo_cancellation=True, noise_suppression=ns, high_pass_filter=True
        )
        # Référence pré-alignée pour précéder l'écho → pas de délai résiduel à déclarer.
        self._apm.set_stream_delay_ms(0)

    def traiter_trame(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        rtc = self._rtc
        self._apm.process_reverse_stream(
            rtc.AudioFrame(data=far.tobytes(), sample_rate=SR_AEC,
                           num_channels=1, samples_per_channel=TRAME)
        )
        na = rtc.AudioFrame(data=near.tobytes(), sample_rate=SR_AEC,
                            num_channels=1, samples_per_channel=TRAME)
        self._apm.process_stream(na)  # nettoie « na » en place
        return np.frombuffer(na.data, dtype=np.int16)


# ── Processeur AEC à état ────────────────────────────────────────────────────

class ProcesseurAEC:
    """Nettoie le micro en continu avec le système comme référence.

    Alimenté par tranche : `pousser(micro, systeme)` renvoie le micro nettoyé en
    **float32 16 kHz**. L'état (filtre AEC, alignement) est conservé entre appels.

    Paramètres :
      - `sr_micro`/`sr_systeme` : taux d'échantillonnage des captures brutes ;
      - `marge_lead_ms` : avance imposée à la référence (filtre causal) ;
      - `ns` : débruitage (désactivé par défaut, dégrade la voix) ;
      - `delai_ms` : délai micro↔système connu (calibration stockée). Si None, il est
        mesuré par cross-corrélation sur le 1ᵉʳ audio reçu ;
      - `moteur` : `MoteurAEC` injectable (défaut : LiveKit, créé à `demarrer()`).
    """

    _MIN_CALIB = SR_AEC  # 1 s d'audio minimum pour caler le délai par cross-corrélation

    def __init__(self, sr_micro: int = 44_100, sr_systeme: int = 48_000,
                 marge_lead_ms: int = MARGE_LEAD_MS_DEFAUT, ns: bool = False,
                 delai_ms: float | None = None, moteur: MoteurAEC | None = None) -> None:
        self._sr_micro = sr_micro
        self._sr_systeme = sr_systeme
        self._marge = int(round(marge_lead_ms / 1000 * SR_AEC))
        self._ns = ns
        self._delai_force = None if delai_ms is None else int(round(delai_ms / 1000 * SR_AEC))
        self._moteur = moteur
        self._moteur_injecte = moteur is not None
        self._reset_etat()

    def _reset_etat(self) -> None:
        self._buf_micro = np.zeros(0, dtype=np.float32)
        self._buf_ref = np.zeros(0, dtype=np.float32)
        self._calibre = False
        self._demarre = False
        self._a_sauter_micro = 0
        self._a_sauter_ref = 0
        self._delai_estime: int | None = None
        self._derniere_attenuation_db: float | None = None

    def demarrer(self) -> None:
        """Prépare une session : moteur AEC **frais** (sauf moteur injecté) + état remis à zéro.

        Un APM neuf à chaque réunion évite qu'un filtre adapté à la session précédente
        ne pollue la suivante (chemin d'écho différent)."""
        moteur = self._moteur if self._moteur_injecte else _MoteurAECLiveKit(ns=self._ns)
        self._reset_etat()
        self._moteur = moteur
        self._demarre = True

    def recalibrer(self) -> None:
        """Reprend l'alignement à zéro sans recréer le moteur AEC — à appeler quand le
        chemin d'écho micro/haut-parleur change en cours de session (ex. switch de
        micro à chaud, docs/20 §6 étape B). Contrairement à `demarrer()`, l'APM en
        cours est conservé : seul le calage (délai, buffers) est remis à zéro."""
        if not self._demarre:
            return
        self._reset_etat()
        self._demarre = True  # `_reset_etat` le remet à False — session déjà en cours ici

    def pousser(self, micro: np.ndarray, systeme: np.ndarray) -> np.ndarray:
        """Ajoute une tranche micro + système ; renvoie le micro nettoyé (16 kHz)."""
        if not self._demarre:
            raise RuntimeError("ProcesseurAEC.demarrer() doit précéder pousser().")

        self._buf_micro = np.concatenate(
            [self._buf_micro, reechantillonner(np.asarray(micro, dtype=np.float32), self._sr_micro)]
        )
        self._buf_ref = np.concatenate(
            [self._buf_ref, reechantillonner(np.asarray(systeme, dtype=np.float32), self._sr_systeme)]
        )

        if not self._calibre and not self._tenter_calibration():
            # Pas d'écho franc à annuler (système silencieux ou pas de pic corrélé) →
            # on laisse PASSER le micro brut (la voix n'est jamais perdue) et on vide les
            # buffers pour réessayer de caler à la tranche suivante. Sans écho, le micro
            # brut = ce que l'AEC produirait de toute façon.
            sortie = self._buf_micro
            self._buf_micro = np.zeros(0, dtype=np.float32)
            self._buf_ref = np.zeros(0, dtype=np.float32)
            _trace(f"non calé → passthrough {len(sortie)} éch (voix préservée)")
            return sortie

        return self._traiter_dispo()

    # ── Privé ────────────────────────────────────────────────────────────────

    def _tenter_calibration(self) -> bool:
        """Cale le délai SI un écho franc est présent. True si calé, False si différé.

        On ne cale que sur un pic de cross-corrélation net (`QUALITE_CORR_MIN`) avec un
        système qui joue (`REF_RMS_MIN`) → jamais sur du bruit, ce qui éviterait de
        sur-soustraire et d'effacer la voix."""
        if self._delai_force is not None:
            delai = self._delai_force
        else:
            n = min(len(self._buf_micro), len(self._buf_ref), int(CALIB_FENETRE_S * SR_AEC))
            if n < self._MIN_CALIB:                       # < 1 s : trop peu pour caler
                return False
            if _rms(self._buf_ref[:n]) < REF_RMS_MIN:      # système silencieux → pas d'écho
                _trace("calibration différée (système silencieux)")
                return False
            delai, qualite = _caler_delai(self._buf_micro[:n], self._buf_ref[:n],
                                          int(DELAI_MAX_MS / 1000 * SR_AEC))
            if qualite < QUALITE_CORR_MIN:                 # pas de pic franc → pas d'écho fiable
                _trace(f"calibration différée (qualité corr {qualite:.1f} < {QUALITE_CORR_MIN})")
                return False

        self._delai_estime = delai
        # On veut que la référence PRÉCÈDE l'écho de `marge` → décalage = délai - marge.
        decalage = delai - self._marge
        # Décalage négatif → avancer la référence (sauter le début de la réf) ;
        # positif → retarder la référence (sauter le début du micro).
        self._a_sauter_ref = max(0, -decalage)
        self._a_sauter_micro = max(0, decalage)
        self._calibre = True
        _trace(f"calée : délai={delai} éch ({delai / SR_AEC * 1000:.0f} ms), "
               f"marge={self._marge}, décalage={decalage} "
               f"(saut réf={self._a_sauter_ref}, saut micro={self._a_sauter_micro})")
        return True

    def _traiter_dispo(self) -> np.ndarray:
        # Appliquer les sauts d'alignement en attente (peuvent s'étaler sur plusieurs tranches).
        if self._a_sauter_ref:
            k = min(self._a_sauter_ref, len(self._buf_ref))
            self._buf_ref = self._buf_ref[k:]
            self._a_sauter_ref -= k
        if self._a_sauter_micro:
            k = min(self._a_sauter_micro, len(self._buf_micro))
            self._buf_micro = self._buf_micro[k:]
            self._a_sauter_micro -= k
        if self._a_sauter_ref or self._a_sauter_micro:
            return np.zeros(0, dtype=np.float32)   # alignement pas encore consommé

        n = (min(len(self._buf_micro), len(self._buf_ref)) // TRAME) * TRAME
        if n == 0:
            return np.zeros(0, dtype=np.float32)

        near = self._buf_micro[:n]
        far = self._buf_ref[:n]
        self._buf_micro = self._buf_micro[n:]
        self._buf_ref = self._buf_ref[n:]

        near_i = (np.clip(near, -1, 1) * 32767).astype(np.int16)
        far_i = (np.clip(far, -1, 1) * 32767).astype(np.int16)
        sortie = np.empty(n, dtype=np.int16)
        for i in range(0, n, TRAME):
            sortie[i:i + TRAME] = self._moteur.traiter_trame(near_i[i:i + TRAME], far_i[i:i + TRAME])

        nettoye = sortie.astype(np.float32) / 32767.0
        self._maj_attenuation(near, nettoye)
        return nettoye

    def _maj_attenuation(self, brut: np.ndarray, nettoye: np.ndarray) -> None:
        """Indicateur d'atténuation (auto-vérif). Affiné en étape 3 (fenêtres de silence)."""
        rb = float(np.sqrt(np.mean(brut ** 2))) if len(brut) else 0.0
        rn = float(np.sqrt(np.mean(nettoye ** 2))) if len(nettoye) else 0.0
        if rb > 1e-4:
            self._derniere_attenuation_db = 20.0 * np.log10(rn / rb) if rn > 0 else float("-inf")
        _trace(f"tranche : RMS micro brut={rb:.5f} → nettoyé={rn:.5f} "
               f"(att {self._derniere_attenuation_db}), seuil={SEUIL_RMS}")

    # ── Accesseurs ─────────────────────────────────────────────────────────────

    @property
    def calibre(self) -> bool:
        return self._calibre

    @property
    def delai_estime(self) -> int | None:
        """Délai micro↔système mesuré (échantillons 16 kHz), None tant que non calé."""
        return self._delai_estime

    @property
    def derniere_attenuation_db(self) -> float | None:
        return self._derniere_attenuation_db

    def terminer(self) -> None:
        if self._moteur is not None:
            self._moteur.terminer()
