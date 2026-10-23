"""Thème centralisé debriefMeet — source unique de vérité. Aucune valeur en dur ailleurs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from debrief_meet.ui.icones import ICON_DIR
from debrief_meet.ui.polices import MONO, SANS  # noqa: F401  (ré-exportés)

_QSS_PATH = Path(__file__).parent / "assets" / "theme.qss"
_CHECK_WHITE = ICON_DIR / "check-white.svg"
_CARET_UP = ICON_DIR / "caret-up-ink300.svg"
_CARET_DOWN = ICON_DIR / "caret-down-ink300.svg"
_CARET_UP_DOWN = ICON_DIR / "caret-up-down-ink300.svg"
_PROPRIETE_STYLE = "debriefmeet_style_sans_cadre_focus"


class C:  # ----- Couleurs (hex) -----
    # Accent (indigo)
    ACCENT = "#3B5BDB"; ACCENT_INK = "#2A46B8"; ACCENT_SOFT = "#EEF1FE"
    # Texte
    INK900 = "#1A1D23"; INK700 = "#344054"; INK600 = "#475467"
    INK500 = "#667085"; INK400 = "#7A828F"; INK350 = "#8A919E"
    INK300 = "#98A2B3"; INK200 = "#B0B7C0"
    # Surfaces & bordures
    SURFACE = "#FFFFFF"; SUNKEN = "#F6F7F9"; HEADER = "#FBFBFC"
    HOVER = "#FAFAFB"; BORDER = "#E7E9EE"; BORDER_SOFT = "#EFF1F4"; DIVIDER = "#F1F2F5"
    # Contour de la fenêtre là où le gestionnaire de fenêtres ne dessine pas d'ombre
    # (Wayland/GNOME). Volontairement plus contrasté que BORDER : il doit rester
    # visible SUR FOND BLANC, ce qui est tout le problème qu'il résout.
    CONTOUR_FENETRE = "#B0B7C0"
    # États sémantiques (texte/icône + fond pastille)
    REC = "#FF3B30"; REC_BG = "#FFECEA"
    SUCCESS = "#1F9D6B"; SUCCESS_BG = "#E7F6EF"
    NEUTRAL = "#7A828F"; NEUTRAL_BG = "#F1F2F5"
    INFO = "#3B5BDB"; INFO_BG = "#EEF1FE"
    DANGER = "#B42318"; DANGER_BG = "#FEF3F2"
    # Un traitement a posteriori tourne sur une réunion (transcription, locuteurs,
    # CR Mistral) : icône de la ligne d'Historique concernée. Même orange que l'icône
    # de tray dans cet état (cf. `TRAY_TRANSCRIBE` plus bas, `arbitre_etat_visuel`) —
    # la ligne dit LAQUELLE de ses opérations tourne, le tray dit qu'il en tourne une.
    JOB = "#FF9500"
    # Icône tray par état d'activité
    TRAY_IDLE = "#3D4351"        # contour monochrome — barre CLAIRE (macOS/Windows)
    # Barre SOMBRE (GNOME : le bandeau supérieur est noir y compris en thème clair,
    # donc ce n'est PAS un choix à dériver du `colorScheme` de l'application).
    # #3D4351 y était invisible : constaté sur le poste du premier utilisateur Linux.
    TRAY_IDLE_BARRE_SOMBRE = "#FFFFFF"
    TRAY_RECORDING = "#FF3B30"; TRAY_TRANSCRIBE = JOB
    TRAY_DONE = "#34C759"; TRAY_ERROR = "#8E8E93"


def color(hex_str: str) -> QColor:
    """QColor depuis un hex du thème (à appeler après QApplication)."""
    return QColor(hex_str)


class M:  # ----- Métriques (px) -----
    TITLEBAR_H = 40; TOOLBAR_H = 58; ROW_H = 52
    PAD_CONTENT = 20; PAD_FORM = 30; PREF_NAV_W = 208
    # Rayons
    R_WINDOW = 12; R_CARD = 9; R_BUTTON = 9; R_TILE = 7; R_PILL = 20; R_CHECK = 5
    # Espacement (× 4) : 4 8 12 16 20 24 28 32


class StyleSansCadreFocus(QProxyStyle):
    """Style natif de la plateforme, moins le rectangle de focus (`PE_FrameFocusRect`).

    Le style Windows le dessine autour de l'index COURANT d'une vue — (0, 0) dès le
    chargement, donc un cadre sur l'icône de la 1ʳᵉ réunion sans aucune action au
    clavier (Qt n'honore pas la convention Windows « caché jusqu'à Alt/Tab »). Fusion
    (Linux) le dessine aussi ; le style macOS ne dessine rien pour cet élément, d'où
    un défaut jamais vu sur Mac. La sélection pleine ligne suffit à repérer la ligne
    courante au clavier.
    """

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


def installer_style(app: QApplication) -> None:
    """Enveloppe le style courant dans `StyleSansCadreFocus` (idempotent).

    Construit par NOM de style, jamais autour de `app.style()` lui-même : `setStyle`
    détruit l'ancien style, qui serait alors la base du proxy. Et autour du style
    courant, pas d'un défaut — sinon Windows basculerait en Fusion.

    Idempotence par propriété de l'application, pas par `isinstance(app.style(), …)` :
    dès qu'une feuille de style est posée, `app.style()` rend l'enveloppe interne du
    QSS (nom vide), plus le proxy — le 2ᵉ appel envelopperait alors un style sans nom.
    """
    if app.property(_PROPRIETE_STYLE):
        return
    app.setStyle(StyleSansCadreFocus(app.style().name()))
    app.setProperty(_PROPRIETE_STYLE, True)


def charger_theme(app: QApplication) -> None:
    """Charge le QSS global (`assets/theme.qss`) — à appeler après `charger_polices()`.

    Pas de .qrc (cf. `polices.charger_polices`) : le chemin de l'icône de case
    cochée (dépend de l'installation) est substitué dans le QSS avant application.
    Le style est posé AVANT la feuille : `setStyle` peut réappliquer la palette.
    """
    installer_style(app)
    qss = _QSS_PATH.read_text(encoding="utf-8")
    qss = qss.replace("__CHECK_WHITE__", _CHECK_WHITE.as_posix())
    qss = qss.replace("__CARET_UP__", _CARET_UP.as_posix())
    qss = qss.replace("__CARET_DOWN__", _CARET_DOWN.as_posix())
    qss = qss.replace("__CARET_UP_DOWN__", _CARET_UP_DOWN.as_posix())
    app.setStyleSheet(qss)
