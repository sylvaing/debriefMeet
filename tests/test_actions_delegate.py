from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem

from debrief_meet.ui.actions_delegate import (
    ESPACEMENT,
    LARGEUR_FLECHE,
    MARGE_DROITE,
    TAILLE_BOUTON,
    ActionsDelegate,
    ActionsLigne,
    ActionSpec,
    BoutonSpec,
    largeur_colonne,
)


def _index():
    modele = QStandardItemModel(1, 1)
    return modele.index(0, 0)


def _option(largeur=210, hauteur=52):
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, largeur, hauteur)
    return option


def _release_event(pos) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _menu_type():
    return [ActionSpec("copy", "Copier", True, lambda: None),
            ActionSpec("trash", "Supprimer", True, lambda: None, danger=True, separateur_avant=True)]


def _zone(delegate, option, ligne, genre, icone=None):
    for zone in delegate._zones(option, ligne):
        if zone.genre != genre:
            continue
        if icone is None or (zone.bouton is not None and zone.bouton.icone == icone):
            return zone
    raise AssertionError(f"zone {genre}/{icone} introuvable")


# ── Peinture ─────────────────────────────────────────────────────────────────────

def test_paint_sans_actions_ne_leve_pas(qapp):
    delegate = ActionsDelegate(lambda idx: ActionsLigne())
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


def test_paint_avec_boutons_menu_et_fleche_ne_leve_pas(qapp):
    ligne = ActionsLigne(
        boutons=[
            BoutonSpec("notebook", "Générer le CR", True, lambda: None,
                       menu_deroulant=[ActionSpec("notebook", "CR simple", True, lambda: None)]),
            BoutonSpec("copy", "Copier le CR", False, lambda: None),  # inactif : peint grisé
        ],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


# ── Zones & clics ────────────────────────────────────────────────────────────────

def test_clic_sur_bouton_actif_declenche_le_callback(qapp):
    appele = []
    ligne = ActionsLigne(
        boutons=[BoutonSpec("copy", "Copier", True, lambda: appele.append(True))],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    option = _option()
    rect = _zone(delegate, option, ligne, "bouton").rect

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is True
    assert appele == [True]


def test_clic_sur_bouton_inactif_ne_declenche_rien(qapp):
    appele = []
    ligne = ActionsLigne(
        boutons=[BoutonSpec("copy", "Copier", False, lambda: appele.append(True))],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    option = _option()
    rect = _zone(delegate, option, ligne, "bouton").rect

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is False
    assert appele == []


def test_clic_sur_menu_ouvre_le_popover_avec_toutes_les_actions(qapp, monkeypatch):
    ouverts = []

    class _MenuFactice:
        def popup(self, *_a, **_k):
            ouverts.append(True)

    recus = []

    def _construire(specs, parent=None):
        recus.append(specs)
        return _MenuFactice()

    monkeypatch.setattr("debrief_meet.ui.actions_menu.construire_menu_actions", _construire)

    menu = _menu_type()
    ligne = ActionsLigne(boutons=[BoutonSpec("copy", "Copier", True, lambda: None)], menu=menu)
    delegate = ActionsDelegate(lambda idx: ligne)
    option = _option()
    rect = _zone(delegate, option, ligne, "menu").rect

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is True
    assert ouverts == [True]
    assert recus == [menu]  # le menu ⋯ reçoit la liste complète, Copier inclus


def test_clic_sur_fleche_ouvre_le_menu_deroulant_du_bouton(qapp, monkeypatch):
    recus = []

    class _MenuFactice:
        def popup(self, *_a, **_k):
            pass

    monkeypatch.setattr(
        "debrief_meet.ui.actions_menu.construire_menu_actions",
        lambda specs, parent=None: recus.append(specs) or _MenuFactice())

    deroulant = [ActionSpec("notebook", "CR simple", True, lambda: None),
                 ActionSpec("notebook", "CR détaillé", True, lambda: None)]
    ligne = ActionsLigne(
        boutons=[BoutonSpec("notebook", "Générer le CR", True, lambda: None,
                            menu_deroulant=deroulant)],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    option = _option()
    rect = _zone(delegate, option, ligne, "fleche").rect

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is True
    assert recus == [deroulant]


def test_fleche_absente_sans_menu_deroulant(qapp):
    ligne = ActionsLigne(boutons=[BoutonSpec("copy", "Copier", True, lambda: None)],
                         menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    genres = [z.genre for z in delegate._zones(_option(), ligne)]
    assert genres == ["bouton", "menu"]


def test_fleche_accolee_a_droite_de_son_bouton(qapp):
    ligne = ActionsLigne(
        boutons=[BoutonSpec("notebook", "Générer le CR", True, lambda: None,
                            menu_deroulant=[ActionSpec("notebook", "CR simple", True, lambda: None)]),
                 BoutonSpec("copy", "Copier le CR", True, lambda: None)],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    zones = delegate._zones(_option(), ligne)
    genres = [z.genre for z in zones]
    assert genres == ["bouton", "fleche", "bouton", "menu"]
    bouton, fleche = zones[0], zones[1]
    assert fleche.rect.left() == bouton.rect.left() + bouton.rect.width()  # accolée, sans gap


# ── Largeurs ─────────────────────────────────────────────────────────────────────

def test_largeur_colonne_journal_et_reunion():
    # La FORMULE seulement — que chaque vue lui passe le bon nombre de boutons est
    # vérifié côté vue (test_reunion_view.py :
    # test_colonne_actions_dimensionnee_pour_les_boutons_reellement_produits).
    # Journal : Copier + ⋯. Réunion : Générer le CR ▾ + Copier le CR + Copier le
    # fichier + ⋯.
    assert largeur_colonne(1) == MARGE_DROITE + 2 * TAILLE_BOUTON + ESPACEMENT
    assert largeur_colonne(3, nb_fleches=1) == (
        MARGE_DROITE + 4 * TAILLE_BOUTON + LARGEUR_FLECHE + 3 * ESPACEMENT)


def test_size_hint_suit_les_boutons_pas_le_menu(qapp):
    menu_court = _menu_type()
    menu_long = menu_court + [ActionSpec("trash", f"Action {i}", True, lambda: None) for i in range(5)]
    boutons = [BoutonSpec("copy", "Copier", True, lambda: None)]

    d_court = ActionsDelegate(lambda idx: ActionsLigne(boutons=boutons, menu=menu_court))
    d_long = ActionsDelegate(lambda idx: ActionsLigne(boutons=boutons, menu=menu_long))
    assert d_court.sizeHint(_option(), _index()).width() == d_long.sizeHint(_option(), _index()).width()
    assert d_court.sizeHint(_option(), _index()).width() == largeur_colonne(1)


def test_boutons_ne_debordent_pas_quand_colonne_a_la_largeur_du_sizehint(qapp):
    # Régression : une colonne trop étroite faisait déborder les boutons à gauche,
    # jusqu'à chevaucher la colonne « lien calendrier ». La colonne doit être
    # dimensionnée sur sizeHint pour que toutes les zones tiennent dedans.
    ligne = ActionsLigne(
        boutons=[BoutonSpec("notebook", "Générer le CR", True, lambda: None,
                            menu_deroulant=[ActionSpec("notebook", "CR simple", True, lambda: None)]),
                 BoutonSpec("copy", "Copier le CR", True, lambda: None)],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    largeur = delegate.sizeHint(_option(), _index()).width()
    option = _option(largeur=largeur)
    for zone in delegate._zones(option, ligne):
        assert zone.rect.left() >= option.rect.left()


# ── Évènements non-souris routés vers editorEvent ────────────────────────────────

def _key_event(touche=Qt.Key.Key_A, texte="a") -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, touche, Qt.KeyboardModifier.NoModifier, texte)


def test_editor_event_ignore_les_evenements_clavier(qapp):
    """Régression du 2026-08-24 (terrain Windows) : Qt ne route pas que la souris vers
    editorEvent — `QAbstractItemView::keyPressEvent` appelle `edit(currentIndex(),
    AnyKeyPressed, event)`, et `edit()` passe l'évènement au délégué AVANT de vérifier
    les editTriggers. Un QKeyEvent n'a ni `position()` ni `pos()` : lire la position
    sans filtrer le type levait AttributeError, soit un CRITICAL par frappe dès que la
    cellule courante était dans la colonne actions."""
    ligne = ActionsLigne(
        boutons=[BoutonSpec("notebook", "Générer le CR", True, lambda: None)],
        menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    assert delegate.editorEvent(_key_event(), QStandardItemModel(1, 1), _option(), _index()) is False


def test_editor_event_ignore_f2_touche_d_edition(qapp):
    """`EditKeyPressed` (F2 sous Windows) passe par le même chemin, avec un QKeyEvent
    dont `text()` est vide — l'autre porte d'entrée du même crash."""
    ligne = ActionsLigne(boutons=[BoutonSpec("copy", "Copier", True, lambda: None)], menu=_menu_type())
    delegate = ActionsDelegate(lambda idx: ligne)
    assert delegate.editorEvent(_key_event(Qt.Key.Key_F2, ""), QStandardItemModel(1, 1),
                                _option(), _index()) is False


def test_un_clavier_ne_declenche_aucune_action(qapp):
    """Le filtre ne doit pas seulement éviter le crash : aucune action de la ligne ne
    doit partir sur une frappe (le clic, lui, reste couvert par les tests ci-dessus)."""
    appels = []
    ligne = ActionsLigne(
        boutons=[BoutonSpec("copy", "Copier", True, lambda: appels.append("bouton"))],
        menu=[ActionSpec("copy", "Copier", True, lambda: appels.append("menu"))])
    delegate = ActionsDelegate(lambda idx: ligne)
    delegate.editorEvent(_key_event(), QStandardItemModel(1, 1), _option(), _index())
    assert appels == []
