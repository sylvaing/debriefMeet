from __future__ import annotations

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats
from debrief_meet.ui.fenetre_principale import PAGE_HISTORIQUE, PAGE_PREFERENCES, FenetrePrincipale
from debrief_meet.ui.tray import IconeTray


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path / "r"))
    cfg.set("dossier_journal", str(tmp_path / "j"))
    return cfg


def test_ouvrir_historique_bascule_la_fenetre_principale(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    fenetre.afficher_preferences()
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._ouvrir_historique()
    assert fenetre._pages.currentIndex() == PAGE_HISTORIQUE


def test_ouvrir_preferences_bascule_la_fenetre_principale(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._ouvrir_preferences()
    assert fenetre._pages.currentIndex() == PAGE_PREFERENCES


def test_notification_cliquee_ouvre_l_historique(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    fenetre.afficher_preferences()
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._on_notification_cliquee()
    assert fenetre._pages.currentIndex() == PAGE_HISTORIQUE


def test_menu_a_les_actions_attendues(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    libelles = [a.text() for a in tray.contextMenu().actions() if a.text()]
    assert any("Historique" in l for l in libelles)
    assert any("Préférences" in l for l in libelles)
    assert any("Quitter" in l for l in libelles)
