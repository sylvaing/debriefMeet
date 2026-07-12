from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem

from debrief_meet.ui.actions_delegate import ActionSpec, ActionsDelegate


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


def test_paint_sans_actions_ne_leve_pas(qapp):
    delegate = ActionsDelegate(lambda idx: [])
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


def test_paint_avec_actions_ne_leve_pas(qapp):
    specs = [
        ActionSpec("copy", "Copier", True, lambda: None),
        ActionSpec("trash", "Supprimer", True, lambda: None, danger=True, separateur_avant=True),
    ]
    delegate = ActionsDelegate(lambda idx: specs)
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


def test_clic_sur_copier_actif_declenche_le_callback(qapp):
    appele = []
    specs = [ActionSpec("copy", "Copier", True, lambda: appele.append(True))]
    delegate = ActionsDelegate(lambda idx: specs)
    option = _option()
    rect = delegate._rect_copier(option)

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is True
    assert appele == [True]


def test_clic_sur_copier_inactif_ne_declenche_rien(qapp):
    appele = []
    specs = [ActionSpec("copy", "Copier", False, lambda: appele.append(True))]
    delegate = ActionsDelegate(lambda idx: specs)
    option = _option()
    rect = delegate._rect_copier(option)

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is False
    assert appele == []


def test_clic_sur_menu_ouvre_le_popover(qapp, monkeypatch):
    import debrief_meet.ui.actions_delegate as ad_module

    ouverts = []
    monkeypatch.setattr(
        ad_module, "_ouvrir_menu_stub", None, raising=False)

    class _MenuFactice:
        def popup(self, *_a, **_k):
            ouverts.append(True)

    monkeypatch.setattr(
        "debrief_meet.ui.actions_menu.construire_menu_actions", lambda specs, parent=None: _MenuFactice())

    specs = [
        ActionSpec("copy", "Copier", True, lambda: None),
        ActionSpec("trash", "Supprimer", True, lambda: None, danger=True),
    ]
    delegate = ActionsDelegate(lambda idx: specs)
    option = _option()
    rect = delegate._rect_menu(option)

    consomme = delegate.editorEvent(_release_event(rect.center()), None, option, _index())
    assert consomme is True
    assert ouverts == [True]


def test_size_hint_stable_quel_que_soit_le_nombre_d_actions(qapp):
    delegate = ActionsDelegate(lambda idx: [])
    taille_vide = delegate.sizeHint(_option(), _index())

    beaucoup = [ActionSpec("copy", "Copier", True, lambda: None)] + [
        ActionSpec("trash", f"Action {i}", True, lambda: None) for i in range(5)
    ]
    delegate_rempli = ActionsDelegate(lambda idx: beaucoup)
    taille_remplie = delegate_rempli.sizeHint(_option(), _index())

    # Largeur fixe (2 boutons) — n'augmente pas avec le nombre d'actions dans le menu ⋯.
    assert taille_vide.width() == taille_remplie.width()
    assert taille_vide.width() > 0


def test_copier_ne_deborde_pas_quand_colonne_a_la_largeur_du_sizehint(qapp):
    # Régression : une colonne trop étroite faisait déborder le bouton Copier à
    # gauche, jusqu'à chevaucher la colonne « lien calendrier ». La colonne doit
    # être dimensionnée sur sizeHint pour que les 2 boutons tiennent dedans.
    specs = [
        ActionSpec("copy", "Copier", True, lambda: None),
        ActionSpec("trash", "Supprimer", True, lambda: None),
    ]
    delegate = ActionsDelegate(lambda idx: specs)
    largeur = delegate.sizeHint(_option(), _index()).width()
    option = _option(largeur=largeur)
    rect_copier = delegate._rect_copier(option)
    assert rect_copier.left() >= option.rect.left()
