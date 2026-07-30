__version__ = "0.2.0"
APP_NAME = "debriefMeet"

try:
    # Généré par le script de build (docs/31 §3.2, docs/32, docs/44) — absent en
    # exécution depuis les sources (dev).
    from debrief_meet import _version as _v
except ImportError:
    VERSION_COMPLETE = __version__ + "+dev"
    EDITION_COMPILEE = "complete"
else:
    # `getattr` plutôt qu'un import de noms : un `_version.py` produit par un
    # générateur antérieur (sans EDITION_COMPILEE) ne doit pas faire retomber
    # VERSION_COMPLETE en "+dev" au passage.
    # Format : "<__version__>+<AAAAMMJJ>.<git-hash-court>".
    VERSION_COMPLETE = getattr(_v, "VERSION_COMPLETE", __version__ + "+dev")
    EDITION_COMPILEE = getattr(_v, "EDITION_COMPILEE", "complete")
