from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem
from PySide6.QtCore import Qt

from debrief_meet.ui.status_pill import HistoryState, StatusPillDelegate, badge_pour_etat


@pytest.mark.parametrize("etat", list(HistoryState))
def test_badge_pour_etat_a_un_libelle_et_des_couleurs(etat):
    badge = badge_pour_etat(etat)
    assert badge.label
    assert badge.fg.startswith("#")
    assert badge.bg.startswith("#")
    assert badge.icone


@pytest.mark.parametrize("etat", list(HistoryState))
def test_delegate_peint_sans_exception(qapp, etat):
    modele = QStandardItemModel(1, 1)
    modele.setData(modele.index(0, 0), etat, Qt.ItemDataRole.UserRole)

    delegate = StatusPillDelegate()
    pixmap = QPixmap(160, 52)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 160, 52)
    delegate.paint(painter, option, modele.index(0, 0))
    painter.end()


def test_delegate_repli_sur_le_rendu_standard_si_pas_un_historystate(qapp):
    modele = QStandardItemModel(1, 1)
    modele.setData(modele.index(0, 0), "texte quelconque", Qt.ItemDataRole.DisplayRole)

    delegate = StatusPillDelegate()
    pixmap = QPixmap(160, 52)
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 160, 52)
    delegate.paint(painter, option, modele.index(0, 0))
    painter.end()
