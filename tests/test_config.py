from __future__ import annotations

import json
import sys

import pytest

from debrief_meet.core import prompts as prompts_mod
from debrief_meet.core.config import Config, VERSION_COURANTE, _DEFAUTS


class TestDefauts:
    def test_valeurs_defaut_presentes(self, config_tmp):
        # Logs ON par défaut sur Windows (décision D5, docs/31 §3.1) ET sur Linux
        # (décision L5, docs/49) : dans les deux cas l'utilisateur est distant et les
        # logs sont le seul canal de debug. macOS reste off (dev local). Ce test
        # tourne sur les trois plateformes (gates VM Windows et LXC Linux), l'attendu
        # dépend donc de la plateforme d'exécution.
        logs_attendus = sys.platform == "win32" or sys.platform.startswith("linux")
        assert config_tmp.get("modele") == "large-v3-turbo"
        assert config_tmp.get("langue") is None
        assert config_tmp.get("intervalle_reunion") == 30
        assert config_tmp.get("logs_actifs") is logs_attendus
        assert config_tmp.get("logs_debug") is logs_attendus
        assert config_tmp.get("demarrage_auto") is False
        assert config_tmp.get("backend") == "auto"

    def test_valeurs_defaut_mistral(self, config_tmp):
        """Interco Mistral (docs/42) — clé vide = fonctionnalité invisible."""
        assert config_tmp.get("mistral_cle_api") == ""
        assert config_tmp.get("mistral_base_url") == "https://api.mistral.ai"
        assert config_tmp.get("mistral_source_transcription") == "auto"
        assert config_tmp.get("mistral_modele_transcription") == "voxtral-mini-latest"
        assert config_tmp.get("mistral_modele_cr") == "mistral-medium-latest"
        assert config_tmp.get("mistral_duree_max_min") == 180
        assert config_tmp.get("mistral_confidentialite_acceptee") is False

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


class TestCheminConfig:
    def test_appauthor_false_evite_le_doublon_windows(self, monkeypatch):
        """Sans `appauthor=False`, platformdirs double le dossier sur Windows
        (`%LOCALAPPDATA%\\debriefMeet\\debriefMeet`, docs/32 §4) : platformdirs traite
        `appname` comme « author » par défaut faute de mieux."""
        import platformdirs
        from debrief_meet.core.config import _chemin_config

        appels = []
        monkeypatch.setattr(
            platformdirs, "user_config_dir",
            lambda *a, **kw: appels.append((a, kw)) or "/tmp/config",
        )
        _chemin_config()
        assert appels[0][1].get("appauthor") is False


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


class TestMigrationV2Prompts:
    """v1 → v2 : rafraîchissement des prompts par défaut (CR simple + CR Pipedrive)."""

    def _v1(self, contenu_cr_simple: str) -> dict:
        return {"version": 1,
                "prompts": [{"titre": prompts_mod.CR_SIMPLE_TITRE,
                             "contenu": contenu_cr_simple}],
                "prompt_actif": 0}

    def test_cr_simple_defaut_v1_mis_a_jour(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(self._v1(prompts_mod.CR_SIMPLE_CONTENU_V1))
        ps = cfg.get("prompts")
        assert ps[0]["contenu"] == prompts_mod.CR_SIMPLE_CONTENU

    def test_cr_simple_edite_laisse_intact(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(self._v1("Mon prompt personnalisé."))
        ps = cfg.get("prompts")
        assert ps[0]["contenu"] == "Mon prompt personnalisé."

    def test_cr_pipedrive_et_full_md_ajoutes_en_fin(self):
        """v2 **en isolation** : passer par `charger()` ferait aussi jouer la v4, qui
        retire le prompt Pipedrive — le test ne parlerait plus de la v2. Sollicitée
        directement, l'étape reste testable telle qu'elle a joué sur les postes."""
        from debrief_meet.core.config import Config
        donnees = self._v1(prompts_mod.CR_SIMPLE_CONTENU_V1)
        Config._migrer_v2_prompts(donnees)
        assert donnees["prompts"][-2:] == [
            {"titre": prompts_mod.CR_PIPEDRIVE_TITRE,
             "contenu": prompts_mod.CR_PIPEDRIVE_CONTENU_V2},
            {"titre": prompts_mod.CR_FULL_MD_TITRE,
             "contenu": prompts_mod.CR_FULL_MD_CONTENU}]
        assert donnees["prompt_actif"] == 0      # l'index actif reste valide

    def test_cr_pipedrive_deja_present_pas_de_doublon(self, config_tmp_avec_fichier):
        donnees = self._v1(prompts_mod.CR_SIMPLE_CONTENU_V1)
        donnees["prompts"].append({"titre": prompts_mod.CR_PIPEDRIVE_TITRE,
                                   "contenu": "Ma version à moi."})
        cfg = config_tmp_avec_fichier(donnees)
        ps = cfg.get("prompts")
        titres = [p["titre"] for p in ps]
        assert titres.count(prompts_mod.CR_PIPEDRIVE_TITRE) == 1
        assert ps[1]["contenu"] == "Ma version à moi."   # version éditée conservée

    def test_migration_persistee_sur_disque(self, tmp_path):
        from debrief_meet.core.config import Config
        chemin = tmp_path / "config.json"
        chemin.write_text(json.dumps(self._v1(prompts_mod.CR_SIMPLE_CONTENU_V1)),
                          encoding="utf-8")
        Config(chemin=chemin).charger()
        sur_disque = json.loads(chemin.read_text(encoding="utf-8"))
        assert sur_disque["version"] == VERSION_COURANTE
        titres = [p["titre"] for p in sur_disque["prompts"]]
        assert prompts_mod.CR_FULL_MD_TITRE in titres
        # Ajouté par la v2 puis retiré par la v4 dans la même passe : l'état écrit sur
        # disque est le résultat net de la chaîne, jamais un intermédiaire.
        assert prompts_mod.CR_PIPEDRIVE_TITRE not in titres

    def test_config_v2_non_retouchee(self, tmp_path):
        # Une config déjà en v2 dont l'utilisateur a supprimé la note Pipedrive
        # ne doit pas la voir réapparaître, ni être réécrite sur disque.
        from debrief_meet.core.config import Config
        chemin = tmp_path / "config.json"
        donnees = {"version": VERSION_COURANTE,
                   "prompts": [{"titre": "Perso", "contenu": "X"}], "prompt_actif": 0}
        chemin.write_text(json.dumps(donnees), encoding="utf-8")
        contenu_initial = chemin.read_text(encoding="utf-8")
        cfg = Config(chemin=chemin)
        cfg.charger()
        assert cfg.get("prompts") == [{"titre": "Perso", "contenu": "X"}]
        assert chemin.read_text(encoding="utf-8") == contenu_initial

    def test_prompts_absents_ou_malformes_sans_crash(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"version": 1, "prompts": "pas une liste"})
        assert cfg.get("version") == VERSION_COURANTE


class TestMigrationV3ModeleCr:
    """v2 → v3 : modèle de CR par défaut mistral-small → mistral-large.
    Depuis la v5, la chaîne complète aboutit à mistral-medium (large → 403
    tier_not_allowed) — les assertions portent sur l'état final."""

    def test_ancien_defaut_migre(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 2, "mistral_modele_cr": "mistral-small-latest"})
        assert cfg.get("mistral_modele_cr") == "mistral-medium-latest"
        assert cfg.get("version") == VERSION_COURANTE

    def test_choix_explicite_conserve(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 2, "mistral_modele_cr": "mistral-medium-latest"})
        assert cfg.get("mistral_modele_cr") == "mistral-medium-latest"
        assert cfg.get("version") == VERSION_COURANTE

    def test_depuis_v1_les_migrations_s_enchainent(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 1, "mistral_modele_cr": "mistral-small-latest",
             "prompts": [{"titre": "Perso", "contenu": "X"}]})
        # v3 l'a passé à large, v5 à medium : résultat net.
        assert cfg.get("mistral_modele_cr") == "mistral-medium-latest"
        titres = [p["titre"] for p in cfg.get("prompts")]
        # v2 a ajouté les deux CR BlueMind, v4 a retiré le Pipedrive : résultat net.
        assert titres == ["Perso", "CR full .md"]
        assert cfg.get("version") == VERSION_COURANTE


class TestMigrationV5ModeleCrMedium:
    """v4 → v5 : mistral-large → mistral-medium (403 tier_not_allowed depuis fin
    août 2026, modèle retiré du sélecteur). Migre AUSSI un choix explicite —
    conserver large figerait un échec que l'UI ne permet plus de corriger."""

    def test_large_latest_migre(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 4, "mistral_modele_cr": "mistral-large-latest"})
        assert cfg.get("mistral_modele_cr") == "mistral-medium-latest"
        assert cfg.get("version") == VERSION_COURANTE

    def test_large_date_migre(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 4, "mistral_modele_cr": "mistral-large-2512"})
        assert cfg.get("mistral_modele_cr") == "mistral-medium-latest"

    def test_small_explicite_conserve(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": 4, "mistral_modele_cr": "mistral-small-latest"})
        assert cfg.get("mistral_modele_cr") == "mistral-small-latest"
        assert cfg.get("version") == VERSION_COURANTE


class TestMigrationV4RetraitPromptPipedrive:
    """v3 → v4 : « CR Pipedrive » retiré des prompts (docs/51) — la copie mise en
    forme convertit le markdown du « CR full .md » au moment du copier."""

    @staticmethod
    def _v3(contenu_pipedrive: str, actif: int = 0) -> dict:
        return {"version": 3, "prompt_actif": actif, "prompts": [
            {"titre": "CR simple", "contenu": "Simple."},
            {"titre": prompts_mod.CR_PIPEDRIVE_TITRE, "contenu": contenu_pipedrive},
            {"titre": prompts_mod.CR_FULL_MD_TITRE, "contenu": "Full."},
        ]}

    def test_prompt_reste_au_defaut_retire(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(self._v3(prompts_mod.CR_PIPEDRIVE_CONTENU_V2))
        assert [p["titre"] for p in cfg.get("prompts")] == ["CR simple", "CR full .md"]
        assert cfg.get("version") == VERSION_COURANTE

    def test_prompt_retouche_conserve(self, config_tmp_avec_fichier):
        """Un prompt que l'utilisateur a édité lui appartient — même règle que la v2
        pour le CR simple."""
        cfg = config_tmp_avec_fichier(self._v3("Ma version à moi."))
        ps = cfg.get("prompts")
        assert [p["titre"] for p in ps] == [
            "CR simple", prompts_mod.CR_PIPEDRIVE_TITRE, "CR full .md"]
        assert ps[1]["contenu"] == "Ma version à moi."

    def test_index_actif_apres_le_retire_est_decremente(self, config_tmp_avec_fichier):
        """LE piège : `prompt_actif` est un index, pas un nom. Sans recalage, un actif
        à 2 (« CR full .md ») désignerait après suppression un prompt hors liste — et
        `contenu_actif` retomberait silencieusement sur le CR simple codé en dur."""
        cfg = config_tmp_avec_fichier(
            self._v3(prompts_mod.CR_PIPEDRIVE_CONTENU_V2, actif=2))
        assert cfg.get("prompt_actif") == 1
        prompts_apres = cfg.get("prompts")
        assert prompts_apres[cfg.get("prompt_actif")]["titre"] == prompts_mod.CR_FULL_MD_TITRE

    def test_index_actif_avant_le_retire_inchange(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            self._v3(prompts_mod.CR_PIPEDRIVE_CONTENU_V2, actif=0))
        assert cfg.get("prompt_actif") == 0

    def test_index_actif_sur_le_retire_revient_au_cr_simple(self, config_tmp_avec_fichier):
        """L'utilisateur avait le prompt Pipedrive pour actif : il faut un repli, pas
        un index qui désigne le prompt ayant pris sa place dans la liste."""
        cfg = config_tmp_avec_fichier(
            self._v3(prompts_mod.CR_PIPEDRIVE_CONTENU_V2, actif=1))
        assert cfg.get("prompt_actif") == prompts_mod.PROMPT_ACTIF_DEFAUT
        assert cfg.get("prompts")[cfg.get("prompt_actif")]["titre"] == "CR simple"

    def test_prompts_malformes_sans_crash(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier({"version": 3, "prompts": "pas une liste"})
        assert cfg.get("version") == VERSION_COURANTE

    def test_config_deja_a_jour_non_retouchee(self, tmp_path):
        """Une config en v4 dont l'utilisateur a **remis** un prompt Pipedrive ne doit
        pas le voir disparaître à chaque démarrage."""
        from debrief_meet.core.config import Config
        chemin = tmp_path / "config.json"
        donnees = {"version": VERSION_COURANTE, "prompt_actif": 0, "prompts": [
            {"titre": prompts_mod.CR_PIPEDRIVE_TITRE,
             "contenu": prompts_mod.CR_PIPEDRIVE_CONTENU_V2}]}
        chemin.write_text(json.dumps(donnees), encoding="utf-8")
        contenu_initial = chemin.read_text(encoding="utf-8")
        cfg = Config(chemin=chemin)
        cfg.charger()
        assert [p["titre"] for p in cfg.get("prompts")] == [prompts_mod.CR_PIPEDRIVE_TITRE]
        assert chemin.read_text(encoding="utf-8") == contenu_initial


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
        nb_defauts = len(b.get("prompts"))
        a.get("prompts").append({"titre": "X", "contenu": "x"})
        assert len(b.get("prompts")) == nb_defauts

    def test_persistance(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"version": VERSION_COURANTE,
             "prompts": [{"titre": "T", "contenu": "C"}], "prompt_actif": None})
        assert cfg.get("prompts") == [{"titre": "T", "contenu": "C"}]
        assert cfg.get("prompt_actif") is None


class TestLexique:
    def test_defaut_pre_rempli_et_actif(self, config_tmp):
        corrections = config_tmp.get("lexique_corrections")
        assert isinstance(corrections, list) and corrections
        assert {"entendu": "Blue Moon, Bluemine, Blue Mind", "ecrire": "BlueMind"} in corrections
        assert config_tmp.get("lexique_actif") is True

    def test_retro_compat_fichier_sans_la_cle(self, config_tmp_avec_fichier):
        # Une installation existante récupère le tableau par défaut, actif (docs/46 §1).
        cfg = config_tmp_avec_fichier({"modele": "small"})
        assert cfg.get("lexique_corrections")
        assert cfg.get("lexique_actif") is True

    def test_instances_isolees(self, tmp_path):
        from debrief_meet.core.config import Config
        a = Config(chemin=tmp_path / "a.json")
        b = Config(chemin=tmp_path / "b.json")
        a.get("lexique_corrections").append({"entendu": "x", "ecrire": "X"})
        assert len(b.get("lexique_corrections")) != len(a.get("lexique_corrections"))

    def test_persistance(self, config_tmp_avec_fichier):
        cfg = config_tmp_avec_fichier(
            {"lexique_corrections": [{"entendu": "a", "ecrire": "A"}], "lexique_actif": False})
        assert cfg.get("lexique_corrections") == [{"entendu": "a", "ecrire": "A"}]
        assert cfg.get("lexique_actif") is False


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
