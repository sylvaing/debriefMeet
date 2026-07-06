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


def test_paint_sans_actions_ne_leve_pas(qapp):
    delegate = ActionsDelegate(lambda idx: [])
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


def test_paint_avec_actions_ne_leve_pas(qapp):
    specs = [
        ActionSpec("copy", "Copier", True, lambda: None),
        ActionSpec("trash", "Supprimer", False, lambda: None),
    ]
    delegate = ActionsDelegate(lambda idx: specs)
    pixmap = QPixmap(210, 52)
    painter = QPainter(pixmap)
    delegate.paint(painter, _option(), _index())
    painter.end()


def test_clic_sur_bouton_actif_declenche_le_callback(qapp):
    appele = []
    specs = [ActionSpec("copy", "Copier", True, lambda: appele.append(True))]
    delegate = ActionsDelegate(lambda idx: specs)
    option = _option()
    rect = delegate._rects(option, specs)[0]

    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease, rect.center(), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    consomme = delegate.editorEvent(event, None, option, _index())
    assert consomme is True
    assert appele == [True]


def test_clic_sur_bouton_inactif_ne_declenche_rien(qapp):
    appele = []
    specs = [ActionSpec("copy", "Copier", False, lambda: appele.append(True))]
    delegate = ActionsDelegate(lambda idx: specs)
    option = _option()
    rect = delegate._rects(option, specs)[0]

    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease, rect.center(), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    consomme = delegate.editorEvent(event, None, option, _index())
    assert consomme is False
    assert appele == []


def test_size_hint_zero_sans_actions(qapp):
    delegate = ActionsDelegate(lambda idx: [])
    taille = delegate.sizeHint(_option(), _index())
    assert taille.width() == 0
