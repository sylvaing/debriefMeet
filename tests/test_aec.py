"""Tests du ProcesseurAEC (Phase A, étape 1).

La logique (alignement, continuité d'état, plomberie) est testée avec un moteur
AEC factice injecté — sans dépendre de LiveKit. Un test e2e séparé valide le vrai
moteur AEC3 sur un écho synthétique (reproduit la validation du spike).
"""
from __future__ import annotations

import numpy as np
import pytest

from debrief_meet.core.aec import (
    RECAL_SEUIL_ECH,
    MoteurAEC,
    ProcesseurAEC,
    SEUIL_RMS,
    SR_AEC,
    TRAME,
    estimer_delai,
)


class _Identite(MoteurAEC):
    """Renvoie le micro inchangé — pour tester la plomberie/alignement."""

    def traiter_trame(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        return near.copy()


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


# ── Garde-fous ────────────────────────────────────────────────────────────────

def test_pousser_avant_demarrer_leve():
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    with pytest.raises(RuntimeError):
        proc.pousser(np.zeros(TRAME, np.float32), np.zeros(TRAME, np.float32))


# ── Plomberie & préservation ─────────────────────────────────────────────────

def test_voix_propre_preservee_avec_identite():
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC,
                         marge_lead_ms=0, delai_ms=0, moteur=_Identite())
    proc.demarrer()
    rng = np.random.default_rng(0)
    micro = rng.normal(0, 0.2, TRAME * 10).astype(np.float32)
    systeme = np.zeros_like(micro)
    out = proc.pousser(micro, systeme)
    assert len(out) == len(micro)                 # multiple de TRAME, marge 0, délai 0
    assert np.allclose(out, micro, atol=1e-3)     # identité (au bruit de quantif int16 près)


def test_continuite_etat_entre_tranches():
    # Deux tranches successives == une seule grosse tranche (report du reste géré).
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.2, 250).astype(np.float32)
    b = rng.normal(0, 0.2, 300).astype(np.float32)
    z = np.zeros(550, np.float32)

    p2 = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, delai_ms=0, moteur=_Identite())
    p2.demarrer()
    out2 = np.concatenate([p2.pousser(a, z[:250]), p2.pousser(b, z[:300])])

    p1 = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, delai_ms=0, moteur=_Identite())
    p1.demarrer()
    out1 = p1.pousser(np.concatenate([a, b]), z)

    assert len(out1) == (550 // TRAME) * TRAME
    assert np.allclose(out2, out1, atol=1e-3)     # même contenu, pas de trou/doublon aux frontières


# ── Alignement ────────────────────────────────────────────────────────────────

def test_estimer_delai_signe_et_borne():
    rng = np.random.default_rng(2)
    ref = rng.normal(0, 0.3, SR_AEC * 2).astype(np.float32)
    delai = 800                                   # micro = réf retardée de 800 éch
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai] * 0.5
    assert abs(estimer_delai(mic, ref) - delai) <= 2
    # bruit non corrélé → reste dans la borne, jamais de faux verrou extrême
    bruit = rng.normal(0, 0.3, SR_AEC * 2).astype(np.float32)
    assert abs(estimer_delai(ref, bruit)) <= int(0.6 * SR_AEC)


def test_estimer_delai_insuffisant_renvoie_none():
    x = np.zeros(SR_AEC // 4, np.float32)         # 0,25 s < 0,5 s
    assert estimer_delai(x, x) is None


def test_calibration_delai_force_pose_la_marge_de_lead():
    # délai forcé négatif (réf en retard) + marge → on saute le début de la RÉFÉRENCE
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC,
                         marge_lead_ms=40, delai_ms=-100.0, moteur=_Identite())
    proc.demarrer()
    proc.pousser(np.zeros(0, np.float32), np.zeros(0, np.float32))  # cale sans rien consommer
    assert proc.calibre
    marge = int(round(0.040 * SR_AEC))            # 640
    delai = int(round(-0.100 * SR_AEC))           # -1600
    assert proc._a_sauter_ref == -(delai - marge)  # 2240 : on avance la référence
    assert proc._a_sauter_micro == 0


def test_recalibrer_remet_le_calage_a_zero_sans_recreer_le_moteur():
    """`recalibrer()` (switch de micro à chaud, docs/20 §6 étape B) : nouveau chemin
    d'écho à recaler, mais l'APM (état interne du moteur AEC) est conservé."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC,
                         marge_lead_ms=40, delai_ms=-100.0, moteur=_Identite())
    proc.demarrer()
    moteur_avant = proc._moteur
    proc.pousser(np.zeros(0, np.float32), np.zeros(0, np.float32))  # cale
    assert proc.calibre

    proc.recalibrer()

    assert not proc.calibre
    assert proc.delai_estime is None
    assert proc._moteur is moteur_avant           # même objet moteur, pas reconstruit
    # La session reste utilisable (pas de RuntimeError « demarrer() doit précéder »).
    proc.pousser(np.zeros(0, np.float32), np.zeros(0, np.float32))
    assert proc.calibre


def test_recalibrer_avant_demarrer_est_un_noop():
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    proc.recalibrer()  # ne doit pas lever
    with pytest.raises(RuntimeError):
        proc.pousser(np.zeros(TRAME, np.float32), np.zeros(TRAME, np.float32))


def test_passthrough_sans_echo_preserve_la_voix():
    # Système muet → pas d'écho à caler → micro brut laissé passer (voix jamais perdue).
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    proc.demarrer()
    rng = np.random.default_rng(5)
    voix = rng.normal(0, 0.2, SR_AEC * 2).astype(np.float32)
    silence = np.zeros(SR_AEC * 2, dtype=np.float32)
    out = proc.pousser(voix, silence)
    assert not proc.calibre
    assert np.array_equal(out, voix)


def test_calibration_differee_puis_engagee():
    # Tranche sans écho → passthrough ; tranche avec écho corrélé → calibration.
    rng = np.random.default_rng(6)
    ref = rng.normal(0, 0.3, SR_AEC * 2).astype(np.float32)
    delai = 400
    echo = np.zeros_like(ref)
    echo[delai:] = ref[:-delai] * 0.5
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()

    voix = rng.normal(0, 0.2, SR_AEC).astype(np.float32)
    out1 = proc.pousser(voix, np.zeros(SR_AEC, np.float32))   # système muet
    assert not proc.calibre
    assert np.array_equal(out1, voix)                         # voix préservée

    proc.pousser(echo, ref)                                   # écho franc → calage
    assert proc.calibre
    assert abs(proc.delai_estime - delai) <= 2


def test_calibration_auto_mesure_le_delai():
    rng = np.random.default_rng(3)
    ref = rng.normal(0, 0.3, SR_AEC * 2).astype(np.float32)
    delai = 800
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai] * 0.5
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    proc.pousser(mic, ref)
    assert proc.calibre
    assert abs(proc.delai_estime - delai) <= 2


# ── e2e avec le vrai moteur AEC3 (LiveKit) sur écho synthétique ───────────────

@pytest.mark.integration
def test_attenuation_echo_e2e_livekit():
    # Marqué `integration` : le FFI Rust de LiveKit ne cohabite pas avec Qt/MLX dans
    # un même process (crash natif). À lancer isolément :
    #   pytest tests/test_aec.py -m integration
    pytest.importorskip("livekit")
    from scipy import signal

    rng = np.random.default_rng(42)
    n = SR_AEC * 8
    t = np.arange(n) / SR_AEC

    ref = rng.normal(0, 0.2, n).astype(np.float32)
    b, a = signal.butter(2, [300 / (SR_AEC / 2), 3400 / (SR_AEC / 2)], btype="band")
    ref = signal.lfilter(b, a, ref).astype(np.float32)
    ref *= 0.5 / (np.max(np.abs(ref)) or 1)

    delai = int(0.08 * SR_AEC)                    # écho retardé de 80 ms
    echo = np.zeros(n, np.float32)
    echo[delai:] = ref[:n - delai] * 0.25
    voix = np.zeros(n, np.float32)
    seg = t >= 4
    voix[seg] = (0.3 * np.sin(2 * np.pi * 220 * t[seg])).astype(np.float32)
    micro = echo + voix

    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC)   # délai auto, marge 40, LiveKit
    proc.demarrer()
    out = proc.pousser(micro, ref)

    # Fenêtre « écho seul » (avant la voix, après convergence) vs voix
    echo_net = _rms(out[int(SR_AEC * 1.5):int(SR_AEC * 3.0)])
    voix_net = _rms(out[int(SR_AEC * 5.0):int(SR_AEC * 7.0)])
    echo_brut = _rms(micro[int(SR_AEC * 1.5):int(SR_AEC * 3.0)])

    assert echo_net < echo_brut * 0.3             # forte atténuation de l'écho
    assert echo_net < SEUIL_RMS                   # sous le seuil anti-hallucination
    assert voix_net > 5 * echo_net                # la voix survit nettement


# ── Suivi continu du délai + alerte d'efficacité (docs/48 §4.2) ───────────────────

def _echo_decale(ref: np.ndarray, delai: int, gain: float = 0.5) -> np.ndarray:
    echo = np.zeros_like(ref)
    echo[delai:] = ref[:-delai] * gain
    return echo


def test_calibration_supporte_l_offset_d_ingestion_700ms():
    # docs/48 : le décalage inter-chaînes mesuré (700 ms) dépassait l'ancienne borne
    # de ±600 ms → verrou parasite. La borne élargie doit caler juste.
    rng = np.random.default_rng(7)
    delai = int(0.7 * SR_AEC)
    ref = rng.normal(0, 0.3, SR_AEC * 4).astype(np.float32)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    proc.pousser(_echo_decale(ref, delai), ref)
    assert proc.calibre
    assert abs(proc.delai_estime - delai) <= 2


def test_derive_declenche_un_realignement_confirme():
    # Écho à 400 éch pendant la calibration, puis brutalement à 2000 éch (dérive
    # cumulée > 80 ms) : après 2 mesures concordantes, le délai suivi rejoint 2000.
    rng = np.random.default_rng(11)
    ref = rng.normal(0, 0.3, SR_AEC * 60).astype(np.float32)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()

    d1, d2 = 400, 2000
    mic = np.concatenate([_echo_decale(ref, d1)[:SR_AEC * 24],
                          _echo_decale(ref, d2)[SR_AEC * 24:]])
    for debut in range(0, SR_AEC * 60, SR_AEC * 12):
        proc.pousser(mic[debut:debut + SR_AEC * 12], ref[debut:debut + SR_AEC * 12])

    assert proc.calibre
    assert abs(proc.delai_estime - d2) <= RECAL_SEUIL_ECH


def test_echo_residuel_persistant_emet_un_warning_unique(caplog):
    # Moteur identité = l'écho survit au nettoyage → au bout de 5 tranches où la
    # sortie reste corrélée à la référence, un WARNING (unique) est émis.
    import logging as _logging
    rng = np.random.default_rng(13)
    ref = rng.normal(0, 0.3, SR_AEC * 12 * 8).astype(np.float32)
    mic = _echo_decale(ref, 320)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    with caplog.at_level(_logging.WARNING, logger="debrief_meet.core.aec"):
        for debut in range(0, len(ref), SR_AEC * 12):
            proc.pousser(mic[debut:debut + SR_AEC * 12], ref[debut:debut + SR_AEC * 12])
    alertes = [r for r in caplog.records if "AEC inefficace" in r.getMessage()]
    assert len(alertes) == 1


def test_derive_residus_discordants_jamais_appliques(monkeypatch):
    # Terrain 2026-08-07 (poste de Alix) : des pics de bruit passaient la porte
    # qualité avec des résidus erratiques → 8 ré-alignements en 10 min, délai suivi
    # en fuite à -3,2 s. Deux mesures consécutives doivent CONCORDER pour agir.
    from debrief_meet.core import aec as aec_mod
    rng = np.random.default_rng(17)
    ref = rng.normal(0, 0.3, SR_AEC * 12 * 6).astype(np.float32)
    mic = _echo_decale(ref, 320)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    proc.pousser(mic[:SR_AEC * 12], ref[:SR_AEC * 12])        # calibration réelle
    delai_initial = proc.delai_estime

    valeurs = [+7000, -14000, +9000, -6000, +13000]           # erratiques 2 à 2
    appels = {"n": 0}

    def faux_caler(a, b, d):
        v = valeurs[appels["n"] % len(valeurs)]
        appels["n"] += 1
        return v, 50.0                                        # qualité forte : la porte passe

    monkeypatch.setattr(aec_mod, "_caler_delai", faux_caler)
    for i in range(1, 6):
        proc.pousser(mic[SR_AEC * 12 * i:SR_AEC * 12 * (i + 1)],
                     ref[SR_AEC * 12 * i:SR_AEC * 12 * (i + 1)])
    assert proc.delai_estime == delai_initial                 # aucun saut appliqué


def test_calibration_refusee_en_butee_de_fenetre(monkeypatch):
    # Un pic EN BUTÉE de la fenêtre de recherche = pic parasite dont le vrai sommet
    # est hors fenêtre (verrou à -1456 ms sur ±1500 observé le 2026-08-07) → différer.
    from debrief_meet.core import aec as aec_mod
    rng = np.random.default_rng(19)
    ref = rng.normal(0, 0.3, SR_AEC * 2).astype(np.float32)
    mic = rng.normal(0, 0.2, SR_AEC * 2).astype(np.float32)
    borne = int(aec_mod.DELAI_MAX_MS / 1000 * SR_AEC)
    monkeypatch.setattr(aec_mod, "_caler_delai", lambda a, b, d: (int(borne * 0.98), 50.0))
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    out = proc.pousser(mic, ref)
    assert not proc.calibre
    assert np.array_equal(out, mic)                           # passthrough : voix préservée
