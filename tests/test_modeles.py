from __future__ import annotations

import pytest

from debrief_meet.core.modeles import NOMS_LOGIQUES, resoudre_faster_whisper, resoudre_mlx


def test_resoudre_mlx_large_v3():
    repo = resoudre_mlx("large-v3")
    assert "mlx-community" in repo
    assert "large-v3" in repo


def test_resoudre_mlx_tous_les_noms():
    for nom in NOMS_LOGIQUES:
        repo = resoudre_mlx(nom)
        assert repo


def test_resoudre_mlx_inconnu_leve_valueerror():
    with pytest.raises(ValueError):
        resoudre_mlx("inexistant")


def test_noms_logiques_non_vide():
    assert len(NOMS_LOGIQUES) > 0


def test_resoudre_faster_whisper_tous_les_noms_du_selecteur():
    """docs/34 §1.5 : tous les nom_logique du sélecteur existant sont couverts."""
    for nom in NOMS_LOGIQUES:
        repo = resoudre_faster_whisper(nom)
        assert repo


def test_resoudre_faster_whisper_large_v3():
    assert resoudre_faster_whisper("large-v3") == "Systran/faster-whisper-large-v3"


def test_resoudre_faster_whisper_turbo():
    assert resoudre_faster_whisper("large-v3-turbo") == "deepdml/faster-whisper-large-v3-turbo-ct2"


def test_resoudre_faster_whisper_inconnu_leve_valueerror():
    with pytest.raises(ValueError):
        resoudre_faster_whisper("inexistant")
