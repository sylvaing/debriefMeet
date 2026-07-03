"""Tests unitaires — CaptureAudioSCK, escalade d'arrêt du helper (docs/23 correctif 2).

QUIT → wait(3s) → SIGTERM → wait(2s) → SIGKILL en dernier recours, jamais un
SIGKILL immédiat qui court-circuiterait stopCapture() côté Swift.
"""
from __future__ import annotations

import subprocess
from unittest.mock import Mock

from debrief_meet.platform.macos.capture_systeme import CaptureAudioSCK


def _capture_avec_proc_factice() -> tuple[CaptureAudioSCK, Mock]:
    capture = CaptureAudioSCK()
    proc = Mock(spec=subprocess.Popen)
    proc.poll.return_value = None
    proc.stdin = Mock()
    capture._proc = proc
    return capture, proc


def test_quit_repond_a_temps_pas_de_terminate_ni_kill():
    capture, proc = _capture_avec_proc_factice()
    proc.wait.return_value = 0

    capture.arreter()

    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()
    assert capture._proc is None


def test_quit_timeout_sigterm_repond_kill_pas_appele():
    capture, proc = _capture_avec_proc_factice()
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=3), 0]

    capture.arreter()

    proc.terminate.assert_called_once()
    proc.kill.assert_not_called()
    assert capture._proc is None


def test_quit_et_sigterm_timeout_kill_en_dernier():
    capture, proc = _capture_avec_proc_factice()
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="x", timeout=3),
        subprocess.TimeoutExpired(cmd="x", timeout=2),
        0,
    ]

    capture.arreter()

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert capture._proc is None
