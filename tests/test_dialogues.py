"""Gabarit des dialogues (docs/50) — débordement et overlay enfant.

Les deux premiers tests sont ceux qui **auraient attrapé le bug d'origine** : sur un
événement à ~34 invités, la carte poussait « Annuler / Associer » hors de l'écran et le
dialogue n'avait plus d'autre sortie que la touche Échap.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QWidget

from debrief_meet.ui.dialogues import CarteFlottante, DialogueGabarit, Intention


def _hote(qapp, largeur: int = 900, hauteur: int = 420) -> QWidget:
    fenetre = QWidget()
    fenetre.resize(largeur, hauteur)
    fenetre.show()
    qapp.processEvents()
    return fenetre


def _gabarit(parent: QWidget | None, lignes: int = 0) -> DialogueGabarit:
    dlg = DialogueGabarit(
        parent, titre="Associer à un événement",
        description="Un événement du calendrier BlueMind correspond à cette réunion.",
        icone="calendar-check", intention=Intention.ACCENT)
    for i in range(lignes):
        dlg.zone_corps.addWidget(QLabel(f"participant.{i}@example.com — sans réponse"))
    dlg.definir_action("Associer")
    return dlg


def _bas_de_carte(dlg: CarteFlottante) -> int:
    """Ordonnée du bas de la carte, dans le repère du dialogue."""
    return dlg._carte.mapTo(dlg, dlg._carte.rect().bottomLeft()).y()


# ── Débordement : le pied doit rester atteignable ──────────────────────────────

def test_contenu_trop_haut_reste_dans_la_fenetre(qapp):
    """40 participants dans une fenêtre de 420 px : la carte tient quand même, et le
    bouton d'action reste dans le rectangle du dialogue."""
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=40)
    dlg.show()
    qapp.processEvents()

    assert dlg._carte.height() <= fenetre.height()
    assert _bas_de_carte(dlg) <= dlg.height()
    bouton = dlg.bouton_action()
    assert bouton.mapTo(dlg, bouton.rect().bottomLeft()).y() <= dlg.height()


def test_contenu_trop_haut_rend_le_corps_defilant(qapp):
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=40)
    dlg.show()
    qapp.processEvents()

    barre = dlg._defilement.verticalScrollBar()
    assert barre.maximum() > 0          # il y a bien de quoi défiler


def test_dialogue_court_garde_sa_taille_naturelle(qapp):
    """Non-régression `confirmer`/`informer`/`avertir` : le `QScrollArea` ne doit pas
    raboter les dialogues qui tiennent — c'est tout l'objet de `_ZoneDefilante`."""
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=2)
    dlg.show()
    qapp.processEvents()

    assert dlg._defilement.verticalScrollBar().maximum() == 0
    assert dlg._defilement.height() >= dlg._contenu_corps.sizeHint().height()


def test_dialogue_sans_corps_ne_gagne_pas_d_espace(qapp):
    """Une confirmation (`confirmer`, `informer`, `avertir`) n'a pas de corps : la zone
    défilante doit être masquée, sinon l'espacement du layout lui ajoute 18 px de blanc
    entre la description et les boutons."""
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=0)
    dlg.show()
    qapp.processEvents()

    assert dlg._defilement.isVisible() is False
    assert dlg._defilement.height() == 0


# ── Overlay enfant : suit la fenêtre hôte ──────────────────────────────────────

def test_avec_parent_le_dialogue_est_un_enfant_de_la_fenetre(qapp):
    fenetre = _hote(qapp)
    interieur = QWidget(fenetre)          # parent ≠ fenêtre : c'est `window()` qui compte
    dlg = _gabarit(interieur, lignes=1)
    dlg.show()
    qapp.processEvents()

    assert dlg.isWindow() is False
    assert dlg.parentWidget() is fenetre
    assert dlg.geometry() == fenetre.rect()


def test_redimensionner_la_fenetre_redimensionne_l_overlay(qapp):
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=1)
    dlg.show()
    qapp.processEvents()

    fenetre.resize(640, 300)
    qapp.processEvents()
    assert dlg.geometry() == fenetre.rect()


def test_sans_parent_reste_une_fenetre_centree(qapp):
    """Chemin conservé pour les appels sans parent : aucun hôte où se greffer."""
    dlg = _gabarit(None, lignes=1)
    dlg.show()
    qapp.processEvents()

    assert dlg.isWindow() is True
    dlg.close()


def test_exec_embarque_rend_le_code_de_sortie(qapp):
    """L'émulation par boucle imbriquée doit respecter le contrat de `QDialog.exec()`."""
    fenetre = _hote(qapp)

    dlg = _gabarit(fenetre, lignes=1)
    QTimer.singleShot(0, dlg.accept)
    assert dlg.exec() == QDialog.DialogCode.Accepted

    autre = _gabarit(fenetre, lignes=1)
    QTimer.singleShot(0, autre.reject)
    assert autre.exec() == QDialog.DialogCode.Rejected


def test_filtre_survit_a_la_destruction_de_l_hote(qapp):
    """Un overlay encore ouvert quand l'application se ferme ne doit pas cracher : à ce
    moment l'hôte est détruit et les attributs Python de l'overlay sont déjà purgés."""
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=1)
    dlg.show()
    qapp.processEvents()

    del dlg.__dict__["_hote"]            # simule la purge d'attributs de la destruction
    fenetre.resize(500, 260)
    qapp.processEvents()                 # ne doit lever aucune AttributeError


def test_fermeture_depose_le_filtre_sur_la_fenetre(qapp):
    """Un overlay fermé ne doit plus suivre l'hôte — sinon chaque dialogue ouvert dans
    la session laisserait un filtre actif sur la fenêtre principale."""
    fenetre = _hote(qapp)
    dlg = _gabarit(fenetre, lignes=1)
    dlg.show()
    qapp.processEvents()
    dlg.accept()
    qapp.processEvents()

    geo_avant = dlg.geometry()
    fenetre.resize(500, 260)
    qapp.processEvents()
    assert dlg.geometry() == geo_avant
