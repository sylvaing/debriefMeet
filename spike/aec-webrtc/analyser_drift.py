#!/usr/bin/env python
"""
Spike AEC WebRTC — Étape 2 : analyse temps réel d'une session longue.

À partir d'une session longue alternée (`enregistrer.py --cycles N`), répond à
l'inconnue décisive du §7 : **la dérive d'horloge micro↔système sur la durée
fait-elle réapparaître l'écho en fin de session ?**

Méthode :
  1. Hint de délai initial = cross-corrélation sur le clap (UNE fois, comme un
     calage de démarrage temps réel — pas de ré-alignement par fenêtre ensuite).
  2. Courbe délai(t) sur toute la session → taux de dérive (ms/min).
  3. Passe AEC (LiveKit AEC3, NS off) avec ce seul hint → l'estimateur interne
     d'AEC3 doit absorber la dérive.
  4. RMS écho résiduel pour CHAQUE phase « participants seuls », du début à la
     fin → la suppression tient-elle dans la durée ?

GO si l'écho résiduel reste sous le seuil sur TOUTES les phases (début → fin).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).parent))
import traiter_offline as t  # noqa: E402


def courbe_delai(mic: np.ndarray, ref: np.ndarray, fenetre_s: float = 2.0,
                 pas_s: float = 4.0) -> list[tuple[float, float]]:
    """Liste de (centre_s, délai_ms) par cross-corrélation glissante (bornée)."""
    n = min(len(mic), len(ref))
    taille = int(fenetre_s * t.SR_CIBLE)
    pas = int(pas_s * t.SR_CIBLE)
    delai_max = int(t.DELAI_MAX_MS / 1000 * t.SR_CIBLE)
    points = []
    for d in range(0, n - taille, pas):
        a = mic[d:d + taille] - mic[d:d + taille].mean()
        b = ref[d:d + taille] - ref[d:d + taille].mean()
        lag = t._meilleur_lag(a, b, delai_max)
        points.append(((d + taille / 2) / t.SR_CIBLE, lag / t.SR_CIBLE * 1000))
    return points


def taux_derive_ms_min(points: list[tuple[float, float]]) -> float:
    """Pente (ms/min) d'un ajustement linéaire de délai(t)."""
    if len(points) < 2:
        return 0.0
    ts = np.array([p[0] for p in points])
    ds = np.array([p[1] for p in points])
    pente_ms_s = np.polyfit(ts, ds, 1)[0]
    return float(pente_ms_s * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Spike AEC WebRTC — analyse dérive temps réel")
    ap.add_argument("--micro", type=Path, required=True)
    ap.add_argument("--systeme", type=Path, required=True)
    ap.add_argument("--phases", type=Path, required=True)
    ap.add_argument("--sortie", type=Path, default=Path("moi_nettoye_live.wav"))
    args = ap.parse_args()

    mic = t.lire_wav_mono16k(args.micro)
    ref = t.lire_wav_mono16k(args.systeme)
    phases = t.charger_phases(args.phases)
    duree = min(len(mic), len(ref)) / t.SR_CIBLE
    print(f"Session : {duree:.0f}s · {len([p for p in phases if p.nom=='participants_seuls'])} "
          f"phases « participants seuls »")

    # 1. Hint initial (calage de démarrage, une seule fois)
    delai0 = t.estimer_delai(mic, ref)
    print(f"Hint délai initial (clap) : {delai0} éch. ({delai0/t.SR_CIBLE*1000:.0f} ms)")

    # 2. Courbe de dérive sur toute la session
    pts = courbe_delai(mic, ref)
    derive_ms_min = taux_derive_ms_min(pts)
    delais_ms = [p[1] for p in pts]

    # 3. Passe AEC « temps réel » : un seul alignement initial (+ marge lead pour
    #    le filtre causal d'AEC3, cf. MARGE_LEAD_AEC_MS), puis AEC3 suit la dérive.
    mic_a, ref_a = t.aligner_pour_aec(mic, ref, delai0)
    mic_net, facteur = t.appliquer_aec(mic_a, ref_a, ns=False)
    t.ecrire_wav_mono16k(args.sortie, mic_net)

    # 4. RMS écho par phase « participants seuls », dans l'ordre temporel
    lignes = []
    tout_sous = True
    for p in sorted([p for p in phases if p.nom == "participants_seuls"], key=lambda p: p.debut):
        brut = t.extraire(mic_a, p)
        net = t.extraire(mic_net, p)
        if not len(net):
            continue
        rb, rn = t.rms(brut), t.rms(net)
        att = t.db(rn / rb) if rb else float("nan")
        sous = rn < t.SEUIL_RMS
        tout_sous = tout_sous and sous
        lignes.append((p.debut, rb, rn, att, sous))

    # ── Rapport ──
    l = print
    l("\n" + "=" * 70)
    l("RAPPORT ÉTAPE 2 — temps réel / dérive")
    l("=" * 70)
    l(f"\n[COÛT] facteur temps réel AEC : {facteur:.3f}×")
    l("\n[DÉRIVE D'HORLOGE micro↔système]")
    if delais_ms:
        l(f"  délai sur la session : min={min(delais_ms):.0f} max={max(delais_ms):.0f} ms "
          f"(étendue {max(delais_ms)-min(delais_ms):.0f} ms)")
        l(f"  taux de dérive       : {derive_ms_min:+.1f} ms/min")
    l("\n[SUPPRESSION ÉCHO PAR PHASE — début → fin de session]")
    l(f"  {'t (s)':>7}  {'RMS brut':>9}  {'RMS net':>9}  {'att (dB)':>8}  verdict")
    for deb, rb, rn, att, sous in lignes:
        l(f"  {deb:7.1f}  {rb:9.5f}  {rn:9.5f}  {att:8.1f}  "
          f"{'✓ sous seuil' if sous else '✗ AU-DESSUS'}")
    l(f"\n  seuil anti-hallucination : {t.SEUIL_RMS:.5f}")

    # Verdict : suppression maintenue partout. La dérive est tolérée si l'écho
    # reste sous le seuil malgré elle (c'est le seul juge qui compte).
    l("\n" + "-" * 70)
    if tout_sous and lignes:
        l("→ ✅ GO temps réel : écho sous le seuil du DÉBUT à la FIN.")
        l(f"   Dérive {max(delais_ms)-min(delais_ms):.0f} ms sur la session ({derive_ms_min:+.1f} ms/min) "
          "— absorbée par AEC3.")
    elif lignes:
        n_sup = sum(1 for *_, sous in lignes if not sous)
        l(f"→ ❌ NO-GO temps réel : écho au-dessus du seuil sur {n_sup}/{len(lignes)} phases.")
        l(f"   (Dérive = {max(delais_ms)-min(delais_ms):.0f} ms, négligeable → cause à chercher "
          "ailleurs : alignement/convergence, pas la dérive.)")
    else:
        l("→ ⚠️ aucune phase « participants seuls » exploitable.")
    l("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
