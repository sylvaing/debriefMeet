"""Édition compilée et capacités qui en découlent (docs/44).

Deux éditions Windows sont produites depuis **le même code source** :

- ``complete`` : transcription locale (faster-whisper), diarization, Dictée, Journal ;
- ``lite`` : enregistrement Opus seul, transcription et CR délégués à l'API Mistral.

L'édition est figée au build par ``packaging/windows/generer_version.py``, qui écrit
``EDITION_COMPILEE`` dans ``_version.py``. Ce **même** fichier est relu par
``packaging/windows/debriefMeet.spec`` (regex) pour ses ``excludes`` : le contenu du
bundle et le comportement de l'app ne peuvent donc pas se contredire.

Le code métier interroge les prédicats ``avec_*`` — jamais ``edition()`` directement :
chaque appel documente ainsi *pourquoi* il est conditionné, et une future édition qui
garderait la dictée en retirant la diarization ne toucherait que ce module.
"""
from __future__ import annotations

import logging
import os

import debrief_meet

logger = logging.getLogger(__name__)

COMPLETE = "complete"
LITE = "lite"
EDITIONS = (COMPLETE, LITE)

# Permet d'exercer l'édition lite depuis les sources (dev macOS, tests) sans rebuild.
VAR_ENV = "DEBRIEFMEET_EDITION"


def _normaliser(valeur: object, origine: str) -> str | None:
    """Édition valide, ou None si absente/invalide (avertie, jamais levée)."""
    if valeur is None:
        return None
    texte = str(valeur).strip().lower()
    if not texte:
        return None
    if texte not in EDITIONS:
        logger.warning("Édition inconnue %r (%s) — ignorée, repli sur « %s »",
                       texte, origine, COMPLETE)
        return None
    return texte


def edition() -> str:
    """Édition courante : « complete » ou « lite ».

    Résolution volontairement **monotone** : la variable d'environnement peut
    *restreindre* (complète → lite), jamais élargir. Un bundle lite ne contient pas
    faster-whisper ; le laisser se croire complet ferait tomber la fabrique sur
    `MoteurStub`, dont la sortie « [stub — pas de transcription réelle] » serait
    écrite dans un vrai débrief.

    L'environnement est relu à **chaque appel** (et non figé à l'import) : c'est ce
    qui rend l'édition lite testable par un simple `monkeypatch.setenv`, sans
    `importlib.reload` — dangereux avec Qt (docs/26). Coût : un `dict.get` au moment
    de construire un widget ou de démarrer une réunion, jamais dans la boucle audio.
    """
    figee = _normaliser(debrief_meet.EDITION_COMPILEE, "build")
    surcharge = _normaliser(os.environ.get(VAR_ENV), f"${VAR_ENV}")
    if figee == LITE or surcharge == LITE:
        return LITE
    return COMPLETE


def est_lite() -> bool:
    return edition() == LITE


# ── Capacités ────────────────────────────────────────────────────────────────
#
# Absentes en lite : le moteur Whisper embarqué, la passe « qui a parlé » (pyannote,
# déjà hors du bundle Windows) et les modes Dictée/Journal, qui n'ont aucun équivalent
# distant (leur intérêt est le retour immédiat : presse-papiers / entrée du jour).

def avec_transcription_locale() -> bool:
    """Moteur de transcription embarqué (sélecteur de modèle, transcription en
    direct, transcription différée depuis l'Historique)."""
    return not est_lite()


def avec_diarization() -> bool:
    """Passe finale « qui a parlé » (pyannote) — dépend du moteur local."""
    return not est_lite()


def avec_dictee_journal() -> bool:
    """Modes Dictée et Journal (tray, pages, raccourcis globaux)."""
    return not est_lite()
