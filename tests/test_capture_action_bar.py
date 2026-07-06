from __future__ import annotations

from debrief_meet.core.modes import Mode
from debrief_meet.ui.capture_action_bar import CaptureActionBar
from debrief_meet.ui.chrono import formater_chrono


def test_formater_chrono():
    assert formater_chrono(0) == "00:00"
    assert formater_chrono(42) == "00:42"
    assert formater_chrono(125) == "02:05"
    assert formater_chrono(3661) == "61:01"


def test_etat_repos_bouton_actif_et_pas_de_chrono(qapp):
    barre = CaptureActionBar(Mode.REUNION, avec_recherche=False)
    barre.definir_etat(Mode.IDLE)
    assert barre._bouton.isEnabled()
    assert barre._chrono.isHidden()
    assert barre._point.isHidden()
    assert barre._msg_autre.isHidden()
    assert "Démarrer la réunion" in barre._bouton.text()


def test_etat_actif_affiche_point_et_chrono(qapp):
    barre = CaptureActionBar(Mode.REUNION, avec_recherche=False)
    barre.definir_etat(Mode.REUNION, secondes=90)
    assert barre._bouton.isEnabled()
    assert not barre._chrono.isHidden()
    assert barre._chrono.text() == "01:30"
    assert not barre._point.isHidden()
    assert "Arrêter" in barre._bouton.text()


def test_etat_autre_type_grise_le_bouton(qapp):
    barre = CaptureActionBar(Mode.DICTEE, avec_recherche=False)
    barre.definir_etat(Mode.REUNION, secondes=5)
    assert not barre._bouton.isEnabled()
    assert not barre._msg_autre.isHidden()
    assert barre._chrono.isHidden()


def test_clic_emet_demande_bascule(qapp, qtbot):
    barre = CaptureActionBar(Mode.JOURNAL, avec_recherche=False)
    with qtbot.waitSignal(barre.demande_bascule, timeout=1000):
        barre._bouton.click()


def test_clic_desactive_n_emet_rien(qapp, qtbot):
    barre = CaptureActionBar(Mode.DICTEE, avec_recherche=False)
    barre.definir_etat(Mode.REUNION)
    appels = []
    barre.demande_bascule.connect(lambda: appels.append(True))
    barre._bouton.click()
    assert appels == []


def test_recherche_optionnelle(qapp):
    sans = CaptureActionBar(Mode.DICTEE, avec_recherche=False)
    assert sans._recherche is None

    avec = CaptureActionBar(Mode.REUNION, avec_recherche=True, placeholder_recherche="Rechercher…")
    assert avec._recherche is not None
    assert avec._recherche.placeholderText() == "Rechercher…"


def test_recherche_change_emet_le_texte(qapp, qtbot):
    barre = CaptureActionBar(Mode.REUNION, avec_recherche=True)
    with qtbot.waitSignal(barre.recherche_change, timeout=1000) as bloqueur:
        barre._recherche.setText("devis")
    assert bloqueur.args == ["devis"]
