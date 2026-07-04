from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon

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


def test_menu_a_les_actions_attendues_dans_l_ordre(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    libelles = [a.text() for a in tray._menu.actions() if a.text()]
    assert libelles == [
        "Démarrer Dictée", "Démarrer Réunion", "Démarrer Journal",
        "Ouvrir debriefMeet", "Historique…", "Préférences…",
        "Exporter le diagnostic…", "Quitter",
    ]


def test_ouvrir_debriefmeet_est_l_action_par_defaut(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    assert tray._menu.defaultAction().text() == "Ouvrir debriefMeet"


def test_pas_de_menu_contextuel_qt_attache(qapp, tmp_path):
    """Ne pas utiliser `setContextMenu()` — sur macOS ça ouvrirait le menu au clic
    gauche aussi (cf. commentaire de `_construire_menu`)."""
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    assert tray.contextMenu() is None


def test_clic_gauche_ouvre_la_fenetre(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    fenetre.afficher_preferences()
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._on_activation(QSystemTrayIcon.ActivationReason.Trigger)
    assert fenetre.isVisible()
    # n'a pas changé d'onglet (contrairement à _ouvrir_historique/_ouvrir_preferences)
    assert fenetre._pages.currentIndex() == PAGE_PREFERENCES


def test_clic_droit_affiche_le_menu(qapp, tmp_path, monkeypatch):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    appels = []
    monkeypatch.setattr(tray._menu, "popup", lambda pos: appels.append(pos))
    tray._on_activation(QSystemTrayIcon.ActivationReason.Context)
    assert len(appels) == 1
