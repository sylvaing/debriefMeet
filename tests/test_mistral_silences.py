"""Tests unitaires — compaction des silences avant envoi à Voxtral (§10.2).

Cas de référence : la piste système d'une réunion PHYSIQUE, mesurée le 2026-08-18 chez
une utilisatrice — 19 s sonores sur 98 min, en 12 bips isolés de 1 à 2 s. Le contrat
central est qu'on ne perd JAMAIS d'audio : la compaction ne peut que retirer du silence,
et une intervention courte reste intégralement transcrite.
Pas de dépendance à ffmpeg : `subprocess.run` est mocké pour `compacter_piste`.
"""
from __future__ import annotations

import re

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


# ── Expression `aselect` : profondeur d'analyse (terrain 2026-09-07) ─────────────
#
# Une réunion de 93 min à 107 plages sortait en 244 sur les DEUX tentatives de CR :
# l'évaluateur de ffmpeg analyse `a+b+c` par récursion, un niveau par terme, et
# s'arrête à 100 (`STACK_SIZE` de libavutil/eval.c, mesuré). `MAX_PLAGES` en
# autorisant 120, toute piste de plus de 100 plages échouait — sur les 3 OS.

def test_expression_reste_plate_pour_une_piste_ordinaire():
    """Les parenthèses n'apparaissent que là où elles servent (lisibilité des logs)."""
    plages = tuple((float(i), float(i) + 0.5) for i in range(silences.TAILLE_GROUPE_EXPRESSION))
    expression = silences.expression_selection(plages)
    # `between(t,…)` a ses propres parenthèses : c'est le GROUPEMENT qu'on interdit ici.
    assert not expression.startswith("(") and ")+(" not in expression
    assert expression.count("between(t,") == len(plages)


def test_expression_groupee_au_dela_du_seuil():
    plages = tuple((float(i), float(i) + 0.5) for i in range(silences.TAILLE_GROUPE_EXPRESSION + 1))
    expression = silences.expression_selection(plages)
    assert expression.startswith("(") and ")+(" in expression


def test_groupement_ne_perd_ni_ne_reordonne_aucune_plage():
    """Le groupement est une réécriture : mêmes plages, même ordre, rien en plus."""
    plages = tuple((float(i) * 3, float(i) * 3 + 1) for i in range(107))
    trouvees = re.findall(r"between\(t,([\d.]+),([\d.]+)\)",
                          silences.expression_selection(plages))
    assert [(float(a), float(b)) for a, b in trouvees] == list(plages)


def test_profondeur_sous_la_limite_ffmpeg_au_pire_cas():
    """Garde-fou : `MAX_PLAGES` doit rester analysable par ffmpeg.

    La limite est invisible au code — elle ne se voit qu'à l'exécution, sur une
    piste assez découpée. Sans groupement, `MAX_PLAGES` (120) dépasse les 100
    niveaux : c'est exactement ce qui a été livré pendant des mois."""
    assert silences.MAX_PLAGES > silences.PROFONDEUR_EVAL_FFMPEG, (
        "si MAX_PLAGES repassait sous la limite, ce garde-fou ne prouverait plus rien"
    )
    assert silences.profondeur_expression(silences.MAX_PLAGES) < silences.PROFONDEUR_EVAL_FFMPEG


def test_compacter_groupe_l_expression_de_beaucoup_de_plages(tmp_path, monkeypatch):
    """Le groupement traverse bien jusqu'à la ligne de commande réellement passée."""
    monkeypatch.setattr(silences, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    commandes: list[list[str]] = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: commandes.append(cmd))
    source = tmp_path / "systeme.opus"
    source.write_bytes(b"audio")
    plages = tuple((float(i) * 3, float(i) * 3 + 1) for i in range(107))

    silences.compacter_piste(source, tmp_path, PlanCompaction(plages, duree_totale_s=5563.0))

    filtre = commandes[0][commandes[0].index("-af") + 1]
    assert filtre.startswith("aselect='(") and filtre.endswith("',asetpts=N/SR")
    assert filtre.count("between(t,") == 107
