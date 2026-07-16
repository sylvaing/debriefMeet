from __future__ import annotations

import logging
import sys
from pathlib import Path

from debrief_meet.platform.interfaces import DemarrageAuto

logger = logging.getLogger(__name__)

_BUNDLE_ID = "com.sylvaingarcia.debriefmeet"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_BUNDLE_ID}.plist"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
</dict>
</plist>
"""


class DemarrageAutoMacOS(DemarrageAuto):
    def __init__(self, plist_path: Path = _PLIST_PATH) -> None:
        self._plist_path = plist_path

    def est_active(self) -> bool:
        return self._plist_path.exists()

    def activer(self) -> None:
        from debrief_meet.core.ressources import est_figee

        # En app figée, sys.argv[0] est peu fiable (peut être relatif, ou différer
        # du binaire réellement exécuté) ; sys.executable pointe toujours sur
        # Contents/MacOS/debriefMeet. En dev, sys.executable serait l'interpréteur
        # Python du venv — on garde donc sys.argv[0] dans ce cas (docs/16 §5.4).
        executable = Path(sys.executable).resolve() if est_figee() else Path(sys.argv[0]).resolve()
        contenu = _PLIST_TEMPLATE.format(label=_BUNDLE_ID, executable=executable)
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._plist_path.write_text(contenu, encoding="utf-8")
        logger.info("Démarrage auto activé → %s", self._plist_path)

    def desactiver(self) -> None:
        if self._plist_path.exists():
            self._plist_path.unlink()
            logger.info("Démarrage auto désactivé")
