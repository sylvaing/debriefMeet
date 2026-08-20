"""Dialog F1 — associer un enregistrement à un événement de calendrier BlueMind
(docs/40 §6.2/§6.3) : choix de l'événement (si plusieurs correspondances), puis
récapitulatif avec la liste des invités **cochables** (tous cochés par défaut).

Restylé sur le gabarit unifié DESIGN.md §8.9/§8.11 (variante accent, positive) :
`DialogueGabarit` porte l'en-tête (tuile `calendar-check` + titre + description)
et le pied (Annuler + Associer) ; `zone_corps` accueille la page de choix
(si plusieurs correspondances) puis le récapitulatif."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.bluemind.association import Association, InviteAssocie, finaliser_association
from debrief_meet.core.bluemind.store import Evenement
from debrief_meet.core.bluemind.sync import libelle_part_status
from debrief_meet.core.fichiers import renommer_dossier_reunion, titre_reunion
from debrief_meet.ui.dialogues import DialogueGabarit, Intention
from debrief_meet.ui.theme import C, SANS


def libelle_section(texte: str) -> QLabel:
    """Étiquette de section discrète (« PARTICIPANTS ») — mêmes codes que les
    libellés de champ des Préférences (DESIGN.md §3/§8.4). Partagée avec le
    dialog de détail (`bluemind_details`)."""
    lab = QLabel(texte.upper())
    lab.setFont(QFont(SANS, 11, QFont.Weight.DemiBold))
    lab.setStyleSheet(f"color: {C.INK400}; letter-spacing: 0.5px;")
    return lab


#: Au-delà de ce nombre d'invités, on ne pré-coche plus tout le monde (docs/50 §3.5).
#: Seuil bas assumé : se tromper dans ce sens coûte un clic sur « Tout cocher », alors
#: que l'erreur inverse envoie au CR des noms de gens absents — et le modèle **invente
#: alors des participants**, sans que rien ne le signale (correctif du 2026-08-06).
SEUIL_PRECOCHAGE = 8

#: Valeur brute BlueMind du statut « accepté » (cf. `_STATUTS_PART` de `sync.py`) — les
#: seuls, avec l'organisateur, à être pré-cochés au-delà du seuil.
STATUT_ACCEPTE = "Accepted"


def _vider_layout(layout) -> None:
    """Vide un layout **et ses sous-layouts**. Récursif à dessein : depuis que l'en-tête
    « PARTICIPANTS » est une ligne (libellé + bascule), un `takeAt` qui ne regarderait
    que `item.widget()` laisserait ces deux widgets orphelins mais toujours affichés au
    changement d'événement."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            _vider_layout(item.layout())


def pre_cocher(personnes: list[dict]) -> bool:
    """Faut-il pré-cocher tout le monde ? Vrai jusqu'à `SEUIL_PRECOCHAGE` invités —
    cas nominal d'une réunion d'équipe, comportement historique inchangé."""
    return len(personnes) <= SEUIL_PRECOCHAGE


def _coche_par_defaut(personne: dict, tout_cocher: bool) -> bool:
    if tout_cocher:
        return True
    return bool(personne.get("organisateur")) or personne.get("part_status") == STATUT_ACCEPTE


class DialogAssociationBluemind(DialogueGabarit):
    """Trois sorties possibles quand `contexte_cr` est vrai (proposition faite juste avant
    un CR Mistral, docs/42) : `Rejected` = renoncer à tout ; `Accepted` avec
    `association_ignoree` = continuer sans associer ; `Accepted` seul = associé (relire
    `chemin_md`). Sans `contexte_cr`, le dialogue garde ses deux sorties historiques."""

    def __init__(self, chemin_md: Path, evenements: list[Evenement], parent: QWidget | None = None,
                 contexte_cr: bool = False) -> None:
        super().__init__(
            parent,
            titre="Associer avant le CR ?" if contexte_cr else "Associer à un événement",
            description=(
                "Un événement du calendrier BlueMind correspond. L'associer transmet son "
                "titre, sa date et ses participants au compte-rendu — et les noms au moteur "
                "de transcription."
                if contexte_cr else
                "Un événement du calendrier BlueMind correspond à cette réunion."),
            # 580 et non 440 (docs/50 §3.4) : « Nom <email> — statut » tient sur une
            # ligne de QCheckBox, qui ne sait pas passer à la ligne. L'infobulle posée
            # sur chaque case reste le filet quand une adresse dépasse quand même.
            icone="calendar-check", intention=Intention.ACCENT, largeur_carte=580)
        self._chemin_md = chemin_md
        self._evenements = evenements
        self._evenement_choisi: Evenement | None = None
        self._checks_invites: list[tuple[QCheckBox, dict]] = []
        self._check_titre: QCheckBox | None = None
        self._association_ignoree = False

        self._pages = QStackedWidget(self)
        self.zone_corps.addWidget(self._pages)

        self._page_choix: QWidget | None = None
        if len(evenements) > 1:
            self._page_choix = self._construire_page_choix()
            self._pages.addWidget(self._page_choix)

        self._page_recap = QWidget()
        self._lay_recap = QVBoxLayout(self._page_recap)
        self._lay_recap.setContentsMargins(0, 0, 0, 0)
        self._pages.addWidget(self._page_recap)

        self.definir_action("Associer", self._valider)
        if contexte_cr:
            # Bouton **toujours actif**, y compris sur la page de choix où « Associer »
            # est désactivé faute d'événement sélectionné : ne pas choisir doit rester
            # une sortie possible sans renoncer au CR.
            self.ajouter_bouton_secondaire("Sans association", self._ignorer)

        if len(evenements) == 1:
            self._selectionner_evenement(evenements[0])
        elif len(evenements) > 1:
            self._pages.setCurrentWidget(self._page_choix)
            self.bouton_action().setEnabled(False)

    @property
    def chemin_md(self) -> Path:
        """Chemin de `transcription.md` — mis à jour après validation si le dossier a
        été renommé (titre appliqué, docs/43 §6.1) : l'appelant doit relire cette
        propriété après `exec()` pour recharger/re-sélectionner la bonne ligne."""
        return self._chemin_md

    @property
    def association_ignoree(self) -> bool:
        """Vrai si l'utilisateur a cliqué « Sans association » (variante `contexte_cr`) :
        le dialogue est accepté mais **rien n'a été écrit** — l'appelant enchaîne sur son
        action (le CR) avec la réunion non associée."""
        return self._association_ignoree

    def _ignorer(self) -> None:
        self._association_ignoree = True
        self.accept()

    # ── Choix (si plusieurs correspondances) ────────────────────────────────────

    def _construire_page_choix(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Plusieurs événements correspondent — choisissez lequel associer :"))
        liste = QListWidget()
        liste.setStyleSheet(
            f"QListWidget {{ border: 1px solid {C.BORDER}; border-radius: 8px; background: #fff; }}")
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
        self.bouton_action().setEnabled(True)

    # ── Récapitulatif + invités cochables ────────────────────────────────────────

    def _selectionner_evenement(self, evt: Evenement) -> None:
        self._evenement_choisi = evt
        _vider_layout(self._lay_recap)
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
        date_lbl.setFont(QFont("IBM Plex Mono", 12))
        date_lbl.setStyleSheet(f"color: {C.INK500};")
        self._lay_recap.addWidget(date_lbl)

        self._check_titre = QCheckBox("Appliquer ce titre à la réunion")
        self._check_titre.setChecked(titre_reunion(self._chemin_md) is None)
        self._lay_recap.addWidget(self._check_titre)

        personnes = []
        if evt.organisateur:
            personnes.append({**evt.organisateur, "organisateur": True})
        for inv in evt.invites:
            personnes.append({**inv, "organisateur": False})

        self._lay_recap.addSpacing(4)
        entete = QHBoxLayout()
        self._libelle_participants = libelle_section("Participants")
        entete.addWidget(self._libelle_participants)
        entete.addStretch()
        self._bouton_tout = QPushButton()
        self._bouton_tout.setObjectName("secondary")
        self._bouton_tout.setStyleSheet("padding: 3px 10px; font-size: 12px;")
        self._bouton_tout.clicked.connect(self._basculer_tout)
        entete.addWidget(self._bouton_tout)
        self._lay_recap.addLayout(entete)

        self._checks_invites = []
        tout_cocher = pre_cocher(personnes)
        for p in personnes:
            libelle = "organisateur" if p["organisateur"] else libelle_part_status(p.get("part_status"))
            texte = f"{p.get('nom') or p.get('email', '')} <{p.get('email', '')}> — {libelle}"
            check = QCheckBox(texte)
            check.setToolTip(texte)          # filet contre la troncature (carte à largeur fixe)
            check.setChecked(_coche_par_defaut(p, tout_cocher))
            check.toggled.connect(self._maj_compteur)
            self._lay_recap.addWidget(check)
            self._checks_invites.append((check, p))

        self._maj_compteur()
        self._pages.setCurrentWidget(self._page_recap)

    # ── Compteur + bascule « tout cocher / tout décocher » ──────────────────────

    def _maj_compteur(self) -> None:
        """Rend visible, sans dérouler la liste, combien d'invités partiront dans le CR —
        et oriente la bascule : tout coché ⇒ on propose de décocher, sinon de cocher."""
        total = len(self._checks_invites)
        coches = sum(1 for check, _ in self._checks_invites if check.isChecked())
        self._libelle_participants.setText(f"PARTICIPANTS ({coches}/{total})")
        self._bouton_tout.setText("Tout décocher" if coches == total and total else "Tout cocher")
        self._bouton_tout.setEnabled(total > 0)

    def _basculer_tout(self) -> None:
        cible = not all(check.isChecked() for check, _ in self._checks_invites)
        for check, _ in self._checks_invites:
            # Signaux coupés : sinon chaque case relance le compteur (34 fois pour rien).
            check.blockSignals(True)
            check.setChecked(cible)
            check.blockSignals(False)
        self._maj_compteur()

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
        if appliquer_titre:
            # Le dossier reflète toujours le titre courant (docs/43 §6.1) — renommage
            # hors enregistrement (l'historique n'affiche que des réunions terminées).
            self._chemin_md = renommer_dossier_reunion(self._chemin_md, association.titre)

        self.accept()
