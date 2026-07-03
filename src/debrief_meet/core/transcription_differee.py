"""Transcription différée — produit le `.md` d'une réunion enregistrée en « audio seul ».

Symétrique de `diarization.generer_locuteurs`, mais **sans diarization** : re-transcrit les
2 pistes retenues (Moi nettoyé AEC + Système), entrelace les segments Whisper par timestamp
et **réécrit** le `.md` (le placeholder « audio seul » est remplacé par la vraie transcription).

Tout est offline, déclenché à la demande depuis l'Historique (cf. docs/10). Le format de
sortie est identique au `.md` produit en direct (blocs **Moi** / **Participants**).
"""
from __future__ import annotations

import logging
from pathlib import Path

from debrief_meet.core.audio import decoder_audio_16k
from debrief_meet.core.fichiers import (
    _entrelaces,
    chemins_audio_reunion,
    definir_duree,
    duree_reunion,
)
from debrief_meet.platform.interfaces import MoteurTranscription, ResultatTranscription

logger = logging.getLogger(__name__)


def _trouver_piste(base: Path) -> Path | None:
    """Localise la piste retenue (.opus prioritaire, sinon .wav) ; None si absente."""
    for ext in (".opus", ".wav"):
        candidat = base.with_suffix(ext)
        if candidat.exists():
            return candidat
    return None


def _titre(md: Path) -> str:
    """Réutilise la ligne de titre du `.md` existant, ou la dérive du nom de fichier."""
    try:
        for ligne in md.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("# "):
                return ligne[2:].strip()
    except OSError:
        pass
    return f"Réunion — {md.stem}"


def _transcrire_piste(chemin_audio: Path, moteur: MoteurTranscription,
                      langue: str | None) -> ResultatTranscription:
    """Décode → transcrit une piste (le moteur normalise en interne, docs/27). Peut lever."""
    audio = decoder_audio_16k(chemin_audio)
    return moteur.transcrire(audio, langue)


def transcrire_reunion(chemin_md, moteur: MoteurTranscription, *,
                       langue: str | None = None) -> Path:
    """Transcrit l'audio retenu d'une réunion et (ré)écrit son `.md`.

    Chaque piste est isolée : une piste manquante ou en échec dégrade le résultat
    sans casser. Lève si AUCUNE piste n'est exploitable."""
    chemin_md = Path(chemin_md)
    base_moi, base_sys = chemins_audio_reunion(chemin_md)
    piste_moi = _trouver_piste(base_moi)
    piste_sys = _trouver_piste(base_sys)
    if piste_moi is None and piste_sys is None:
        raise FileNotFoundError(
            f"Aucune piste audio retenue à côté de {chemin_md.name} "
            "(rétention désactivée ou audio supprimé).")

    res_moi = _transcrire_ou_vide(piste_moi, moteur, langue, "micro")
    res_sys = _transcrire_ou_vide(piste_sys, moteur, langue, "système")
    if res_moi is None and res_sys is None:
        raise RuntimeError("Transcription différée : aucune piste exploitable (toutes en échec).")

    res_moi = res_moi or ResultatTranscription(texte="", langue_detectee=None)
    res_sys = res_sys or ResultatTranscription(texte="", langue_detectee=None)
    segs_moi = [(s.debut, s.texte) for s in res_moi.segments]
    segs_parts = [(s.debut, s.texte) for s in res_sys.segments]
    blocs = _entrelaces(res_moi.texte.strip(), res_sys.texte.strip(), segs_moi, segs_parts)

    # La réécriture remplace tout le fichier : on préserve la durée enregistrée en
    # fin de captation (le titre custom est conservé via `_titre`). Cf. docs/14.
    duree = duree_reunion(chemin_md)
    _ecrire_md(chemin_md, blocs, avec_micro=piste_moi is not None,
               avec_systeme=piste_sys is not None)
    if duree is not None:
        definir_duree(chemin_md, duree)
    logger.info("Transcription différée écrite : %s", chemin_md)
    return chemin_md


def _transcrire_ou_vide(piste: Path | None, moteur, langue, label: str
                        ) -> ResultatTranscription | None:
    if piste is None:
        return None
    try:
        return _transcrire_piste(piste, moteur, langue)
    except Exception as exc:  # noqa: BLE001 — on dégrade, l'autre piste peut passer
        logger.warning("Transcription différée piste %s : ÉCHEC (%s)", label, exc, exc_info=True)
        return None


def _ecrire_md(chemin: Path, blocs: list[tuple[str, str]], *,
               avec_micro: bool, avec_systeme: bool) -> None:
    lignes = [f"# {_titre(chemin)}", "",
              "> Transcription différée — générée depuis l'audio retenu."]
    if not avec_systeme:
        lignes.append("> ⚠️ Audio système non disponible — transcription micro uniquement.")
    if not avec_micro:
        lignes.append("> ⚠️ Microphone non disponible — transcription audio système uniquement.")
    lignes += ["", "---", ""]
    for locuteur, texte in blocs:
        lignes.append(f"**{locuteur} :** {texte}")
        lignes.append("")
    chemin.write_text("\n".join(lignes), encoding="utf-8")
