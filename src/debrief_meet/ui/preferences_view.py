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

from PySide6.QtCore import QRectF, QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QFont, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core import edition
from debrief_meet.core import raccourcis as raccourcis_core
from debrief_meet.core.arret_threads import proteger_thread
from debrief_meet.core.config import Config
from debrief_meet.core.logs import configurer_logs
from debrief_meet.core.modeles import NOMS_LOGIQUES
from debrief_meet.core.raccourcis import libelle_modificateurs
from debrief_meet.platform.interfaces import DemarrageAuto, MoteurTranscription
from debrief_meet.ui import dialogues
from debrief_meet.ui.chargeur_modele import ChargeurModele
from debrief_meet.ui.icones import icone_phosphor, icone_svg_teintee
from debrief_meet.ui.remote_ia_view import RemoteIAView
from debrief_meet.ui.testeur_connexion_bluemind import TesteurConnexionBlueMind
from debrief_meet.ui.theme import C, M, MONO, SANS, color

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

_DELAI_AUTOSAVE_MS = 400  # débounce des champs texte (titre/contenu prompt)


def _a_modificateur_suffisant(texte_portable: str) -> bool:
    return bool(set(texte_portable.split("+")) & _MODIFICATEURS_SUFFISANTS)


def _suffixe_api(peripherique: dict) -> str:
    """« — WASAPI », « — MME »… Sans cette précision, un même micro apparaît plusieurs
    fois avec un libellé IDENTIQUE (constaté chez une utilisatrice le 2026-08-04 : le
    même casque Bluetooth listé 3 fois via MME, DirectSound et WASAPI). Le choix
    devenait impossible, alors que ces pilotes ne se comportent pas pareil."""
    try:
        import sounddevice as sd

        nom = sd.query_hostapis(peripherique["hostapi"])["name"]
    except Exception:  # noqa: BLE001 — libellé décoratif, jamais bloquant
        return ""
    return f" — {nom}" if nom else ""


def _suffixe_defaut_micro() -> str:
    """« (actuellement : Microphone Array…) » — rend visible ce que « par défaut »
    résout réellement. C'est ce qui manquait pour comprendre qu'un micro interne était
    enregistré alors qu'un casque était branché."""
    try:
        import sounddevice as sd

        index = sd.default.device[0]
        if index is None or index < 0:
            return ""
        return f" (actuellement : {sd.query_devices(index)['name']})"
    except Exception:  # noqa: BLE001 — libellé décoratif, jamais bloquant
        return ""


def _note(texte: str) -> QLabel:
    lab = QLabel(texte)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {C.INK400}; font-size: 12px; line-height: 1.7;")
    return lab


def _libelle_champ(texte: str) -> QLabel:
    """Label au-dessus d'un champ (colonne, jamais à côté) — DESIGN.md §3/§8.4."""
    lab = QLabel(texte)
    lab.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {C.INK700};")
    return lab


_STYLE_MINI_CARRE = (
    "QPushButton { background: #fff; border: 1px solid #D6D9DE; border-radius: 7px; }"
    f"QPushButton:hover {{ border-color: {C.ACCENT}; }}"
)


class _PromptDelegate(QStyledItemDelegate):
    """Ligne de la liste des prompts (onglet Préférences › Prompts, CHANGELOG_v2
    §1) : item actif = fond accent-soft + texte gras + coche à droite ; les
    autres = fond blanc + texte normal. Séparateur fin sous chaque ligne."""

    ROLE_ACTIF = Qt.ItemDataRole.UserRole + 1

    def paint(self, painter: QPainter, option, index) -> None:
        actif = bool(index.data(self.ROLE_ACTIF))
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if actif:
            painter.fillRect(rect, color(C.ACCENT_SOFT))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, color(C.HOVER))

        marge = 12
        largeur_coche = 19 if actif else 0
        police = QFont(SANS, 13, QFont.Weight.DemiBold if actif else QFont.Weight.Medium)
        painter.setFont(police)
        painter.setPen(color(C.ACCENT_INK if actif else C.INK900))
        zone = QRectF(rect.left() + marge, rect.top(),
                       rect.width() - marge * 2 - largeur_coche, rect.height())
        texte = index.data(Qt.ItemDataRole.DisplayRole) or ""
        texte_elide = painter.fontMetrics().elidedText(
            texte, Qt.TextElideMode.ElideRight, int(zone.width()))
        painter.drawText(zone, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texte_elide)

        if actif:
            icone = icone_svg_teintee(icone_phosphor("check"), C.ACCENT_INK, 13)
            icone.paint(painter, int(rect.right() - marge - 13), int(rect.center().y() - 6), 13, 13)

        painter.setPen(color(C.BORDER_SOFT))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, 33)


class PreferencesView(QWidget):
    def __init__(
        self,
        config: Config,
        demarrage_auto: DemarrageAuto | None = None,
        moteur: MoteurTranscription | None = None,
        reappliquer_raccourcis: Callable[[], list[str]] | None = None,
        bluemind_reinitialiser_sync: Callable[[], None] | None = None,
        bluemind_declencher_sync: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._demarrage_auto = demarrage_auto
        self._moteur = moteur
        self._reappliquer_raccourcis = reappliquer_raccourcis
        self._bluemind_reinitialiser_sync = bluemind_reinitialiser_sync
        self._bluemind_declencher_sync = bluemind_declencher_sync
        self._chargeur: ChargeurModele | None = None
        self._thread_modele: QThread | None = None
        self._dlg_modele: QProgressDialog | None = None
        self._thread_test_bm: QThread | None = None
        self._testeur_bm: TesteurConnexionBlueMind | None = None

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
        self._pages = QStackedWidget(corps)

        # Nav et pile remplies dans la MÊME boucle : l'index de nav est égal à l'index de
        # page par construction, il n'y a plus deux tuples parallèles à synchroniser.
        for titre, icone_nom, construire in self._sections():
            item = QListWidgetItem(titre)
            item.setIcon(QIcon(icone_svg_teintee(icone_phosphor(icone_nom), C.INK500, 16)))
            self._nav.addItem(item)
            self._pages.addWidget(self._enrober_scroll(construire()))

        # Connecté APRÈS le remplissage : `currentRowChanged` sur une pile encore vide
        # indexerait dans le vide.
        self._nav.currentRowChanged.connect(self._on_section_change)
        lay_corps.addWidget(self._nav)
        lay_corps.addWidget(self._pages, 1)

        layout.addWidget(corps, 1)

        barre = QLabel("  ✓  Modifications enregistrées automatiquement", self)
        barre.setObjectName("autosaveBar")
        layout.addWidget(barre)

        self._nav.setCurrentRow(0)

    def _sections(self) -> list[tuple[str, str, Callable[[], QWidget]]]:
        """(titre, icône Phosphor, constructeur) — source unique de la nav et de la pile.

        Méthode et non constante de module : les constructeurs sont des méthodes liées
        (c'est précisément pourquoi il y avait deux tuples parallèles auparavant). Lue à
        la construction de la vue, donc l'édition est prise en compte sans rebuild.
        """
        sections: list[tuple[str, str, Callable[[], QWidget]]] = []
        if edition.avec_transcription_locale():
            # Sélecteur de modèle Whisper : sans objet en lite (aucun moteur embarqué).
            sections.append(("Modèle", "brain", self._section_modele))
        sections += [
            ("Audio", "waveform", self._section_audio),
            ("Dossiers", "folders", self._section_dossiers),
            ("Prompts", "chat-text", self._section_prompts),
            ("Général", "sliders-horizontal", self._section_general),
            ("Raccourcis", "keyboard", self._section_raccourcis),
            ("BlueMind", "list", self._section_bluemind),
            ("Remote IA", "brain", self._section_remote_ia),
            ("Journalisation", "bug", self._section_logs),
        ]
        return sections

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
        w.setMaximumWidth(540)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(_libelle_champ("Modèle Whisper"))

        self._combo_modele = QComboBox()
        self._combo_modele.setFont(QFont(MONO, 13.5))
        for nom in NOMS_LOGIQUES:
            self._combo_modele.addItem(nom, nom)
        idx = self._combo_modele.findData(self._config.get("modele"))
        if idx >= 0:
            self._combo_modele.setCurrentIndex(idx)
        self._combo_modele.currentIndexChanged.connect(self._sur_modele_change)
        lay.addWidget(self._combo_modele)

        lay.addSpacing(4)
        lay.addWidget(_note(
            "tiny et small sont rapides mais moins précis.\n"
            "large-v3-turbo : meilleur rapport qualité/vitesse (≈ 1,6 Go) — recommandé.\n"
            "large-v3 : qualité maximale (≈ 3 Go).\n"
            "Le modèle est téléchargé au premier usage."
        ))
        lay.addStretch()
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
        w.setMaximumWidth(600)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        bloc_micro = QVBoxLayout()
        bloc_micro.setSpacing(6)
        bloc_micro.addWidget(_libelle_champ("Microphone"))
        self._combo_micro = QComboBox()
        self._combo_micro.setMaximumWidth(600)
        self._combo_micro.addItem(f"Périphérique par défaut{_suffixe_defaut_micro()}", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self._combo_micro.addItem(f"{d['name']}{_suffixe_api(d)}", i)
        except Exception:
            pass
        micro_idx = self._config.get("micro_index")
        if micro_idx is not None:
            idx = self._combo_micro.findData(micro_idx)
            if idx >= 0:
                self._combo_micro.setCurrentIndex(idx)
        self._combo_micro.currentIndexChanged.connect(
            lambda _i: self._definir("micro_index", self._combo_micro.currentData()))
        bloc_micro.addWidget(self._combo_micro)
        lay.addLayout(bloc_micro)

        bloc_intervalle = QVBoxLayout()
        bloc_intervalle.setSpacing(6)
        bloc_intervalle.addWidget(_libelle_champ("Intervalle réunion"))
        self._spin_intervalle = QSpinBox()
        self._spin_intervalle.setMaximumWidth(180)
        self._spin_intervalle.setRange(10, 300)
        self._spin_intervalle.setSuffix(" s")
        self._spin_intervalle.setValue(self._config.get("intervalle_reunion") or 30)
        self._spin_intervalle.valueChanged.connect(lambda v: self._definir("intervalle_reunion", v))
        bloc_intervalle.addWidget(self._spin_intervalle)
        lay.addLayout(bloc_intervalle)

        bloc_checks = QVBoxLayout()
        bloc_checks.setSpacing(11)

        # En lite l'orchestrateur force l'audio seul (core/reunion.py) : afficher la case
        # serait un contrôle menteur.
        if edition.avec_transcription_locale():
            self._check_transcription_live = QCheckBox("Transcrire pendant l'enregistrement")
            self._check_transcription_live.setChecked(bool(self._config.get("transcription_live")))
            self._check_transcription_live.setToolTip(
                "Décoché : la réunion enregistre seulement l'audio ; la transcription se lance "
                "ensuite à la demande depuis l'Historique (l'audio est alors toujours conservé)."
            )
            self._check_transcription_live.toggled.connect(
                lambda c: self._definir("transcription_live", c))
            bloc_checks.addWidget(self._check_transcription_live)

        self._check_aec = QCheckBox("Annuler l'écho des haut-parleurs (sans casque)")
        self._check_aec.setChecked(bool(self._config.get("aec_actif")))
        self._check_aec.setToolTip(
            "Nettoie le micro avec l'audio système pour éviter que « Moi » ne reprenne "
            "la voix des participants. Prend effet à la prochaine réunion."
        )
        self._check_aec.toggled.connect(lambda c: self._definir("aec_actif", c))
        bloc_checks.addWidget(self._check_aec)

        if edition.avec_transcription_locale():
            self._check_retention = QCheckBox("Conserver l'audio des réunions (diarization)")
            self._check_retention.setChecked(bool(self._config.get("retention_audio")))
            self._check_retention.setToolTip(
                "Garde l'audio des 2 pistes à côté du compte-rendu pour pouvoir générer "
                "« qui a parlé » plus tard depuis l'Historique. Supprimable par réunion."
            )
            self._check_retention.toggled.connect(lambda c: self._definir("retention_audio", c))
            bloc_checks.addWidget(self._check_retention)
        lay.addLayout(bloc_checks)

        if edition.avec_transcription_locale():
            lay.addWidget(self._construire_ligne_diarization())
        else:
            # Rétention non négociable en lite : c'est l'audio qui est envoyé à l'IA
            # distante. Le contrôle par réunion reste dans l'Historique (« Supprimer
            # l'audio (garde le débrief) »).
            lay.addWidget(_note(
                "L'audio des réunions est toujours conservé : c'est lui qui sert à la "
                "transcription et au compte-rendu via l'IA distante (Historique › "
                "Générer le CR). Supprimable réunion par réunion depuis l'Historique."))
        lay.addStretch()
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
        """Structure plate — pas de carte grise englobante (CHANGELOG_v2 §1) :
        label seul au-dessus, puis une ligne champ mono + bouton blanc « Choisir… »."""
        w = QWidget()
        w.setMaximumWidth(620)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self._edit_dossier_reunions = QLineEdit(self._config.get("dossier_reunions"))
        layout.addLayout(self._bloc_dossier(
            "Réunions", self._edit_dossier_reunions, "dossier_reunions"))

        self._edit_dossier_journal = QLineEdit(self._config.get("dossier_journal"))
        layout.addLayout(self._bloc_dossier(
            "Journal", self._edit_dossier_journal, "dossier_journal"))

        layout.addWidget(_note("Changer un dossier ne déplace pas les fichiers déjà produits."))
        layout.addStretch()
        return w

    def _bloc_dossier(self, label_texte: str, edit: QLineEdit, cle: str) -> QVBoxLayout:
        bloc = QVBoxLayout()
        bloc.setSpacing(6)
        bloc.addWidget(_libelle_champ(label_texte))

        ligne = QHBoxLayout()
        ligne.setSpacing(8)
        edit.setFont(QFont(MONO, 12.5))
        edit.setStyleSheet(f"color: {C.INK600};")
        edit.editingFinished.connect(lambda c=cle, e=edit: self._sur_dossier_edite(c, e))
        btn = QPushButton("Choisir…")
        btn.setObjectName("secondary")
        btn.clicked.connect(lambda c=cle, e=edit: self._choisir_dossier(c, e))
        ligne.addWidget(edit, 1)
        ligne.addWidget(btn)
        bloc.addLayout(ligne)
        return bloc

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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        gauche = QVBoxLayout()
        gauche.setSpacing(10)
        self._liste_prompts = QListWidget()
        self._liste_prompts.setObjectName("promptsList")
        self._liste_prompts.setFixedWidth(200)
        self._liste_prompts.setMouseTracking(True)
        self._liste_prompts.setItemDelegate(_PromptDelegate(self._liste_prompts))
        self._liste_prompts.currentRowChanged.connect(self._prompt_selection_change)
        gauche.addWidget(self._liste_prompts, 1)
        barre = QHBoxLayout()
        barre.setSpacing(8)
        btn_add = QPushButton()
        btn_add.setIcon(icone_svg_teintee(icone_phosphor("plus"), C.INK600, 14))
        btn_add.setFixedSize(32, 28)
        btn_add.setToolTip("Ajouter un prompt")
        btn_add.setStyleSheet(_STYLE_MINI_CARRE)
        btn_add.clicked.connect(self._prompt_ajouter)
        btn_del = QPushButton()
        btn_del.setIcon(icone_svg_teintee(icone_phosphor("minus"), C.INK600, 14))
        btn_del.setFixedSize(32, 28)
        btn_del.setToolTip("Supprimer le prompt sélectionné")
        btn_del.setStyleSheet(_STYLE_MINI_CARRE)
        btn_del.clicked.connect(self._prompt_supprimer)
        barre.addWidget(btn_add)
        barre.addWidget(btn_del)
        barre.addStretch()
        gauche.addLayout(barre)
        lay.addLayout(gauche)

        droite = QVBoxLayout()
        droite.setSpacing(13)
        bloc_titre = QVBoxLayout()
        bloc_titre.setSpacing(6)
        bloc_titre.addWidget(_libelle_champ("Titre"))
        self._edit_prompt_titre = QLineEdit()
        self._edit_prompt_titre.textEdited.connect(self._prompt_titre_change)
        bloc_titre.addWidget(self._edit_prompt_titre)
        droite.addLayout(bloc_titre)

        bloc_contenu = QVBoxLayout()
        bloc_contenu.setSpacing(6)
        bloc_contenu.addWidget(_libelle_champ("Contenu"))
        self._edit_prompt_contenu = QPlainTextEdit()
        self._edit_prompt_contenu.setObjectName("promptEditor")
        self._edit_prompt_contenu.textChanged.connect(self._prompt_contenu_change)
        bloc_contenu.addWidget(self._edit_prompt_contenu, 1)
        droite.addLayout(bloc_contenu, 1)

        self._check_prompt_actif = QCheckBox("Utiliser ce prompt à la copie")
        self._check_prompt_actif.toggled.connect(self._prompt_actif_toggle)
        droite.addWidget(self._check_prompt_actif)
        droite.addWidget(_note(
            "Le prompt actif est ajouté en tête lors de la copie d'une transcription "
            "ou d'un débrief locuteurs depuis l'Historique."))
        lay.addLayout(droite, 1)

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
            item = QListWidgetItem(titre)
            item.setData(_PromptDelegate.ROLE_ACTIF, i == self._prompt_actif)
            self._liste_prompts.addItem(item)
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
            item.setText(texte)
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
        w.setMaximumWidth(540)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        bloc_langue = QVBoxLayout()
        bloc_langue.setSpacing(6)
        bloc_langue.addWidget(_libelle_champ("Langue"))
        self._combo_langue = QComboBox()
        self._combo_langue.setMaximumWidth(300)
        for label, code in _LANGUES:
            self._combo_langue.addItem(label, code)
        idx = self._combo_langue.findData(self._config.get("langue"))
        if idx >= 0:
            self._combo_langue.setCurrentIndex(idx)
        self._combo_langue.currentIndexChanged.connect(
            lambda _i: self._definir("langue", self._combo_langue.currentData()))
        bloc_langue.addWidget(self._combo_langue)
        lay.addLayout(bloc_langue)

        self._check_autostart = QCheckBox("Lancer debriefMeet au démarrage de session")
        if self._demarrage_auto:
            self._check_autostart.setChecked(self._demarrage_auto.est_active())
            self._check_autostart.toggled.connect(self._sur_autostart_toggle)
        else:
            self._check_autostart.setEnabled(False)
        lay.addWidget(self._check_autostart)

        self._check_notifs = QCheckBox("Activer les notifications")
        self._check_notifs.setChecked(bool(self._config.get("notifications")))
        self._check_notifs.toggled.connect(lambda c: self._definir("notifications", c))
        lay.addWidget(self._check_notifs)

        lay.addStretch()
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
        w.setMaximumWidth(440)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        # Un éditeur par action de l'édition courante (`raccourcis.actions()` — Dictée et
        # Journal absentes en lite). Dict et non attributs nommés : la réinitialisation et
        # la détection de doublon en dérivent, sans table codée en dur à re-synchroniser.
        self._edits_raccourcis: dict[str, QKeySequenceEdit] = {}
        for cle, _defaut, nom in raccourcis_core.actions():
            edit = self._creer_edit_raccourci(cle, nom)
            self._edits_raccourcis[cle] = edit
            lay.addLayout(self._ligne_raccourci(nom, edit))

        pied = QVBoxLayout()
        pied.setContentsMargins(98, 0, 0, 0)
        pied.setSpacing(13)
        btn_defaut = QPushButton("Réinitialiser les défauts")
        btn_defaut.setObjectName("secondary")
        btn_defaut.clicked.connect(self._reinitialiser_raccourcis)
        pied.addWidget(btn_defaut, alignment=Qt.AlignmentFlag.AlignLeft)
        note = _note(
            "Un raccourci démarre/arrête l'action correspondante, même quand "
            "debriefMeet n'a pas le focus. Laisser un champ vide désactive ce "
            "raccourci.")
        note.setMaximumWidth(320)
        pied.addWidget(note)
        lay.addLayout(pied)

        lay.addStretch()
        return w

    def _ligne_raccourci(self, label_texte: str, edit: QKeySequenceEdit) -> QHBoxLayout:
        ligne = QHBoxLayout()
        ligne.setSpacing(14)
        label = QLabel(label_texte)
        label.setFixedWidth(84)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(f"font-size: 13.5px; font-weight: 600; color: {C.INK700};")
        ligne.addWidget(label)
        ligne.addWidget(edit, 1)
        return ligne

    def _champs_raccourcis(self) -> tuple[tuple[str, QKeySequenceEdit, str], ...]:
        return tuple(
            (cle, self._edits_raccourcis[cle], nom)
            for cle, _defaut, nom in raccourcis_core.actions()
        )

    def _creer_edit_raccourci(self, cle: str, nom: str) -> QKeySequenceEdit:
        edit = QKeySequenceEdit()
        edit.setFont(QFont(MONO, 14))
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
            dialogues.avertir(
                self, titre="Raccourcis",
                description=f"Le raccourci « {nom} » doit inclure au moins une touche {mods} "
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
            dialogues.avertir(
                self, titre="Raccourcis",
                description=f"Le raccourci « {nom} » est déjà utilisé par une autre action.")
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
                dialogues.avertir(
                    self, titre="Raccourcis",
                    description="Combinaison(s) déjà utilisée(s) par une autre application :\n"
                    + "\n".join(echecs))

    def _reinitialiser_raccourcis(self) -> None:
        """Défauts relus dans `raccourcis.ACTIONS` — jamais re-déclarés ici."""
        for cle, defaut, _nom in raccourcis_core.actions():
            self._edits_raccourcis[cle].setKeySequence(QKeySequence.fromString(defaut))
            self._appliquer_raccourci(cle, defaut)

    # ── Section BlueMind (interco calendrier, docs/40 §4) ───────────────────────

    def _section_bluemind(self) -> QWidget:
        w = QWidget()
        w.setMaximumWidth(560)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        bloc_url = QVBoxLayout()
        bloc_url.setSpacing(6)
        bloc_url.addWidget(_libelle_champ("URL du serveur"))
        self._edit_bm_url = QLineEdit(self._config.get("bluemind_url"))
        self._edit_bm_url.setPlaceholderText("https://bm.exemple.com/api")
        self._edit_bm_url.setFont(QFont(MONO, 12.5))
        self._edit_bm_url.editingFinished.connect(self._sur_bluemind_url_edite)
        bloc_url.addWidget(self._edit_bm_url)
        lay.addLayout(bloc_url)

        bloc_email = QVBoxLayout()
        bloc_email.setSpacing(6)
        bloc_email.addWidget(_libelle_champ("Votre adresse email"))
        self._edit_bm_email = QLineEdit(self._config.get("bluemind_email"))
        self._edit_bm_email.editingFinished.connect(self._sur_bluemind_email_edite)
        bloc_email.addWidget(self._edit_bm_email)
        lay.addLayout(bloc_email)

        bloc_token = QVBoxLayout()
        bloc_token.setSpacing(6)
        bloc_token.addWidget(_libelle_champ("Clé API personnelle"))
        self._edit_bm_token = QLineEdit(self._config.get("bluemind_token"))
        self._edit_bm_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_bm_token.editingFinished.connect(
            lambda: self._definir("bluemind_token", self._edit_bm_token.text().strip()))
        bloc_token.addWidget(self._edit_bm_token)
        lay.addLayout(bloc_token)

        self._check_bm_tls = QCheckBox("Vérifier le certificat TLS du serveur")
        self._check_bm_tls.setChecked(bool(self._config.get("bluemind_verifier_tls")))
        self._check_bm_tls.toggled.connect(lambda c: self._definir("bluemind_verifier_tls", c))
        lay.addWidget(self._check_bm_tls)

        ligne_test = QHBoxLayout()
        ligne_test.setSpacing(12)
        btn_test = QPushButton("Tester la connexion")
        btn_test.setObjectName("secondary")
        btn_test.clicked.connect(self._tester_connexion_bluemind)
        ligne_test.addWidget(btn_test)
        self._label_bm_statut = QLabel("")
        ligne_test.addWidget(self._label_bm_statut, 1)
        lay.addLayout(ligne_test)

        lay.addWidget(_note(
            "URL vide = interco désactivée : aucun bouton, aucune requête réseau, aucun "
            "message ailleurs dans l'app. La synchronisation du calendrier se fait "
            "entièrement en tâche de fond, jamais bloquante."))

        lay.addSpacing(4)
        lay.addWidget(_libelle_champ("Notifications de début de réunion"))

        self._check_bm_notif = QCheckBox("Notifier avant le début d'une réunion")
        self._check_bm_notif.setChecked(bool(self._config.get("bluemind_notif_reunions")))
        self._check_bm_notif.toggled.connect(lambda c: self._definir("bluemind_notif_reunions", c))
        lay.addWidget(self._check_bm_notif)

        bloc_avance = QHBoxLayout()
        bloc_avance.setSpacing(10)
        bloc_avance.addWidget(QLabel("Prévenir"))
        self._spin_bm_avance = QSpinBox()
        self._spin_bm_avance.setRange(1, 60)
        self._spin_bm_avance.setSuffix(" min avant")
        self._spin_bm_avance.setValue(int(self._config.get("bluemind_notif_avance_min") or 5))
        self._spin_bm_avance.valueChanged.connect(lambda v: self._definir("bluemind_notif_avance_min", v))
        bloc_avance.addWidget(self._spin_bm_avance)
        bloc_avance.addStretch()
        lay.addLayout(bloc_avance)

        self._check_bm_solo = QCheckBox("Inclure les réunions sans autre invité")
        self._check_bm_solo.setChecked(bool(self._config.get("bluemind_notif_inclure_solo")))
        self._check_bm_solo.toggled.connect(lambda c: self._definir("bluemind_notif_inclure_solo", c))
        lay.addWidget(self._check_bm_solo)

        self._check_bm_refuses = QCheckBox("Inclure les réunions que j'ai refusées")
        self._check_bm_refuses.setChecked(bool(self._config.get("bluemind_notif_inclure_refuses")))
        self._check_bm_refuses.toggled.connect(lambda c: self._definir("bluemind_notif_inclure_refuses", c))
        lay.addWidget(self._check_bm_refuses)

        self._check_bm_journee = QCheckBox("Inclure les événements « journée entière »")
        self._check_bm_journee.setChecked(bool(self._config.get("bluemind_notif_inclure_journee")))
        self._check_bm_journee.toggled.connect(lambda c: self._definir("bluemind_notif_inclure_journee", c))
        lay.addWidget(self._check_bm_journee)

        lay.addSpacing(4)
        btn_reset = QPushButton("Réinitialiser la synchronisation")
        btn_reset.setObjectName("destructive")
        btn_reset.clicked.connect(self._reinitialiser_sync_bluemind)
        lay.addWidget(btn_reset, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addStretch()
        return w

    def _sur_bluemind_url_edite(self) -> None:
        ancien = self._config.get("bluemind_url")
        nouveau = self._edit_bm_url.text().strip()
        if nouveau == ancien:
            return
        self._definir("bluemind_url", nouveau)
        self._declencher_reset_sync_si_necessaire()

    def _sur_bluemind_email_edite(self) -> None:
        ancien = self._config.get("bluemind_email")
        nouveau = self._edit_bm_email.text().strip()
        if nouveau == ancien:
            return
        self._definir("bluemind_email", nouveau)
        self._declencher_reset_sync_si_necessaire()

    def _declencher_reset_sync_si_necessaire(self) -> None:
        """Changement d'URL ou d'email → réplique + identité en cache invalides par
        construction (docs/40 §5.1, point 2) — un simple renouvellement de clé API
        ne déclenche PAS ce reset (cf. `_edit_bm_token`, aucun appel ici)."""
        if self._bluemind_reinitialiser_sync is not None:
            self._bluemind_reinitialiser_sync()

    def _tester_connexion_bluemind(self) -> None:
        url = self._edit_bm_url.text().strip()
        email = self._edit_bm_email.text().strip()
        token = self._edit_bm_token.text().strip()
        if not url or not email or not token:
            self._label_bm_statut.setText("URL, email et clé API sont requis.")
            self._label_bm_statut.setStyleSheet(f"color: {C.INK400};")
            return

        self._label_bm_statut.setText("Connexion en cours…")
        self._label_bm_statut.setStyleSheet(f"color: {C.INK400};")

        self._thread_test_bm = QThread()
        self._testeur_bm = TesteurConnexionBlueMind(
            url, token, email, bool(self._check_bm_tls.isChecked()))
        proteger_thread(self._thread_test_bm, self._testeur_bm)
        self._testeur_bm.moveToThread(self._thread_test_bm)
        self._thread_test_bm.started.connect(self._testeur_bm.executer)
        self._testeur_bm.reussi.connect(self._thread_test_bm.quit)
        self._testeur_bm.echec.connect(self._thread_test_bm.quit)
        self._thread_test_bm.finished.connect(self._testeur_bm.deleteLater)
        self._testeur_bm.reussi.connect(self._sur_test_bluemind_reussi)
        self._testeur_bm.echec.connect(self._sur_test_bluemind_echec)
        self._thread_test_bm.start()

    @Slot(str, str)
    def _sur_test_bluemind_reussi(self, nom_affiche: str, email: str) -> None:
        self._label_bm_statut.setText(f"✓ Connecté : {nom_affiche} <{email}>")
        self._label_bm_statut.setStyleSheet(f"color: {C.SUCCESS};")
        if self._bluemind_declencher_sync is not None:
            self._bluemind_declencher_sync()

    @Slot(str)
    def _sur_test_bluemind_echec(self, message: str) -> None:
        self._label_bm_statut.setText(f"Échec : {message}")
        self._label_bm_statut.setStyleSheet(f"color: {C.REC};")

    def _reinitialiser_sync_bluemind(self) -> None:
        confirme = dialogues.confirmer(
            self, titre="Réinitialiser la synchronisation ?",
            description="La réplique locale du calendrier sera effacée puis resynchronisée.\n"
            "Les transcriptions et associations existantes ne sont pas modifiées.",
            label_action="Réinitialiser", icone="arrows-clockwise", intention=dialogues.Intention.ACCENT)
        if not confirme:
            return
        if self._bluemind_reinitialiser_sync is not None:
            self._bluemind_reinitialiser_sync()

    # ── Section Remote IA (interco Mistral, docs/42 §9.1) ───────────────────────

    def _section_remote_ia(self) -> QWidget:
        return RemoteIAView(self._config, self)

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

        from debrief_meet.core.logs import chemin_log
        chemin = chemin_log()

        # Emplacement résolu, jamais codé en dur : `~/Library/Logs/debriefMeet/` était
        # faux sur Windows (%LOCALAPPDATA%\debriefMeet\Logs).
        layout.addWidget(_note(
            "Les logs ne contiennent jamais de transcriptions ni d'audio.\n"
            f"Emplacement : {chemin.parent}"))

        row = QHBoxLayout()
        btn_ouvrir = QPushButton("Ouvrir le fichier de log")
        btn_ouvrir.setObjectName("secondary")
        btn_ouvrir.clicked.connect(lambda: self._ouvrir_log(chemin))
        self._btn_exporter_logs = QPushButton("Exporter les logs (.zip)…")
        self._btn_exporter_logs.setObjectName("secondary")
        self._btn_exporter_logs.setToolTip(
            "Crée une archive sur le Bureau à envoyer pour diagnostic : logs, "
            "configuration et infos machine — jamais de transcription ni d'audio.")
        self._btn_exporter_logs.clicked.connect(self._exporter_logs)
        btn_vider = QPushButton("Vider le log")
        btn_vider.setObjectName("destructive")
        btn_vider.clicked.connect(lambda: self._vider_log(chemin))
        row.addWidget(btn_ouvrir)
        row.addWidget(self._btn_exporter_logs)
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
            dialogues.informer(self, titre="Log", description="Aucun fichier de log trouvé.",
                              icone="file-text")
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

    def _exporter_logs(self) -> None:
        """Même chemin de code que l'item « Exporter le diagnostic… » du tray."""
        from debrief_meet.ui.export_diagnostic import exporter_et_informer
        exporter_et_informer(self)

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
        dialogues.avertir(
            self, titre="Modèle",
            description=f"Le changement de modèle a échoué :\n{message}\n\n"
            "Le nouveau modèle sera utilisé au prochain démarrage.")
