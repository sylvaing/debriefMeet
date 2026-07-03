"""Outil de benchmark cross-platform pour debriefMeet.

Rejoue le pipeline réel (chargement → transcription → diarisation) sur un audio
canonique embarqué, mesure perf + qualité, sonde la capture audio système et les
accélérateurs, puis produit un rapport au format identique sur tous les OS.

Conçu pour tourner **une seule fois** sur une machine cible (Windows / Linux /
macOS baseline) et n'exiger ni installation ni réseau. Voir docs/08-benchmark.md.
"""
from __future__ import annotations

VERSION_SCHEMA = 1
