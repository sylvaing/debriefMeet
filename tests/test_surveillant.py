"""Tests unitaires — SurveillantPeripheriques : anti-rebond et suppression des
signaux Qt parasites (Windows uniquement, docs/44 §8).

`supprimer_parasites` est passé **explicitement** partout : le défaut dépend de
`sys.platform`, et ces tests tournent aussi sur la VM Windows (gate de build).
"""
from __future__ import annotations

import sys

from debrief_meet.platform.commun.surveillant_peripheriques import SurveillantPeripheriques


def _surveillant(supprimer=False, debounce_ms=80):
    return SurveillantPeripheriques(debounce_ms=debounce_ms, supprimer_parasites=supprimer)


# ── Anti-rebond (comportement historique) ────────────────────────────────────

def test_rafale_evenements_emet_un_seul_change(qapp, qtbot):
    """Plusieurs changements rapprochés (un retrait en émet plusieurs) → 1 seul `change`."""
    s = _surveillant()
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    s._planifier()
    s._planifier()

    qtbot.wait(200)
    assert len(recus) == 1


def test_aucun_evenement_aucun_change(qapp, qtbot):
    s = _surveillant()
    recus = []
    s.change.connect(lambda: recus.append(1))

    qtbot.wait(200)
    assert recus == []


def test_deux_salves_espacees_emettent_deux_change(qapp, qtbot):
    s = _surveillant()
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    qtbot.wait(200)
    s._planifier()
    qtbot.wait(200)

    assert len(recus) == 2


# ── Suppression des parasites : Windows seulement (docs/44 §8) ───────────────

def test_windows_liste_inchangee_ignore_l_evenement(qapp, qtbot, monkeypatch):
    """3086 événements à liste identique mesurés chez Alix — chacun coûtait une
    reconnexion micro qui affamait le flux."""
    s = _surveillant(supprimer=True)
    monkeypatch.setattr(s, "_releve_entrees", lambda: ("Micro interne",))
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()          # relevé initial → jamais ignoré
    qtbot.wait(200)
    assert len(recus) == 1

    s._planifier()          # liste inchangée → ignoré
    s._planifier()
    qtbot.wait(200)
    assert len(recus) == 1, "un événement à liste inchangée ne doit pas reconnecter"


def test_windows_liste_modifiee_emet_toujours(qapp, qtbot, monkeypatch):
    """Le cas qui compte : casque Bluetooth branché/débranché (3 fois chez Alix)."""
    s = _surveillant(supprimer=True)
    entrees = ["Micro interne"]
    monkeypatch.setattr(s, "_releve_entrees", lambda: tuple(entrees))
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    qtbot.wait(200)
    entrees.append("Headset (casque Bluetooth)")
    s._planifier()
    qtbot.wait(200)

    assert len(recus) == 2, "un vrai changement de liste doit toujours reconnecter"


def test_hors_windows_liste_inchangee_emet_quand_meme(qapp, qtbot, monkeypatch):
    """Garde-fou macOS : la reconnexion inconditionnelle de docs/25 couvre des cas que
    la comparaison sur `description()` ne verrait PAS (taux d'échantillonnage AirPods à
    périphérique constant, docs/20 ; changement de périphérique par défaut à liste
    constante). Aucune donnée macOS ne permet de les supprimer sans risque."""
    s = _surveillant(supprimer=False)
    monkeypatch.setattr(s, "_releve_entrees", lambda: ("Micro interne",))
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    qtbot.wait(200)
    s._planifier()
    qtbot.wait(200)

    assert len(recus) == 2, "hors Windows, le comportement historique doit être intact"


def test_releve_indisponible_n_ignore_jamais(qapp, qtbot, monkeypatch):
    """Fail-open : une panne de l'instrumentation ne doit pas désactiver en silence la
    reconnexion à chaud. Dans le doute, on reconnecte."""
    s = _surveillant(supprimer=True)
    monkeypatch.setattr(s, "_releve_entrees", lambda: ())
    recus = []
    s.change.connect(lambda: recus.append(1))

    s._planifier()
    qtbot.wait(200)
    s._planifier()
    qtbot.wait(200)

    assert len(recus) == 2


def test_defaut_suit_la_plateforme(qapp):
    """Windows supprime, les autres non — sans avoir à le préciser à l'appel."""
    assert _surveillant(supprimer=None)._supprimer_parasites is (sys.platform == "win32")
