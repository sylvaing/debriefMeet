__version__ = "0.4.0"
APP_NAME = "debriefMeet"

# `_version.py` est généré par le script de build (docs/31 §3.2, docs/32) — absent en
# exécution depuis les sources (dev).
#
# Garder la forme `from debrief_meet._version import X` : ne PAS remplacer par
# `from debrief_meet import _version` + getattr — cette forme se satisfait de
# l'attribut déjà posé sur le paquet et court-circuite alors `sys.modules`, ce qui rend
# le module intestable (tests/test_version.py neutralise justement le sous-module par
# `sys.modules[...] = None`) — régression constatée sur la gate VM le 2026-07-30.
try:
    # Format : "<__version__>+<AAAAMMJJ>.<git-hash-court>".
    from debrief_meet._version import VERSION_COMPLETE
except ImportError:
    VERSION_COMPLETE = __version__ + "+dev"
