"""Assistant guidé d'activation de la diarization (modèle pyannote gated).

Cinq étapes : créer un compte Hugging Face → accepter la licence du modèle → créer un
token (read) → coller le token → télécharger. Le token est utilisé **à la volée** au
téléchargement puis **oublié** (jamais stocké). Cf. docs/13-diarization-onboarding.md.

Lot 1 : assistant fonctionnel avec **placeholders visuels** (les illustrations finales
sont conçues en Lot 2).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.arret_threads import proteger_thread
from debrief_meet.ui.dialogues import CarteFlottante

logger = logging.getLogger(__name__)

_DOSSIER_ASSETS = Path(__file__).parent / "assets"
_LARGEUR_ILLUSTRATION = 460


def _pixmap_svg(chemin: Path, largeur: int = _LARGEUR_ILLUSTRATION, dpr: int = 2) -> QPixmap:
    """Rend un SVG d'asset en QPixmap à `largeur` (ratio préservé, net en Retina via dpr)."""
    from PySide6.QtSvg import QSvgRenderer

    rendu = QSvgRenderer(str(chemin))
    taille = rendu.defaultSize()
    if not taille.isValid() or taille.width() <= 0:
        return QPixmap()
    hauteur = round(largeur * taille.height() / taille.width())
    image = QImage(largeur * dpr, hauteur * dpr, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    peintre = QPainter(image)
    peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
    rendu.render(peintre)
    peintre.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap

URL_COMPTE = "https://huggingface.co/join"
URL_LICENCE = "https://huggingface.co/pyannote/speaker-diarization-community-1"
URL_TOKEN = "https://huggingface.co/settings/tokens"

# Index des pages du QStackedWidget.
_PAGE_TOKEN = 3
_PAGE_TELECHARGEMENT = 4


class _WorkerTelechargement(QObject):
    """Lance `diarization.telecharger(token)` dans un QThread. Ne lève jamais."""

    fini = Signal()
    echec = Signal(str)

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    @Slot()
    def executer(self) -> None:
        try:
            from debrief_meet.core import diarization
            diarization.telecharger(self._token)
            self.fini.emit()
        except Exception as exc:  # noqa: BLE001 — message déjà destiné à l'utilisateur
            self.echec.emit(str(exc))


class AssistantDiarization(CarteFlottante):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, largeur_carte=520)
        self.setWindowTitle("Activer la diarization — debriefMeet")
        self._succes = False
        self._thread: QThread | None = None
        self._worker: _WorkerTelechargement | None = None
        self._construire_ui()
        self._maj_navigation()

    # ── Construction ────────────────────────────────────────────────────────────

    def _construire_ui(self) -> None:
        layout = self.corps
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page(
            "diar_etape_1.svg",
            "1. Créer un compte Hugging Face",
            "La diarization (« qui a parlé ») utilise un modèle gratuit hébergé sur "
            "Hugging Face. Créez un compte si vous n'en avez pas.",
            URL_COMPTE, "Créer un compte"))
        self._stack.addWidget(self._page(
            "diar_etape_2.svg",
            "2. Accepter la licence du modèle",
            "Ouvrez la page du modèle et cliquez « Agree and access repository » pour "
            "accepter ses conditions d'utilisation (gratuit).",
            URL_LICENCE, "Ouvrir la page du modèle"))
        self._stack.addWidget(self._page(
            "diar_etape_3.svg",
            "3. Créer un jeton d'accès",
            "Créez un token de type « Read ». Il sert uniquement à télécharger le modèle.",
            URL_TOKEN, "Ouvrir mes tokens"))
        self._stack.addWidget(self._page_token())
        self._stack.addWidget(self._page_telechargement())
        layout.addWidget(self._stack, 1)

        barre = QHBoxLayout()
        self._btn_prec = QPushButton("Précédent")
        self._btn_prec.setObjectName("secondary")
        self._btn_prec.clicked.connect(self._precedent)
        self._btn_suiv = QPushButton("Suivant")
        self._btn_suiv.setObjectName("primary")
        self._btn_suiv.clicked.connect(self._suivant)
        barre.addStretch()
        barre.addWidget(self._btn_prec)
        barre.addWidget(self._btn_suiv)
        layout.addLayout(barre)

    def _illustration(self, fichier: str) -> QLabel:
        """Illustration de l'étape (SVG d'asset). Repli discret si l'asset manque."""
        lab = QLabel()
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chemin = _DOSSIER_ASSETS / fichier
        pixmap = _pixmap_svg(chemin) if chemin.exists() else QPixmap()
        if pixmap.isNull():
            lab.setText("(illustration indisponible)")
            lab.setStyleSheet("color:gray;")
        else:
            lab.setPixmap(pixmap)
        return lab

    def _page(self, fichier: str, titre: str, texte: str,
              url: str, libelle_lien: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._illustration(fichier))
        t = QLabel(titre)
        t.setStyleSheet("font-weight:bold;font-size:15px;")
        lay.addWidget(t)
        corps = QLabel(texte)
        corps.setWordWrap(True)
        lay.addWidget(corps)
        lien = QPushButton(libelle_lien)
        lien.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        lay.addWidget(lien, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return w

    def _page_token(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._illustration("diar_etape_4.svg"))
        t = QLabel("4. Coller le token")
        t.setStyleSheet("font-weight:bold;font-size:15px;")
        lay.addWidget(t)
        corps = QLabel(
            "Collez ici le token de l'étape 3. Il est utilisé seulement pour télécharger "
            "le modèle, puis oublié — il n'est jamais enregistré.")
        corps.setWordWrap(True)
        lay.addWidget(corps)
        self._champ_token = QLineEdit()
        self._champ_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._champ_token.setPlaceholderText("hf_…")
        # Pré-remplissage confort si un token existe déjà (env/cache) — jamais réécrit.
        try:
            from debrief_meet.core import diarization
            tok = diarization._token_hf()
            if tok:
                self._champ_token.setText(tok)
        except Exception:
            pass
        lay.addWidget(self._champ_token)
        lay.addStretch()
        return w

    def _page_telechargement(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._illustration("diar_etape_5.svg"))
        self._label_resultat = QLabel("Téléchargement du modèle…")
        self._label_resultat.setWordWrap(True)
        lay.addWidget(self._label_resultat)
        self._barre = QProgressBar()
        self._barre.setRange(0, 0)          # indéterminée
        lay.addWidget(self._barre)
        lay.addStretch()
        return w

    # ── Navigation ──────────────────────────────────────────────────────────────

    def _aller(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._maj_navigation()

    def _precedent(self) -> None:
        i = self._stack.currentIndex()
        if 0 < i <= _PAGE_TOKEN:
            self._aller(i - 1)

    def _suivant(self) -> None:
        i = self._stack.currentIndex()
        if i < _PAGE_TOKEN:
            self._aller(i + 1)
        elif i == _PAGE_TOKEN:
            self._lancer_telechargement()
        elif i == _PAGE_TELECHARGEMENT:
            if self._succes:
                self.accept()
            else:
                self._aller(_PAGE_TOKEN)     # échec → revenir corriger le token

    def _maj_navigation(self) -> None:
        i = self._stack.currentIndex()
        self._btn_prec.setEnabled(0 < i <= _PAGE_TOKEN)
        if i < _PAGE_TOKEN:
            self._btn_suiv.setText("Suivant")
            self._btn_suiv.setEnabled(True)
        elif i == _PAGE_TOKEN:
            self._btn_suiv.setText("Vérifier et télécharger")
            self._btn_suiv.setEnabled(True)
        else:  # page téléchargement : l'état est piloté par les slots succès/échec
            self._btn_suiv.setText("Terminer" if self._succes else "Réessayer")

    # ── Téléchargement (worker en arrière-plan) ─────────────────────────────────

    def _lancer_telechargement(self) -> None:
        token = self._champ_token.text().strip()
        if not token:
            self._label_resultat.setText("Veuillez coller un token (étape 3).")
            self._aller(_PAGE_TELECHARGEMENT)
            self._barre.hide()
            self._succes = False
            self._maj_navigation()
            return
        self._succes = False
        self._aller(_PAGE_TELECHARGEMENT)
        self._label_resultat.setText(
            "Téléchargement du modèle… (une seule fois, cela peut prendre une minute)")
        self._barre.setRange(0, 0)
        self._barre.show()
        self._btn_prec.setEnabled(False)
        self._btn_suiv.setEnabled(False)

        self._thread = QThread()                 # PAS de parent : la destruction du
        self._worker = _WorkerTelechargement(token)
        proteger_thread(self._thread, self._worker)  # dialogue ne tue plus le thread
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.executer)
        self._worker.fini.connect(self._thread.quit)
        self._worker.echec.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        # Slots de `self` (thread principal) → GUI jamais touchée depuis le worker.
        self._worker.fini.connect(self._sur_succes)
        self._worker.echec.connect(self._sur_echec)
        self._thread.start()

    @Slot()
    def _sur_succes(self) -> None:
        self._succes = True
        self._barre.hide()
        self._label_resultat.setText("✅ Diarization activée. Vous pouvez fermer cette fenêtre.")
        self._btn_suiv.setText("Terminer")
        self._btn_suiv.setEnabled(True)

    @Slot(str)
    def _sur_echec(self, message: str) -> None:
        self._succes = False
        self._barre.hide()
        self._label_resultat.setText(f"❌ {message}")
        self._btn_prec.setEnabled(True)
        self._btn_suiv.setText("Réessayer")
        self._btn_suiv.setEnabled(True)
