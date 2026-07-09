"""Dialog F2 — mapping des locuteurs `_locuteurs.md` sur les invités de la réunion
associée (docs/40 §7). Fonctionne aussi **sans** association BlueMind (saisie libre
seule) — ce n'est pas une fonctionnalité gatée par la config de l'interco."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.bluemind import association as bluemind_association
from debrief_meet.core.bluemind.mapping import extraire_locuteurs, pre_remplir, renommer_locuteurs


def _valeur_combo(combo: QComboBox) -> str:
    donnee = combo.currentData()
    if donnee:
        return str(donnee)
    return combo.currentText().strip()


class DialogMappingLocuteurs(QDialog):
    def __init__(self, md: Path, chemin_locuteurs: Path, email_moi: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nommer les locuteurs")
        self.setMinimumWidth(460)
        self._md = md
        self._chemin_locuteurs = chemin_locuteurs
        self._combos: dict[str, QComboBox] = {}

        association = bluemind_association.lire(md)
        invites = association.invites if association is not None else []
        mapping_existant = association.mapping if association is not None else {}

        locuteurs = extraire_locuteurs(chemin_locuteurs)
        suggestions = pre_remplir(locuteurs, invites)

        layout = QVBoxLayout(self)
        if not locuteurs:
            layout.addWidget(QLabel("Aucun locuteur détecté dans le débrief."))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        contenu = QWidget()
        formulaire = QFormLayout(contenu)

        for loc in locuteurs:
            apercu = " / ".join(loc.apercu) or "(aucune intervention)"
            libelle_apercu = QLabel(apercu)
            libelle_apercu.setWordWrap(True)
            libelle_apercu.setStyleSheet("color: #6b7280; font-size: 11.5px;")

            combo = QComboBox()
            combo.setEditable(True)
            combo.addItem("", "")
            if email_moi:
                combo.addItem(f"Moi ({email_moi})", "Moi")
            else:
                combo.addItem("Moi", "Moi")
            for inv in invites:
                combo.addItem(inv.nom, inv.nom)

            valeur_initiale = mapping_existant.get(loc.label) or suggestions.get(loc.label, "")
            if valeur_initiale:
                idx = combo.findData(valeur_initiale)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentText(valeur_initiale)

            bloc = QVBoxLayout()
            bloc.addWidget(libelle_apercu)
            bloc.addWidget(combo)
            conteneur = QWidget()
            conteneur.setLayout(bloc)
            formulaire.addRow(QLabel(f"« {loc.label} »"), conteneur)
            self._combos[loc.label] = combo

        scroll.setWidget(contenu)
        layout.addWidget(scroll)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

    def _valider(self) -> None:
        mapping = {
            label: _valeur_combo(combo)
            for label, combo in self._combos.items()
            if _valeur_combo(combo)
        }
        if mapping:
            renommer_locuteurs(self._chemin_locuteurs, mapping)
            bluemind_association.enregistrer_mapping(self._md, mapping)
        self.accept()
