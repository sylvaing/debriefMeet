from __future__ import annotations

import json
import sys

import pytest

from debrief_meet.core.config import Config, VERSION_COURANTE, _DEFAUTS


class TestDefauts:
    def test_valeurs_defaut_presentes(self, config_tmp):
        assert config_tmp.get("modele") == "large-v3-turbo"
        assert config_tmp.get("langue") is None
        assert config_tmp.get("intervalle_reunion") == 30
        assert config_tmp.get("logs_actifs") is False
        assert config_tmp.get("logs_debug") is False
        assert config_tmp.get("demarrage_auto") is False
        assert config_tmp.get("backend") == "auto"

    def test_version_defaut(self, config_tmp):
        assert config_tmp.get("version") == VERSION_COURANTE

    def test_cle_inconnue_retourne_none(self, config_tmp):
        assert config_tmp.get("cle_inexistante") is None


class TestDefautsWindows:
    """docs/31 §3.1 : logs DEBUG on + raccourcis Ctrl+Alt+D/R/J par défaut sur Windows
    uniquement — les défauts dépendent de `sys.platform` au chargement du module."""

    def _recharger_avec_platform(self, monkeypatch, plateforme: str):
        import importlib
        monkeypatch.setattr(sys, "platform", plateforme)
        from debrief_meet.core import config as config_module
        importlib.reload(config_module)
        return config_module

    def test_defauts_windows(self, monkeypatch):
        original = sys.platform
        try:
            config_module = self._recharger_avec_platform(monkeypatch, "win32")
            assert config_module._DEFAUTS["logs_actifs"] is True
            assert config_module._DEFAUTS["logs_debug"] is True
            assert config_module._DEFAUTS["raccourci_dictee"] == "Ctrl+Alt+D"
            assert config_module._DEFAUTS["raccourci_reunion"] == "Ctrl+Alt+R"
            assert config_module._DEFAUTS["raccourci_journal"] == "Ctrl+Alt+J"
        finally:
            self._recharger_avec_platform(monkeypatch, original)

    def test_defauts_macos_inchanges(self, monkeypatch):
        original = sys.platform
        try:
            config_module = self._recharger_avec_platform(monkeypatch, "darwin")
            assert config_module._DEFAUTS["logs_actifs"] is False
            assert config_module._DEFAUTS["logs_debug"] is False
            assert config_module._DEFAUTS["raccourci_dictee"] == "Meta+Alt+Ctrl+D"
        finally:
            self._recharger_avec_platform(monkeypatch, original)


class TestSauvegardeChargement:
    def test_roundtrip(self, config_tmp):
        config_tmp.set("modele", "medium")
        config_tmp.sauvegarder()

        config2 = Config(chemin=config_tmp._chemin)
        config2.charger()
        assert config2.get("modele") == "medium"

    def test_fichier_cree(self, config_tmp):
        assert not config_tmp._chemin.exists()
        config_tmp.sauvegarder()
        assert config_tmp._chemin.exists()

    def test_charger_absent_utilise_defauts(self, config_tmp):
        config_tmp.charger()   # fichier n'existe pas
        assert config_tmp.get("modele") == "large-v3-turbo"

    def test_charger_json_invalide(self, config_tmp):
        config_tmp._chemin.parent.mkdir(parents=True, exist_ok=True)
        config_tmp._chemin.write_text("{pas_du_json", encoding="utf-8")
        config_tmp.charger()   # ne doit pas lever
        assert config_tmp.get("modele") == "large-v3-turbo"


class TestSet:
    def test_set_cle_valide(self, config_tmp):
        config_tmp.set("modele", "tiny")
        assert config_tmp.get("modele") == "tiny"

    def test_set_cle_inconnue_leve(self, config_tmp):
        with pytest.raises(KeyError):
            config_tmp.set("cle_inexistante", "valeur")

    def test_set_none(self, config_tmp):
        config_tmp.set("langue", None)
        assert config_tmp.get("langue") is None


class TestMigration:
    def test_migration_version_absente(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"modele": "small"})   # pas de champ "version"
        assert cfg.get("version") == VERSION_COURANTE

    def test_migration_version_ancienne(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"version": 0, "modele": "base"})
        assert cfg.get("version") == VERSION_COURANTE
        assert cfg.get("modele") == "base"

    def test_version_courante_non_modifiee(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"version": VERSION_COURANTE, "modele": "large-v3"})
        assert cfg.get("version") == VERSION_COURANTE


class TestPrompts:
    def test_defaut_cr_simple_actif(self, config_tmp):
        ps = config_tmp.get("prompts")
        assert isinstance(ps, list) and ps[0]["titre"] == "CR simple"
        assert config_tmp.get("prompt_actif") == 0

    def test_retro_compat_fichier_sans_la_cle(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"modele": "small"})
        assert cfg.get("prompts")[0]["titre"] == "CR simple"
        assert cfg.get("prompt_actif") == 0

    def test_instances_isolees(self, tmp_path):
        # deepcopy des défauts : modifier une instance ne touche pas l'autre.
        from debrief_meet.core.config import Config
        a = Config(chemin=tmp_path / "a.json")
        b = Config(chemin=tmp_path / "b.json")
        a.get("prompts").append({"titre": "X", "contenu": "x"})
        assert len(b.get("prompts")) == 1

    def test_persistance(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"prompts": [{"titre": "T", "contenu": "C"}], "prompt_actif": None})
        assert cfg.get("prompts") == [{"titre": "T", "contenu": "C"}]
        assert cfg.get("prompt_actif") is None


class TestTranscriptionLive:
    def test_defaut_true(self, config_tmp):
        assert config_tmp.get("transcription_live") is True

    def test_retro_compat_fichier_sans_la_cle(self, config_tmp_avec_fichier):
        # Un config.json antérieur n'a pas la clé → valeur par défaut appliquée.
        cfg = config_tmp_avec_fichier({"modele": "small"})
        assert cfg.get("transcription_live") is True

    def test_persistance_false(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"transcription_live": False})
        assert cfg.get("transcription_live") is False
