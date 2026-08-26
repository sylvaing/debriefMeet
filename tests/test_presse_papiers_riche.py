"""Collage riche — implémentation commune aux 3 OS (docs/51).

Les adaptateurs sont testés **tous les trois sur la machine courante** : leur
`copier_riche` ne fait que déléguer à `commun.presse_papiers_riche`, du Qt pur sans
appel système, donc instanciable partout. C'est ce qui rend le test utile — il
attrape un adaptateur qui aurait oublié la méthode ou l'aurait mal câblée, sur un OS
où personne ne fait tourner la suite.
"""
from __future__ import annotations

import pytest

from debrief_meet.platform.linux.presse_papiers import PressePapiersLinux
from debrief_meet.platform.macos.presse_papiers import PressePapiersMaxOS
from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows

_ADAPTATEURS = [PressePapiersMaxOS, PressePapiersWindows, PressePapiersLinux]


@pytest.mark.parametrize("classe", _ADAPTATEURS, ids=lambda c: c.__name__)
def test_copier_riche_pose_les_deux_flavors(qapp, classe):
    """Le maillon décisif : sans flavor `text/html`, l'éditeur riche reçoit du texte
    brut et le markdown reste littéral — c'est le symptôme d'origine (docs/51 §1)."""
    from PySide6.QtGui import QGuiApplication

    classe().copier_riche("<p><strong>TITRE</strong></p>", "**TITRE**")
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasHtml()
    assert "<strong>TITRE</strong>" in mime.html()
    assert mime.text() == "**TITRE**"           # repli brut disponible en parallèle


def test_copier_riche_de_macos_nutilise_pas_pbcopy(qapp, monkeypatch):
    """`pbcopy` n'écrit que du texte brut : il ne peut pas porter de flavor HTML.
    L'adaptateur macOS doit donc passer par Qt ici, contrairement à `copier()`."""
    import subprocess

    def interdit(*a, **k):
        raise AssertionError("copier_riche ne doit pas passer par un sous-processus")

    monkeypatch.setattr(subprocess, "run", interdit)
    PressePapiersMaxOS().copier_riche("<p>x</p>", "x")


def test_copier_reste_du_texte_brut_sans_flavor_html(qapp):
    """Garde-fou de non-régression : la copie ordinaire (transcription, journal,
    dictée) ne doit jamais gagner de HTML — coller dans un éditeur markdown ou un
    terminal donnerait des balises."""
    from PySide6.QtGui import QGuiApplication

    PressePapiersWindows().copier("**TITRE**")
    assert not QGuiApplication.clipboard().mimeData().hasHtml()
