"""Découpage = REPLI seulement (§10, docs/42) — jamais le chemin normal.

Le spike (`spike/mistral-cr/`) a validé l'envoi d'une piste ENTIÈRE de 37,6 min en un
seul appel à l'endpoint transcription : ce module n'est déclenché que si une piste
très longue est refusée pour cause de durée, en timeout malgré les reprises, ou en
quota (429) dès le premier refus — en tier gratuit une piste longue dépasse à elle
seule la fenêtre tokens/minute (74 min refusées chez une utilisatrice le 2026-08-05)
(cf. `transcription.py`). Découpe l'Opus PAR COPIE (aucun ré-encodage) — chunks
compacts, contrairement à un ré-encodage WAV.
"""
from __future__ import annotations

from pathlib import Path

from debrief_meet.core.ffmpeg import executer
from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable, chemin_ffmpeg

# 840 s = 14 min — marge sous la limite « ~15 min » documentée par Mistral pour
# l'endpoint transcription (le plafond réel exact est inconnu, cf. docs/42 §10).
LIMITE_SEGMENT_S = 14 * 60


def decouper_piste(chemin: Path, dossier_sortie: Path,
                   limite_s: int = LIMITE_SEGMENT_S) -> list[Path]:
    """Découpe `chemin` en segments ≤ `limite_s`, par copie (pas de ré-encodage).

    Retourne les chemins des segments dans l'ordre chronologique — l'offset temporel
    du segment d'index `i` est `i * limite_s` secondes (chaque segment est réécrit
    avec des timestamps repartant de 0 via `-reset_timestamps 1`, à réappliquer côté
    appelant). Lève `ErreurFfmpegIntrouvable` si ffmpeg est indisponible, et
    `ErreurFfmpeg` — stderr résumé compris — si la commande échoue : c'est ce repli
    qui sortait en 8 sans rien dire le 2026-09-02, muxer `segment` absent du binaire
    embarqué (docs/42 §10.4)."""
    exe = chemin_ffmpeg()
    if exe is None:
        raise ErreurFfmpegIntrouvable()
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    motif = dossier_sortie / f"seg_%03d{chemin.suffix}"
    executer(exe, "-y", "-loglevel", "error", "-i", str(chemin),
             "-f", "segment", "-segment_time", str(limite_s),
             "-reset_timestamps", "1", "-c", "copy", str(motif))
    return sorted(dossier_sortie.glob(f"seg_*{chemin.suffix}"))
