"""Pose HTML + texte brut sur le presse-papiers — implémentation commune aux 3 OS.

Un éditeur riche (note Pipedrive, webmail, traitement de texte) ne met en forme que
ce qu'il reçoit **en HTML** : du markdown collé en texte brut reste littéral. Qt
expose les deux formats en une seule opération et traduit `text/html` vers le format
natif de chaque plate-forme (`public.html` sur macOS, `CF_HTML` sur Windows,
`text/html` sur X11/Wayland) — d'où ce module unique plutôt que trois adaptateurs.

Le repli texte n'est pas un pis-aller : c'est lui que reçoit une cible qui ne prend
pas le HTML (terminal, champ de saisie simple) **et** un éditeur markdown, où le
markdown source est justement le bon contenu. Les deux flavors sont donc utiles,
chacune à sa cible.

⚠️ macOS n'utilise pas `pbcopy` ici, contrairement à `copier()` : `pbcopy` n'écrit
que du texte brut, il ne peut pas porter de flavor HTML.

Appels depuis le thread principal Qt uniquement — comme le reste du presse-papiers.
Les 4 sites de copie de l'app sont sur ce thread (les vues, et la dictée via un slot
en connexion queued).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def poser_html(html: str, texte: str, origine: str = "") -> None:
    """Pose `html` (flavor riche) et `texte` (repli brut) en une seule opération."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QGuiApplication

    mime = QMimeData()
    mime.setHtml(html)
    mime.setText(texte)
    QGuiApplication.clipboard().setMimeData(mime)
    # Jamais le contenu lui-même dans les logs (docs/31 §3.7.1) — les longueurs seules.
    logger.debug("%s: copier_riche(%d chars HTML, %d chars texte)",
                 origine or "PressePapiers", len(html), len(texte))
