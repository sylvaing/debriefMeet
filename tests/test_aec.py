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
    RECALIBRAGES_AUTO_MAX,
    SAUT_OFFSET_ECH,
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


class _Attenue(MoteurAEC):
    """Atténue tout de ~26 dB — figure une AEC qui fait son travail."""

    def traiter_trame(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        return (near.astype(np.float32) * 0.05).astype(np.int16)


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


def test_echo_residuel_persistant_alerte_et_recale(caplog):
    # Moteur identité = l'écho survit au nettoyage → au bout de 5 tranches où la
    # sortie reste corrélée à la référence, un WARNING est émis (une seule fois par
    # cycle, pas à chaque tranche) et il annonce le recalage complet de l'alignement.
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
    assert "recalage complet" in alertes[0].getMessage()
    assert proc._recalibrages_auto == 1


def test_derive_residus_discordants_jamais_appliques(monkeypatch):
    # Terrain 2026-08-07 (poste de Alix) : des pics de bruit passaient la porte
    # qualité avec des résidus erratiques → 8 ré-alignements en 10 min, délai suivi
    # en fuite à -3,2 s. Deux mesures consécutives doivent CONCORDER pour agir.
    from debrief_meet.core import aec as aec_mod
    rng = np.random.default_rng(17)
    ref = rng.normal(0, 0.3, SR_AEC * 12 * 6).astype(np.float32)
    mic = _echo_decale(ref, 320)
    # Moteur qui ATTÉNUE : sur le terrain l'AEC de Alix marchait (−14 dB), c'est le seul
    # suivi de dérive qui partait en fuite. Avec un moteur identité, l'inefficacité
    # constatée déclencherait — à raison — un recalage complet (cf. test dédié), et ce
    # test-ci ne parlerait plus de ce qu'il documente.
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Attenue())
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


def test_attenuation_forte_n_emet_pas_d_alerte(caplog):
    # Terrain 2026-08-10 : WARNING émis avec −14 dB d'atténuation — un écho bien
    # annulé laisse un résidu corrélé détectable, la corrélation seule ne suffit pas.
    import logging as _logging

    rng = np.random.default_rng(23)
    ref = rng.normal(0, 0.3, SR_AEC * 12 * 8).astype(np.float32)
    mic = _echo_decale(ref, 320)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Attenue())
    proc.demarrer()
    with caplog.at_level(_logging.WARNING, logger="debrief_meet.core.aec"):
        for debut in range(0, len(ref), SR_AEC * 12):
            proc.pousser(mic[debut:debut + SR_AEC * 12], ref[debut:debut + SR_AEC * 12])
    assert not [r for r in caplog.records if "AEC inefficace" in r.getMessage()]


class _SoustractionAlignee(MoteurAEC):
    """Annule l'écho par simple soustraction de la référence — donc SEULEMENT si
    l'appelant a correctement aligné les deux flux. Un délai calé qui se périme laisse
    l'écho passer intact, exactement comme AEC3 sur le terrain du 2026-08-18."""

    def traiter_trame(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        return (near.astype(np.int32) - (far.astype(np.int32) // 2)).astype(np.int16)


def test_inefficacite_declenche_un_recalage_qui_retrouve_le_nouveau_delai(caplog, monkeypatch):
    """Terrain 2026-08-18 : délai calé à 383 ms (= l'offset d'ingestion du moment), trajet
    d'écho réel passé à ~30 ms → l'AEC ne soustrayait plus rien (−0,2 dB) pendant 22 min.
    Le recalage déclenché par l'inefficacité doit retrouver le nouveau délai d'un coup et
    l'annulation doit repartir.

    Le suivi de dérive est neutralisé ici : c'est justement le cas où il n'a pas convergé
    (2 ré-alignements en 20 min sur ~400 ms d'écart, log du 2026-08-18). Sur du bruit
    blanc synthétique il rattraperait en 2 tranches et masquerait ce qu'on teste."""
    import logging as _logging
    monkeypatch.setattr(ProcesseurAEC, "_suivre_alignement", lambda self: None)
    rng = np.random.default_rng(29)
    ref = rng.normal(0, 0.3, SR_AEC * 12 * 12).astype(np.float32)
    d1, d2 = 6135, 480                      # 383 ms → 30 ms : les valeurs mesurées
    bascule = SR_AEC * 12 * 3
    mic = np.concatenate([_echo_decale(ref, d1)[:bascule], _echo_decale(ref, d2)[bascule:]])
    mic += rng.normal(0, 0.001, len(mic)).astype(np.float32)   # plancher de bruit réaliste

    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         moteur=_SoustractionAlignee())
    proc.demarrer()
    proc.pousser(mic[:bascule], ref[:bascule])                # calibration sur l'écho à d1
    assert abs(proc.delai_estime - d1) <= 2
    assert proc.derniere_attenuation_db < -20                 # annulation effective

    with caplog.at_level(_logging.WARNING, logger="debrief_meet.core.aec"):
        for debut in range(bascule, len(ref), SR_AEC * 12):
            proc.pousser(mic[debut:debut + SR_AEC * 12], ref[debut:debut + SR_AEC * 12])

    recalages = [r for r in caplog.records if "recalage complet" in r.getMessage()]
    assert len(recalages) == 1                                # une réaction, pas une rafale
    assert abs(proc.delai_estime - d2) <= 2                   # nouveau délai retrouvé d'un coup
    assert proc.derniere_attenuation_db < -20                 # l'annulation est repartie


def test_recalages_automatiques_bornes(caplog):
    """Un écho que l'alignement ne peut pas régler (ici : moteur identité) ne doit pas
    faire recaler en boucle — chaque recalage jette du micro. Au-delà du budget, un
    WARNING terminal et plus rien."""
    import logging as _logging
    rng = np.random.default_rng(31)
    tranches = 6 * (RECALIBRAGES_AUTO_MAX + 2)       # de quoi épuiser le budget et au-delà
    ref = rng.normal(0, 0.3, SR_AEC * 12 * tranches).astype(np.float32)
    mic = _echo_decale(ref, 320)
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    with caplog.at_level(_logging.WARNING, logger="debrief_meet.core.aec"):
        for debut in range(0, len(ref), SR_AEC * 12):
            proc.pousser(mic[debut:debut + SR_AEC * 12], ref[debut:debut + SR_AEC * 12])

    messages = [r.getMessage() for r in caplog.records if "AEC inefficace" in r.getMessage()]
    assert sum("recalage complet" in m for m in messages) == RECALIBRAGES_AUTO_MAX
    assert sum("recalage automatique abandonné" in m for m in messages) == 1
    assert messages[-1] == [m for m in messages if "abandonné" in m][0]   # terminal = dernier
    assert proc._recalibrages_auto == RECALIBRAGES_AUTO_MAX
    # L'offset ne bouge pas ici (écho à délai constant) : l'écho est bien acoustique,
    # donc le message acoustique est le bon et l'AEC continue de traiter.
    assert not any("DÉSACTIVÉE" in r.getMessage() for r in caplog.records)
    assert proc._abandonne is False


def test_recalibrer_manuel_reouvre_le_budget_de_recalages():
    """Un switch de micro à chaud = chemin d'écho réellement neuf : le budget consommé
    par la session précédente ne doit pas condamner le nouveau."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         delai_ms=0, moteur=_Identite())
    proc.demarrer()
    proc._recalibrages_auto = RECALIBRAGES_AUTO_MAX
    proc.recalibrer()
    assert proc._recalibrages_auto == 0


def test_demarrer_reouvre_le_budget_de_recalages():
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         delai_ms=0, moteur=_Identite())
    proc.demarrer()
    proc._recalibrages_auto = RECALIBRAGES_AUTO_MAX
    proc.demarrer()
    assert proc._recalibrages_auto == 0


# ── Délais qui ne concordent pas : deux causes opposées, deux verdicts ────────────
#
# Terrain 2026-08-26 (Windows, micro sous MME) : 4 calages à +11240, −9765, −19427,
# −11802 éch sur une même réunion. L'AEC courait après une cible qui bougeait plus vite
# qu'elle, finissait à −0,3 dB, et concluait « casque recommandé » à une utilisatrice qui
# en portait un. D'où le premier garde-fou : « flux non synchronisables ».
#
# Terrain 2026-08-27 (même poste, casque Bluetooth) : des calages tout aussi erratiques
# (−188, −12523, −6725, −6913 éch, 771 ms d'écart) — mais cette fois les durées livrées
# par tranche ne bougeaient que de ±70 ms. Les pistes étaient alignées : c'est la MESURE
# du délai qui tirait au hasard, faute d'écho à verrouiller (casque fermé). Le garde-fou
# accusait donc une perte d'échantillons inexistante. Les deux tests ci-dessous figent
# les deux cas, et c'est le déplacement RÉEL de l'offset qui les sépare.

def _pousser_par_tranches(proc, mic, ref, secondes=12):
    pas = SR_AEC * secondes
    for debut in range(0, len(ref), pas):
        proc.pousser(mic[debut:debut + pas], ref[debut:debut + pas])


def _mic_a_delai_alternant(ref, tranches, pas, saut=int(0.7 * SR_AEC)):
    """Micro dont le délai d'écho ALTERNE de `saut` toutes les 6 tranches — au lieu du
    délai constant du test de bornage. Alterner plutôt que croître, comme sur le terrain
    (des sauts dans les deux sens) : une croissance monotone finirait par sortir de
    ±DELAI_MAX_MS et ne se recalerait plus du tout."""
    mic = np.zeros_like(ref)
    for i in range(tranches):
        delai = 400 if (i // 6) % 2 == 0 else 400 + saut
        bloc = ref[i * pas:(i + 1) * pas]
        mic[i * pas:(i + 1) * pas] = _echo_decale(bloc, delai)
    return mic


def test_delais_erratiques_sans_deplacement_reel_ne_condamnent_pas_les_flux(caplog):
    """Terrain 2026-08-27 : les calages ne concordent pas, mais les deux pistes livrent
    autant d'échantillons l'une que l'autre — elles ne se sont donc pas désynchronisées.
    Il n'y a rien à annuler (casque fermé) : verdict en INFO, sans accuser les flux ni
    conseiller un casque à quelqu'un qui en porte un."""
    import logging as _logging
    rng = np.random.default_rng(101)
    tranches = 6 * (RECALIBRAGES_AUTO_MAX + 4)
    pas = SR_AEC * 12
    ref = rng.normal(0, 0.3, pas * tranches).astype(np.float32)
    mic = _mic_a_delai_alternant(ref, tranches, pas)

    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    with caplog.at_level(_logging.INFO, logger="debrief_meet.core.aec"):
        _pousser_par_tranches(proc, mic, ref)   # tranches micro et système de même taille

    messages = [r.getMessage() for r in caplog.records]
    verdicts = [m for m in messages if "AEC sans objet" in m]
    assert len(verdicts) == 1
    assert "aucun écho à annuler" in verdicts[0]
    assert not any("DÉSACTIVÉE" in m for m in messages)
    assert not any("casque recommandé" in m for m in messages)
    # Le verdict est en INFO : rien d'anormal ne s'est produit, le log rotatif du terrain
    # n'a pas à porter un WARNING pour une configuration parfaitement saine.
    assert all(r.levelno < _logging.WARNING
               for r in caplog.records if "AEC sans objet" in r.getMessage())
    assert proc._abandonne is True             # on cesse quand même de traiter pour rien
    assert proc._abandon_confirme is False
    assert "aucun écho à annuler" in proc.bilan()


def test_saut_confirme_par_les_longueurs_livrees_condamne_bien_les_flux(caplog):
    """Terrain 2026-08-26 : même désaccord entre calages, mais la piste micro arrive
    AMPUTÉE — des échantillons perdus que rien ne compense. Là, le déplacement de
    l'offset est réel et le verdict « flux non synchronisables » est le bon."""
    import logging as _logging
    rng = np.random.default_rng(101)
    tranches = 6 * (RECALIBRAGES_AUTO_MAX + 4)
    pas = SR_AEC * 12
    saut = int(0.7 * SR_AEC)
    ref = rng.normal(0, 0.3, pas * tranches).astype(np.float32)
    mic = _mic_a_delai_alternant(ref, tranches, pas, saut)

    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0, moteur=_Identite())
    proc.demarrer()
    with caplog.at_level(_logging.INFO, logger="debrief_meet.core.aec"):
        # À chaque changement de délai, la tranche micro livre `saut` échantillons de
        # moins (ou de plus) : c'est la signature d'une perte de paquets non compensée,
        # et c'est ce qui manquait au cas du casque.
        for i in range(tranches):
            tranche_mic = mic[i * pas:(i + 1) * pas]
            if i % 6 == 0 and i:
                tranche_mic = (tranche_mic[:-saut] if (i // 6) % 2
                               else np.concatenate([tranche_mic, tranche_mic[:saut]]))
            proc.pousser(tranche_mic, ref[i * pas:(i + 1) * pas])

    messages = [r.getMessage() for r in caplog.records]
    desactivations = [m for m in messages if "DÉSACTIVÉE" in m]
    assert len(desactivations) == 1
    assert "ne sont pas synchronisables" in desactivations[0]
    assert "casque n'y changerait rien" in desactivations[0]
    assert "longueurs livrées" in desactivations[0]      # la preuve est citée
    assert not any("casque recommandé" in m for m in messages)
    assert not any("AEC sans objet" in m for m in messages)
    assert proc._abandonne is True
    assert proc._abandon_confirme is True
    assert "flux non synchronisables" in proc.bilan()


def test_abandon_rend_le_micro_brut_sans_appeler_le_moteur():
    """Abdiquer, c'est laisser passer la voix telle quelle — et ne plus consommer les
    ~0,2 s de calcul par tranche qui tenaient le GIL (or c'est cette famine qui fait
    perdre les échantillons, docs/48 §8 : renoncer réduit la cause)."""
    class _Compteur(MoteurAEC):
        def __init__(self):
            self.appels = 0

        def traiter_trame(self, near, far):
            self.appels += 1
            return near.copy()

    moteur = _Compteur()
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         delai_ms=0, moteur=moteur)
    proc.demarrer()
    proc._abandonne = True
    micro = np.random.default_rng(5).normal(0, 0.2, TRAME * 10).astype(np.float32)

    sortie = proc.pousser(micro, np.zeros_like(micro))

    assert np.array_equal(sortie, micro)      # bit pour bit, aucun traitement
    assert moteur.appels == 0


def test_offset_observe_compte_meme_quand_l_aec_a_renonce():
    """Les pistes continuent d'arriver après l'abandon. Si la mesure s'arrêtait là, un
    `recalibrer()` en cours de session repartirait sur un offset faussement figé."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         delai_ms=0, moteur=_Identite())
    proc.demarrer()
    proc._abandonne = True
    micro = np.zeros(TRAME * 10, dtype=np.float32)

    proc.pousser(micro, np.zeros(TRAME * 4, dtype=np.float32))

    assert proc._cumul_ecart_ech == TRAME * 6


def test_saut_offset_mesure_entre_calages_consecutifs_pas_en_cumul():
    """Une dérive lente qui finit par cumuler plus que le seuil ne doit PAS être prise
    pour un saut : la dérive lente, `_suivre_alignement` sait la rattraper."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    pas = SAUT_OFFSET_ECH // 4                      # chaque pas est sous le seuil…
    proc._delais_calages = [i * pas for i in range(6)]   # …mais le cumul le dépasse
    proc._ecarts_calages = [0] * 6
    assert proc._saut_offset_max() is None

    proc._delais_calages = [0, SAUT_OFFSET_ECH + 1]     # un seul vrai saut suffit
    proc._ecarts_calages = [0, 0]
    assert proc._saut_offset_max() == (SAUT_OFFSET_ECH + 1, 0)


def test_saut_offset_rend_le_deplacement_reel_du_pire_intervalle():
    """Le déplacement rendu est celui de l'intervalle où les délais divergent le plus —
    pas un cumul de session : c'est LUI qui dit si les pistes ont bougé à ce moment-là."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    proc._delais_calages = [0, 500, 500 + 4 * SAUT_OFFSET_ECH, 500 + 4 * SAUT_OFFSET_ECH]
    # L'offset a beaucoup bougé AVANT le pire écart de délais, et rien pendant.
    proc._ecarts_calages = [0, 9 * SAUT_OFFSET_ECH, 9 * SAUT_OFFSET_ECH, 0]

    ecart, deplacement = proc._saut_offset_max()

    assert ecart == 4 * SAUT_OFFSET_ECH
    assert deplacement == 0


def test_un_seul_calage_ne_conclut_rien():
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, moteur=_Identite())
    proc._delais_calages = [12345]
    proc._ecarts_calages = [0]
    assert proc._saut_offset_max() is None


def test_demarrer_et_recalibrer_rearment_l_abandon():
    """Session neuve ou micro réellement changé : les offsets d'avant ne condamnent pas
    la suite (et comparer les calages de DEUX périphériques ferait crier au saut)."""
    proc = ProcesseurAEC(sr_micro=SR_AEC, sr_systeme=SR_AEC, marge_lead_ms=0,
                         delai_ms=0, moteur=_Identite())
    proc.demarrer()
    proc._abandonne = True
    proc._abandon_confirme = True
    proc._delais_calages = [0, 99999]
    proc._ecarts_calages = [0, 99999]
    proc._cumul_ecart_ech = 99999

    proc.recalibrer()
    assert proc._abandonne is False
    assert proc._abandon_confirme is False
    assert proc._delais_calages == []
    # L'offset observé repart de zéro avec les calages : un cumul hérité d'AVANT le
    # changement de micro ferait conclure à un déplacement réel qui n'a pas eu lieu.
    assert proc._ecarts_calages == []
    assert proc._cumul_ecart_ech == 0

    proc._abandonne = True
    proc._delais_calages = [0, 99999]
    proc._ecarts_calages = [0, 99999]
    proc._cumul_ecart_ech = 99999
    proc.demarrer()
    assert proc._abandonne is False
    assert proc._delais_calages == []
    assert proc._ecarts_calages == []
    assert proc._cumul_ecart_ech == 0
