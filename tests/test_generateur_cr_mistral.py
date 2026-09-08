"""Tests — GestionnaireCRMistral (persistant, un seul job à la fois). Miroir de
`gestionnaire_diarization.py` : `core.mistral.pipeline.generer_cr_reunion` est
monkeypatché, aucun réseau réel."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from debrief_meet.core.mistral import pipeline
from debrief_meet.core.mistral.client import ErreurMistral
from debrief_meet.ui.generateur_cr_mistral import (
    TACHE_TRANSCRIPTION,
    GestionnaireCRMistral,
)


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


# ── Transcription distante seule (sans CR) ─────────────────────────────────────

def test_lancer_transcription_appelle_le_pipeline_de_transcription(
        config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    appels = []
    monkeypatch.setattr(pipeline, "transcrire_reunion",
                        lambda chemin, config: appels.append(chemin) or chemin)
    # Le CR ne doit PAS être appelé : c'est toute la différence entre les deux tâches.
    monkeypatch.setattr(pipeline, "generer_cr_reunion",
                        lambda *a, **k: pytest.fail("le CR ne doit pas être rédigé"))

    g = GestionnaireCRMistral(config_tmp)
    termines = []
    g.transcription_terminee.connect(lambda md_, sortie: termines.append((md_, sortie)))

    assert g.lancer_transcription(md) is True
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert appels == [md]
    assert termines == [(md, md)]


def test_transcription_emet_sa_propre_paire_pas_celle_du_cr(
        config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    """Les deux tâches ne s'annoncent pas de la même façon : l'Historique ouvre
    `transcription.md` dans un cas et `CR.md` dans l'autre."""
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    monkeypatch.setattr(pipeline, "transcrire_reunion", lambda chemin, config: chemin)

    g = GestionnaireCRMistral(config_tmp)
    cr, transcription = [], []
    g.termine.connect(lambda *a: cr.append(a))
    g.transcription_terminee.connect(lambda *a: transcription.append(a))

    g.lancer_transcription(md)
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert len(transcription) == 1
    assert cr == []


def test_transcription_echouee_emet_sa_propre_paire(
        config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"

    def _echoue(chemin, config):
        raise RuntimeError("503 persistant")

    monkeypatch.setattr(pipeline, "transcrire_reunion", _echoue)

    g = GestionnaireCRMistral(config_tmp)
    echecs_cr, echecs_transcription = [], []
    g.echoue.connect(lambda *a: echecs_cr.append(a))
    g.transcription_echouee.connect(lambda md_, msg: echecs_transcription.append((md_, msg)))

    g.lancer_transcription(md)
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    assert echecs_transcription == [(md, "503 persistant")]
    assert echecs_cr == []


def test_tache_en_cours_distingue_les_deux_operations(
        config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    demarrees = threading.Event()

    def _lent(chemin, config):
        demarrees.wait(5)
        return chemin

    monkeypatch.setattr(pipeline, "transcrire_reunion", _lent)

    g = GestionnaireCRMistral(config_tmp)
    assert g.tache_en_cours() is None
    g.lancer_transcription(md)
    assert g.tache_en_cours() == TACHE_TRANSCRIPTION
    demarrees.set()
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)
    # Remise à None avec le job : une tâche qui survivrait au job collerait son icône
    # à une ligne inactive.
    assert g.tache_en_cours() is None


def test_transcription_refusee_pendant_un_job_de_cr(
        config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    """Exclusion mutuelle : les deux tâches réécrivent `transcription.md`."""
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    liberer = threading.Event()

    def _cr_lent(chemin, config, prompt=None):
        liberer.wait(5)
        return chemin

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _cr_lent)
    monkeypatch.setattr(pipeline, "transcrire_reunion",
                        lambda *a, **k: pytest.fail("transcription lancée pendant un CR"))

    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer(md) is True
    assert g.lancer_transcription(md) is False
    liberer.set()
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)


def test_cr_refuse_pendant_une_transcription(config_tmp, tmp_path, qapp, qtbot, monkeypatch):
    config_tmp.set("mistral_cle_api", "x")
    md = tmp_path / "reunion.md"
    liberer = threading.Event()

    def _transcription_lente(chemin, config):
        liberer.wait(5)
        return chemin

    monkeypatch.setattr(pipeline, "transcrire_reunion", _transcription_lente)
    monkeypatch.setattr(pipeline, "generer_cr_reunion",
                        lambda *a, **k: pytest.fail("CR lancé pendant une transcription"))

    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer_transcription(md) is True
    assert g.lancer(md) is False
    liberer.set()
    qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)


def test_lancer_transcription_refuse_si_indisponible(config_tmp, tmp_path, qapp):
    g = GestionnaireCRMistral(config_tmp)
    assert g.lancer_transcription(tmp_path / "reunion.md") is False
    assert g.job_en_cours() is None


# ── trace des bugs du pipeline (diagnostic du 2026-09-07) ──────────────────────────
#
# Un `TypeError` levé au fond du repli découpage n'a laissé qu'une ligne sans
# provenance dans le diagnostic terrain (« unsupported operand type(s) for +: 'int'
# and 'dict' ») : le worker ne remontait que `str(exc)`. Localiser le défaut a
# demandé de relire le code. Les échecs DIAGNOSTIQUÉS (`ErreurMistral`), eux, sont
# des messages destinés à l'utilisateur : y ajouter une trace ne ferait que du bruit.

def test_exception_inattendue_journalise_la_trace(config_tmp, tmp_path, qapp, qtbot,
                                                  monkeypatch, caplog):
    config_tmp.set("mistral_cle_api", "x")

    def _bug(chemin, config, prompt=None):
        raise TypeError("unsupported operand type(s) for +: 'int' and 'dict'")

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _bug)

    g = GestionnaireCRMistral(config_tmp)
    with caplog.at_level(logging.ERROR):
        assert g.lancer(tmp_path / "reunion.md") is True
        qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)

    traces = [r for r in caplog.records if r.exc_info and r.name.endswith("generateur_cr_mistral")]
    assert traces, "un bug du pipeline doit laisser sa trace dans les logs"
    assert "TypeError" in traces[0].getMessage()


def test_erreur_mistral_diagnostiquee_ne_journalise_pas_de_trace(config_tmp, tmp_path, qapp,
                                                                 qtbot, monkeypatch, caplog):
    config_tmp.set("mistral_cle_api", "x")

    def _refus(chemin, config, prompt=None):
        raise ErreurMistral("Réunion trop longue pour la transcription cloud")

    monkeypatch.setattr(pipeline, "generer_cr_reunion", _refus)

    g = GestionnaireCRMistral(config_tmp)
    echecs: list[tuple] = []
    g.echoue.connect(lambda md, message: echecs.append((md, message)))
    with caplog.at_level(logging.ERROR):
        assert g.lancer(tmp_path / "reunion.md") is True
        qtbot.waitUntil(lambda: g.job_en_cours() is None, timeout=5000)

    assert echecs, "le message part quand même à l'UI"
    assert not [r for r in caplog.records if r.exc_info], "pas de trace pour un refus attendu"
