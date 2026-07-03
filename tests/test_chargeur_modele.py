"""Tests — téléchargement/rechargement de modèle (Préférences + premier lancement).

Le moteur réel n'est jamais touché : MoteurFake (aucun réseau). Cf. docs/15.
"""
from __future__ import annotations

from debrief_meet.core.config import Config
from debrief_meet.ui import chargeur_modele as cm
from debrief_meet.ui.chargeur_modele import ChargeurModele, precharger_au_demarrage
from tests.fakes.adapters import MoteurFake


def _config(tmp_path, **kv):
    cfg = Config(chemin=tmp_path / "config.json")
    for k, v in kv.items():
        cfg.set(k, v)
    return cfg


# ── ChargeurModele (worker, appelé en direct) ───────────────────────────────────

def test_chargeur_telecharge_si_absent(qapp):
    m = MoteurFake()
    finis = []
    ch = ChargeurModele(m, "medium", telecharger=True)
    ch.fini.connect(lambda: finis.append(True))
    ch.executer()
    assert "medium" in m.modeles_telecharges       # téléchargé
    assert m.modele_charge == "medium"             # puis rechargé à chaud
    assert finis == [True]


def test_chargeur_sans_telechargement(qapp):
    m = MoteurFake()
    ch = ChargeurModele(m, "medium", telecharger=False)
    ch.executer()
    assert "medium" not in m.modeles_telecharges   # déjà en cache → pas de DL
    assert m.modele_charge == "medium"             # mais rechargé quand même


def test_chargeur_echec_emet_signal(qapp):
    class _MoteurKO(MoteurFake):
        def telecharger_modele(self, nom, progression=None):
            raise RuntimeError("réseau coupé")
    erreurs = []
    ch = ChargeurModele(_MoteurKO(), "medium", telecharger=True)
    ch.echec.connect(erreurs.append)
    ch.executer()
    assert erreurs == ["réseau coupé"]


# ── precharger_au_demarrage (premier lancement) ─────────────────────────────────

def test_precharge_silencieuse_si_deja_en_cache(qapp, tmp_path):
    m = MoteurFake()
    m.modeles_telecharges.add("large-v3")          # déjà téléchargé
    precharger_au_demarrage(m, _config(tmp_path, modele="large-v3"))
    assert m.modele_charge == "large-v3"           # préchargé directement, sans fenêtre


def test_precharge_telecharge_si_absent(qapp, tmp_path):
    m = MoteurFake()                               # "medium" pas en cache → DL visible
    precharger_au_demarrage(m, _config(tmp_path, modele="medium"))
    assert "medium" in m.modeles_telecharges       # téléchargé
    assert m.modele_charge == "medium"             # puis préchargé


def test_precharge_hors_ligne_avertit_et_demarre_quand_meme(qapp, tmp_path, monkeypatch):
    class _MoteurKO(MoteurFake):
        def telecharger_modele(self, nom, progression=None):
            raise RuntimeError("pas de réseau")
    avertissements = []
    monkeypatch.setattr(cm.QMessageBox, "warning",
                        lambda *a, **k: avertissements.append(a))
    m = _MoteurKO()
    precharger_au_demarrage(m, _config(tmp_path, modele="medium"))
    assert avertissements                          # l'utilisateur est prévenu
    assert m.modele_charge is None                 # rien préchargé (DL échoué), app continue
