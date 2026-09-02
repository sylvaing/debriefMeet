"""Mini-didacticiel « obtenir une clé API Mistral » (docs/42 §9.4).

Calqué sur l'onboarding diarization (`ui/assistant_diarization.py`, docs/13) : guide un
utilisateur non technique de « je n'ai rien » à « ma clé est saisie et testée ». Pas
d'ordre de grandeur de coût (règle transverse, docs/42 §11) — seulement confidentialité
(serveurs UE) et existence d'un tier gratuit, sans chiffres.

Les pièces d'étape (maquette SVG, titre, bouton d'ouverture du navigateur) sont
communes avec l'assistant diarization : cf. `ui/assistant_etape.py`.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Slot
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
from debrief_meet.core.config import Config
from debrief_meet.ui.assistant_etape import illustration, page_etape, titre_etape
from debrief_meet.ui.dialogues import CarteFlottante
from debrief_meet.ui.testeur_connexion_mistral import TesteurConnexionMistral

URL_COMPTE = "https://console.mistral.ai"
URL_CLES = "https://console.mistral.ai/api-keys"

# Index des pages du QStackedWidget.
_PAGE_CLE = 2
_PAGE_TEST = 3


class AssistantMistral(CarteFlottante):
    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent, largeur_carte=520)
        self.setWindowTitle("Activer Mistral — debriefMeet")
        self._config = config
        self._succes = False
        self._thread: QThread | None = None
        self._testeur: TesteurConnexionMistral | None = None
        self._construire_ui()
        self._maj_navigation()

    # ── Construction ────────────────────────────────────────────────────────────

    def _construire_ui(self) -> None:
        layout = self.corps
        self._stack = QStackedWidget()
        self._stack.addWidget(page_etape(
            "mistral_etape_1.svg",
            "1. Créer un compte Mistral",
            "debriefMeet génère les comptes-rendus via l'API Mistral (serveurs "
            "européens). Créez un compte si vous n'en avez pas.",
            URL_COMPTE, "Créer un compte"))
        self._stack.addWidget(page_etape(
            "mistral_etape_2.svg",
            "2. Générer une clé API",
            "Ouvrez la page des clés API, cliquez « Create new key », donnez-lui un "
            "nom puis copiez la clé générée — elle ne s'affiche qu'une seule fois. "
            "Un tier gratuit avec limites existe pour découvrir le service.",
            URL_CLES, "Ouvrir mes clés API"))
        self._stack.addWidget(self._page_cle())
        self._stack.addWidget(self._page_test())
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

    def _page_cle(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(illustration("mistral_etape_3.svg"))
        lay.addWidget(titre_etape("3. Coller la clé"))
        corps = QLabel("Collez ici la clé de l'étape précédente.")
        corps.setWordWrap(True)
        lay.addWidget(corps)
        self._champ_cle = QLineEdit()
        self._champ_cle.setEchoMode(QLineEdit.EchoMode.Password)
        self._champ_cle.setPlaceholderText("Clé API Mistral")
        cle_existante = self._config.get("mistral_cle_api")
        if cle_existante:
            self._champ_cle.setText(cle_existante)
        lay.addWidget(self._champ_cle)
        lay.addStretch()
        return w

    def _page_test(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        # Maquette d'ARRIVÉE, pas de lieu à visiter : masquée tant que le test n'a pas
        # réussi, sinon elle annonce « Connexion réussie » pendant que le libellé juste
        # en dessous dit encore « Test de la connexion… », et pire encore après un échec.
        # Sa place reste prise (le QStackedWidget se dimensionne sur la page la plus
        # haute) : rien ne saute quand elle apparaît, et le ressort ci-dessus centre le
        # contenu dans cet espace au lieu de laisser la barre seule en haut du vide.
        lay.addStretch()
        self._illustration_fin = illustration("mistral_etape_4.svg")
        self._illustration_fin.setVisible(False)
        lay.addWidget(self._illustration_fin)
        self._label_resultat = QLabel("Test de la connexion…")
        self._label_resultat.setWordWrap(True)
        lay.addWidget(self._label_resultat)
        self._barre = QProgressBar()
        self._barre.setRange(0, 0)  # indéterminée
        lay.addWidget(self._barre)
        lay.addStretch()
        return w

    # ── Navigation ──────────────────────────────────────────────────────────────

    def _aller(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._maj_navigation()

    def _precedent(self) -> None:
        i = self._stack.currentIndex()
        if 0 < i <= _PAGE_CLE:
            self._aller(i - 1)

    def _suivant(self) -> None:
        i = self._stack.currentIndex()
        if i < _PAGE_CLE:
            self._aller(i + 1)
        elif i == _PAGE_CLE:
            self._lancer_test()
        elif i == _PAGE_TEST:
            if self._succes:
                self.accept()
            else:
                self._aller(_PAGE_CLE)  # échec → revenir corriger la clé

    def _maj_navigation(self) -> None:
        i = self._stack.currentIndex()
        self._btn_prec.setEnabled(0 < i <= _PAGE_CLE)
        if i < _PAGE_CLE:
            self._btn_suiv.setText("Suivant")
            self._btn_suiv.setEnabled(True)
        elif i == _PAGE_CLE:
            self._btn_suiv.setText("Vérifier et enregistrer")
            self._btn_suiv.setEnabled(True)
        else:
            self._btn_suiv.setText("Terminer" if self._succes else "Réessayer")

    # ── Test de connexion (worker en arrière-plan) ──────────────────────────────

    def _lancer_test(self) -> None:
        cle = self._champ_cle.text().strip()
        if not cle:
            self._label_resultat.setText("Veuillez coller une clé API (étape 2).")
            self._aller(_PAGE_TEST)
            self._barre.hide()
            self._succes = False
            self._maj_navigation()
            return
        self._succes = False
        self._aller(_PAGE_TEST)
        self._illustration_fin.setVisible(False)
        self._label_resultat.setText("Test de la connexion…")
        self._barre.setRange(0, 0)
        self._barre.show()
        self._btn_prec.setEnabled(False)
        self._btn_suiv.setEnabled(False)

        url = self._config.get("mistral_base_url")
        self._thread = QThread()
        self._testeur = TesteurConnexionMistral(url, cle)
        proteger_thread(self._thread, self._testeur)
        self._testeur.moveToThread(self._thread)
        self._thread.started.connect(self._testeur.executer)
        self._testeur.reussi.connect(self._thread.quit)
        self._testeur.echec.connect(self._thread.quit)
        self._thread.finished.connect(self._testeur.deleteLater)
        self._testeur.reussi.connect(lambda _msg, c=cle: self._sur_succes(c))
        self._testeur.echec.connect(self._sur_echec)
        self._thread.start()

    @Slot(str)
    def _sur_succes(self, cle: str) -> None:
        self._config.set("mistral_cle_api", cle)
        self._config.sauvegarder()
        self._barre.hide()
        self._illustration_fin.setVisible(True)
        self._label_resultat.setText("✅ Connexion réussie. Vous pouvez fermer cette fenêtre.")
        self._btn_suiv.setText("Terminer")
        self._btn_suiv.setEnabled(True)
        # Drapeau positionné en DERNIER : il signifie « tout est appliqué » (clé
        # persistée, libellés à jour), et non « le réseau a répondu ». Le placer en tête
        # exposait un état intermédiaire — flake constaté sur la gate VM le 2026-07-30,
        # `_succes` vrai alors que le label affichait encore « Test de la connexion… ».
        self._succes = True

    @Slot(str)
    def _sur_echec(self, message: str) -> None:
        self._succes = False
        self._barre.hide()
        self._label_resultat.setText(f"❌ {message}")
        self._btn_prec.setEnabled(True)
        self._btn_suiv.setText("Réessayer")
        self._btn_suiv.setEnabled(True)
