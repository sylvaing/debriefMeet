"""Tests unitaires — compaction des silences avant envoi à Voxtral (§10.2).

Cas de référence : la piste système d'une réunion PHYSIQUE, mesurée le 2026-08-18 chez
une utilisatrice — 19 s sonores sur 98 min, en 12 bips isolés de 1 à 2 s. Le contrat
central est qu'on ne perd JAMAIS d'audio : la compaction ne peut que retirer du silence,
et une intervention courte reste intégralement transcrite.
Pas de dépendance à ffmpeg : `subprocess.run` est mocké pour `compacter_piste`.
"""
from __future__ import annotations

import numpy as np
import pytest

from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable
from debrief_meet.core.mistral import silences
from debrief_meet.core.mistral.silences import PlanCompaction, plan_compaction

SR = 16_000


def _piste(evenements: list[tuple[float, float]], duree_s: float, niveau: float = 0.05):
    """Piste de `duree_s` silencieuse, sonore sur chaque (début, durée) donné."""
    audio = np.zeros(int(duree_s * SR), dtype=np.float32)
    for debut, duree in evenements:
        bruit = np.full(int(duree * SR), niveau, dtype=np.float32)
        audio[int(debut * SR):int(debut * SR) + len(bruit)] = bruit
    return audio


# ── Détection des plages ─────────────────────────────────────────────────────────

def test_piste_quasi_vide_de_reunion_physique_est_compactable():
    # 12 bips de 2 s répartis sur 20 min — le cas terrain, en réduction.
    audio = _piste([(60.0 * i + 10, 2.0) for i in range(12)], duree_s=20 * 60)
    plan = plan_compaction(audio)

    assert len(plan.plages) == 12
    assert plan.utile
    # Chaque bip garde 2 s + 1 s de marge de chaque côté, arrondi à la tranche.
    assert plan.duree_gardee_s == pytest.approx(12 * 4.0, abs=12.0)
    assert plan.duree_gardee_s < 0.05 * plan.duree_totale_s


def test_piste_normalement_parlee_part_telle_quelle():
    audio = _piste([(0.0, 300.0)], duree_s=300.0)
    plan = plan_compaction(audio)

    assert plan.utile is False, "une piste pleine de parole ne doit pas être ré-encodée"
    assert plan.duree_gardee_s == pytest.approx(plan.duree_totale_s, abs=2.0)


def test_intervention_courte_conservee_entierement():
    """Le point qui a fait rejeter un critère de proportion : 1 min de visio dans une
    réunion de 98 min ne pèse que 0,6 % — elle doit malgré tout être transcrite."""
    audio = _piste([(3000.0, 60.0)], duree_s=98 * 60)
    plan = plan_compaction(audio)

    assert plan.utile
    assert plan.duree_gardee_s >= 60.0, "toute la minute de parole doit être gardée"
    debut, fin = plan.plages[0]
    assert debut <= 3000.0 and fin >= 3060.0, "marge de sécurité autour de la parole"


def test_plages_proches_fusionnees():
    # Deux bips séparés de 2 s (< FUSION_S) : une seule plage, le court silence gardé.
    audio = _piste([(10.0, 1.0), (13.0, 1.0)], duree_s=120.0)
    assert len(plan_compaction(audio).plages) == 1


def test_piste_entierement_silencieuse_ne_donne_aucune_plage():
    plan = plan_compaction(np.zeros(10 * SR, dtype=np.float32))
    assert plan.plages == ()
    assert plan.utile is False


def test_piste_vide():
    plan = plan_compaction(np.zeros(0, dtype=np.float32))
    assert plan.plages == ()
    assert plan.duree_totale_s == 0.0


def test_piste_plus_courte_que_le_pas_est_gardee_entiere():
    plan = plan_compaction(np.full(SR // 2, 0.05, dtype=np.float32))
    assert plan.plages == ((0.0, pytest.approx(0.5)),)


def test_trop_de_plages_declenche_une_fusion_plus_large_sans_perdre_d_audio():
    # 300 bips espacés de 10 s : au-delà de MAX_PLAGES on élargit la fusion, ce qui
    # ne peut qu'ajouter du silence gardé — jamais retirer du son.
    audio = _piste([(10.0 * i + 5, 1.0) for i in range(300)], duree_s=3200.0)
    plan = plan_compaction(audio)

    assert len(plan.plages) <= silences.MAX_PLAGES
    couvert = sum(
        1 for i in range(300)
        if any(d <= 10.0 * i + 5 and f >= 10.0 * i + 6 for d, f in plan.plages))
    assert couvert == 300, "chaque bip doit rester couvert par une plage"


# ── Remise des horodatages dans la timeline d'origine ────────────────────────────

def test_vers_original_replace_les_instants():
    plan = PlanCompaction(plages=((10.0, 20.0), (100.0, 130.0)), duree_totale_s=200.0)

    assert plan.vers_original(0.0) == 10.0       # début de la 1re plage
    assert plan.vers_original(5.0) == 15.0       # au milieu de la 1re
    assert plan.vers_original(10.0) == 20.0      # jointure
    assert plan.vers_original(15.0) == 105.0     # dans la 2e plage
    assert plan.vers_original(40.0) == 130.0     # au-delà : borné à la fin


def test_vers_original_sans_plage_est_neutre():
    assert PlanCompaction(plages=(), duree_totale_s=10.0).vers_original(3.0) == 3.0


# ── compacter_piste (ffmpeg mocké) ──────────────────────────────────────────────

def test_compacter_leve_si_ffmpeg_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(silences, "chemin_ffmpeg", lambda: None)
    source = tmp_path / "systeme.opus"
    source.write_bytes(b"audio")
    plan = PlanCompaction(plages=((1.0, 2.0),), duree_totale_s=100.0)

    with pytest.raises(ErreurFfmpegIntrouvable):
        silences.compacter_piste(source, tmp_path, plan)


def test_compacter_construit_le_filtre_aselect(tmp_path, monkeypatch):
    monkeypatch.setattr(silences, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    commandes: list[list[str]] = []

    def _run(cmd, **kwargs):
        commandes.append(cmd)
        # `compacter_piste` renvoie le chemin ; le contenu n'importe pas ici.
        return None

    monkeypatch.setattr("subprocess.run", _run)
    source = tmp_path / "systeme.opus"
    source.write_bytes(b"audio")
    plan = PlanCompaction(plages=((10.0, 12.5), (100.0, 101.0)), duree_totale_s=200.0)

    sortie = silences.compacter_piste(source, tmp_path, plan)

    assert sortie.name == "systeme_compacte.opus"
    # Deux passes : sélection vers un WAV, puis encodage Opus. Tout faire d'un coup
    # produit un Ogg dont l'en-tête annonce une durée absurde (0,08 s pour 38 s).
    assert len(commandes) == 2
    filtre = commandes[0][commandes[0].index("-af") + 1]
    # Apostrophes obligatoires : sans elles ffmpeg lirait les virgules de `between`
    # comme des séparateurs de filtres.
    assert filtre == "aselect='between(t,10.000,12.500)+between(t,100.000,101.000)',asetpts=N/SR"
    assert commandes[0][-1].endswith("_compacte.wav") and "16000" in commandes[0]
    assert "libopus" in commandes[1] and commandes[1][-1].endswith("_compacte.opus")
