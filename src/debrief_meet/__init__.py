__version__ = "0.2.0"
APP_NAME = "debriefMeet"

# `_version.py` est généré par le script de build (docs/31 §3.2, docs/32, docs/44) —
# absent en exécution depuis les sources (dev).
#
# DEUX blocs séparés, et la forme `from debrief_meet._version import X` : un
# `_version.py` produit par un générateur antérieur (sans EDITION_COMPILEE) ne doit pas
# faire retomber VERSION_COMPLETE en "+dev" au passage. Ne PAS remplacer par
# `from debrief_meet import _version` + getattr : cette forme se satisfait de
# l'attribut déjà posé sur le paquet et court-circuite alors `sys.modules`, ce qui rend
# le module intestable (tests/test_version.py neutralise justement le sous-module par
# `sys.modules[...] = None`) — régression constatée sur la gate VM le 2026-07-30.
try:
    # Format : "<__version__>+<AAAAMMJJ>.<git-hash-court>".
    from debrief_meet._version import VERSION_COMPLETE
except ImportError:
    VERSION_COMPLETE = __version__ + "+dev"

try:
    from debrief_meet._version import EDITION_COMPILEE   # "complete" | "lite"
except ImportError:
    EDITION_COMPILEE = "complete"
