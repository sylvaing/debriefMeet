from __future__ import annotations

import logging

from debrief_meet.platform.commun.micro_sounddevice import CaptureMicroSounddevice
from debrief_meet.platform.factory import _linux
from debrief_meet.platform.linux.demarrage_auto import DemarrageAutoLinux
from debrief_meet.platform.linux.presse_papiers import PressePapiersLinux
from debrief_meet.platform.stubs import RaccourcisStub


def test_adaptateurs_ecrits_sont_bien_cables(qapp, mode_distant):
    adaptateurs = _linux()
    assert isinstance(adaptateurs.micro, CaptureMicroSounddevice)
    assert isinstance(adaptateurs.presse_papiers, PressePapiersLinux)
    assert isinstance(adaptateurs.demarrage_auto, DemarrageAutoLinux)


def test_distant_aucun_moteur_local(qapp, mode_distant):
    """LE test de contrat du mode distant (docs/45), transposé à Linux : la fabrique
    ne construit aucun moteur, et le reste de la chaîne d'enregistrement tient."""
    adaptateurs = _linux()
    assert adaptateurs.moteur is None
    assert isinstance(adaptateurs.micro, CaptureMicroSounddevice)
    assert isinstance(adaptateurs.presse_papiers, PressePapiersLinux)


def test_mode_local_donne_un_stub_et_previent(qapp, mode_local, caplog):
    """v1 = distant seul (docs/49 L1). Forcer `mode_transcription: local` sur Linux ne
    doit pas produire un moteur silencieusement inopérant : stub + WARNING explicite."""
    from debrief_meet.platform.stubs import MoteurStub

    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        adaptateurs = _linux()

    assert isinstance(adaptateurs.moteur, MoteurStub)
    assert any("aucun moteur local n'existe sur Linux" in r.message for r in caplog.records)


def test_capture_systeme_est_l_adaptateur_monitor(qapp, mode_distant):
    """docs/49 §5.1 : la capture système passe par les sources `.monitor` PipeWire.
    Ce test remplace celui qui vérifiait le stub d'attente, retiré avec lui."""
    from debrief_meet.platform.linux.capture_systeme_monitor import CaptureAudioSystemeMonitor

    assert isinstance(_linux().systeme, CaptureAudioSystemeMonitor)


def test_raccourcis_globaux_hors_v1(qapp, mode_distant):
    """Décision L2 : Wayland, reportés au portail XDG. Le stub est le comportement
    attendu, pas un accident."""
    assert isinstance(_linux().raccourcis, RaccourcisStub)
