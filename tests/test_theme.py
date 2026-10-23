from __future__ import annotations

from debrief_meet.ui.theme import C, M, charger_theme, color


def test_charger_theme_applique_le_qss(qapp):
    charger_theme(qapp)
    qss = qapp.styleSheet()
    assert qss
    assert "__CHECK_WHITE__" not in qss  # jeton bien substitué
    assert "#3B5BDB" in qss  # accent (QPushButton#primary)


def test_couleur_helper(qapp):
    assert color(C.ACCENT).name().upper() == C.ACCENT

    q = color(C.ACCENT)
    assert q.isValid()


def test_metriques_positives():
    for nom in ("TITLEBAR_H", "TOOLBAR_H", "ROW_H", "PAD_CONTENT", "PAD_FORM", "PREF_NAV_W"):
        assert getattr(M, nom) > 0


# ---------------------------------------------------------------------------
# Rectangle de focus parasite (cadre autour de l'index courant sous Windows)
# ---------------------------------------------------------------------------

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QStyle,
    QStyleFactory,
    QStyleOptionFocusRect,
    QStyleOptionViewItem,
    QTableView,
)

from debrief_meet.ui.icon_delegate import IconeColonneDelegate  # noqa: E402
from debrief_meet.ui.theme import StyleSansCadreFocus, installer_style  # noqa: E402

_FOCUS = QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_KeyboardFocusChange


def _image_vierge(w=120, h=40):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    return img


def _cadre_focus(style):
    img = _image_vierge()
    opt = QStyleOptionFocusRect()
    opt.rect = QRect(4, 4, 100, 30)
    opt.state = _FOCUS | QStyle.StateFlag.State_Enabled
    p = QPainter(img)
    style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, opt, p, None)
    p.end()
    return img


def test_proxy_ne_dessine_pas_le_cadre_de_focus(qapp):
    # Témoin : Fusion seul dessine bien le cadre — sinon le test passerait à vide.
    assert _cadre_focus(QStyleFactory.create("Fusion")) != _image_vierge()
    assert _cadre_focus(StyleSansCadreFocus("Fusion")) == _image_vierge()


def _cellule(style, etat_focus: bool):
    """Peint la cellule (0, 0) du tableau des réunions via son vrai délégué."""
    modele = QStandardItemModel(1, 1)
    modele.setItem(0, 0, QStandardItem("réunion"))
    vue = QTableView()
    vue.setModel(modele)
    vue.setStyle(style)
    delegue = IconeColonneDelegate(vue)
    opt = QStyleOptionViewItem()
    opt.initFrom(vue)
    opt.widget = vue  # c'est là que le délégué prend son style — pas dans initFrom
    opt.rect = QRect(0, 0, 120, 40)
    opt.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
    if etat_focus:
        opt.state |= _FOCUS
    img = _image_vierge()
    p = QPainter(img)
    delegue.paint(p, opt, modele.index(0, 0))
    p.end()
    return img


def test_index_courant_sans_cadre_dans_le_tableau_des_reunions(qapp):
    """Le symptôme terrain : cadre autour de l'icône de la 1ʳᵉ réunion (index courant)."""
    fusion = QStyleFactory.create("Fusion")
    assert _cellule(fusion, True) != _cellule(fusion, False)  # témoin
    proxy = StyleSansCadreFocus("Fusion")
    assert _cellule(proxy, True) == _cellule(proxy, False)


def test_installer_style_enveloppe_le_style_natif_et_est_idempotent(qapp, monkeypatch):
    # « Windows » simulé par un style natif qui n'est PAS celui des tests (Fusion) :
    # le proxy doit envelopper celui-là, pas basculer silencieusement sur un défaut.
    natif = QStyleFactory.create("Windows")
    poses = []
    monkeypatch.setattr(qapp, "style", lambda: natif)
    monkeypatch.setattr(qapp, "setStyle", poses.append)
    monkeypatch.setattr(qapp, "property", lambda nom: None)
    monkeypatch.setattr(qapp, "setProperty", lambda nom, v: None)
    installer_style(qapp)
    assert len(poses) == 1 and isinstance(poses[0], StyleSansCadreFocus)
    assert poses[0].baseStyle().name().lower() == "windows"


def test_charger_theme_deux_fois_ne_reenveloppe_pas(qapp, monkeypatch):
    charger_theme(qapp)
    poses = []
    monkeypatch.setattr(qapp, "setStyle", poses.append)
    charger_theme(qapp)
    assert poses == []


def test_qss_neutralise_aussi_le_cadre_des_vues(qapp):
    charger_theme(qapp)
    assert "QAbstractItemView { outline: 0; }" in qapp.styleSheet()
