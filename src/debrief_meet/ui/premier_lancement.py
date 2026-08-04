"""Écran de bienvenue au premier lancement : choix du mode de transcription (docs/45).

Joué quand `accueil_fait` est faux — donc aussi une fois sur les installations
antérieures à docs/45 (clé absente de leur config.json) : c'est ce qui rend le
défaut « distant » acceptable pour tous, personne ne perd la transcription locale
sans un choix explicite. Fermer sans choisir = distant (le défaut sûr), et
`accueil_fait` passe à vrai dans tous les cas — jamais de harcèlement au
lancement suivant.

Exécuté dans `__main__` AVANT `mode_transcription.initialiser(config)` : le choix
fait ici est effectif dès ce premier démarrage, sans redémarrage.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QWidget,
)

from debrief_meet.core import mode_transcription
from debrief_meet.core.config import Config
from debrief_meet.ui.dialogues import CarteFlottante
from debrief_meet.ui.theme import C, SANS


def _note(texte: str, retrait: int = 24) -> QLabel:
    lab = QLabel(texte)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {C.INK400}; font-size: 12px; line-height: 1.7;")
    lab.setContentsMargins(retrait, 0, 0, 0)
    return lab


class PremierLancement(CarteFlottante):
    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent, largeur_carte=470)
        self.setWindowTitle("Bienvenue — debriefMeet")
        self._config = config
        self._construire_ui()

    def _construire_ui(self) -> None:
        lay = self.corps

        titre = QLabel("Bienvenue dans debriefMeet")
        titre.setFont(QFont(SANS, 17, QFont.Weight.DemiBold))
        lay.addWidget(titre)
        intro = QLabel("Comment voulez-vous transcrire vos réunions ?\n"
                       "Ce choix se change à tout moment dans Préférences › Transcription.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {C.INK700}; font-size: 13px;")
        lay.addWidget(intro)

        self._radio_distant = QRadioButton("Via l'IA en ligne (Mistral) — recommandé")
        self._radio_distant.setChecked(True)
        lay.addWidget(self._radio_distant)
        lay.addWidget(_note(
            "L'audio est enregistré, puis transcrit et résumé par l'API Mistral à la "
            "demande. Aucun téléchargement, fonctionne sur toutes les machines — "
            "nécessite une clé API."))

        # Clé optionnelle, seulement en distant : saisissable tout de suite, ou plus
        # tard dans Préférences › IA en ligne (l'assistant teste ET persiste lui-même).
        self._bloc_cle = QWidget()
        lay_cle = QHBoxLayout(self._bloc_cle)
        lay_cle.setContentsMargins(24, 0, 0, 0)
        lay_cle.setSpacing(8)
        self._edit_cle = QLineEdit()
        self._edit_cle.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_cle.setPlaceholderText("Clé API Mistral (optionnel, plus tard aussi)")
        lay_cle.addWidget(self._edit_cle, 1)
        btn_obtenir = QPushButton("Obtenir une clé…")
        btn_obtenir.setObjectName("secondary")
        btn_obtenir.clicked.connect(self._ouvrir_assistant)
        lay_cle.addWidget(btn_obtenir)
        lay.addWidget(self._bloc_cle)

        self._radio_local = QRadioButton("Sur cet ordinateur")
        lay.addWidget(self._radio_local)
        lay.addWidget(_note(
            "La transcription tourne en local : rien ne quitte la machine, et les "
            "modes Dictée et Journal deviennent disponibles. Le modèle Whisper "
            "(≈ 1,6 Go) est téléchargé au premier usage."))

        self._radio_distant.toggled.connect(self._bloc_cle.setVisible)

        pied = QHBoxLayout()
        pied.addStretch()
        btn_ok = QPushButton("Commencer")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._valider)
        pied.addWidget(btn_ok)
        lay.addLayout(pied)

    def _ouvrir_assistant(self) -> None:
        from debrief_meet.ui.assistant_mistral import AssistantMistral
        AssistantMistral(self._config, self).exec()
        # L'assistant persiste la clé après un test réussi — refléter dans le champ.
        self._edit_cle.setText(str(self._config.get("mistral_cle_api") or ""))

    def _valider(self) -> None:
        mode = (mode_transcription.LOCAL if self._radio_local.isChecked()
                else mode_transcription.DISTANT)
        cle = self._edit_cle.text().strip()
        if mode == mode_transcription.DISTANT and cle:
            self._config.set("mistral_cle_api", cle)
        self._enregistrer(mode)
        self.accept()

    def reject(self) -> None:  # noqa: N802 — override Qt (Échap, croix)
        """Fermer sans choisir = distant, le défaut sûr — et on ne redemandera pas."""
        self._enregistrer(mode_transcription.DISTANT)
        super().reject()

    def _enregistrer(self, mode: str) -> None:
        self._config.set("mode_transcription", mode)
        self._config.set("accueil_fait", True)
        self._config.sauvegarder()
