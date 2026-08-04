from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from debrief_meet.platform.factory import _windows
from debrief_meet.platform.windows.capture_systeme_wasapi import CaptureAudioSystemeWasapi
from debrief_meet.platform.windows.demarrage_auto import DemarrageAutoWindows
from debrief_meet.platform.windows.moteur_faster_whisper import MoteurFasterWhisper
from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows
from debrief_meet.platform.windows.raccourcis_win32 import RaccourcisGlobauxWindows


@pytest.fixture(autouse=True)
def _edition(edition_complete_sauf_si_lite):
    """Sujet du module : le moteur faster-whisper local — édition complète épinglée sauf test lite explicite
    (docs/44)."""


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


# ── Édition lite (docs/44) ───────────────────────────────────────────────────

def test_lite_aucun_moteur_local(qapp, edition_lite):
    """LE test de contrat de l'édition lite : c'est lui qui attrape « bundle livré sans
    ctranslate2 mais la fabrique construit quand même le moteur CT2 ».

    Un garde `except ImportError` ne suffirait PAS : `moteur_faster_whisper.py` n'importe
    `faster_whisper` nulle part au niveau module (c'est le sous-processus worker qui le
    fait), donc le moteur se construirait sans erreur et ne mourrait qu'à la première
    transcription, chez l'utilisateur.
    """
    adaptateurs = _windows()
    try:
        assert adaptateurs.moteur is None
        # Le reste de la chaîne d'enregistrement doit rester intact.
        assert isinstance(adaptateurs.systeme, CaptureAudioSystemeWasapi)
        assert isinstance(adaptateurs.presse_papiers, PressePapiersWindows)
    finally:
        QCoreApplication.instance().removeNativeEventFilter(adaptateurs.raccourcis._filtre)
