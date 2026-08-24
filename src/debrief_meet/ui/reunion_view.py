"""Page Réunion (refonte design v2, CHANGELOG_v2 §2/§3) — barre d'action
(bouton Démarrer/Arrêter + recherche) au-dessus du tableau des réunions, avec
une ligne « en cours » insérée en tête pendant l'enregistrement.

Porte la logique métier réunion de l'ancienne `HistoryView` (v1, disparue) —
actions, diarization déléguée au gestionnaire persistant, rafraîchissement
live. La partie Journal vit désormais dans `journal_view.py`.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QFileSystemWatcher, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core import mode_transcription
from debrief_meet.core.bluemind import association as bluemind_association
from debrief_meet.core.bluemind.matching import evenements_correspondants
from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier
from debrief_meet.core.bluemind.sync import SynchroCalendrier
from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import (
    chemin_cr_mistral,
    chemin_locuteurs,
    date_heure_reunion,
    duree_reunion,
    pistes_audio_existantes,
)
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.platform.interfaces import PressePapiers
from debrief_meet.ui import dialogues
from debrief_meet.ui.actions_delegate import (
    ActionsDelegate,
    ActionsLigne,
    ActionSpec,
    BoutonSpec,
    largeur_colonne,
)
from debrief_meet.ui.attente_sync_bluemind import attendre_sync
from debrief_meet.ui.calendrier_delegate import CalendrierColonneDelegate, CalendrierSpec
from debrief_meet.ui.capture_action_bar import CaptureActionBar
from debrief_meet.ui.capture_model import (
    COL_ACTIONS_REUNION,
    COL_CALENDRIER_REUNION,
    COL_TITRE_REUNION,
    JOB_CR_MISTRAL,
    CaptureModel,
)
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.generateur_cr_mistral import GestionnaireCRMistral
from debrief_meet.ui.icon_delegate import IconeColonneDelegate
from debrief_meet.ui.status_pill import StatusPillDelegate
from debrief_meet.ui.survol_ligne import TableAvecSurvolLigne
from debrief_meet.ui.texte_delegate import TexteLigneDelegate
from debrief_meet.ui.theme import C, M

logger = logging.getLogger(__name__)

_ICONE_COPIER = "copy"
_ICONE_COPIER_FICHIER = "file-arrow-up"
_ICONE_TRANSCRIRE = "file-text"
_ICONE_GENERER = "users"
_ICONE_EN_COURS = "clock-counter-clockwise"
_ICONE_OUVRIR = "arrow-square-out"
_ICONE_REVELER = "folder"
_ICONE_SUPPR_AUDIO = "microphone-slash"
_ICONE_TOUT_SUPPR = "trash"
_ICONE_BLUEMIND_ASSOCIER = "calendar-plus"
_ICONE_BLUEMIND_ASSOCIE = "calendar-check"
_ICONE_NOMMER_LOCUTEURS = "chat-text"
_ICONE_CR_MISTRAL = "notebook"

# Nombre MAXIMAL de boutons dédiés que `_boutons_reunion` peut produire (Générer le
# CR ▾ + Copier le CR + Copier le fichier) et de flèches parmi eux. La colonne actions
# est dimensionnée là-dessus : ajouter un bouton sans bouger ces constantes le fait
# déborder à gauche, hors de sa colonne (cf. `_construire_table`).
NB_BOUTONS_REUNION = 3
NB_FLECHES_REUNION = 1


@dataclass(frozen=True)
class _EtatBluemind:
    """Résultat partagé du calcul d'état BlueMind (§6.2) — consommé à la fois par
    l'item du menu ⋯ (`_action_bluemind`) et par la colonne dédiée
    (`_calendrier_pour_index`), pour ne calculer la correspondance qu'une fois."""

    etat: str  # "linked" | "match" | "none"
    titre_evenement: str = ""
    on_associer: Callable[[], None] | None = None
    # Ouvre le détail de l'événement associé (état "linked") — None si le sidecar
    # est illisible : rien à afficher, l'icône redevient passive.
    on_details: Callable[[], None] | None = None


@dataclass(frozen=True)
class _EtatCRMistral:
    """État CR Mistral d'une ligne — partagé entre l'item du menu ⋯ et le bouton
    dédié « Générer le CR » (mêmes disponibilité et infobulle aux deux endroits)."""

    actif: bool
    tooltip: str
    en_cours: bool = False



class ReunionView(QWidget):
    def __init__(
        self,
        config: Config,
        machine: MachineEtats,
        presse_papiers: PressePapiers | None = None,
        gestionnaire: GestionnaireDiarization | None = None,
        store_bluemind: StoreCalendrier | None = None,
        gestionnaire_cr_mistral: GestionnaireCRMistral | None = None,
        synchro_bluemind: SynchroCalendrier | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._machine = machine
        self._presse_papiers = presse_papiers
        self._gestionnaire = gestionnaire
        self._store_bluemind = store_bluemind
        self._gestionnaire_cr_mistral = gestionnaire_cr_mistral
        # Sert **uniquement** à rafraîchir la réplique avant la proposition d'association
        # du flux CR (docs/42 §4.1) : la détection au paint reste locale, sur `_store_bluemind`.
        self._synchro_bluemind = synchro_bluemind
        self._proposition_en_cours = False

        self._modele = CaptureModel(self._dossier(), est_reunion=True, parent=self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._modele)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(COL_TITRE_REUNION)

        self._table = self._creer_table()

        self._construire_ui(machine)
        self._cabler_gestionnaire()
        self._cabler_gestionnaire_cr_mistral()
        self._installer_surveillance()
        self.recharger()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _creer_table(self) -> TableAvecSurvolLigne:
        table = TableAvecSurvolLigne(self)
        table.setModel(self._proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setFrameShape(TableAvecSurvolLigne.Shape.NoFrame)
        table.setSortingEnabled(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(M.ROW_H)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        table.setMouseTracking(True)

        table.setItemDelegate(TexteLigneDelegate(table))
        table.setItemDelegateForColumn(0, IconeColonneDelegate(table))
        table.setItemDelegateForColumn(
            COL_CALENDRIER_REUNION, CalendrierColonneDelegate(self._calendrier_pour_index, table))
        table.setItemDelegateForColumn(
            COL_ACTIONS_REUNION, ActionsDelegate(self._actions_pour_index, table))
        table.setItemDelegateForColumn(4, StatusPillDelegate(table))

        entete = table.horizontalHeader()
        entete.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setColumnWidth(0, 40)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(2, 190)  # date + heure ("JJ/MM/AAAA · HH:MM") — 150px les tronque en mono
        table.setColumnWidth(3, 74)
        table.setColumnWidth(4, 116)
        table.setColumnWidth(COL_CALENDRIER_REUNION, 34)  # icône 28×28 + marge (§8.6.2)
        # Les boutons dédiés + ⋯ : la colonne doit tous les contenir (= sizeHint
        # d'ActionsDelegate, qui ne clippe pas). Sous-dimensionner fait déborder les
        # boutons à GAUCHE, hors de la colonne — c'est ce qui a fait peindre le bouton
        # « Générer le CR » par-dessus l'icône de la colonne « lien calendrier »
        # (constaté sur macOS et Windows le 2026-08-24 : la largeur était restée
        # calée sur 2 boutons après l'ajout du 3ᵉ, « Copier le fichier »).
        table.setColumnWidth(
            COL_ACTIONS_REUNION,
            largeur_colonne(NB_BOUTONS_REUNION, nb_fleches=NB_FLECHES_REUNION))

        raccourci = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), table)
        raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
        raccourci.activated.connect(lambda: self._tout_supprimer(None))

        return table

    def _construire_ui(self, machine: MachineEtats) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._action_bar = CaptureActionBar(
            Mode.REUNION, avec_recherche=True, placeholder_recherche="Rechercher une réunion…",
            actions_masse=True, avec_ignorer_audio=True, parent=self)
        self._action_bar.demande_bascule.connect(machine.toggle_reunion)
        self._action_bar.recherche_change.connect(self._proxy.setFilterFixedString)
        # Actions en masse (§8.6.4) : réutilisent les handlers unitaires avec chemin=None
        # (→ _cibles(None) = sélection), confirmation §8.9 portant le décompte.
        self._action_bar.demande_supprimer_masse.connect(lambda: self._tout_supprimer(None))
        self._action_bar.demande_ignorer_audio_masse.connect(lambda: self._supprimer_audio_un(None))
        self._action_bar.demande_deselection.connect(self._table.clearSelection)
        self._table.selectionModel().selectionChanged.connect(self._sur_selection_change)
        self._modele.modelReset.connect(self._sur_selection_change)
        layout.addWidget(self._action_bar)

        layout.addWidget(self._table, 1)

    def _sur_selection_change(self, *_args) -> None:
        self._action_bar.definir_compte_selection(len(self._chemins_selectionnes()))

    # ── Machine à états (RecordingController) ───────────────────────────────────

    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None:
        self._action_bar.definir_etat(mode_actif, secondes)
        self._modele.definir_ligne_en_cours(mode_actif is Mode.REUNION, secondes)

    # ── Chargement ───────────────────────────────────────────────────────────

    def _dossier(self) -> Path:
        return Path(self._config.get("dossier_reunions"))

    def recharger(self) -> None:
        """Unique point de rechargement de la vue : pousse d'abord au modèle le
        traitement a posteriori en cours (transcription / locuteurs / CR), pour que la
        colonne 0 de la réunion concernée montre l'icône de l'opération. Tout passe
        ici — un `self._modele.recharger()` direct laisserait l'icône se périmer."""
        self._modele.definir_job_en_cours(*self._job_en_cours())
        self._modele.recharger()

    def _job_en_cours(self) -> tuple[Path | None, str | None]:
        """(réunion, type) du job a posteriori en cours. Les deux gestionnaires sont
        exclusifs en pratique (chacun refuse de démarrer si l'autre tourne, via
        `un_job_tourne`), mais Mistral est interrogé d'abord : c'est le seul dont le
        job peut durer sans que `_gestionnaire` en sache quoi que ce soit."""
        if self._gestionnaire_cr_mistral is not None:
            chemin = self._gestionnaire_cr_mistral.job_en_cours()
            if chemin is not None:
                return Path(chemin), JOB_CR_MISTRAL
        if self._gestionnaire is not None:
            chemin = self._gestionnaire.job_en_cours()
            if chemin is not None:
                return Path(chemin), self._gestionnaire.type_job_en_cours()
        return None, None

    # ── Actions par ligne (fournisseur du délégué) ──────────────────────────────

    def _actions_pour_index(self, index: QModelIndex) -> ActionsLigne:
        proxy = index.model()
        source = proxy.mapToSource(index)
        info = self._modele.info_ligne(source.row())
        if info is None or info.en_cours:
            return ActionsLigne()
        return self._actions_reunion(info)

    def _actions_reunion(self, ligne) -> ActionsLigne:
        """Menu ⋯ **exhaustif** (toutes les actions de la ligne) + 2 boutons dédiés :
        « Générer le CR ▾ » (flèche = choix ponctuel du prompt) et « Copier le CR »."""
        chemin = ligne.chemin
        job = self._gestionnaire.job_en_cours() if self._gestionnaire else None
        type_job = self._gestionnaire.type_job_en_cours() if self._gestionnaire else None
        en_cours = chemin == job
        un_job_tourne = job is not None
        etat_cr = self._etat_cr_mistral(ligne, un_job_tourne)

        actions = [ActionSpec(_ICONE_COPIER, "Copier la transcription", not ligne.en_attente,
                              lambda c=chemin: self._copier(c)),
                   ActionSpec(_ICONE_COPIER_FICHIER, "Copier le fichier de la transcription",
                              True, lambda c=chemin: self._copier_fichier(c))]

        # Édition lite : ces deux actions n'existent pas du tout (docs/44). Sans ce gate
        # elles seraient bien ajoutées puis grisées — `dispo`/`prete` ne pilotent que
        # `actif` et l'infobulle — donc CHAQUE ligne afficherait une icône morte
        # « Moteur de transcription indisponible », et l'autre renverrait vers une
        # ligne de Préférences › Audio qui n'existe plus.
        if ligne.en_attente and mode_transcription.avec_transcription_locale():
            if en_cours and type_job == "transcription":
                actions.append(ActionSpec(_ICONE_EN_COURS, "Transcription en cours…", False, lambda: None))
            else:
                dispo = self._gestionnaire is not None and self._gestionnaire.disponible()
                actif = dispo and bool(ligne.audio) and not un_job_tourne
                tooltip = "Transcrire la réunion"
                if not ligne.audio:
                    tooltip = "Aucun audio à transcrire"
                elif not dispo:
                    tooltip = "Moteur de transcription indisponible"
                elif un_job_tourne:
                    tooltip = "Une tâche est déjà en cours"
                actions.append(ActionSpec(_ICONE_TRANSCRIRE, tooltip, actif,
                                          lambda c=chemin: self._transcrire(c)))
        elif not ligne.en_attente and mode_transcription.avec_diarization():
            if en_cours and type_job == "diarization":
                actions.append(
                    ActionSpec(_ICONE_EN_COURS, "Génération des locuteurs en cours…", False, lambda: None))
            else:
                prete = self._gestionnaire is not None and self._gestionnaire.diarization_prete()
                actif = prete and bool(ligne.audio) and not ligne.locuteurs and not un_job_tourne
                tooltip = "Générer les locuteurs"
                if ligne.locuteurs:
                    tooltip = "Locuteurs déjà générés"
                elif not ligne.audio:
                    tooltip = "Aucun audio retenu"
                elif not prete:
                    tooltip = "Diarization non configurée — Préférences › Audio"
                elif un_job_tourne:
                    tooltip = "Une génération est déjà en cours"
                actions.append(ActionSpec(_ICONE_GENERER, tooltip, actif,
                                          lambda c=chemin: self._generer(c)))

        if ligne.locuteurs:
            actions.append(ActionSpec(
                _ICONE_NOMMER_LOCUTEURS, "Nommer les locuteurs", True,
                lambda c=chemin: self._nommer_locuteurs(c)))

        if etat_cr is not None:
            icone = _ICONE_EN_COURS if etat_cr.en_cours else _ICONE_CR_MISTRAL
            actions.append(ActionSpec(icone, etat_cr.tooltip, etat_cr.actif,
                                      lambda c=chemin: self._generer_cr_mistral(c)))

        actions.append(ActionSpec(_ICONE_OUVRIR, "Ouvrir la transcription", True,
                                  lambda c=chemin: self._ouvrir(c)))
        if ligne.cr_disponible:
            actions.append(ActionSpec(_ICONE_OUVRIR, "Ouvrir le CR", True,
                                      lambda c=chemin: self._ouvrir(chemin_cr_mistral(c))))
            actions.append(ActionSpec(_ICONE_COPIER, "Copier le CR", True,
                                      lambda c=chemin: self._copier_cr(c)))
        actions.append(ActionSpec(_ICONE_REVELER, "Révéler dans le dossier", True,
                                  lambda c=chemin: self._reveler(c)))

        action_bluemind = self._action_bluemind(chemin)
        if action_bluemind is not None:
            actions.append(action_bluemind)

        actions.append(ActionSpec(
            _ICONE_SUPPR_AUDIO, "Supprimer l'audio (garde le débrief)", bool(ligne.audio),
            lambda c=chemin: self._supprimer_audio_un(c), separateur_avant=True))
        actions.append(ActionSpec(
            _ICONE_TOUT_SUPPR, "Supprimer", True,
            lambda c=chemin: self._tout_supprimer_un(c), danger=True))
        return ActionsLigne(boutons=self._boutons_reunion(ligne, etat_cr), menu=actions)

    def _etat_cr_mistral(self, ligne, un_job_tourne: bool) -> _EtatCRMistral | None:
        """None si aucun gestionnaire n'est câblé (l'interco n'existe pas). Sinon
        toujours un état — indisponible/grisé compris — pour que le bouton dédié
        reste présent sur toutes les lignes (colonne régulière, fonction découvrable)."""
        if self._gestionnaire_cr_mistral is None:
            return None
        job_mistral = self._gestionnaire_cr_mistral.job_en_cours()
        if ligne.chemin == job_mistral:
            return _EtatCRMistral(False, "Génération du CR en cours…", en_cours=True)
        if not self._gestionnaire_cr_mistral.disponible():
            return _EtatCRMistral(False, "Mistral non configuré — Préférences › IA distante")
        a_de_quoi_generer = (not ligne.en_attente) or bool(ligne.audio)
        un_autre_job_tourne = un_job_tourne or job_mistral is not None
        if not a_de_quoi_generer:
            return _EtatCRMistral(False, "Aucune transcription ni audio disponible")
        if un_autre_job_tourne:
            return _EtatCRMistral(False, "Une tâche est déjà en cours")
        return _EtatCRMistral(True, "Générer le CR (Mistral)")

    def _boutons_reunion(self, ligne, etat_cr) -> list[BoutonSpec]:
        chemin = ligne.chemin
        boutons: list[BoutonSpec] = []
        if etat_cr is not None:
            boutons.append(BoutonSpec(
                _ICONE_CR_MISTRAL, etat_cr.tooltip, etat_cr.actif,
                lambda c=chemin: self._generer_cr_mistral(c),
                menu_deroulant=self._menu_prompts(chemin) if etat_cr.actif else None,
                tooltip_fleche="Générer le CR avec un autre prompt"))
        boutons.append(BoutonSpec(
            _ICONE_COPIER, "Copier le CR" if ligne.cr_disponible else "Aucun CR à copier",
            ligne.cr_disponible, lambda c=chemin: self._copier_cr(c)))
        boutons.append(BoutonSpec(
            _ICONE_COPIER_FICHIER, "Copier le fichier de la transcription", True,
            lambda c=chemin: self._copier_fichier(c)))
        return boutons

    def _menu_prompts(self, chemin: Path) -> list[ActionSpec] | None:
        """Items de la flèche du bouton « Générer le CR » : un par prompt de la config
        (choix **ponctuel** — le prompt actif ne change pas). None s'il n'y a pas au
        moins 2 prompts exploitables : la flèche serait du bruit sans alternative."""
        prompts = [p for p in (self._config.get("prompts") or [])
                   if (p or {}).get("contenu", "").strip()]
        if len(prompts) < 2:
            return None
        return [ActionSpec(
            _ICONE_CR_MISTRAL, p.get("titre") or "Sans titre", True,
            lambda c=chemin, contenu=p["contenu"]: self._generer_cr_mistral(c, prompt=contenu))
            for p in prompts]

    # ── Interco BlueMind — F1 (docs/40 §6) ──────────────────────────────────────

    def _evenements_correspondants_pour(self, chemin: Path) -> list[Evenement]:
        """Correspondances de la réplique locale pour cette réunion (§6.1) : pré-filtre SQL
        large autour du début, puis tolérance fine de `evenements_correspondants`. Liste
        vide si BlueMind n'est pas configuré ou si la date d'enregistrement est illisible."""
        if self._store_bluemind is None:
            return []
        debut = date_heure_reunion(chemin)
        if debut is None:
            return []
        marge = timedelta(hours=6)
        debut_ms = int((debut - marge).timestamp() * 1000)
        fin_ms = int((debut + marge).timestamp() * 1000)
        candidats = self._store_bluemind.evenements_dans_plage(debut_ms, fin_ms)
        return evenements_correspondants(candidats, debut, duree_reunion(chemin))

    def _etat_bluemind_pour(self, chemin: Path) -> _EtatBluemind | None:
        """Détection **automatique et locale** (réplique) — aucun réseau sur ce
        chemin (§6.2). None si BlueMind n'est pas configuré (interco invisible) ;
        calcul partagé par le menu ⋯ (`_action_bluemind`) et la colonne dédiée
        (`_calendrier_pour_index`, §8.6.2)."""
        if self._store_bluemind is None:
            return None
        if bluemind_association.existe(chemin):
            asso = bluemind_association.lire(chemin)
            titre = asso.titre if asso else chemin.parent.name
            on_details = (lambda a=asso: self._details_bluemind(a)) if asso else None
            return _EtatBluemind("linked", titre, on_details=on_details)

        correspondances = self._evenements_correspondants_pour(chemin)
        if not correspondances:
            return _EtatBluemind("none")
        return _EtatBluemind(
            "match", on_associer=lambda c=chemin, evts=correspondances: self._associer_bluemind(c, evts))

    def _action_bluemind(self, chemin: Path) -> ActionSpec | None:
        """Item du menu ⋯ (§8.6.3) — None si BlueMind non configuré ou aucune
        correspondance (l'interco reste invisible)."""
        etat = self._etat_bluemind_pour(chemin)
        if etat is None or etat.etat == "none":
            return None
        if etat.etat == "linked":
            # Actif dès qu'il y a un détail à montrer (même dialogue que l'icône verte
            # de la colonne calendrier — le menu ⋯ reste exhaustif).
            return ActionSpec(
                _ICONE_BLUEMIND_ASSOCIE, f"Associé — {etat.titre_evenement}",
                etat.on_details is not None, etat.on_details or (lambda: None))
        return ActionSpec(_ICONE_BLUEMIND_ASSOCIER, "Associer à la réunion", True, etat.on_associer)

    def _calendrier_pour_index(self, index: QModelIndex) -> CalendrierSpec | None:
        """Fournisseur de la colonne « lien calendrier » dédiée (§8.6.2)."""
        proxy = index.model()
        source = proxy.mapToSource(index)
        info = self._modele.info_ligne(source.row())
        if info is None or info.en_cours:
            return None
        etat = self._etat_bluemind_pour(info.chemin)
        if etat is None or etat.etat == "none":
            return CalendrierSpec(None, "", "", False)
        if etat.etat == "linked":
            tooltip = f"Associé à « {etat.titre_evenement} »"
            if etat.on_details is not None:
                tooltip += " — voir le détail"
            return CalendrierSpec(
                "calendar-check", C.SUCCESS, tooltip,
                etat.on_details is not None, etat.on_details)
        # Cliquable tant que non associé : raccourci d'association d'un coup d'œil,
        # en plus de l'item « Associer à la réunion » du menu ⋯ (exhaustif).
        return CalendrierSpec(
            "calendar-plus", C.ACCENT_INK,
            "Un événement du calendrier BlueMind correspond — associer", True, etat.on_associer)

    def _details_bluemind(self, association) -> None:
        """Détail (lecture seule) de l'événement associé — clic sur l'icône verte de
        la colonne calendrier ou item « Associé — … » du menu ⋯."""
        from debrief_meet.ui.bluemind_details import DialogDetailsBluemind
        DialogDetailsBluemind(association, self).exec()

    def _associer_bluemind(self, chemin: Path, evenements) -> None:
        from debrief_meet.ui.bluemind_association import DialogAssociationBluemind
        dlg = DialogAssociationBluemind(chemin, evenements, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            # Le dossier a pu être renommé (titre appliqué, docs/43 §6.1) — recharger
            # avant de re-sélectionner, sinon la ligne visée n'existe pas encore.
            self.selectionner_reunion(dlg.chemin_md)

    # ── Interco BlueMind — F2 (docs/40 §7) ──────────────────────────────────────

    def _nommer_locuteurs(self, chemin: Path) -> None:
        """Disponible même sans BlueMind configuré — le mapping reste utilisable en
        saisie libre seule (§7)."""
        loc = chemin_locuteurs(chemin)
        if not loc.exists():
            return
        from debrief_meet.ui.bluemind_mapping import DialogMappingLocuteurs
        email_moi = self._config.get("bluemind_email") or ""
        dlg = DialogMappingLocuteurs(chemin, loc, email_moi, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.recharger()

    # ── Sélection ──────────────────────────────────────────────────────────────

    def _chemins_selectionnes(self) -> list[Path]:
        out: list[Path] = []
        lignes_vues = set()
        for proxy_idx in self._table.selectionModel().selectedIndexes():
            if proxy_idx.row() in lignes_vues:
                continue
            lignes_vues.add(proxy_idx.row())
            source = self._proxy.mapToSource(proxy_idx)
            chemin = self._modele.chemin_a_la_ligne(source.row())
            if chemin is not None:
                out.append(chemin)
        return out

    def _cibles(self, chemin: Path | None) -> list[Path]:
        selection = self._chemins_selectionnes()
        if chemin is None:
            return selection
        if chemin in selection and len(selection) > 1:
            return selection
        return [chemin]

    # ── Actions simples (mono-cible) ────────────────────────────────────────────

    def _copier(self, chemin: Path) -> None:
        """Copie brute — jamais de préfixe prompt/lexique : le prompt actif et le
        lexique ne servent plus qu'au CR Mistral (décision du 2026-08-21)."""
        source = chemin
        loc = chemin_locuteurs(chemin)
        if loc.exists():
            source = loc
        if not source.exists():
            return
        texte = source.read_text(encoding="utf-8")
        if self._presse_papiers:
            self._presse_papiers.copier(texte)
        else:
            try:
                subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)
            except Exception:
                pass

    def _copier_fichier(self, chemin: Path) -> None:
        """Pose `transcription.md` lui-même (jamais la version diarizée) dans le
        presse-papiers — collable dans le gestionnaire de fichiers ou un mail."""
        if self._presse_papiers and chemin.exists():
            self._presse_papiers.copier_fichier(chemin)

    def _copier_cr(self, chemin: Path) -> None:
        """Copie le CR généré tel quel — pas de préfixe de prompt : contrairement à la
        transcription (matière première pour un assistant), le CR est déjà rédigé."""
        cr = chemin_cr_mistral(chemin)
        if not cr.exists():
            return
        texte = cr.read_text(encoding="utf-8")
        if self._presse_papiers:
            self._presse_papiers.copier(texte)
        else:
            try:
                subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)
            except Exception:
                pass

    def _ouvrir(self, chemin: Path) -> None:
        # `open` (macOS) n'existe pas sur Windows — trouvé en test interactif réel
        # sur la VM (2026-07-04) : crash FileNotFoundError [WinError 2] ailleurs
        # dans les Préférences pour ce même motif.
        if not chemin.exists():
            return
        if sys.platform == "win32":
            os.startfile(str(chemin))  # noqa: S606 — ouverture explicite demandée par l'utilisateur
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin)])

    def _reveler(self, chemin: Path) -> None:
        if not chemin.exists():
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(chemin)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin.parent)])

    # ── Diarization (déléguée au gestionnaire persistant) ───────────────────────

    def _generer(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.diarization_prete():
            return
        if not pistes_audio_existantes(chemin):
            dialogues.avertir(
                self, titre="Diarization",
                description=f"Aucun audio retenu pour « {chemin.name} ».\n"
                "Activez la rétention audio dans les Préférences avant la réunion.",
                icone="waveform")
            return
        if not self._gestionnaire.lancer(chemin):
            dialogues.avertir(self, titre="Diarization", description="Une génération est déjà en cours.")

    def _transcrire(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.disponible():
            return
        if not pistes_audio_existantes(chemin):
            dialogues.avertir(self, titre="Transcription",
                              description=f"Aucun audio retenu pour « {chemin.name} ».", icone="waveform")
            return
        if not self._gestionnaire.lancer_transcription(chemin):
            dialogues.avertir(self, titre="Transcription", description="Une tâche est déjà en cours.")

    def _cabler_gestionnaire(self) -> None:
        if self._gestionnaire is None:
            return
        self._gestionnaire.demarre.connect(self._sur_diar_change)
        self._gestionnaire.termine.connect(self._sur_diar_change)
        self._gestionnaire.echoue.connect(self._sur_diar_echoue)

    def _sur_diar_change(self, *_args) -> None:
        self.recharger()

    def _sur_diar_echoue(self, _md: object, message: str) -> None:
        self.recharger()
        if self.isVisible():
            dialogues.avertir(self, titre="Diarization — échec",
                              description=f"La génération des locuteurs a échoué :\n{message}")

    # ── CR Mistral (déléguée au gestionnaire persistant, docs/42) ───────────────

    def _proposer_association_avant_cr(self, chemin: Path) -> Path | None:
        """Propose l'association BlueMind **avant** l'envoi (docs/40 §6, docs/42) : le
        sidecar fournit au CR le sujet, la date et les participants, et les noms d'invités
        servent de `context_bias` à Voxtral — un CR n'étant pas régénéré, c'est le seul
        moment où l'utilisateur peut encore enrichir le contexte.

        Retourne le chemin sur lequel lancer le job (**celui d'après renommage** si le
        titre de l'événement a été appliqué), ou None si l'utilisateur renonce au CR.
        No-op transparent si BlueMind n'est pas configuré, si la réunion est déjà associée
        ou si aucun événement ne correspond."""
        if self._store_bluemind is None or bluemind_association.existe(chemin):
            return chemin

        # Resync forcée : la détection ne doit pas manquer un événement créé depuis la
        # dernière synchro (les autres déclencheurs sont tous « au fil de l'eau »).
        if attendre_sync(self._synchro_bluemind, self):
            self.recharger()                  # la colonne calendrier suit la réplique

        evenements = self._evenements_correspondants_pour(chemin)
        if not evenements:
            return chemin

        from debrief_meet.ui.bluemind_association import DialogAssociationBluemind
        dlg = DialogAssociationBluemind(chemin, evenements, self, contexte_cr=True)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return None                               # « Annuler » : ni association, ni CR
        if dlg.association_ignoree:
            return chemin                             # « Sans association » : CR quand même
        # Le dossier a pu être renommé (titre appliqué, docs/43 §6.1) : le job doit porter
        # sur le nouveau chemin, sinon il travaillerait sur un dossier disparu.
        nouveau = dlg.chemin_md
        self.selectionner_reunion(nouveau)
        return nouveau if nouveau.exists() else chemin

    def _generer_cr_mistral(self, chemin: Path, prompt: str | None = None) -> None:
        """`prompt` : contenu ponctuel choisi via la flèche du bouton « Générer le CR »
        (None → prompt actif de la config, cf. pipeline)."""
        if self._gestionnaire_cr_mistral is None or not self._gestionnaire_cr_mistral.disponible():
            return
        if self._proposition_en_cours:
            # Dialogues + attente de sync laissent tourner l'event loop : sans ce garde-fou,
            # un second clic (bouton dédié ou menu ⋯) rentrerait une 2ᵉ fois dans le flux.
            return
        self._proposition_en_cours = True
        try:
            if chemin_cr_mistral(chemin).exists():
                # Le CR n'est jamais régénéré silencieusement (docs/42) — le remplacer est
                # un choix explicite (ex. relancer avec un autre prompt).
                confirme = dialogues.confirmer(
                    self, titre="Remplacer le CR existant ?",
                    description="Un compte-rendu a déjà été généré pour cette réunion. "
                    "En générer un nouveau le remplacera définitivement.",
                    label_action="Remplacer", icone="notebook",
                    intention=dialogues.Intention.ACCENT)
                if not confirme:
                    return
            chemin_cible = self._proposer_association_avant_cr(chemin)
        finally:
            self._proposition_en_cours = False
        if chemin_cible is None:
            return
        chemin = chemin_cible
        if not self._config.get("mistral_confidentialite_acceptee"):
            # Confirmation au premier envoi (docs/42 §2) — mémorisée ensuite (vaut
            # « ne plus demander », pas de case à cocher dédiée en v1).
            confirme = dialogues.confirmer(
                self, titre="Générer le CR via Mistral ?",
                description="Cet enregistrement va être envoyé aux serveurs Mistral (UE) : "
                "la transcription locale si elle existe, sinon l'audio retenu pour "
                "transcription. Continuer ?",
                label_action="Envoyer", icone="notebook", intention=dialogues.Intention.ACCENT)
            if not confirme:
                return
            self._config.set("mistral_confidentialite_acceptee", True)
            self._config.sauvegarder()
        if not self._gestionnaire_cr_mistral.lancer(chemin, prompt=prompt):
            dialogues.avertir(self, titre="CR Mistral", description="Une tâche est déjà en cours.")

    def _cabler_gestionnaire_cr_mistral(self) -> None:
        if self._gestionnaire_cr_mistral is None:
            return
        self._gestionnaire_cr_mistral.demarre.connect(self._sur_cr_mistral_change)
        self._gestionnaire_cr_mistral.termine.connect(self._sur_cr_mistral_termine)
        self._gestionnaire_cr_mistral.echoue.connect(self._sur_cr_mistral_echoue)

    def _sur_cr_mistral_change(self, *_args) -> None:
        self.recharger()

    def _sur_cr_mistral_termine(self, _md: object, sortie: Path) -> None:
        self.recharger()
        if self.isVisible():
            ouvrir = dialogues.confirmer(
                self, titre="CR généré",
                description=f"Le compte-rendu « {sortie.name} » a été généré.",
                label_action="Ouvrir", icone="notebook", intention=dialogues.Intention.ACCENT)
            if ouvrir:
                self._ouvrir(sortie)

    def _sur_cr_mistral_echoue(self, _md: object, message: str) -> None:
        self.recharger()
        if self.isVisible():
            dialogues.avertir(self, titre="CR Mistral — échec",
                              description=f"La génération du CR a échoué :\n{message}")

    # ── Suppressions ────────────────────────────────────────────────────────────

    def _supprimer_audio_un(self, chemin: Path | None = None) -> None:
        # chemin=None → cible la sélection courante (action en masse, §8.6.4).
        cibles = [c for c in self._cibles(chemin) if pistes_audio_existantes(c)]
        if not cibles:
            dialogues.avertir(self, titre="Audio retenu", description="Aucun audio retenu à supprimer.")
            return
        n = len(cibles)
        noun = "réunions" if n > 1 else "réunion"
        confirme = dialogues.confirmer(
            self, titre=f"Supprimer l'audio de {n} {noun} ?",
            description=f"L'audio retenu de {n} {noun} sera supprimé définitivement "
            "(transcription et compte-rendu conservés).",
            label_action="Ignorer l'audio", icone="microphone-slash")
        if not confirme:
            return
        for c in cibles:
            for p in pistes_audio_existantes(c):
                try:
                    p.unlink()
                except OSError:
                    pass
        self.recharger()

    def _tout_supprimer_un(self, chemin: Path) -> None:
        self._tout_supprimer(chemin)

    def _tout_supprimer(self, chemin: Path | None) -> None:
        cibles = self._cibles(chemin)
        if not cibles:
            return
        n = len(cibles)
        noun = "réunions" if n > 1 else "réunion"
        verbe = "seront supprimées" if n > 1 else "sera supprimée"
        confirme = dialogues.confirmer(
            self, titre=f"Supprimer {n} {noun} ?",
            description=f"{n} {noun} {verbe} définitivement (transcription, débrief et audio inclus).",
            label_action="Supprimer", icone="trash")
        if not confirme:
            return
        for c in cibles:
            self._supprimer_un(c)
        self.recharger()

    def _supprimer_un(self, chemin: Path) -> None:
        """Supprime le dossier entier de la réunion (docs/43 §8) — plus aucun
        artefact dérivé ne peut rester orphelin."""
        dossier = chemin.parent
        try:
            racine = self._dossier().resolve()
            cible = dossier.resolve()
        except OSError:
            logger.warning("Suppression impossible (résolution du chemin) : %s", dossier)
            return
        if cible != racine and racine not in cible.parents:
            # Garde-fou : ne jamais rmtree en dehors du dossier des réunions
            # (protège contre un chemin corrompu).
            logger.warning("Suppression refusée : %s n'est pas sous %s", cible, racine)
            return
        try:
            shutil.rmtree(dossier)
        except OSError:
            logger.warning("Suppression du dossier réunion impossible : %s", dossier, exc_info=True)

    # ── Rafraîchissement live ────────────────────────────────────────────────────

    def _installer_surveillance(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        self._chemin_actif: Path | None = None
        dossier = str(self._dossier())
        if Path(dossier).exists():
            self._watcher.addPath(dossier)
        self._watcher.directoryChanged.connect(self._sur_dossier_change)
        # Le dossier racine ne réagit qu'aux entrées ajoutées/retirées (une réunion
        # apparaît/disparaît) — les modifications d'un fichier DANS un sous-dossier
        # (tranches ajoutées en direct) ne remontent pas. `fileChanged` couvre ce cas
        # pour le `transcription.md` de la réunion active, ajouté par
        # `definir_reunion_active` (docs/43 §9).
        self._watcher.fileChanged.connect(self._sur_dossier_change)
        self._timer_refresh = QTimer(self)
        self._timer_refresh.setSingleShot(True)
        self._timer_refresh.setInterval(200)
        self._timer_refresh.timeout.connect(self.recharger)
        self._machine.mode_change.connect(self._sur_mode_change_surveillance)

    def _sur_dossier_change(self, _chemin: str) -> None:
        self._timer_refresh.start()

    def _sur_mode_change_surveillance(self, mode: Mode) -> None:
        if mode is Mode.IDLE:
            # Fin d'enregistrement : la réunion redevient une ligne normale du listing.
            self.definir_reunion_active(None)

    def definir_reunion_active(self, chemin: Path | None) -> None:
        """Réunion tout juste démarrée (`OrchestrateurReunion.reunion_demarree`,
        docs/43 §9) — deux effets :

        1. surveiller son sous-dossier et son `transcription.md`, pour que les tranches
           ajoutées en direct rafraîchissent l'Historique ;
        2. l'**exclure du listing** : son `transcription.md` est créé dès le démarrage,
           donc sans exclusion elle s'afficherait à la fois comme ligne normale et comme
           ligne « en cours » (doublon).

        `chemin=None` remet l'état au repos (fin d'enregistrement)."""
        self._retirer_surveillance_active()
        chemin = Path(str(chemin)) if chemin is not None else None
        self._chemin_actif = chemin
        self._modele.definir_chemin_actif(chemin)
        if chemin is not None:
            dossier = str(chemin.parent)
            if Path(dossier).exists() and dossier not in self._watcher.directories():
                self._watcher.addPath(dossier)
            if chemin.exists() and str(chemin) not in self._watcher.files():
                self._watcher.addPath(str(chemin))
        self.recharger()

    def _retirer_surveillance_active(self) -> None:
        if self._chemin_actif is None:
            return
        dossier, fichier = str(self._chemin_actif.parent), str(self._chemin_actif)
        if dossier in self._watcher.directories():
            self._watcher.removePath(dossier)
        if fichier in self._watcher.files():
            self._watcher.removePath(fichier)
        self._chemin_actif = None

    # ── Sélection programmatique (clic sur notification) ─────────────────────────

    def selectionner_reunion(self, chemin_md: Path | None) -> None:
        """Sélectionne la ligne du `.md` donné."""
        self.recharger()
        if chemin_md is None:
            return
        row = self._modele.ligne_pour_chemin(Path(chemin_md))
        if row is None:
            return
        source_index = self._modele.index(row, 0)
        proxy_index = self._proxy.mapFromSource(source_index)
        self._table.selectionModel().clearSelection()
        self._table.selectRow(proxy_index.row())
        self._table.scrollTo(proxy_index)
