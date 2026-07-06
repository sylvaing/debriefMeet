"""Garde-fou stdout/stderr None en app figée fenêtrée (PyInstaller console=False).

Régression : au premier lancement Windows, le téléchargement du modèle plantait avec
`'NoneType' object has no attribute 'write'` — les barres tqdm de huggingface_hub
écrivaient dans un `sys.stderr` valant None (2026-07-06)."""
from __future__ import annotations

import sys

from debrief_meet.__main__ import _FluxNul, _garantir_stdio


def test_flux_nul_est_ecrivable():
    flux = _FluxNul()
    assert flux.write("peu importe") == 0
    flux.flush()  # ne lève pas


def test_garantir_stdio_remplace_none(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    _garantir_stdio()
    # Après le garde-fou, une écriture (ex. tqdm) ne lève plus.
    sys.stdout.write("x")
    sys.stderr.write("y")


def test_garantir_stdio_ne_touche_pas_les_flux_reels(monkeypatch):
    import io
    faux_out, faux_err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", faux_out)
    monkeypatch.setattr(sys, "stderr", faux_err)
    _garantir_stdio()
    # Flux réels (dev, ou pipes d'un worker subprocess) : laissés intacts.
    assert sys.stdout is faux_out
    assert sys.stderr is faux_err
