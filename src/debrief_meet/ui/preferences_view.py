"""Vue Préférences (refonte design) — sous-nav verticale + auto-save.

Remplace l'ancienne `FenetrePreferences` (QDialog + onglets + OK/Annuler) par un
widget embarquable : chaque champ persiste immédiatement (pas de bouton Appliquer).
Porte à l'identique la logique métier (7 sections, validation des raccourcis,
téléchargement de modèle à chaud, assistant diarization).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, QTimer, Slot
from PySide6.QtGui import QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.arret_threads import proteger_thread
from debrief_meet.core.config import Config
from debrief_meet.core.logs import configurer_logs
from debrief_meet.core.modeles import NOMS_LOGIQUES
from debrief_meet.core.raccourcis import libelle_modificateurs
from debrief_meet.platform.interfaces import DemarrageAuto, MoteurTranscription
from debrief_meet.ui.chargeur_modele import ChargeurModele
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.theme import C, M, SANS

logger = logging.getLogger(__name__)

_LANGUES = [
    ("Détection automatique", None),
    ("Français", "fr"),
    ("Anglais", "en"),
    ("Espagnol", "es"),
    ("Allemand", "de"),
    ("Italien", "it"),
    ("Portugais", "pt"),
]

_MODIFICATEURS_SUFFISANTS = {"Ctrl", "Alt", "Meta"}

# (titre section, icône Phosphor)
_SECTIONS = (
    ("Modèle", "brain"),
    ("Audio", "waveform"),
    ("Dossiers", "folders"),
    ("Prompts", "chat-text"),
    ("Général", "sliders-horizontal"),
    ("Raccourcis", "keyboard"),
    ("Journalisation", "bug"),
)

_DELAI_AUTOSAVE_MS = 400  # débounce des champs texte (titre/contenu prompt)


def _a_modificateur_suffisant(texte_portable: str) -> bool:
    return bool(set(texte_portable.split("+")) & _MODIFICATEURS_SUFFISANTS)


def _note(texte: str) -> QLabel:
    lab = QLabel(texte)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {C.INK400}; font-size: 11px;")
    return lab


class PreferencesView(QWidget):
    def __init__(
        self,
        config: Config,
        demarrage_auto: DemarrageAuto | None = None,
        moteur: MoteurTranscription | None = None,
        reappliquer_raccourcis: Callable[[], list[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._demarrage_auto = demarrage_auto
        self._moteur = moteur
        self._reappliquer_raccourcis = reappliquer_raccourcis
        self._chargeur: ChargeurModele | None = None
        self._thread_modele: QThread | None = None
        self._dlg_modele: QProgressDialog | None = None

        self._timer_autosave = QTimer(self)
        self._timer_autosave.setSingleShot(True)
        self._timer_autosave.setInterval(_DELAI_AUTOSAVE_MS)
        self._timer_autosave.timeout.connect(self._config.sauvegarder)

        self._construire_ui()

    # ── Sauvegarde ───────────────────────────────────────────────────────────

    def _definir(self, cle: str, valeur) -> None:
        """Persiste immédiatement une valeur (autosave)."""
        self._config.set(cle, valeur)
        self._config.sauvegarder()

    def _definir_differe(self, cle: str, valeur) -> None:
        """Comme `_definir`, mais débounce l'écriture disque (champs texte tapés au clavier)."""
        self._config.set(cle, valeur)
        self._timer_autosave.start()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _construire_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        corps = QWidget(self)
        lay_corps = QHBoxLayout(corps)
        lay_corps.setContentsMargins(0, 0, 0, 0)
        lay_corps.setSpacing(0)

        self._nav = QListWidget(corps)
        self._nav.setObjectName("prefNav")
        self._nav.setFixedWidth(M.PREF_NAV_W)
        self._nav.setFont(QFont(SANS, 13))
        for titre, icone_nom in _SECTIONS:
            item = QListWidgetItem(titre)
            item.setIcon(QIcon(icone_svg_teintee(icone_phosphor(icone_nom), C.INK500, 16)))
            self._nav.addItem(item)
        self._nav.currentRowChanged.connect(self._on_section_change)
        lay_corps.addWidget(self._nav)

        self._pages = QStackedWidget(corps)
        constructeurs = (
            self._section_modele, self._section_audio, self._section_dossiers,
            self._section_prompts, self._section_general, self._section_raccourcis,
            self._section_logs,
        )
        for construire in constructeurs:
            self._pages.addWidget(self._enrober_scroll(construire()))
        lay_corps.addWidget(self._pages, 1)

        layout.addWidget(corps, 1)

        barre = QLabel("  ✓  Modifications enregistrées automatiquement", self)
        barre.setObjectName("autosaveBar")
        layout.addWidget(barre)

        self._nav.setCurrentRow(0)

    def _enrober_scroll(self, contenu: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        contenu.setContentsMargins(30, 26, 30, 26)
        scroll.setWidget(contenu)
        return scroll

    def _on_section_change(self, index: int) -> None:
        if index >= 0:
            self._pages.setCurrentIndex(index)

    # ── Section Modèle ─────────────────────────────────────────────────────────

    def _section_modele(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._combo_modele = QComboBox()
        for nom in NOMS_LOGIQUES:
            self._combo_modele.addItem(nom, nom)
        idx = self._combo_modele.findData(self._config.get("modele"))
        if idx >= 0:
            self._combo_modele.setCurrentIndex(idx)
        self._combo_modele.currentIndexChanged.connect(self._sur_modele_change)
        form.addRow("Modèle Whisper :", self._combo_modele)

        form.addRow("", _note(
            "tiny et small sont rapides mais moins précis.\n"
            "large-v3-turbo : meilleur rapport qualité/vitesse (≈ 1,6 Go) — recommandé.\n"
            "large-v3 : qualité maximale (≈ 3 Go).\n"
            "Le modèle est téléchargé au premier usage."
        ))
        return w

    def _sur_modele_change(self, _index: int) -> None:
        ancien = self._config.get("modele")
        nouveau = self._combo_modele.currentData()
        if nouveau == ancien:
            return
        self._definir("modele", nouveau)
        if self._moteur is not None:
            self._changer_modele(nouveau)

    # ── Section Audio ──────────────────────────────────────────────────────────

    def _section_audio(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._combo_micro = QComboBox()
        self._combo_micro.addItem("Périphérique par défaut", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self._combo_micro.addItem(f"{d['name']}", i)
        except Exception:
            pass
        micro_idx = self._config.get("micro_index")
        if micro_idx is not None:
            idx = self._combo_micro.findData(micro_idx)
            if idx >= 0:
                self._combo_micro.setCurrentIndex(idx)
        self._combo_micro.currentIndexChanged.connect(
            lambda _i: self._definir("micro_index", self._combo_micro.currentData()))
        form.addRow("Microphone :", self._combo_micro)

        self._spin_intervalle = QSpinBox()
        self._spin_intervalle.setRange(10, 300)
        self._spin_intervalle.setSuffix(" s")
        self._spin_intervalle.setValue(self._config.get("intervalle_reunion") or 30)
        self._spin_intervalle.valueChanged.connect(lambda v: self._definir("intervalle_reunion", v))
        form.addRow("Intervalle réunion :", self._spin_intervalle)

        self._check_transcription_live = QCheckBox("Transcrire pendant l'enregistrement")
        self._check_transcription_live.setChecked(bool(self._config.get("transcription_live")))
        self._check_transcription_live.setToolTip(
            "Décoché : la réunion enregistre seulement l'audio ; la transcription se lance "
            "ensuite à la demande depuis l'Historique (l'audio est alors toujours conservé)."
        )
        self._check_transcription_live.toggled.connect(
            lambda c: self._definir("transcription_live", c))
        form.addRow("Transcription :", self._check_transcription_live)

        self._check_aec = QCheckBox("Annuler l'écho des haut-parleurs (sans casque)")
        self._check_aec.setChecked(bool(self._config.get("aec_actif")))
        self._check_aec.setToolTip(
            "Nettoie le micro avec l'audio système pour éviter que « Moi » ne reprenne "
            "la voix des participants. Prend effet à la prochaine réunion."
        )
        self._check_aec.toggled.connect(lambda c: self._definir("aec_actif", c))
        form.addRow("Annulation d'écho :", self._check_aec)

        self._check_retention = QCheckBox("Conserver l'audio des réunions (diarization)")
        self._check_retention.setChecked(bool(self._config.get("retention_audio")))
        self._check_retention.setToolTip(
            "Garde l'audio des 2 pistes à côté du compte-rendu pour pouvoir générer "
            "« qui a parlé » plus tard depuis l'Historique. Supprimable par réunion."
        )
        self._check_retention.toggled.connect(lambda c: self._definir("retention_audio", c))
        form.addRow("Rétention audio :", self._check_retention)

        form.addRow("Diarization :", self._construire_ligne_diarization())

        return w

    def _construire_ligne_diarization(self) -> QWidget:
        """Pastille badge (état) + bouton secondaire discret sur la même ligne
        (CHANGELOG_v2 correctif #9) — remplace la case à cocher + gros bouton
        pleine largeur de la version précédente."""
        ligne = QWidget()
        lay = QHBoxLayout(ligne)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self._badge_diarization = QWidget()
        lay_badge = QHBoxLayout(self._badge_diarization)
        lay_badge.setContentsMargins(11, 6, 11, 6)
        lay_badge.setSpacing(6)
        self._badge_diarization_icone = QLabel()
        self._badge_diarization_texte = QLabel()
        self._badge_diarization_texte.setFont(QFont(SANS, 12.5, QFont.Weight.DemiBold))
        lay_badge.addWidget(self._badge_diarization_icone)
        lay_badge.addWidget(self._badge_diarization_texte)
        lay.addWidget(self._badge_diarization)

        btn_diar = QPushButton("Configurer…")
        btn_diar.setObjectName("secondary")
        btn_diar.setToolTip(
            "Activer « qui a parlé » : téléchargement guidé du modèle (compte Hugging "
            "Face + licence gratuite). Le token n'est jamais enregistré."
        )
        btn_diar.clicked.connect(self._ouvrir_assistant_diarization)
        lay.addWidget(btn_diar)
        lay.addStretch()

        self._maj_etat_diarization()
        return ligne

    def _maj_etat_diarization(self) -> None:
        from debrief_meet.core import diarization
        ok = diarization.configuree()
        if ok:
            icone, texte, fg, bg = "check-circle", "Diarization configurée", C.SUCCESS, C.SUCCESS_BG
        else:
            icone, texte, fg, bg = "warning-circle", "Diarization non configurée", C.INK400, C.NEUTRAL_BG
        self._badge_diarization_icone.setPixmap(
            icone_svg_teintee(icone_phosphor(icone), fg, 15).pixmap(15, 15))
        self._badge_diarization_texte.setText(texte)
        self._badge_diarization_texte.setStyleSheet(f"color: {fg};")
        self._badge_diarization.setStyleSheet(f"background: {bg}; border-radius: 7px;")

    def _ouvrir_assistant_diarization(self) -> None:
        from debrief_meet.ui.assistant_diarization import AssistantDiarization
        AssistantDiarization(self).exec()
        self._maj_etat_diarization()

    # ── Section Dossiers ───────────────────────────────────────────────────────

    def _section_dossiers(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        group_r = QGroupBox("Réunions")
        row_r = QHBoxLayout(group_r)
        self._edit_dossier_reunions = QLineEdit(self._config.get("dossier_reunions"))
        self._edit_dossier_reunions.editingFinished.connect(
            lambda: self._sur_dossier_edite("dossier_reunions", self._edit_dossier_reunions))
        btn_r = QPushButton("Choisir…")
        btn_r.setObjectName("secondary")
        btn_r.clicked.connect(
            lambda: self._choisir_dossier("dossier_reunions", self._edit_dossier_reunions))
        row_r.addWidget(self._edit_dossier_reunions)
        row_r.addWidget(btn_r)
        layout.addWidget(group_r)

        group_j = QGroupBox("Journal")
        row_j = QHBoxLayout(group_j)
        self._edit_dossier_journal = QLineEdit(self._config.get("dossier_journal"))
        self._edit_dossier_journal.editingFinished.connect(
            lambda: self._sur_dossier_edite("dossier_journal", self._edit_dossier_journal))
        btn_j = QPushButton("Choisir…")
        btn_j.setObjectName("secondary")
        btn_j.clicked.connect(
            lambda: self._choisir_dossier("dossier_journal", self._edit_dossier_journal))
        row_j.addWidget(self._edit_dossier_journal)
        row_j.addWidget(btn_j)
        layout.addWidget(group_j)

        layout.addStretch()
        layout.addWidget(_note("Changer un dossier ne déplace pas les fichiers déjà produits."))
        return w

    def _choisir_dossier(self, cle: str, edit: QLineEdit) -> None:
        dossier = QFileDialog.getExistingDirectory(
            self, "Choisir un dossier", edit.text() or str(Path.home()))
        if dossier:
            edit.setText(dossier)
            self._definir(cle, dossier)

    def _sur_dossier_edite(self, cle: str, edit: QLineEdit) -> None:
        valeur = edit.text().strip()
        if valeur:
            self._definir(cle, valeur)

    # ── Section Prompts ────────────────────────────────────────────────────────

    def _section_prompts(self) -> QWidget:
        from copy import deepcopy

        self._prompts: list[dict] = deepcopy(self._config.get("prompts") or [])
        pa = self._config.get("prompt_actif")
        self._prompt_actif = pa if isinstance(pa, int) and 0 <= pa < len(self._prompts) else None
        self._maj_prompt = False

        w = QWidget()
        lay = QHBoxLayout(w)

        gauche = QVBoxLayout()
        self._liste_prompts = QListWidget()
        self._liste_prompts.currentRowChanged.connect(self._prompt_selection_change)
        gauche.addWidget(self._liste_prompts)
        barre = QHBoxLayout()
        btn_add = QPushButton("＋")
        btn_add.setToolTip("Ajouter un prompt")
        btn_add.clicked.connect(self._prompt_ajouter)
        btn_del = QPushButton("−")
        btn_del.setToolTip("Supprimer le prompt sélectionné")
        btn_del.clicked.connect(self._prompt_supprimer)
        barre.addWidget(btn_add)
        barre.addWidget(btn_del)
        barre.addStretch()
        gauche.addLayout(barre)
        lay.addLayout(gauche, 1)

        droite = QVBoxLayout()
        droite.addWidget(QLabel("Titre :"))
        self._edit_prompt_titre = QLineEdit()
        self._edit_prompt_titre.textEdited.connect(self._prompt_titre_change)
        droite.addWidget(self._edit_prompt_titre)
        droite.addWidget(QLabel("Contenu :"))
        self._edit_prompt_contenu = QPlainTextEdit()
        self._edit_prompt_contenu.setObjectName("promptEditor")
        self._edit_prompt_contenu.textChanged.connect(self._prompt_contenu_change)
        droite.addWidget(self._edit_prompt_contenu, 1)
        self._check_prompt_actif = QCheckBox("Utiliser ce prompt à la copie")
        self._check_prompt_actif.toggled.connect(self._prompt_actif_toggle)
        droite.addWidget(self._check_prompt_actif)
        droite.addWidget(_note(
            "Le prompt actif est ajouté en tête lors de la copie d'une transcription "
            "ou d'un débrief locuteurs depuis l'Historique."))
        lay.addLayout(droite, 2)

        self._remplir_liste_prompts()
        if self._prompts:
            self._liste_prompts.setCurrentRow(0)
        return w

    def _sauver_prompts(self) -> None:
        self._definir_differe("prompts", self._prompts)

    def _sauver_prompts_immediat(self) -> None:
        self._definir("prompts", self._prompts)

    def _remplir_liste_prompts(self) -> None:
        self._maj_prompt = True
        self._liste_prompts.clear()
        for i, p in enumerate(self._prompts):
            titre = p.get("titre") or "(sans titre)"
            self._liste_prompts.addItem(titre + ("  ✓" if i == self._prompt_actif else ""))
        self._maj_prompt = False

    def _prompt_selection_change(self, row: int) -> None:
        if row < 0 or row >= len(self._prompts):
            return
        self._maj_prompt = True
        p = self._prompts[row]
        self._edit_prompt_titre.setText(p.get("titre", ""))
        self._edit_prompt_contenu.setPlainText(p.get("contenu", ""))
        self._check_prompt_actif.setChecked(self._prompt_actif == row)
        self._maj_prompt = False

    def _prompt_titre_change(self, texte: str) -> None:
        row = self._liste_prompts.currentRow()
        if self._maj_prompt or row < 0:
            return
        self._prompts[row]["titre"] = texte
        self._maj_prompt = True
        item = self._liste_prompts.item(row)
        if item is not None:
            item.setText(texte + ("  ✓" if self._prompt_actif == row else ""))
        self._maj_prompt = False
        self._sauver_prompts()

    def _prompt_contenu_change(self) -> None:
        row = self._liste_prompts.currentRow()
        if self._maj_prompt or row < 0:
            return
        self._prompts[row]["contenu"] = self._edit_prompt_contenu.toPlainText()
        self._sauver_prompts()

    def _prompt_actif_toggle(self, coche: bool) -> None:
        row = self._liste_prompts.currentRow()
        if self._maj_prompt or row < 0:
            return
        if coche:
            self._prompt_actif = row
        elif self._prompt_actif == row:
            self._prompt_actif = None
        self._remplir_liste_prompts()
        self._liste_prompts.setCurrentRow(row)
        self._definir("prompt_actif", self._prompt_actif)

    def _prompt_ajouter(self) -> None:
        self._prompts.append({"titre": "Nouveau prompt", "contenu": ""})
        self._remplir_liste_prompts()
        self._liste_prompts.setCurrentRow(len(self._prompts) - 1)
        self._sauver_prompts_immediat()

    def _prompt_supprimer(self) -> None:
        row = self._liste_prompts.currentRow()
        if row < 0 or row >= len(self._prompts):
            return
        del self._prompts[row]
        if self._prompt_actif == row:
            self._prompt_actif = None
        elif self._prompt_actif is not None and self._prompt_actif > row:
            self._prompt_actif -= 1
        self._remplir_liste_prompts()
        if self._prompts:
            self._liste_prompts.setCurrentRow(min(row, len(self._prompts) - 1))
        else:
            self._maj_prompt = True
            self._edit_prompt_titre.clear()
            self._edit_prompt_contenu.clear()
            self._check_prompt_actif.setChecked(False)
            self._maj_prompt = False
        self._sauver_prompts_immediat()
        self._definir("prompt_actif", self._prompt_actif)

    # ── Section Général ────────────────────────────────────────────────────────

    def _section_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._combo_langue = QComboBox()
        for label, code in _LANGUES:
            self._combo_langue.addItem(label, code)
        idx = self._combo_langue.findData(self._config.get("langue"))
        if idx >= 0:
            self._combo_langue.setCurrentIndex(idx)
        self._combo_langue.currentIndexChanged.connect(
            lambda _i: self._definir("langue", self._combo_langue.currentData()))
        form.addRow("Langue :", self._combo_langue)

        self._check_autostart = QCheckBox("Lancer debriefMeet au démarrage de session")
        if self._demarrage_auto:
            self._check_autostart.setChecked(self._demarrage_auto.est_active())
            self._check_autostart.toggled.connect(self._sur_autostart_toggle)
        else:
            self._check_autostart.setEnabled(False)
        form.addRow("Démarrage auto :", self._check_autostart)

        self._check_notifs = QCheckBox("Activer les notifications")
        self._check_notifs.setChecked(bool(self._config.get("notifications")))
        self._check_notifs.toggled.connect(lambda c: self._definir("notifications", c))
        form.addRow("Notifications :", self._check_notifs)

        return w

    def _sur_autostart_toggle(self, coche: bool) -> None:
        try:
            if coche:
                self._demarrage_auto.activer()
            else:
                self._demarrage_auto.desactiver()
        except OSError as exc:
            logger.error("Erreur démarrage auto : %s", exc)

    # ── Section Raccourcis ─────────────────────────────────────────────────────

    def _section_raccourcis(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._edit_raccourci_dictee = self._creer_edit_raccourci("raccourci_dictee", "Dictée")
        form.addRow("Dictée :", self._edit_raccourci_dictee)
        self._edit_raccourci_reunion = self._creer_edit_raccourci("raccourci_reunion", "Réunion")
        form.addRow("Réunion :", self._edit_raccourci_reunion)
        self._edit_raccourci_journal = self._creer_edit_raccourci("raccourci_journal", "Journal")
        form.addRow("Journal :", self._edit_raccourci_journal)

        btn_defaut = QPushButton("Réinitialiser les défauts")
        btn_defaut.setObjectName("secondary")
        btn_defaut.clicked.connect(self._reinitialiser_raccourcis)
        form.addRow("", btn_defaut)

        form.addRow("", _note(
            "Un raccourci démarre/arrête l'action correspondante, même quand "
            "debriefMeet n'a pas le focus. Laisser un champ vide désactive ce "
            "raccourci."))
        return w

    def _champs_raccourcis(self) -> tuple[tuple[str, QKeySequenceEdit, str], ...]:
        return (
            ("raccourci_dictee", self._edit_raccourci_dictee, "Dictée"),
            ("raccourci_reunion", self._edit_raccourci_reunion, "Réunion"),
            ("raccourci_journal", self._edit_raccourci_journal, "Journal"),
        )

    def _creer_edit_raccourci(self, cle: str, nom: str) -> QKeySequenceEdit:
        edit = QKeySequenceEdit()
        edit.setMaximumSequenceLength(1)
        valeur = self._config.get(cle)
        if valeur:
            edit.setKeySequence(QKeySequence.fromString(valeur))
        edit.keySequenceChanged.connect(lambda _seq, c=cle, n=nom, e=edit: self._sur_raccourci_change(c, n, e))
        return edit

    def _sur_raccourci_change(self, cle: str, nom: str, edit: QKeySequenceEdit) -> None:
        sequence = edit.keySequence()
        if sequence.isEmpty():
            self._appliquer_raccourci(cle, "")
            return

        texte = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        if not _a_modificateur_suffisant(texte):
            mods = libelle_modificateurs(("Meta", "Ctrl", "Alt"))
            QMessageBox.warning(
                self, "Raccourcis",
                f"Le raccourci « {nom} » doit inclure au moins une touche {mods} "
                "(une lettre seule ou Maj+lettre capturée globalement rendrait "
                "le clavier inutilisable).")
            self._revert_raccourci(cle, edit)
            return

        # Comparaison sur la forme canonique des deux côtés : `QKeySequence.toString()`
        # réordonne les modificateurs (ex. "Meta+Alt+Ctrl+D" → "Meta+Ctrl+Alt+D") — une
        # comparaison texte brut contre la valeur stockée en config raterait un doublon.
        autres = [
            QKeySequence.fromString(self._config.get(c) or "").toString(QKeySequence.SequenceFormat.PortableText)
            for c, e, _n in self._champs_raccourcis() if e is not edit
        ]
        if texte in autres:
            QMessageBox.warning(
                self, "Raccourcis",
                f"Le raccourci « {nom} » est déjà utilisé par une autre action.")
            self._revert_raccourci(cle, edit)
            return

        self._appliquer_raccourci(cle, texte)

    def _revert_raccourci(self, cle: str, edit: QKeySequenceEdit) -> None:
        """Restaure l'affichage sans re-déclencher la validation (signaux bloqués) —
        sinon la ré-émission de `keySequenceChanged` re-sauvegarderait la valeur sous
        sa forme canonique (`QKeySequence.toString()` réordonne les modificateurs)."""
        edit.blockSignals(True)
        edit.setKeySequence(QKeySequence.fromString(self._config.get(cle) or ""))
        edit.blockSignals(False)

    def _appliquer_raccourci(self, cle: str, valeur: str) -> None:
        self._definir(cle, valeur)
        if self._reappliquer_raccourcis is not None:
            echecs = self._reappliquer_raccourcis()
            if echecs:
                QMessageBox.warning(
                    self, "Raccourcis",
                    "Combinaison(s) déjà utilisée(s) par une autre application :\n"
                    + "\n".join(echecs))

    def _reinitialiser_raccourcis(self) -> None:
        from debrief_meet.core.raccourcis import ACTIONS
        for cle, defaut, _nom in ACTIONS:
            edit = {"raccourci_dictee": self._edit_raccourci_dictee,
                    "raccourci_reunion": self._edit_raccourci_reunion,
                    "raccourci_journal": self._edit_raccourci_journal}[cle]
            edit.setKeySequence(QKeySequence.fromString(defaut))
            self._appliquer_raccourci(cle, defaut)

    # ── Section Journalisation ─────────────────────────────────────────────────

    def _section_logs(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self._check_logs = QCheckBox("Activer la journalisation (mode debug)")
        self._check_logs.setChecked(bool(self._config.get("logs_actifs")))
        self._check_logs.toggled.connect(self._sur_logs_toggle)
        layout.addWidget(self._check_logs)

        self._check_debug = QCheckBox("Logs détaillés (debug)")
        self._check_debug.setChecked(bool(self._config.get("logs_debug")))
        self._check_debug.toggled.connect(self._sur_logs_toggle)
        layout.addWidget(self._check_debug)

        layout.addWidget(_note(
            "Les logs ne contiennent jamais de transcriptions ni d'audio.\n"
            "Emplacement : ~/Library/Logs/debriefMeet/"))

        from debrief_meet.core.logs import chemin_log
        chemin = chemin_log()

        row = QHBoxLayout()
        btn_ouvrir = QPushButton("Ouvrir le fichier de log")
        btn_ouvrir.setObjectName("secondary")
        btn_ouvrir.clicked.connect(lambda: self._ouvrir_log(chemin))
        btn_vider = QPushButton("Vider le log")
        btn_vider.setObjectName("destructive")
        btn_vider.clicked.connect(lambda: self._vider_log(chemin))
        row.addWidget(btn_ouvrir)
        row.addWidget(btn_vider)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        return w

    def _sur_logs_toggle(self, _coche: bool) -> None:
        self._config.set("logs_actifs", self._check_logs.isChecked())
        self._config.set("logs_debug", self._check_debug.isChecked())
        self._config.sauvegarder()
        configurer_logs(actifs=self._check_logs.isChecked(), debug=self._check_debug.isChecked())

    def _ouvrir_log(self, chemin: Path) -> None:
        if not chemin.exists():
            QMessageBox.information(self, "Log", "Aucun fichier de log trouvé.")
            return
        # `open` (macOS) n'existe pas sur Windows — trouvé en test interactif réel
        # sur la VM (2026-07-04) : FileNotFoundError [WinError 2] en Préférences.
        if sys.platform == "win32":
            os.startfile(str(chemin))  # noqa: S606 — ouverture explicite demandée par l'utilisateur
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin)])

    def _vider_log(self, chemin: Path) -> None:
        if chemin.exists():
            chemin.write_text("", encoding="utf-8")

    # ── Changement de modèle à chaud ─────────────────────────────────────────────

    def _changer_modele(self, nom: str) -> None:
        besoin_dl = not self._moteur.est_telecharge(nom)
        self._dlg_modele = QProgressDialog(
            "Téléchargement du modèle…" if besoin_dl else "Chargement du modèle…",
            None, 0, 0, self)
        self._dlg_modele.setWindowTitle("Modèle")
        self._dlg_modele.setWindowModality(Qt.WindowModality.WindowModal)
        self._dlg_modele.setMinimumDuration(0)
        self._dlg_modele.setValue(0)

        self._thread_modele = QThread()
        self._chargeur = ChargeurModele(self._moteur, nom, besoin_dl)
        proteger_thread(self._thread_modele, self._chargeur)
        self._chargeur.moveToThread(self._thread_modele)
        self._thread_modele.started.connect(self._chargeur.executer)
        self._chargeur.fini.connect(self._thread_modele.quit)
        self._chargeur.echec.connect(self._thread_modele.quit)
        self._thread_modele.finished.connect(self._chargeur.deleteLater)
        self._chargeur.fini.connect(self._sur_modele_charge)
        self._chargeur.echec.connect(self._sur_modele_echec)
        self._thread_modele.start()
        self._dlg_modele.show()

    @Slot()
    def _sur_modele_charge(self) -> None:
        if self._dlg_modele is not None:
            self._dlg_modele.close()

    @Slot(str)
    def _sur_modele_echec(self, message: str) -> None:
        if self._dlg_modele is not None:
            self._dlg_modele.close()
        QMessageBox.warning(
            self, "Modèle",
            f"Le changement de modèle a échoué :\n{message}\n\n"
            "Le nouveau modèle sera utilisé au prochain démarrage.")
