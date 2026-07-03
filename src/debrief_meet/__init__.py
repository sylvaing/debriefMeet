__version__ = "0.2.0"
APP_NAME = "debriefMeet"

try:
    # Généré par le script de build (docs/31 §3.2, docs/32) — absent en exécution
    # depuis les sources (dev). Format : "<__version__>+<AAAAMMJJ>.<git-hash-court>".
    from debrief_meet._version import VERSION_COMPLETE
except ImportError:
    VERSION_COMPLETE = __version__ + "+dev"
