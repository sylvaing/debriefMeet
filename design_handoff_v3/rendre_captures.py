"""Rend les écrans réels de debriefMeet en offscreen (PNG) pour le handoff design."""
from __future__ import annotations

import sys, tempfile
from pathlib import Path

SORTIE = Path(sys.argv[1]); SORTIE.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication([])
from debrief_meet.ui.polices import charger_polices
from debrief_meet.ui.theme import charger_theme
charger_polices(app); charger_theme(app)

from debrief_meet.core import mode_transcription
mode_transcription._mode = "local"          # montre toutes les pages (Dictée/Journal)

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, chemin_cr_mistral, chemin_locuteurs
from debrief_meet.core.modes import MachineEtats, Mode

tmp = Path(tempfile.mkdtemp())
reunions = tmp / "reunions"; reunions.mkdir()
journal = tmp / "journal"; journal.mkdir()

def reunion(nom, titre, duree, etat="transcrit", audio=True):
    d = reunions / nom; d.mkdir()
    md = d / "transcription.md"
    corps = f"# {titre}\n\n<!-- duree_s: {duree} -->\n\n"
    if etat == "attente":
        corps += f"> {MARQUEUR_EN_ATTENTE}\n\n"
    else:
        corps += "**[00:12] Moi** — On démarre ?\n\n**[00:31] Participants** — Oui, c'est parti.\n"
    md.write_text(corps, encoding="utf-8")
    if audio:
        (d / "moi.opus").write_bytes(b"x")
        (d / "systeme.opus").write_bytes(b"x")
    if etat == "locuteurs":
        chemin_locuteurs(md).write_text("## Locuteur 1\n", encoding="utf-8")
    if etat == "cr":
        chemin_cr_mistral(md).write_text("**Compte-rendu**\n", encoding="utf-8")
    return md

reunion("2026-09-11_09-30-00_point-commerce-hebdo", "Point commerce hebdo", 3180, "cr")
reunion("2026-09-10_14-05-00_acme-discussion-devis", "Acme — discussion devis", 1702, "locuteurs")
reunion("2026-09-09_11-00-00_demo-produit-mairie-de-villeneuve", "Démo produit — Mairie de Villeneuve", 2410, "transcrit")
reunion("2026-09-08_16-20-00", "Réunion — 08/09/2026 16:20", 940, "attente")
reunion("2026-09-05_08-45-00_retro-sprint-42", "Rétro sprint 42", 2755, "transcrit", audio=False)

for jour, note in (("2026-09-11", "Relancer Bastien sur le devis Acme"),
                   ("2026-09-10", "3 notes"),
                   ("2026-09-09", "Penser à préparer la démo de vendredi")):
    (journal / f"{jour}.md").write_text(f"# {jour}\n\n- {note}\n", encoding="utf-8")

cfg = Config(chemin=tmp / "config.json")
cfg.set("dossier_reunions", str(reunions)); cfg.set("dossier_journal", str(journal))
cfg.set("mode_transcription", "local")
cfg.set("mistral_cle_api", "")
cfg.sauvegarder()

from debrief_meet.ui.fenetre_principale import FenetrePrincipale, PAGE_DICTEE, PAGE_JOURNAL

machine = MachineEtats()
fen = FenetrePrincipale(machine, cfg)
fen.resize(1000, 660)
fen.show()
app.processEvents()

def grab(widget, nom):
    app.processEvents()
    widget.grab().save(str(SORTIE / f"{nom}.png"), "PNG")
    print("→", nom)

grab(fen, "01-reunion-liste")

# Page Réunion avec enregistrement en cours (ligne « en cours » + bouton Arrêter)
fen._reunion_view.definir_etat_enregistrement(Mode.REUNION, 137)
grab(fen, "02-reunion-enregistrement-en-cours")
fen._reunion_view.definir_etat_enregistrement(Mode.IDLE, 0)

# Sélection multiple → barre d'actions en masse
tbl = fen._reunion_view._table
tbl.selectRow(0); tbl.selectRow(1)
from PySide6.QtCore import QItemSelectionModel
sm = tbl.selectionModel()
sm.select(tbl.model().index(0, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
grab(fen, "03-reunion-selection-multiple")
tbl.clearSelection()

# Dictée / Journal
fen._sur_nav_change(PAGE_DICTEE); grab(fen, "04-dictee")
fen._sur_nav_change(PAGE_JOURNAL); grab(fen, "05-journal")

# Préférences, section par section
fen.afficher_preferences()
nav = fen._preferences_view._nav
for i in range(nav.count()):
    nav.setCurrentRow(i)
    titre = nav.item(i).text().lower().replace(" ", "-").replace("é", "e")
    grab(fen, f"06-preferences-{i}-{titre}")

# Menu ⋯ d'une ligne de réunion
fen.afficher_reunion()
from debrief_meet.ui.actions_menu import construire_menu_actions
index = fen._reunion_view._proxy.index(1, 6)
ligne = fen._reunion_view._actions_pour_index(index)
menu = construire_menu_actions(ligne.menu, fen)
menu.show(); grab(menu, "07-menu-actions-ligne"); menu.hide()

# Menu du tray
from debrief_meet.ui.tray import IconeTray
tray = IconeTray(machine, cfg, fenetre_principale=fen)
tray._menu.show(); app.processEvents(); grab(tray._menu, "08-menu-tray"); tray._menu.hide()

# Dialogues
from debrief_meet.ui import dialogues
dlg = dialogues.DialogueGabarit(
    fen, titre="Supprimer 2 réunions ?",
    description="2 réunions seront supprimées définitivement (transcription, débrief et audio inclus).",
    icone="trash", intention=dialogues.Intention.DESTRUCTIF)
dlg.definir_action("Supprimer")
dlg.show(); grab(fen, "09-dialogue-confirmation"); dlg.reject()

dlg2 = dialogues.DialogueGabarit(
    fen, titre="Générer le CR via Mistral ?",
    description="Cet enregistrement va être envoyé aux serveurs Mistral (UE) : la transcription "
                "locale si elle existe, sinon l'audio retenu pour transcription. Continuer ?",
    icone="notebook", intention=dialogues.Intention.ACCENT)
dlg2.definir_action("Envoyer")
dlg2.show(); grab(fen, "10-dialogue-accent"); dlg2.reject()

# Assistants
from debrief_meet.ui.assistant_mistral import AssistantMistral
a = AssistantMistral(cfg, fen); a.show(); grab(fen, "11-assistant-mistral-etape1")
a._stack.setCurrentIndex(2); grab(fen, "12-assistant-mistral-cle"); a.reject()

from debrief_meet.ui.assistant_diarization import AssistantDiarization
b = AssistantDiarization(fen); b.show(); grab(fen, "13-assistant-diarization-etape1"); b.reject()

# Écran de bienvenue
from debrief_meet.ui.premier_lancement import PremierLancement
p = PremierLancement(cfg, fen); p.show(); grab(fen, "14-premier-lancement"); p.reject()

print("OK", SORTIE)
