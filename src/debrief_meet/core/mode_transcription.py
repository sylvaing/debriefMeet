"""Mode de transcription choisi par l'utilisateur et capacités qui en découlent (docs/45).

Un seul build est produit (les éditions complete/lite de docs/44 ont disparu) ; le
comportement est piloté par la clé de config ``mode_transcription`` :

- ``distant`` (défaut) : enregistrement Opus seul, transcription et CR délégués à
  l'API Mistral — l'ancien comportement « lite » ;
- ``local`` : moteur Whisper embarqué (transcription live, différée), diarization,
  modes Dictée/Journal — l'ancien comportement « complete ».

Le mode est **figé pour la durée du process** : ``initialiser(config)`` est appelé
une fois au démarrage (``__main__``), et changer le réglage dans les Préférences
propose un redémarrage. C'est ce qui autorise des prédicats sans argument lus
partout (fabrique du moteur, tray, fenêtre, raccourcis) sans transporter la config.
Avant initialisation, le mode est ``distant`` : le pire cas est une fonctionnalité
masquée, jamais un moteur fantôme.

Le code métier interroge les prédicats ``avec_*`` — jamais ``mode()`` directement :
chaque appel documente ainsi *pourquoi* il est conditionné, et un futur mode qui
garderait la dictée en retirant la diarization ne toucherait que ce module.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DISTANT = "distant"
LOCAL = "local"
MODES = (DISTANT, LOCAL)

# Force un mode depuis les sources (dev, `make run`) sans toucher au config.json.
# Bidirectionnel, contrairement à l'ancien DEBRIEFMEET_EDITION : le bundle unifié
# contient toute la pile, un mode « local » forcé ne peut plus tomber sur un moteur
# absent du bundle.
VAR_ENV = "DEBRIEFMEET_MODE"

_mode: str | None = None


def _normaliser(valeur: object, origine: str) -> str | None:
    """Mode valide, ou None si absent/invalide (averti, jamais levé)."""
    if valeur is None:
        return None
    texte = str(valeur).strip().lower()
    if not texte:
        return None
    if texte not in MODES:
        logger.warning("Mode de transcription inconnu %r (%s) — ignoré, repli sur « %s »",
                       texte, origine, DISTANT)
        return None
    return texte


def initialiser(config) -> None:
    """Fige le mode pour la durée du process : env > config > « distant ».

    À appeler tôt dans ``__main__`` — avant ``configurer_logs`` (qui logge le mode
    en première ligne) et avant toute construction gatée (fabrique, orchestrateurs,
    raccourcis, fenêtre, tray).
    """
    global _mode
    surcharge = _normaliser(os.environ.get(VAR_ENV), f"${VAR_ENV}")
    regle = _normaliser(config.get("mode_transcription"), "config")
    _mode = surcharge or regle or DISTANT


def mode() -> str:
    """Mode courant : « distant » ou « local » (« distant » si non initialisé)."""
    return _mode or DISTANT


# ── Capacités ────────────────────────────────────────────────────────────────
#
# Absentes en distant : le moteur Whisper embarqué, la passe « qui a parlé »
# (pyannote, déjà hors du bundle Windows) et les modes Dictée/Journal, qui n'ont
# aucun équivalent distant (leur intérêt est le retour immédiat : presse-papiers /
# entrée du jour).

def avec_transcription_locale() -> bool:
    """Moteur de transcription embarqué (sélecteur de modèle, transcription en
    direct, transcription différée depuis l'Historique)."""
    return mode() == LOCAL


def avec_diarization() -> bool:
    """Passe finale « qui a parlé » (pyannote) — dépend du moteur local."""
    return mode() == LOCAL


def avec_dictee_journal() -> bool:
    """Modes Dictée et Journal (tray, pages, raccourcis globaux)."""
    return mode() == LOCAL
