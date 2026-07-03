from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from debrief_meet.platform.factory import _windows
from debrief_meet.platform.windows.capture_systeme_wasapi import CaptureAudioSystemeWasapi
from debrief_meet.platform.windows.demarrage_auto import DemarrageAutoWindows
from debrief_meet.platform.windows.moteur_faster_whisper import MoteurFasterWhisper
from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows
from debrief_meet.platform.windows.raccourcis_win32 import RaccourcisGlobauxWindows


@pytest.fixture
def adaptateurs_windows(qapp):
    adaptateurs = _windows()
    yield adaptateurs
    # RaccourcisGlobauxWindows installe un native event filter sur le qapp partagé
    # par la suite — le retirer pour ne pas en accumuler d'un test à l'autre.
    QCoreApplication.instance().removeNativeEventFilter(adaptateurs.raccourcis._filtre)


def test_windows_ne_rend_plus_aucun_stub(adaptateurs_windows):
    """docs/34 §9 DoD : `creer_adaptateurs()` sur Windows ne rend plus aucun stub
    maintenant que tous les adaptateurs (§0-§6) sont écrits."""
    assert isinstance(adaptateurs_windows.moteur, MoteurFasterWhisper)
    assert isinstance(adaptateurs_windows.systeme, CaptureAudioSystemeWasapi)
    assert isinstance(adaptateurs_windows.presse_papiers, PressePapiersWindows)
    assert isinstance(adaptateurs_windows.demarrage_auto, DemarrageAutoWindows)
    assert isinstance(adaptateurs_windows.raccourcis, RaccourcisGlobauxWindows)
