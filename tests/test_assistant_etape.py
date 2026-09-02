"""Tests — pièces communes aux assistants guidés (`ui/assistant_etape.py`).

Le défaut d'origine : le bouton qui ouvre le site tiers était un `QPushButton` **sans
`objectName`**, or `theme.qss` ne donne fond et bordure qu'aux boutons nommés — il se
peignait donc en gras noir sur blanc, que l'utilisateur ne voyait pas comme cliquable
(constaté sur les deux assistants). Les tests portent sur ce qui le rendait invisible,
et sur les pages réelles des deux assistants, pas seulement sur la fabrique.
"""
from __future__ import annotations

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton

from debrief_meet.ui.assistant_etape import (
    DOSSIER_ASSETS,
    bouton_lien,
    illustration,
    page_etape,
    pixmap_svg,
)

# Seuls noms auxquels `theme.qss` accroche un fond ou une bordure.
_NOMS_STYLES = {"primary", "secondary", "danger", "destructive"}


# ── Bouton d'ouverture du navigateur ────────────────────────────────────────────

def test_bouton_lien_porte_un_nom_style(qapp):
    btn = bouton_lien("Créer un compte", "https://example.test")
    assert btn.objectName() in _NOMS_STYLES


def test_bouton_lien_porte_une_icone(qapp):
    btn = bouton_lien("Créer un compte", "https://example.test")
    assert not btn.icon().isNull()
    assert not btn.icon().pixmap(15, 15).isNull()


def test_bouton_lien_ouvre_l_url(qapp, monkeypatch):
    vues = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: vues.append(url.toString()))
    bouton_lien("Ouvrir", "https://example.test/cles").click()
    assert vues == ["https://example.test/cles"]


# ── Fabrique de page ────────────────────────────────────────────────────────────

def test_page_etape_assemble_maquette_titre_et_bouton(qapp):
    w = page_etape("diar_etape_1.svg", "1. Titre", "Explication.",
                   "https://example.test", "Ouvrir")
    labels = w.findChildren(QLabel)
    assert any(not lab.pixmap().isNull() for lab in labels)          # maquette
    assert any(lab.text() == "1. Titre" for lab in labels)
    assert any(lab.text() == "Explication." for lab in labels)
    boutons = w.findChildren(QPushButton)
    assert len(boutons) == 1 and boutons[0].text() == "Ouvrir"


def test_illustration_manquante_ne_casse_pas_la_page(qapp):
    lab = illustration("asset_inexistant.svg")
    assert lab.pixmap().isNull() and "indisponible" in lab.text()


def test_pixmap_svg_rend_une_image(qapp):
    pm = pixmap_svg(DOSSIER_ASSETS / "diar_etape_1.svg")
    assert not pm.isNull() and pm.width() > 0


# ── Les deux assistants réels ───────────────────────────────────────────────────
#
# Garde-fou de non-régression : une page ajoutée plus tard avec un `QPushButton` nu
# retomberait dans le défaut d'origine. On inspecte les pages du `QStackedWidget`,
# donc jamais les boutons Précédent/Suivant du pied (hors de la pile).

def _boutons_des_pages(assistant) -> list[QPushButton]:
    return [b for i in range(assistant._stack.count())
            for b in assistant._stack.widget(i).findChildren(QPushButton)]


def test_tous_les_boutons_de_page_sont_styles(qapp, tmp_path):
    from debrief_meet.core.config import Config
    from debrief_meet.ui.assistant_diarization import AssistantDiarization
    from debrief_meet.ui.assistant_mistral import AssistantMistral

    assistants = [AssistantDiarization(),
                  AssistantMistral(Config(chemin=tmp_path / "config.json"))]
    for a in assistants:
        boutons = _boutons_des_pages(a)
        assert boutons, f"{type(a).__name__} : aucun bouton de page trouvé"
        for b in boutons:
            assert b.objectName() in _NOMS_STYLES, f"{type(a).__name__} : « {b.text()} » sans style"
            assert not b.icon().isNull(), f"{type(a).__name__} : « {b.text()} » sans icône"
