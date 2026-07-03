from __future__ import annotations

import logging

from debrief_meet.platform.windows.selection_backend import (
    SelectionBackend,
    detecter_materiel,
    selectionner_backend,
)


class _FauxConfig:
    def __init__(self, backend: str = "auto") -> None:
        self._backend = backend

    def get(self, cle: str):
        assert cle == "backend"
        return self._backend


def test_selectionner_backend_auto_retourne_toujours_cpu():
    resultat = selectionner_backend(_FauxConfig("auto"))
    assert resultat == SelectionBackend("faster-whisper", {"device": "cpu", "compute_type": "int8"})


def test_selectionner_backend_faster_whisper_explicite():
    resultat = selectionner_backend(_FauxConfig("faster-whisper"))
    assert resultat.nom == "faster-whisper"


def test_selectionner_backend_valeur_inconnue_replie_avec_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        resultat = selectionner_backend(_FauxConfig("openvino"))
    assert resultat.nom == "faster-whisper"
    assert any("non reconnu" in r.message for r in caplog.records)


def test_detecter_materiel_ne_leve_jamais_et_a_les_bonnes_cles():
    materiel = detecter_materiel()
    assert "cpu" in materiel
    assert "igpu" in materiel
    assert isinstance(materiel["igpu"], list)
    assert "ram_go" in materiel


def test_detecter_materiel_loggue_en_info(caplog):
    with caplog.at_level(logging.INFO, logger="debrief_meet"):
        selectionner_backend(_FauxConfig("auto"))
    assert any("Matériel détecté" in r.message for r in caplog.records)
