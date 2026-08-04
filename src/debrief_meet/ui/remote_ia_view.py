"""Section Préférences « Remote IA » (docs/42 §9.1) — fournisseurs d'IA distante.

Conçue **extensible** : un bloc par fournisseur, empilés verticalement. Un seul bloc
en v1 (Mistral) ; ajouter un fournisseur plus tard = ajouter une méthode `_bloc_xxx()`
+ ses clés `<fournisseur>_*` dans `core/config.py`, sans toucher la structure. Pas de
système de plugins en v1 (sur-ingénierie inutile pour un seul fournisseur).
"""
from __future__ import annotations

from PySide6.QtCore import QThread, QTimer, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core import edition
from debrief_meet.core.arret_threads import proteger_thread
from debrief_meet.core.config import Config
from debrief_meet.ui.assistant_mistral import AssistantMistral
from debrief_meet.ui.testeur_connexion_mistral import TesteurConnexionMistral
from debrief_meet.ui.theme import C, SANS

_DELAI_AUTOSAVE_MS = 400

# Modèles proposés au combo — à reconfirmer sur docs.mistral.ai (docs/42 §5).
_MODELES_TRANSCRIPTION = ["voxtral-mini-latest"]
_MODELES_CR = ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"]


def _libelle_champ(texte: str) -> QLabel:
    lab = QLabel(texte)
    lab.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {C.INK700};")
    return lab


def _note(texte: str) -> QLabel:
    lab = QLabel(texte)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {C.INK400}; font-size: 12px; line-height: 1.7;")
    return lab


class RemoteIAView(QWidget):
    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._thread_test: QThread | None = None
        self._testeur: TesteurConnexionMistral | None = None

        self._timer_autosave = QTimer(self)
        self._timer_autosave.setSingleShot(True)
        self._timer_autosave.setInterval(_DELAI_AUTOSAVE_MS)
        self._timer_autosave.timeout.connect(self._config.sauvegarder)

        self.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(self._bloc_mistral())
        layout.addStretch()

    # ── Sauvegarde (même pattern que PreferencesView) ───────────────────────────

    def _definir(self, cle: str, valeur) -> None:
        self._config.set(cle, valeur)
        self._config.sauvegarder()

    def _definir_differe(self, cle: str, valeur) -> None:
        self._config.set(cle, valeur)
        self._timer_autosave.start()

    # ── Bloc Mistral ─────────────────────────────────────────────────────────────

    def _bloc_mistral(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        titre = QLabel("Mistral")
        titre.setFont(QFont(SANS, 14, QFont.Weight.DemiBold))
        lay.addWidget(titre)
        lay.addWidget(_note(
            "Génère des comptes-rendus via l'API Mistral (Voxtral + modèles texte, "
            "serveurs UE). Par défaut, réutilise la transcription locale existante — "
            "repli automatique vers Voxtral si absente (mode enregistrement seul)."))

        bloc_cle = QVBoxLayout()
        bloc_cle.setSpacing(6)
        bloc_cle.addWidget(_libelle_champ("Clé API"))
        ligne_cle = QHBoxLayout()
        ligne_cle.setSpacing(8)
        self._edit_cle = QLineEdit(self._config.get("mistral_cle_api"))
        self._edit_cle.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_cle.editingFinished.connect(
            lambda: self._definir("mistral_cle_api", self._edit_cle.text().strip()))
        ligne_cle.addWidget(self._edit_cle, 1)
        btn_obtenir = QPushButton("Obtenir une clé…")
        btn_obtenir.setObjectName("secondary")
        btn_obtenir.clicked.connect(self._ouvrir_assistant)
        ligne_cle.addWidget(btn_obtenir)
        bloc_cle.addLayout(ligne_cle)
        lay.addLayout(bloc_cle)

        bloc_transcription = QVBoxLayout()
        bloc_transcription.setSpacing(6)
        bloc_transcription.addWidget(_libelle_champ("Modèle de transcription"))
        self._combo_modele_transcription = QComboBox()
        for nom in _MODELES_TRANSCRIPTION:
            self._combo_modele_transcription.addItem(nom, nom)
        idx = self._combo_modele_transcription.findData(self._config.get("mistral_modele_transcription"))
        if idx >= 0:
            self._combo_modele_transcription.setCurrentIndex(idx)
        self._combo_modele_transcription.currentIndexChanged.connect(
            lambda _i: self._definir(
                "mistral_modele_transcription", self._combo_modele_transcription.currentData()))
        bloc_transcription.addWidget(self._combo_modele_transcription)
        lay.addLayout(bloc_transcription)

        bloc_cr = QVBoxLayout()
        bloc_cr.setSpacing(6)
        bloc_cr.addWidget(_libelle_champ("Modèle de rédaction du CR"))
        self._combo_modele_cr = QComboBox()
        for nom in _MODELES_CR:
            self._combo_modele_cr.addItem(nom, nom)
        idx = self._combo_modele_cr.findData(self._config.get("mistral_modele_cr"))
        if idx >= 0:
            self._combo_modele_cr.setCurrentIndex(idx)
        self._combo_modele_cr.currentIndexChanged.connect(
            lambda _i: self._definir("mistral_modele_cr", self._combo_modele_cr.currentData()))
        bloc_cr.addWidget(self._combo_modele_cr)
        lay.addLayout(bloc_cr)

        # Inerte en édition lite : il n'y a jamais de transcription locale à ignorer, et
        # `mistral_source_transcription="auto"` y est déjà équivalent à "voxtral"
        # (`pipeline._lire_transcript_local` rend None sur le placeholder) — docs/44.
        if edition.avec_transcription_locale():
            self._check_forcer_voxtral = QCheckBox(
                "Toujours transcrire via Voxtral (ignorer la transcription locale)")
            self._check_forcer_voxtral.setChecked(
                self._config.get("mistral_source_transcription") == "voxtral")
            self._check_forcer_voxtral.setToolTip(
                "Décoché (recommandé) : réutilise la transcription locale quand elle existe "
                "— instantané. Coché : re-transcrit systématiquement via Voxtral (utile en "
                "enregistrement-seul, ou si la transcription locale est médiocre).")
            self._check_forcer_voxtral.toggled.connect(self._sur_forcer_voxtral_toggle)
            lay.addWidget(self._check_forcer_voxtral)

        ligne_test = QHBoxLayout()
        ligne_test.setSpacing(12)
        btn_test = QPushButton("Tester la connexion")
        btn_test.setObjectName("secondary")
        btn_test.clicked.connect(self._tester_connexion)
        ligne_test.addWidget(btn_test)
        self._label_statut = QLabel("")
        ligne_test.addWidget(self._label_statut, 1)
        lay.addLayout(ligne_test)

        lay.addWidget(_note(
            "Clé vide = fonctionnalité invisible : aucun bouton, aucune requête réseau "
            "ailleurs dans l'app. Une confirmation est demandée avant le premier envoi "
            "(audio ou texte) vers les serveurs Mistral."))
        return w

    def _sur_forcer_voxtral_toggle(self, coche: bool) -> None:
        self._definir("mistral_source_transcription", "voxtral" if coche else "auto")

    def _ouvrir_assistant(self) -> None:
        AssistantMistral(self._config, self).exec()
        self._edit_cle.setText(self._config.get("mistral_cle_api"))

    def _tester_connexion(self) -> None:
        cle = self._edit_cle.text().strip()
        if not cle:
            self._label_statut.setText("Clé API requise.")
            self._label_statut.setStyleSheet(f"color: {C.INK400};")
            return
        self._label_statut.setText("Connexion en cours…")
        self._label_statut.setStyleSheet(f"color: {C.INK400};")

        self._thread_test = QThread()
        self._testeur = TesteurConnexionMistral(self._config.get("mistral_base_url"), cle)
        proteger_thread(self._thread_test, self._testeur)
        self._testeur.moveToThread(self._thread_test)
        self._thread_test.started.connect(self._testeur.executer)
        self._testeur.reussi.connect(self._thread_test.quit)
        self._testeur.echec.connect(self._thread_test.quit)
        self._thread_test.finished.connect(self._testeur.deleteLater)
        self._testeur.reussi.connect(self._sur_test_reussi)
        self._testeur.echec.connect(self._sur_test_echec)
        self._thread_test.start()

    @Slot(str)
    def _sur_test_reussi(self, message: str) -> None:
        self._label_statut.setText(f"✓ {message}")
        self._label_statut.setStyleSheet(f"color: {C.SUCCESS};")

    @Slot(str)
    def _sur_test_echec(self, message: str) -> None:
        self._label_statut.setText(f"Échec : {message}")
        self._label_statut.setStyleSheet(f"color: {C.REC};")
