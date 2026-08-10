from __future__ import annotations

import sys

import pytest

from debrief_meet.platform.linux.demarrage_auto import (
    DemarrageAutoLinux,
    dossier_autostart,
)


@pytest.fixture
def autostart(tmp_path):
    """Dossier d'autostart isolé — jamais le vrai `~/.config/autostart`."""
    return tmp_path / "autostart"


@pytest.fixture
def executable_fige(monkeypatch, tmp_path):
    faux = tmp_path / "debriefMeet"
    faux.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(faux))
    return faux


def test_est_active_absente_par_defaut(autostart):
    assert DemarrageAutoLinux(autostart).est_active() is False


def test_activer_hors_bundle_ne_fait_rien(autostart, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        DemarrageAutoLinux(autostart).activer()
    assert not autostart.exists()
    assert any("hors bundle" in r.message for r in caplog.records)


def test_cycle_activer_est_active_desactiver(autostart, executable_fige):
    adaptateur = DemarrageAutoLinux(autostart)
    assert adaptateur.est_active() is False

    adaptateur.activer()
    assert adaptateur.est_active() is True

    adaptateur.desactiver()
    assert adaptateur.est_active() is False


def test_fichier_desktop_conforme_freedesktop(autostart, executable_fige):
    """Sans `[Desktop Entry]`/`Type=Application`, le bureau ignore silencieusement le
    fichier ; sans `X-GNOME-Autostart-enabled`, GNOME peut le laisser inerte."""
    DemarrageAutoLinux(autostart).activer()
    contenu = (autostart / "debriefmeet.desktop").read_text(encoding="utf-8")

    assert contenu.startswith("[Desktop Entry]")
    assert "Type=Application" in contenu
    assert f"Exec={executable_fige}" in contenu
    assert "X-GNOME-Autostart-enabled=true" in contenu


def test_entree_orpheline_est_inactive(autostart, executable_fige):
    """L'exécutable référencé a été déplacé/désinstallé depuis → considéré inactif,
    même règle que la valeur de Registre orpheline sur Windows."""
    adaptateur = DemarrageAutoLinux(autostart)
    adaptateur.activer()
    assert adaptateur.est_active() is True

    executable_fige.unlink()
    assert adaptateur.est_active() is False


def test_activer_deux_fois_ne_duplique_pas(autostart, executable_fige):
    adaptateur = DemarrageAutoLinux(autostart)
    adaptateur.activer()
    adaptateur.activer()
    assert list(autostart.iterdir()) == [autostart / "debriefmeet.desktop"]


def test_desactiver_sans_fichier_ne_leve_pas(autostart):
    DemarrageAutoLinux(autostart).desactiver()


def test_dossier_autostart_respecte_xdg_config_home(monkeypatch, tmp_path):
    """C'est `XDG_CONFIG_HOME` que lit le bureau — pas `~/.config` en dur."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert dossier_autostart() == tmp_path / "cfg" / "autostart"


def test_dossier_autostart_repli_sur_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert dossier_autostart() == tmp_path / ".config" / "autostart"
