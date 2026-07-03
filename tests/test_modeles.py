from __future__ import annotations

import pytest

from debrief_meet.core.modeles import NOMS_LOGIQUES, resoudre_mlx


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
