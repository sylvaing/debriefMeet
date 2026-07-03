"""Tests unitaires — arreter_thread() / proteger_thread() (docs/26)."""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QThread

from debrief_meet.core import arret_threads
from debrief_meet.core.arret_threads import arreter_thread, proteger_thread


class _ThreadRapide(QThread):
    def run(self) -> None:
        time.sleep(0.05)


class _ThreadBloquante(QThread):
    def __init__(self, event: threading.Event) -> None:
        super().__init__()
        self._event = event

    def run(self) -> None:
        self._event.wait()


def test_cas_nominal_thread_rapide(qapp):
    avant = len(arret_threads._threads_fuites)
    thread = _ThreadRapide()
    thread.start()

    ok = arreter_thread(thread, 2_000)

    assert ok is True
    assert not thread.isRunning()
    assert len(arret_threads._threads_fuites) == avant


def test_timeout_puis_deblocage_reussit(qapp):
    event = threading.Event()
    thread = _ThreadBloquante(event)
    thread.start()
    time.sleep(0.05)  # laisse le thread démarrer et se bloquer sur l'event

    ok = arreter_thread(thread, 100, debloquer=event.set, timeout_deblocage_ms=2_000)

    assert ok is True
    assert not thread.isRunning()


def test_fuite_volontaire_sans_deblocage(qapp):
    event = threading.Event()
    thread = _ThreadBloquante(event)
    parent = QObject()
    thread.setParent(parent)
    thread.start()
    time.sleep(0.05)

    marqueur = object()
    try:
        ok = arreter_thread(thread, 50, garder=(marqueur,))

        assert ok is False
        assert thread.parent() is None
        assert any(t is thread and marqueur in g for t, g in arret_threads._threads_fuites)
    finally:
        # Nettoyage : débloquer réellement le thread pour ne pas polluer les tests suivants.
        event.set()
        thread.wait(2_000)
        arret_threads._threads_fuites[:] = [
            (t, g) for t, g in arret_threads._threads_fuites if t is not thread
        ]


def test_deblocage_inoperant_finit_en_fuite_volontaire(qapp):
    """Le callback `debloquer` est appelé mais ne débloque rien (thread toujours vivant
    après le re-wait) → fuite volontaire malgré tout."""
    event = threading.Event()
    thread = _ThreadBloquante(event)
    appels_deblocage = []

    def _deblocage_inoperant():
        appels_deblocage.append(1)
        # ne fait rien : n'appelle pas event.set()

    thread.start()
    time.sleep(0.05)
    try:
        ok = arreter_thread(thread, 50, debloquer=_deblocage_inoperant, timeout_deblocage_ms=50)

        assert ok is False
        assert appels_deblocage == [1]
        assert thread.parent() is None
    finally:
        event.set()
        thread.wait(2_000)
        arret_threads._threads_fuites[:] = [
            (t, g) for t, g in arret_threads._threads_fuites if t is not thread
        ]


def test_thread_deja_arrete_retourne_vrai_sans_effet(qapp):
    thread = _ThreadRapide()
    # Jamais démarré : isRunning() est False.
    assert arreter_thread(thread, 100) is True


def test_proteger_thread_retire_a_la_fin(qapp, qtbot):
    thread = _ThreadRapide()
    worker = object()

    proteger_thread(thread, worker)
    assert any(t is thread for t, _g in arret_threads._threads_vivants)

    with qtbot.waitSignal(thread.finished, timeout=2_000):
        thread.start()

    qtbot.waitUntil(
        lambda: not any(t is thread for t, _g in arret_threads._threads_vivants),
        timeout=2_000,
    )
