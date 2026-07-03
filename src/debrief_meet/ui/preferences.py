from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.arret_threads import proteger_thread
from debrief_meet.core.config import Config
from debrief_meet.core.logs import configurer_logs
from debrief_meet.core.modeles import NOMS_LOGIQUES
from debrief_meet.platform.interfaces import DemarrageAuto, MoteurTranscription
from debrief_meet.ui.chargeur_modele import ChargeurModele

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


def _a_modificateur_suffisant(texte_portable: str) -> bool:
    """Au moins un ⌘/⌃/⌥ — Maj (Shift) seul ne suffit pas, une lettre nue ou
    Shift+lettre capturée globalement rendrait le clavier inutilisable."""
    return bool(set(texte_portable.split("+")) & _MODIFICATEURS_SUFFISANTS)


class FenetrePreferences(QDialog):
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
        self.setWindowTitle("Préférences — debriefMeet")
        self.setMinimumWidth(500)
        self._construire_ui()

    def _construire_ui(self) -> None:
        layout = QVBoxLayout(self)

        onglets = QTabWidget()
        onglets.addTab(self._onglet_modele(), "Modèle")
        onglets.addTab(self._onglet_audio(), "Audio")
        onglets.addTab(self._onglet_dossiers(), "Dossiers")
        onglets.addTab(self._onglet_prompts(), "Prompts")
        onglets.addTab(self._onglet_general(), "Général")
        onglets.addTab(self._onglet_raccourcis(), "Raccourcis")
        onglets.addTab(self._onglet_logs(), "Journalisation")
        layout.addWidget(onglets)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.accepted.connect(self._appliquer)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

    # ── Onglet Modèle ──────────────────────────────────────────────────────────

    def _onglet_modele(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)

        self._combo_modele = QComboBox()
        for nom in NOMS_LOGIQUES:
            self._combo_modele.addItem(nom, nom)
        modele_actuel = self._config.get("modele")
        idx = self._combo_modele.findData(modele_actuel)
        if idx >= 0:
            self._combo_modele.setCurrentIndex(idx)
        form.addRow("Modèle Whisper :", self._combo_modele)

        note = QLabel(
            "tiny et small sont rapides mais moins précis.\n"
            "large-v3-turbo : meilleur rapport qualité/vitesse (≈ 1,6 Go) — recommandé.\n"
            "large-v3 : qualité maximale (≈ 3 Go).\n"
            "Le modèle est téléchargé au premier usage."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", note)

        return w

    # ── Onglet Audio ───────────────────────────────────────────────────────────

    def _onglet_audio(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)

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
        form.addRow("Microphone :", self._combo_micro)

        self._spin_intervalle = QSpinBox()
        self._spin_intervalle.setRange(10, 300)
        self._spin_intervalle.setSuffix(" s")
        self._spin_intervalle.setValue(self._config.get("intervalle_reunion") or 30)
        form.addRow("Intervalle réunion :", self._spin_intervalle)

        self._check_transcription_live = QCheckBox("Transcrire pendant l'enregistrement")
        self._check_transcription_live.setChecked(bool(self._config.get("transcription_live")))
        self._check_transcription_live.setToolTip(
            "Décoché : la réunion enregistre seulement l'audio ; la transcription se lance "
            "ensuite à la demande depuis l'Historique (l'audio est alors toujours conservé)."
        )
        form.addRow("Transcription :", self._check_transcription_live)

        self._check_aec = QCheckBox("Annuler l'écho des haut-parleurs (sans casque)")
        self._check_aec.setChecked(bool(self._config.get("aec_actif")))
        self._check_aec.setToolTip(
            "Nettoie le micro avec l'audio système pour éviter que « Moi » ne reprenne "
            "la voix des participants. Prend effet à la prochaine réunion."
        )
        form.addRow("Annulation d'écho :", self._check_aec)

        self._check_retention = QCheckBox("Conserver l'audio des réunions (diarization)")
        self._check_retention.setChecked(bool(self._config.get("retention_audio")))
        self._check_retention.setToolTip(
            "Garde l'audio des 2 pistes à côté du compte-rendu pour pouvoir générer "
            "« qui a parlé » plus tard depuis l'Historique. Supprimable par réunion."
        )
        form.addRow("Rétention audio :", self._check_retention)

        # Onboarding diarization (modèle pyannote gated) — cf. docs/13.
        self._label_diarization = QLabel()
        self._maj_etat_diarization()
        form.addRow("Diarization :", self._label_diarization)
        btn_diar = QPushButton("Configurer la diarization…")
        btn_diar.setToolTip(
            "Activer « qui a parlé » : téléchargement guidé du modèle (compte Hugging "
            "Face + licence gratuite). Le token n'est jamais enregistré."
        )
        btn_diar.clicked.connect(self._ouvrir_assistant_diarization)
        form.addRow("", btn_diar)

        return w

    def _maj_etat_diarization(self) -> None:
        from debrief_meet.core import diarization
        ok = diarization.configuree()
        self._label_diarization.setText("✅ configurée" if ok else "non configurée")
        self._label_diarization.setStyleSheet("" if ok else "color: gray;")

    def _ouvrir_assistant_diarization(self) -> None:
        from debrief_meet.ui.assistant_diarization import AssistantDiarization
        AssistantDiarization(self).exec()
        self._maj_etat_diarization()      # rafraîchir l'état après un éventuel téléchargement

    # ── Onglet Dossiers ────────────────────────────────────────────────────────

    def _onglet_dossiers(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 8)

        group_r = QGroupBox("Réunions")
        row_r = QHBoxLayout(group_r)
        self._edit_dossier_reunions = QLineEdit(self._config.get("dossier_reunions"))
        btn_r = QPushButton("Choisir…")
        btn_r.clicked.connect(lambda: self._choisir_dossier(self._edit_dossier_reunions))
        row_r.addWidget(self._edit_dossier_reunions)
        row_r.addWidget(btn_r)
        layout.addWidget(group_r)

        group_j = QGroupBox("Journal")
        row_j = QHBoxLayout(group_j)
        self._edit_dossier_journal = QLineEdit(self._config.get("dossier_journal"))
        btn_j = QPushButton("Choisir…")
        btn_j.clicked.connect(lambda: self._choisir_dossier(self._edit_dossier_journal))
        row_j.addWidget(self._edit_dossier_journal)
        row_j.addWidget(btn_j)
        layout.addWidget(group_j)

        layout.addStretch()
        note = QLabel("Changer un dossier ne déplace pas les fichiers déjà produits.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)
        return w

    def _choisir_dossier(self, edit: QLineEdit) -> None:
        dossier = QFileDialog.getExistingDirectory(
            self, "Choisir un dossier", edit.text() or str(Path.home())
        )
        if dossier:
            edit.setText(dossier)

    # ── Onglet Prompts ──────────────────────────────────────────────────────────

    def _onglet_prompts(self) -> QWidget:
        from copy import deepcopy

        self._prompts: list[dict] = deepcopy(self._config.get("prompts") or [])
        pa = self._config.get("prompt_actif")
        self._prompt_actif = pa if isinstance(pa, int) and 0 <= pa < len(self._prompts) else None
        self._maj_prompt = False  # garde anti-boucle pendant le chargement des champs

        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 8)

        # Colonne gauche : liste + boutons ＋ / −
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

        # Colonne droite : édition
        droite = QVBoxLayout()
        droite.addWidget(QLabel("Titre :"))
        self._edit_prompt_titre = QLineEdit()
        self._edit_prompt_titre.textEdited.connect(self._prompt_titre_change)
        droite.addWidget(self._edit_prompt_titre)
        droite.addWidget(QLabel("Contenu :"))
        self._edit_prompt_contenu = QPlainTextEdit()
        self._edit_prompt_contenu.textChanged.connect(self._prompt_contenu_change)
        droite.addWidget(self._edit_prompt_contenu, 1)
        self._check_prompt_actif = QCheckBox("Utiliser ce prompt à la copie")
        self._check_prompt_actif.toggled.connect(self._prompt_actif_toggle)
        droite.addWidget(self._check_prompt_actif)
        note = QLabel(
            "Le prompt actif est ajouté en tête lors de la copie d'une transcription "
            "ou d'un débrief locuteurs depuis l'Historique."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        droite.addWidget(note)
        lay.addLayout(droite, 2)

        self._remplir_liste_prompts()
        if self._prompts:
            self._liste_prompts.setCurrentRow(0)
        return w

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

    def _prompt_contenu_change(self) -> None:
        row = self._liste_prompts.currentRow()
        if self._maj_prompt or row < 0:
            return
        self._prompts[row]["contenu"] = self._edit_prompt_contenu.toPlainText()

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

    def _prompt_ajouter(self) -> None:
        self._prompts.append({"titre": "Nouveau prompt", "contenu": ""})
        self._remplir_liste_prompts()
        self._liste_prompts.setCurrentRow(len(self._prompts) - 1)

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

    # ── Onglet Général ─────────────────────────────────────────────────────────

    def _onglet_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)

        self._combo_langue = QComboBox()
        for label, code in _LANGUES:
            self._combo_langue.addItem(label, code)
        langue = self._config.get("langue")
        idx = self._combo_langue.findData(langue)
        if idx >= 0:
            self._combo_langue.setCurrentIndex(idx)
        form.addRow("Langue :", self._combo_langue)

        self._check_autostart = QCheckBox("Lancer debriefMeet au démarrage de session")
        if self._demarrage_auto:
            self._check_autostart.setChecked(self._demarrage_auto.est_active())
        else:
            self._check_autostart.setEnabled(False)
        form.addRow("Démarrage auto :", self._check_autostart)

        self._check_notifs = QCheckBox("Activer les notifications")
        self._check_notifs.setChecked(bool(self._config.get("notifications")))
        form.addRow("Notifications :", self._check_notifs)

        return w

    # ── Onglet Raccourcis (docs/28) ────────────────────────────────────────────

    def _onglet_raccourcis(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)

        self._edit_raccourci_dictee = self._creer_edit_raccourci("raccourci_dictee")
        form.addRow("Dictée :", self._edit_raccourci_dictee)
        self._edit_raccourci_reunion = self._creer_edit_raccourci("raccourci_reunion")
        form.addRow("Réunion :", self._edit_raccourci_reunion)
        self._edit_raccourci_journal = self._creer_edit_raccourci("raccourci_journal")
        form.addRow("Journal :", self._edit_raccourci_journal)

        btn_defaut = QPushButton("Réinitialiser les défauts")
        btn_defaut.clicked.connect(self._reinitialiser_raccourcis)
        form.addRow("", btn_defaut)

        note = QLabel(
            "Un raccourci démarre/arrête l'action correspondante, même quand "
            "debriefMeet n'a pas le focus. Laisser un champ vide désactive ce "
            "raccourci."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", note)

        return w

    def _creer_edit_raccourci(self, cle: str) -> QKeySequenceEdit:
        edit = QKeySequenceEdit()
        edit.setMaximumSequenceLength(1)
        valeur = self._config.get(cle)
        if valeur:
            edit.setKeySequence(QKeySequence.fromString(valeur))
        return edit

    def _reinitialiser_raccourcis(self) -> None:
        from debrief_meet.core.raccourcis import ACTIONS
        defauts = {cle: defaut for cle, defaut, _nom in ACTIONS}
        self._edit_raccourci_dictee.setKeySequence(QKeySequence.fromString(defauts["raccourci_dictee"]))
        self._edit_raccourci_reunion.setKeySequence(QKeySequence.fromString(defauts["raccourci_reunion"]))
        self._edit_raccourci_journal.setKeySequence(QKeySequence.fromString(defauts["raccourci_journal"]))

    def _valider_raccourcis(self) -> dict[str, str] | None:
        """Vérifie les 3 champs avant sauvegarde. Retourne {clé_config: valeur portable}
        ou None (et affiche l'erreur) si un champ est invalide."""
        champs = (
            ("raccourci_dictee", self._edit_raccourci_dictee, "Dictée"),
            ("raccourci_reunion", self._edit_raccourci_reunion, "Réunion"),
            ("raccourci_journal", self._edit_raccourci_journal, "Journal"),
        )
        valeurs: dict[str, str] = {}
        deja_vues: list[str] = []
        for cle, edit, nom in champs:
            sequence = edit.keySequence()
            if sequence.isEmpty():
                valeurs[cle] = ""
                continue
            texte = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            if not _a_modificateur_suffisant(texte):
                QMessageBox.warning(
                    self, "Raccourcis",
                    f"Le raccourci « {nom} » doit inclure au moins une touche ⌘/⌃/⌥ "
                    "(une lettre seule ou Maj+lettre capturée globalement rendrait "
                    "le clavier inutilisable).")
                return None
            if texte in deja_vues:
                QMessageBox.warning(
                    self, "Raccourcis",
                    f"Le raccourci « {nom} » est déjà utilisé par une autre action.")
                return None
            deja_vues.append(texte)
            valeurs[cle] = texte
        return valeurs

    # ── Onglet Journalisation ──────────────────────────────────────────────────

    def _onglet_logs(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 8)

        self._check_logs = QCheckBox("Activer la journalisation (mode debug)")
        self._check_logs.setChecked(bool(self._config.get("logs_actifs")))
        layout.addWidget(self._check_logs)

        self._check_debug = QCheckBox("Logs détaillés (debug)")
        self._check_debug.setChecked(bool(self._config.get("logs_debug")))
        layout.addWidget(self._check_debug)

        note = QLabel(
            "Les logs ne contiennent jamais de transcriptions ni d'audio.\n"
            "Emplacement : ~/Library/Logs/debriefMeet/"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        from debrief_meet.core.logs import chemin_log
        chemin = chemin_log()

        row = QHBoxLayout()
        btn_ouvrir = QPushButton("Ouvrir le fichier de log")
        btn_ouvrir.clicked.connect(lambda: self._ouvrir_log(chemin))
        btn_vider = QPushButton("Vider le log")
        btn_vider.clicked.connect(lambda: self._vider_log(chemin))
        row.addWidget(btn_ouvrir)
        row.addWidget(btn_vider)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        return w

    def _ouvrir_log(self, chemin: Path) -> None:
        if chemin.exists():
            subprocess.Popen(["open", str(chemin)])
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Log", "Aucun fichier de log trouvé.")

    def _vider_log(self, chemin: Path) -> None:
        if chemin.exists():
            chemin.write_text("", encoding="utf-8")

    # ── Appliquer ──────────────────────────────────────────────────────────────

    def _appliquer(self) -> None:
        raccourcis_valides = self._valider_raccourcis()
        if raccourcis_valides is None:
            return   # message déjà affiché — on reste dans la boîte de dialogue

        ancien_modele = self._config.get("modele")
        nouveau_modele = self._combo_modele.currentData()
        self._config.set("modele", nouveau_modele)
        self._config.set("micro_index", self._combo_micro.currentData())
        self._config.set("intervalle_reunion", self._spin_intervalle.value())
        self._config.set("transcription_live", self._check_transcription_live.isChecked())
        self._config.set("aec_actif", self._check_aec.isChecked())
        self._config.set("retention_audio", self._check_retention.isChecked())
        self._config.set("prompts", self._prompts)
        self._config.set("prompt_actif", self._prompt_actif)
        for cle, valeur in raccourcis_valides.items():
            self._config.set(cle, valeur)

        dossier_r = self._edit_dossier_reunions.text().strip()
        if dossier_r:
            self._config.set("dossier_reunions", dossier_r)

        dossier_j = self._edit_dossier_journal.text().strip()
        if dossier_j:
            self._config.set("dossier_journal", dossier_j)

        self._config.set("langue", self._combo_langue.currentData())
        self._config.set("notifications", self._check_notifs.isChecked())
        self._config.set("logs_actifs", self._check_logs.isChecked())
        self._config.set("logs_debug", self._check_debug.isChecked())
        configurer_logs(actifs=self._check_logs.isChecked(),
                        debug=self._check_debug.isChecked())

        if self._demarrage_auto:
            try:
                if self._check_autostart.isChecked():
                    self._demarrage_auto.activer()
                else:
                    self._demarrage_auto.desactiver()
            except OSError as exc:
                logger.error("Erreur démarrage auto : %s", exc)

        self._config.sauvegarder()

        if self._reappliquer_raccourcis is not None:
            echecs = self._reappliquer_raccourcis()
            if echecs:
                QMessageBox.warning(
                    self, "Raccourcis",
                    "Combinaison(s) déjà utilisée(s) par une autre application :\n"
                    + "\n".join(echecs))

        # Changement de modèle → téléchargement (si absent) + rechargement à chaud,
        # sans redémarrer l'app (docs/15). Sinon on ferme directement.
        if self._moteur is not None and nouveau_modele != ancien_modele:
            self._changer_modele(nouveau_modele)
        else:
            self.accept()

    def _changer_modele(self, nom: str) -> None:
        besoin_dl = not self._moteur.est_telecharge(nom)
        self._dlg_modele = QProgressDialog(
            "Téléchargement du modèle…" if besoin_dl else "Chargement du modèle…",
            None, 0, 0, self)                       # pas de bouton Annuler ; barre indéterminée
        self._dlg_modele.setWindowTitle("Modèle")
        self._dlg_modele.setWindowModality(Qt.WindowModality.WindowModal)
        self._dlg_modele.setMinimumDuration(0)
        self._dlg_modele.setValue(0)

        self._thread_modele = QThread()          # PAS de parent : la destruction du
        self._chargeur = ChargeurModele(self._moteur, nom, besoin_dl)
        proteger_thread(self._thread_modele, self._chargeur)  # dialogue ne tue plus le thread
        self._chargeur.moveToThread(self._thread_modele)
        self._thread_modele.started.connect(self._chargeur.executer)
        self._chargeur.fini.connect(self._thread_modele.quit)
        self._chargeur.echec.connect(self._thread_modele.quit)
        self._thread_modele.finished.connect(self._chargeur.deleteLater)
        # Slots de `self` (QObject du thread principal) → exécutés dans le thread GUI
        # même si le signal est émis depuis le worker (sinon : GUI hors thread = blocage).
        self._chargeur.fini.connect(self._sur_modele_charge)
        self._chargeur.echec.connect(self._sur_modele_echec)
        self._thread_modele.start()
        self._dlg_modele.show()

    @Slot()
    def _sur_modele_charge(self) -> None:
        if self._dlg_modele is not None:
            self._dlg_modele.close()
        self.accept()

    @Slot(str)
    def _sur_modele_echec(self, message: str) -> None:
        if self._dlg_modele is not None:
            self._dlg_modele.close()
        QMessageBox.warning(
            self, "Modèle",
            f"Le changement de modèle a échoué :\n{message}\n\n"
            "Le nouveau modèle sera utilisé au prochain démarrage.")
        self.accept()
