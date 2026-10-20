"""Compléments de captures : onglets correctement cochés + dialogue d'association BlueMind."""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
SORTIE = Path(sys.argv[1]); SORTIE.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
app = QApplication([])
from debrief_meet.ui.polices import charger_polices
from debrief_meet.ui.theme import charger_theme
charger_polices(app); charger_theme(app)
from debrief_meet.core import mode_transcription
mode_transcription._mode = "local"

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats
tmp = Path(tempfile.mkdtemp())
reunions = tmp / "reunions"; reunions.mkdir(); journal = tmp / "journal"; journal.mkdir()
d = reunions / "2026-09-10_14-05-00"; d.mkdir()
md = d / "transcription.md"
md.write_text("# Réunion — 10/09/2026 14:05\n\n<!-- duree_s: 1702 -->\n", encoding="utf-8")
for jour in ("2026-09-11", "2026-09-10"):
    (journal / f"{jour}.md").write_text(f"# {jour}\n\n- Relancer Bastien\n", encoding="utf-8")
cfg = Config(chemin=tmp / "config.json")
cfg.set("dossier_reunions", str(reunions)); cfg.set("dossier_journal", str(journal)); cfg.sauvegarder()

from debrief_meet.ui.fenetre_principale import FenetrePrincipale, PAGE_DICTEE, PAGE_JOURNAL
fen = FenetrePrincipale(MachineEtats(), cfg); fen.resize(1000, 660); fen.show(); app.processEvents()

def grab(w, nom):
    app.processEvents(); w.grab().save(str(SORTIE / f"{nom}.png"), "PNG"); print("→", nom)

for bouton, page, nom in ((fen._nav_dictee, PAGE_DICTEE, "04-dictee"),
                          (fen._nav_journal, PAGE_JOURNAL, "05-journal")):
    bouton.setChecked(True); fen._sur_nav_change(page); grab(fen, nom)

fen.afficher_reunion()
from debrief_meet.core.bluemind.store import Evenement
from debrief_meet.ui.bluemind_association import DialogAssociationBluemind
import datetime as dt
debut = int(dt.datetime(2026, 9, 10, 14, 5).timestamp() * 1000)
evt = Evenement(
    uid="u1", cal_uid="c1", debut_ms=debut, fin_ms=debut + 3600_000, journee_entiere=False,
    titre="Acme — discussion devis", lieu="Visio",
    organisateur={"nom": "Sylvain Garcia", "email": "sylvain.garcia@bluemind.net"},
    invites=[{"nom": "Alix Morel", "email": "alix.morel@exemple.fr", "part_status": "Accepted"},
             {"nom": "Bastien Lenoir", "email": "bastien.lenoir@exemple.fr", "part_status": "NeedsAction"},
             {"nom": "Claire Durand", "email": "c.durand@acme.example", "part_status": "Declined"}])
dlg = DialogAssociationBluemind(md, [evt], fen, contexte_cr=True)
dlg.show(); grab(fen, "15-dialogue-association-bluemind"); dlg.reject()
print("OK")
