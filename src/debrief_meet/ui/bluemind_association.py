"""Dialog F1 — associer un enregistrement à un événement de calendrier BlueMind
(docs/40 §6.2/§6.3) : choix de l'événement (si plusieurs correspondances), puis
récapitulatif avec la liste des invités **cochables** (tous cochés par défaut)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.bluemind.association import Association, InviteAssocie, finaliser_association
from debrief_meet.core.bluemind.store import Evenement
from debrief_meet.core.bluemind.sync import libelle_part_status
from debrief_meet.core.fichiers import titre_reunion
from debrief_meet.ui.theme import C, SANS


def _libelle_section(texte: str) -> QLabel:
    """Étiquette de section discrète (« PARTICIPANTS ») — mêmes codes que les
    libellés de champ des Préférences (DESIGN.md §3/§8.4)."""
    lab = QLabel(texte.upper())
    lab.setFont(QFont(SANS, 11, QFont.Weight.DemiBold))
    lab.setStyleSheet(f"color: {C.INK400}; letter-spacing: 0.5px;")
    return lab


class DialogAssociationBluemind(QDialog):
    def __init__(self, chemin_md: Path, evenements: list[Evenement], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Associer à la réunion")
        self.setMinimumWidth(460)
        self._chemin_md = chemin_md
        self._evenements = evenements
        self._evenement_choisi: Evenement | None = None
        self._checks_invites: list[tuple[QCheckBox, dict]] = []
        self._check_titre: QCheckBox | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        self._pages = QStackedWidget(self)
        layout.addWidget(self._pages)

        self._page_choix: QWidget | None = None
        if len(evenements) > 1:
            self._page_choix = self._construire_page_choix()
            self._pages.addWidget(self._page_choix)

        self._page_recap = QWidget()
        self._lay_recap = QVBoxLayout(self._page_recap)
        self._pages.addWidget(self._page_recap)

        self._boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._boutons.accepted.connect(self._valider)
        self._boutons.rejected.connect(self.reject)
        layout.addWidget(self._boutons)

        if len(evenements) == 1:
            self._selectionner_evenement(evenements[0])
        elif len(evenements) > 1:
            self._pages.setCurrentWidget(self._page_choix)
            self._boutons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    # ── Choix (si plusieurs correspondances) ────────────────────────────────────

    def _construire_page_choix(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Plusieurs événements correspondent — choisissez lequel associer :"))
        liste = QListWidget()
        for evt in self._evenements:
            heure = datetime.fromtimestamp(evt.debut_ms / 1000).strftime("%H:%M")
            item = QListWidgetItem(f"{evt.titre} — {heure}")
            item.setData(Qt.ItemDataRole.UserRole, evt)
            liste.addItem(item)
        liste.currentItemChanged.connect(self._sur_choix_liste)
        lay.addWidget(liste)
        self._liste_choix = liste
        return w

    def _sur_choix_liste(self, courant: QListWidgetItem | None, _precedent) -> None:
        if courant is None:
            return
        self._selectionner_evenement(courant.data(Qt.ItemDataRole.UserRole))
        self._pages.setCurrentWidget(self._page_recap)
        self._boutons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    # ── Récapitulatif + invités cochables ────────────────────────────────────────

    def _selectionner_evenement(self, evt: Evenement) -> None:
        self._evenement_choisi = evt
        while self._lay_recap.count():
            item = self._lay_recap.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._lay_recap.setSpacing(10)

        # En-tête : « Titre : » en gras + titre de l'événement, puis date/heure
        # en second plan (même hiérarchie que les libellés de champ des Préférences).
        debut_dt = datetime.fromtimestamp(evt.debut_ms / 1000)
        titre_lbl = QLabel(f"<b>Titre :</b> {evt.titre}")
        titre_lbl.setFont(QFont(SANS, 13.5))
        titre_lbl.setStyleSheet(f"color: {C.INK900};")
        titre_lbl.setWordWrap(True)
        self._lay_recap.addWidget(titre_lbl)

        date_lbl = QLabel(debut_dt.strftime("%d/%m/%Y à %H:%M"))
        date_lbl.setFont(QFont(SANS, 12))
        date_lbl.setStyleSheet(f"color: {C.INK500};")
        self._lay_recap.addWidget(date_lbl)

        self._check_titre = QCheckBox("Appliquer ce titre à la réunion")
        self._check_titre.setChecked(titre_reunion(self._chemin_md) is None)
        self._lay_recap.addWidget(self._check_titre)

        self._lay_recap.addSpacing(14)
        self._lay_recap.addWidget(_libelle_section("Participants"))

        self._checks_invites = []
        personnes = []
        if evt.organisateur:
            personnes.append({**evt.organisateur, "organisateur": True})
        for inv in evt.invites:
            personnes.append({**inv, "organisateur": False})

        for p in personnes:
            libelle = "organisateur" if p["organisateur"] else libelle_part_status(p.get("part_status"))
            check = QCheckBox(f"{p.get('nom') or p.get('email', '')} <{p.get('email', '')}> — {libelle}")
            check.setChecked(True)
            self._lay_recap.addWidget(check)
            self._checks_invites.append((check, p))

        self._pages.setCurrentWidget(self._page_recap)

    # ── Validation ───────────────────────────────────────────────────────────────

    def _valider(self) -> None:
        evt = self._evenement_choisi
        if evt is None:
            self.reject()
            return

        invites = [
            InviteAssocie(
                nom=p.get("nom") or p.get("email", ""), email=p.get("email", ""),
                part_status=p.get("part_status"), organisateur=bool(p.get("organisateur")),
                coche=check.isChecked(),
            )
            for check, p in self._checks_invites
        ]

        debut_dt = datetime.fromtimestamp(evt.debut_ms / 1000).astimezone()
        association = Association(
            event_uid=evt.uid, cal_uid=evt.cal_uid, titre=evt.titre,
            debut=debut_dt.isoformat(), invites=invites,
        )
        appliquer_titre = self._check_titre is not None and self._check_titre.isChecked()
        finaliser_association(self._chemin_md, association, appliquer_titre)

        self.accept()
