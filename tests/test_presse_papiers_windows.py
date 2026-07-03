from __future__ import annotations

from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows


def test_copier_puis_lire_aller_retour(qapp):
    pp = PressePapiersWindows()
    pp.copier("texte de test")
    assert pp.lire() == "texte de test"
