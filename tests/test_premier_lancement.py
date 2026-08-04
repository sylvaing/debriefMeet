"""Écran de bienvenue du premier lancement (docs/45)."""
from __future__ import annotations

from debrief_meet.core.config import Config
from debrief_meet.ui.premier_lancement import PremierLancement


def _config(tmp_path) -> Config:
    return Config(chemin=tmp_path / "config.json")


def _relire(tmp_path) -> Config:
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.charger()
    return cfg


def test_defaut_distant_et_accueil_fait(qapp, tmp_path):
    dlg = PremierLancement(_config(tmp_path))
    assert dlg._radio_distant.isChecked()
    dlg._valider()
    relu = _relire(tmp_path)
    assert relu.get("mode_transcription") == "distant"
    assert relu.get("accueil_fait") is True


def test_choisir_local_persiste(qapp, tmp_path):
    dlg = PremierLancement(_config(tmp_path))
    dlg._radio_local.setChecked(True)
    dlg._valider()
    relu = _relire(tmp_path)
    assert relu.get("mode_transcription") == "local"
    assert relu.get("accueil_fait") is True


def test_cle_saisie_persistee_en_distant(qapp, tmp_path):
    dlg = PremierLancement(_config(tmp_path))
    dlg._edit_cle.setText("  sk-test  ")
    dlg._valider()
    assert _relire(tmp_path).get("mistral_cle_api") == "sk-test"


def test_cle_ignoree_si_local(qapp, tmp_path):
    """Une clé tapée puis un revirement vers « local » ne doit pas écraser la config
    avec une saisie que l'utilisateur n'associe plus à son choix."""
    dlg = PremierLancement(_config(tmp_path))
    dlg._edit_cle.setText("sk-test")
    dlg._radio_local.setChecked(True)
    dlg._valider()
    assert _relire(tmp_path).get("mistral_cle_api") == ""


def test_fermer_sans_choisir_vaut_distant_sans_harcelement(qapp, tmp_path):
    """Échap/croix = défaut sûr, et on ne redemandera pas au prochain lancement."""
    dlg = PremierLancement(_config(tmp_path))
    dlg._radio_local.setChecked(True)     # même un radio touché ne compte pas
    dlg.reject()
    relu = _relire(tmp_path)
    assert relu.get("mode_transcription") == "distant"
    assert relu.get("accueil_fait") is True


def test_champ_cle_suit_le_radio(qapp, tmp_path):
    dlg = PremierLancement(_config(tmp_path))
    assert not dlg._bloc_cle.isHidden()
    dlg._radio_local.setChecked(True)
    assert dlg._bloc_cle.isHidden()
    dlg._radio_distant.setChecked(True)
    assert not dlg._bloc_cle.isHidden()
