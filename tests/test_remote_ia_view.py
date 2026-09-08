"""Tests — section Préférences « Remote IA » (docs/42 §9.1). Bloc Mistral, extensible
(un seul bloc en v1). Sans réseau réel pour le test de connexion (respx)."""
from __future__ import annotations

import pytest

import httpx
import respx

from debrief_meet.core.config import MODELES_CR, Config
from debrief_meet.ui.remote_ia_view import RemoteIAView


URL = "https://api.mistral.ai"


def _config(tmp_path):
    return Config(chemin=tmp_path / "config.json")


def test_cle_api_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("s3cr3t")
    vue._edit_cle.editingFinished.emit()
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_cle_api") == "s3cr3t"


def test_combo_modele_transcription_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._combo_modele_transcription.currentData() == "voxtral-mini-latest"


def test_combo_modele_cr_persiste(qapp, tmp_path):
    # Pas le premier item : c'est le défaut, le sélectionner n'émettrait pas
    # currentIndexChanged et le test ne persisterait rien.
    autre = MODELES_CR[1]
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    idx = vue._combo_modele_cr.findData(autre)
    vue._combo_modele_cr.setCurrentIndex(idx)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_modele_cr") == autre


def test_combo_modele_cr_demarre_sur_le_defaut(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._combo_modele_cr.currentData() == "ministral-14b-latest"


@pytest.mark.parametrize("mort", ["mistral-large-latest", "mistral-medium-latest",
                                  "mistral-small-latest", "magistral-medium-latest"])
def test_modeles_non_servis_retires_du_selecteur(qapp, tmp_path, mort):
    """Mesuré le 2026-09-08 : large répond 403 tier_not_allowed, tout le reste de la
    famille mistral-* répond 429 avec une limite de 0 req/min. Les proposer envoie
    l'utilisateur sur 2 min d'attente puis « Quota dépassé », sans issue."""
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._combo_modele_cr.findData(mort) == -1


def test_selecteur_et_migration_partagent_la_meme_liste(qapp, tmp_path):
    """Un sélecteur qui divergerait de `MODELES_CR` proposerait un modèle que la
    migration v6 remplacerait au démarrage suivant — choix sans effet, en silence."""
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    proposes = [vue._combo_modele_cr.itemData(i)
                for i in range(vue._combo_modele_cr.count())]
    assert proposes == list(MODELES_CR)


def test_case_forcer_voxtral_decochee_par_defaut(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._check_forcer_voxtral.isChecked() is False
    assert cfg.get("mistral_source_transcription") == "auto"


def test_case_forcer_voxtral_coche_bascule_la_source(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._check_forcer_voxtral.setChecked(True)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_source_transcription") == "voxtral"


def test_case_forcer_voxtral_decoche_revient_auto(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("mistral_source_transcription", "voxtral")
    vue = RemoteIAView(cfg)
    assert vue._check_forcer_voxtral.isChecked() is True
    vue._check_forcer_voxtral.setChecked(False)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_source_transcription") == "auto"


def test_tester_connexion_sans_cle_affiche_message(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("")
    vue._tester_connexion()
    assert "requise" in vue._label_statut.text().lower()


@respx.mock
def test_tester_connexion_succes(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("cle-valide")
    vue._tester_connexion()
    qtbot.waitUntil(lambda: "✓" in vue._label_statut.text(), timeout=5000)


@respx.mock
def test_tester_connexion_echec(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(401))
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("mauvaise-cle")
    vue._tester_connexion()
    qtbot.waitUntil(lambda: "Échec" in vue._label_statut.text(), timeout=5000)


# ── Mode distant (docs/45) ───────────────────────────────────────────────────

def test_distant_pas_de_case_forcer_voxtral(qapp, tmp_path, mode_distant):
    """Inerte en distant : il n'y a jamais de transcription locale à ignorer, et
    « auto » y est déjà équivalent à « voxtral »."""
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert not hasattr(vue, "_check_forcer_voxtral")
    assert cfg.get("mistral_source_transcription") == "auto"
    assert vue._edit_cle is not None      # la clé API reste configurable, et obligatoire


def test_duree_max_reglable_et_persiste(qapp, tmp_path):
    """Le message d'erreur du pipeline renvoie vers ce réglage : il doit exister."""
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._spin_duree_max.value() == 180

    vue._spin_duree_max.setValue(240)

    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_duree_max_min") == 240
