"""Dialog — détail de l'événement BlueMind associé (lecture seule).

Ouvert par un clic sur l'icône calendrier verte de l'Historique (ou l'item
« Associé — … » du menu ⋯) une fois la réunion associée : titre et date de
l'événement, puis les participants — ceux retenus à l'association en encre
normale, ceux décochés dans le dialogue F1 en grisé (« non retenu »). Tout
vient du sidecar `bluemind.json`, aucun accès réseau ni au store."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from debrief_meet.core.bluemind.association import Association
from debrief_meet.core.bluemind.sync import libelle_part_status
from debrief_meet.ui.bluemind_association import libelle_section
from debrief_meet.ui.dialogues import DialogueGabarit, Intention
from debrief_meet.ui.theme import C, SANS


class DialogDetailsBluemind(DialogueGabarit):
    def __init__(self, association: Association, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            titre="Événement associé",
            description="Cette réunion est associée à un événement du calendrier BlueMind.",
            icone="calendar-check", intention=Intention.ACCENT, largeur_carte=440)

        titre_lbl = QLabel(f"<b>Titre :</b> {association.titre}")
        titre_lbl.setFont(QFont(SANS, 13.5))
        titre_lbl.setStyleSheet(f"color: {C.INK900};")
        titre_lbl.setWordWrap(True)
        self.zone_corps.addWidget(titre_lbl)

        try:
            debut_texte = datetime.fromisoformat(association.debut).strftime("%d/%m/%Y à %H:%M")
        except ValueError:
            debut_texte = association.debut
        date_lbl = QLabel(debut_texte)
        date_lbl.setFont(QFont("IBM Plex Mono", 12))
        date_lbl.setStyleSheet(f"color: {C.INK500};")
        self.zone_corps.addWidget(date_lbl)

        self.zone_corps.addWidget(libelle_section("Participants"))
        for invite in association.invites:
            statut = "organisateur" if invite.organisateur else libelle_part_status(invite.part_status)
            texte = f"{invite.nom} <{invite.email}> — {statut}"
            if not invite.coche:
                texte += " — non retenu"
            lab = QLabel(texte)
            lab.setFont(QFont(SANS, 13))
            lab.setStyleSheet(f"color: {C.INK900 if invite.coche else C.INK400};")
            lab.setWordWrap(True)
            self.zone_corps.addWidget(lab)
        if not association.invites:
            vide = QLabel("Aucun participant enregistré à l'association.")
            vide.setFont(QFont(SANS, 13))
            vide.setStyleSheet(f"color: {C.INK400};")
            self.zone_corps.addWidget(vide)

        self.masquer_annuler()
        self.definir_action("Fermer")
