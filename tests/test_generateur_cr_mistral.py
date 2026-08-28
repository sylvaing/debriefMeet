"""Tests — GestionnaireCRMistral (persistant, un seul job à la fois). Miroir de
`gestionnaire_diarization.py` : `core.mistral.pipeline.generer_cr_reunion` est
monkeypatché, aucun réseau réel."""
from __future__ import annotations

import threading
from pathlib import Path

from debrief_meet.core.mistral import pipeline
from debrief_meet.ui.generateur_cr_mistral import GestionnaireCRMistral


def test_disponible_faux_sans_cle(config_tmp):
    assert GestionnaireCRMistral(config_tmp).disponible() is False


def test_disponible_vrai_avec_cle(config_tmp):
    config_tmp.set("mistral_cle_api", "x")
    assert GestionnaireCRMistral(config_tmp).disponible() is True


def test_lancer_refuse_si_indisponible(config_tmp, tmp_path, qapp):
    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer(tmp_path / "reunion.md") is False
    assert g.job_en_cours() is None


def test_lancer_execute_le_pipeline_et_emet_termine(config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    md.write_text("# Réunion", encoding="utf-8")
    sortie_attendue = tmp_path / "reunion_CR.md"

    monkeypatch.setattr(pipeline, "generer_cr_reunion",
                        lambda chemin, config, prompt=None: sortie_attendue)

    g = GestionnaireCRMistral(config_tmp)
    termines = []
    g.termine.connect(lambda md, sortie: termines.append((md, sortie)))

    assert g.lancer(md) is True
    assert g.job_en_cours() == md

    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert termines == [(md, sortie_attendue)]


def test_lancer_echec_emet_echoue(config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"

    def _echoue(chemin, config, prompt=None):
        raise RuntimeError("clé invalide")

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _echoue)

    g = GestionnaireCRMistral(config_tmp)
    echecs = []
    g.echoue.connect(lambda md, message: echecs.append((md, message)))

    assert g.lancer(md) is True
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert echecs == [(md, "clé invalide")]


def test_lancer_transmet_le_prompt_ponctuel_au_pipeline(config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    recus = []

    def _capture(chemin, config, prompt=None):
        recus.append(prompt)
        return tmp_path / "sortie.md"

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _capture)

    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer(md, prompt="Rédige un CR détaillé :") is True
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert recus == ["Rédige un CR détaillé :"]


def test_lancer_refuse_si_job_deja_en_cours(config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md1 = tmp_path / "reunion1.md"
    md2 = tmp_path / "reunion2.md"

    peut_continuer = threading.Event()

    def _lente(chemin, config, prompt=None):
        peut_continuer.wait(timeout=5)
        return tmp_path / "sortie.md"

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _lente)

    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer(md1) is True
    assert g.job_en_cours() == md1

    assert g.lancer(md2) is False   # un job tourne déjà — refusé

    peut_continuer.set()
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)


def test_termine_emet_le_chemin_renomme_pendant_le_job(config_tmp, tmp_path, qapp, qtbot,
                                                       monkeypatch):
    """Le job renomme (indirectement) sa propre réunion : l'utilisateur l'associe à un
    événement BlueMind pendant la génération. Le signal doit porter le chemin réel, sinon
    la vue re-sélectionne une ligne qui n'existe plus."""
    from debrief_meet.core.fichiers import renommer_dossier_reunion

    config_tmp.set("mistral_cle_api", "x")
    dossier = tmp_path / "2026-08-26_16-20-54"
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text("# Réunion", encoding="utf-8")
    apres = {}

    def _genere(chemin, config, prompt=None):
        apres["md"] = renommer_dossier_reunion(md, "Point Acme")
        return apres["md"].with_name("CR.md")

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _genere)

    g = GestionnaireCRMistral(config_tmp)
    termines = []
    g.termine.connect(lambda md_, sortie: termines.append((md_, sortie)))

    assert g.lancer(md) is True
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)

    assert termines == [(apres["md"], apres["md"].with_name("CR.md"))]
