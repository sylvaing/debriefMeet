from __future__ import annotations

import json
import zipfile

import platformdirs
import pytest

from debrief_meet import VERSION_COMPLETE
from debrief_meet.core.diagnostic import dossier_diagnostic_par_defaut, exporter_diagnostic
from debrief_meet.core.logs import chemin_log, configurer_logs


@pytest.fixture
def dossiers_isoles(tmp_path, monkeypatch):
    dossier_logs = tmp_path / "logs"
    dossier_config = tmp_path / "config"
    monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(dossier_logs))
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **kw: str(dossier_config))
    return dossier_logs, dossier_config


def test_zip_cree_avec_infos_et_config(dossiers_isoles, tmp_path):
    infos = {"os": "Test-OS", "cpu": "Test-CPU"}
    cible = tmp_path / "export"

    chemin_zip = exporter_diagnostic(cible, infos)

    assert chemin_zip.exists()
    assert chemin_zip.name.startswith(f"debriefMeet-diagnostic-{VERSION_COMPLETE}-")
    assert chemin_zip.suffix == ".zip"

    with zipfile.ZipFile(chemin_zip) as zf:
        noms = zf.namelist()
        assert "infos_systeme.json" in noms
        assert "config.json" in noms
        assert json.loads(zf.read("infos_systeme.json")) == infos
        config_lue = json.loads(zf.read("config.json"))
        assert config_lue["modele"] == "large-v3-turbo"


def test_zip_produit_meme_sans_dossier_logs(dossiers_isoles, tmp_path):
    """Dossier logs absent (jamais activés) : le zip est quand même produit."""
    cible = tmp_path / "export"
    chemin_zip = exporter_diagnostic(cible, {"os": "Test-OS"})

    with zipfile.ZipFile(chemin_zip) as zf:
        assert "infos_systeme.json" in zf.namelist()
        assert not any(n.startswith("debriefMeet.log") for n in zf.namelist())


def test_zip_inclut_les_fichiers_de_rotation_des_logs(dossiers_isoles, tmp_path):
    dossier_logs, _ = dossiers_isoles
    configurer_logs(actifs=True)
    import logging
    logger = logging.getLogger("debrief_meet")
    logger.info("message de test")
    for h in logger.handlers:
        h.flush()
    # Simule un fichier de rotation supplémentaire.
    (chemin_log().parent / "debriefMeet.log.1").write_text("ancien log", encoding="utf-8")

    cible = tmp_path / "export"
    chemin_zip = exporter_diagnostic(cible, {"os": "Test-OS"})

    with zipfile.ZipFile(chemin_zip) as zf:
        noms = zf.namelist()
        assert "debriefMeet.log" in noms
        assert "debriefMeet.log.1" in noms


def test_zip_inclut_le_crash_log_si_present(dossiers_isoles, tmp_path):
    dossier_logs, _ = dossiers_isoles
    dossier_logs.mkdir(parents=True, exist_ok=True)
    (dossier_logs / "debriefMeet-crash.log").write_text("trace crash", encoding="utf-8")

    cible = tmp_path / "export"
    chemin_zip = exporter_diagnostic(cible, {"os": "Test-OS"})

    with zipfile.ZipFile(chemin_zip) as zf:
        assert "debriefMeet-crash.log" in zf.namelist()


def test_dossier_par_defaut_repli_sur_home_si_pas_de_bureau(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert dossier_diagnostic_par_defaut() == tmp_path


def test_dossier_par_defaut_utilise_le_bureau_si_present(monkeypatch, tmp_path):
    from pathlib import Path
    (tmp_path / "Desktop").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert dossier_diagnostic_par_defaut() == tmp_path / "Desktop"


# ── Caviardage des secrets (2026-07-31) ──────────────────────────────────────

def test_caviarde_les_secrets_connus():
    from debrief_meet.core.diagnostic import caviarder

    propre = caviarder({"mistral_cle_api": "sk-abc123", "bluemind_token": "t" * 36})
    assert propre["mistral_cle_api"] == "<masqué — 9 caractères>"
    assert propre["bluemind_token"] == "<masqué — 36 caractères>"


def test_caviarde_par_heuristique_pas_par_liste_figee():
    """Un fournisseur ajouté demain ne doit pas fuiter faute d'avoir été énuméré."""
    from debrief_meet.core.diagnostic import caviarder

    propre = caviarder({"openai_cle_api": "x" * 51, "un_token_quelconque": "y" * 12,
                        "webhook_secret": "z" * 8})
    assert all(v.startswith("<masqué") for v in propre.values())


def test_secret_vide_reste_vide():
    """La distinction configuré / pas configuré est justement ce qu'on diagnostique
    (édition lite sans clé Mistral = enregistre mais ne transcrira jamais)."""
    from debrief_meet.core.diagnostic import caviarder

    assert caviarder({"mistral_cle_api": ""})["mistral_cle_api"] == ""


def test_ne_touche_pas_aux_valeurs_non_secretes():
    from debrief_meet.core.diagnostic import caviarder

    donnees = {"bluemind_url": "https://bm.exemple.com", "modele": "large-v3-turbo",
               "intervalle_reunion": 30, "aec_actif": True, "micro_index": None}
    assert caviarder(donnees) == donnees


def test_zip_ne_contient_aucun_secret_en_clair(tmp_path, monkeypatch):
    """Test de bout en bout : c'est le CONTENU DU ZIP qui part chez le mainteneur."""
    import json, zipfile
    from debrief_meet.core import diagnostic
    from debrief_meet.core.config import Config

    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("mistral_cle_api", "CLE-SECRETE-A-NE-PAS-DIVULGUER")
    cfg.set("bluemind_token", "TOKEN-SECRET-A-NE-PAS-DIVULGUER")
    cfg.sauvegarder()
    monkeypatch.setattr("debrief_meet.core.config._chemin_config",
                        lambda: tmp_path / "config.json")

    chemin = diagnostic.exporter_diagnostic(tmp_path / "sortie", {"os": "test"})
    with zipfile.ZipFile(chemin) as zf:
        brut = zf.read("config.json").decode("utf-8")
        lue = json.loads(brut)
    assert "CLE-SECRETE-A-NE-PAS-DIVULGUER" not in brut
    assert "TOKEN-SECRET-A-NE-PAS-DIVULGUER" not in brut
    assert lue["mistral_cle_api"].startswith("<masqué")
    assert lue["bluemind_token"].startswith("<masqué")
