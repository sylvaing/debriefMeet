"""Helper d'export des logs partagé tray / Préférences › Journalisation (docs/44).

`core/diagnostic.exporter_diagnostic` (contenu du zip, absence de texte transcrit) est
couvert par tests/test_diagnostic.py — ici on ne teste que l'enrobage UI : chemin
retourné, révélation sur acceptation, et surtout le fait qu'une erreur soit **affichée**
et non loguée silencieusement (contrainte docs/31 §3.6).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from debrief_meet.ui import export_diagnostic


@pytest.fixture
def zip_factice(tmp_path, monkeypatch):
    """Court-circuite l'export réel et la collecte d'infos système."""
    cible = tmp_path / "debriefMeet-diagnostic-0.2.0+dev-20260730-120000.zip"
    cible.write_bytes(b"PK\x03\x04")
    appels = {}

    def _exporter(dossier, infos):
        appels["dossier"] = dossier
        appels["infos"] = infos
        return cible

    monkeypatch.setattr(export_diagnostic, "exporter_diagnostic", _exporter)
    monkeypatch.setattr(export_diagnostic, "dossier_diagnostic_par_defaut", lambda: tmp_path)
    monkeypatch.setattr(
        "debrief_meet.platform.infos_systeme.collecter_infos_systeme", lambda: {"os": "test"})
    return cible, appels


def _dialogue(monkeypatch, accepte: bool):
    """Remplace DialogueGabarit par un double qui n'ouvre aucune fenêtre."""
    from PySide6.QtWidgets import QDialog

    vus = {}

    class _Faux:
        def __init__(self, parent, **kwargs):
            vus.update(kwargs)

        def bouton_annuler(self):
            class _B:
                def setText(self, _t): pass
            return _B()

        def definir_action(self, label):
            vus["label_action"] = label

        def exec(self):
            return QDialog.DialogCode.Accepted if accepte else QDialog.DialogCode.Rejected

    monkeypatch.setattr(export_diagnostic.dialogues, "DialogueGabarit", _Faux)
    return vus


def test_retourne_le_chemin_du_zip(qapp, zip_factice, monkeypatch):
    cible, appels = zip_factice
    _dialogue(monkeypatch, accepte=False)
    assert export_diagnostic.exporter_et_informer(None) == cible
    assert appels["infos"] == {"os": "test"}


def test_revele_seulement_si_accepte(qapp, zip_factice, monkeypatch):
    cible, _ = zip_factice
    reveles: list[Path] = []
    monkeypatch.setattr(export_diagnostic, "reveler", reveles.append)

    _dialogue(monkeypatch, accepte=False)
    export_diagnostic.exporter_et_informer(None)
    assert reveles == []

    _dialogue(monkeypatch, accepte=True)
    export_diagnostic.exporter_et_informer(None)
    assert reveles == [cible]


def test_dialogue_mentionne_le_nom_du_zip(qapp, zip_factice, monkeypatch):
    cible, _ = zip_factice
    vus = _dialogue(monkeypatch, accepte=False)
    export_diagnostic.exporter_et_informer(None)
    assert cible.name in vus["description"]
    assert vus["label_action"] == "Révéler dans le dossier"


def test_echec_affiche_un_avertissement_et_retourne_none(qapp, tmp_path, monkeypatch):
    """Erreur affichée, jamais un silence : c'est le seul canal quand tout est cassé."""
    monkeypatch.setattr(export_diagnostic, "dossier_diagnostic_par_defaut", lambda: tmp_path)
    monkeypatch.setattr(
        "debrief_meet.platform.infos_systeme.collecter_infos_systeme", lambda: {})

    def _boum(dossier, infos):
        raise OSError("disque plein")

    monkeypatch.setattr(export_diagnostic, "exporter_diagnostic", _boum)
    avertis = {}
    monkeypatch.setattr(export_diagnostic.dialogues, "avertir",
                        lambda parent, **kw: avertis.update(kw))

    assert export_diagnostic.exporter_et_informer(None) is None
    assert "disque plein" in avertis["description"]


def test_reveler_ignore_un_chemin_absent(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(export_diagnostic.subprocess, "Popen", appels.append)
    export_diagnostic.reveler(tmp_path / "absent.zip")
    assert appels == []


def test_dialogue_reel_se_construit(qapp):
    """Comble le trou qui a laissé passer le crash du 2026-08-04 : les tests ci-dessus
    remplacent `DialogueGabarit` par un double, donc l'icône réelle n'était jamais
    chargée. Ici on construit le VRAI dialogue avec les mêmes paramètres, sans `exec()`."""
    from debrief_meet.ui import dialogues

    dlg = dialogues.DialogueGabarit(
        None, titre="Logs exportés", description="Archive déposée sur le Bureau : x.zip",
        icone="file-text", intention=dialogues.Intention.ACCENT)
    dlg.bouton_annuler().setText("Fermer")
    dlg.definir_action("Révéler dans le dossier")
    assert dlg.bouton_action().text() == "Révéler dans le dossier"


def test_echec_du_dialogue_ne_perd_pas_le_zip(qapp, zip_factice, monkeypatch, caplog):
    """Le zip est écrit AVANT la confirmation : plus rien en aval ne doit faire perdre
    l'application (le crash réel est survenu après un export réussi)."""
    import logging

    cible, _ = zip_factice

    def _boum(*a, **kw):
        raise FileNotFoundError("icône absente")

    monkeypatch.setattr(export_diagnostic.dialogues, "DialogueGabarit", _boum)
    with caplog.at_level(logging.ERROR, logger="debrief_meet.ui.export_diagnostic"):
        assert export_diagnostic.exporter_et_informer(None) == cible
    assert "zip écrit" in caplog.text
