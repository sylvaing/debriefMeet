"""Fenêtre Historique — liste les transcriptions (réunions + journal) avec, par ligne,
une colonne d'actions (icônes système + tooltips).

Cf. docs/09-refonte-historique.md. Points clés :
- listing des transcriptions seules (les `*_locuteurs.md` et l'audio sont exclus) ;
- sélection multiple (⌘/⇧) + suppression de masse (#5 audio, #6 tout ; touche Suppr = #6) ;
- diarization déléguée à un `GestionnaireDiarization` **persistant** (survit à la fermeture) ;
- icône « générer » → état « work in progress » non cliquable pendant le job ;
- rafraîchissement live du listing (`QFileSystemWatcher`) en préservant la sélection.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import (
    chemin_locuteurs,
    date_heure_reunion,
    definir_titre,
    duree_reunion,
    formater_duree,
    lister_enregistrements,
    pistes_audio_existantes,
    titre_reunion,
    transcription_en_attente,
)
from debrief_meet.platform.interfaces import PressePapiers
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
from debrief_meet.ui.icones import icone_glyphe, icone_glyphe_pivotee, pixmap_glyphe

# Glyphes maison monochromes (cf. doc 09 §3 + assets/apercu-icones-historique.html).
_ICONE_COPIER = "copier"
_ICONE_GENERER = "personnes"
_ICONE_TRANSCRIRE = "ecrire"
_ICONE_WIP = "attente"
_ICONE_OUVRIR = "note"
_ICONE_REVELER = "dossier"
_ICONE_SUPPR_AUDIO = "muet"
_ICONE_TOUT_SUPPR = "corbeille"

# Style « plat » des boutons d'action (pas de cadre ; fond léger au survol). Cf. doc 09 §3.
_STYLE_BOUTON = (
    "QToolButton{border:none;background:transparent;padding:5px;border-radius:7px;}"
    "QToolButton:hover{background:rgba(127,127,127,0.15);}"
    "QToolButton:pressed{background:rgba(127,127,127,0.25);}"
    "QToolButton:disabled{background:transparent;}"
)
# Fenêtre entièrement blanche (marges + zone d'onglets), adaptatif clair/sombre.
_STYLE_DIALOG = (
    "QDialog{background:palette(base);}"
    "QTabWidget::pane{border:none;background:transparent;}"
)
# Liste : conteneur arrondi, séparateurs hairline, pas de zébrage, sélection discrète.
_STYLE_LISTE = (
    "QListWidget{background:palette(base);border:1px solid rgba(127,127,127,0.28);"
    "border-radius:12px;outline:none;padding:2px;}"
    "QListWidget::item{border-bottom:1px solid rgba(127,127,127,0.16);}"
    "QListWidget::item:selected{background:rgba(10,132,255,0.14);color:palette(text);}"
)


class _ChampTitre(QWidget):
    """Titre de réunion éditable en place : double-clic → champ ; Entrée valide,
    Échap annule. Le callback `on_commit(nouveau_titre)` n'est appelé qu'en cas de
    changement réel. Cf. docs/14."""

    def __init__(self, affiche: str, brut: str, on_commit) -> None:
        super().__init__()
        self._brut = brut
        self._on_commit = on_commit
        self._garde = False  # anti-réentrance : masquer le champ refait émettre editingFinished
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._label = QLabel(affiche)
        self._label.setToolTip("Double-cliquer pour renommer")
        self._edit = QLineEdit(brut)
        self._edit.setPlaceholderText("Titre de la réunion")
        self._edit.setMinimumWidth(220)
        self._edit.hide()
        lay.addWidget(self._label)
        lay.addWidget(self._edit)
        self._label.installEventFilter(self)
        self._edit.installEventFilter(self)
        self._edit.editingFinished.connect(self._valider)

    def eventFilter(self, obj, ev):  # noqa: N802 (API Qt)
        if obj is self._label and ev.type() == QEvent.Type.MouseButtonDblClick:
            self._editer()
            return True
        if (obj is self._edit and ev.type() == QEvent.Type.KeyPress
                and ev.key() == Qt.Key.Key_Escape):
            self._annuler()
            return True  # consomme Échap (sinon il rejette le QDialog parent)
        return super().eventFilter(obj, ev)

    def _editer(self) -> None:
        self._edit.setText(self._brut)
        self._label.hide()
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _valider(self) -> None:
        if self._garde or self._edit.isHidden():
            return
        self._garde = True
        nouveau = self._edit.text().strip()
        self._restaurer()
        self._garde = False
        if nouveau != self._brut:
            self._on_commit(nouveau)

    def _annuler(self) -> None:
        self._garde = True
        self._restaurer()
        self._garde = False

    def _restaurer(self) -> None:
        self._edit.hide()
        self._label.show()


class FenetreHistorique(QDialog):
    def __init__(
        self,
        config: Config,
        presse_papiers: PressePapiers | None = None,
        gestionnaire: GestionnaireDiarization | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._presse_papiers = presse_papiers
        self._gestionnaire = gestionnaire
        self.setWindowTitle("Historique — debriefMeet")
        self.setMinimumSize(720, 460)
        self._construire_ui()
        self._cabler_gestionnaire()
        self._installer_surveillance()

    # ── Construction UI ────────────────────────────────────────────────────────

    def _construire_ui(self) -> None:
        self.setStyleSheet(_STYLE_DIALOG)
        layout = QVBoxLayout(self)

        self._liste_reunions = self._creer_liste()
        self._liste_journal = self._creer_liste()

        self._onglets = QTabWidget()
        self._onglets.addTab(self._enrober(self._liste_reunions), "Réunions")
        self._onglets.addTab(self._enrober(self._liste_journal), "Journal")
        self._onglets.currentChanged.connect(lambda _i: self._recharger_actif())
        layout.addWidget(self._onglets)

        fermer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        fermer.rejected.connect(self.close)
        layout.addWidget(fermer)

        self._recharger_tout()

    def _creer_liste(self) -> QListWidget:
        w = QListWidget()
        w.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        w.setAlternatingRowColors(False)
        w.setStyleSheet(_STYLE_LISTE)
        w.setFrameShape(w.Shape.NoFrame)
        # Touche Suppr = « Tout supprimer » sur la sélection (doc 09 §7).
        raccourci = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), w)
        raccourci.setContext(Qt.ShortcutContext.WidgetShortcut)
        raccourci.activated.connect(lambda liste=w: self._tout_supprimer(liste, None))
        return w

    def _enrober(self, liste: QListWidget) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(liste)
        return w

    def _indicateur(self, nom_glyphe: str, tooltip: str) -> QLabel:
        lab = QLabel()
        lab.setPixmap(pixmap_glyphe(nom_glyphe, taille=16))
        lab.setToolTip(tooltip)
        return lab

    def _bouton(self, nom_glyphe: str, tooltip: str, slot, active: bool = True) -> QToolButton:
        b = QToolButton()
        b.setIcon(icone_glyphe(nom_glyphe, 20))
        b.setIconSize(QSize(20, 20))
        b.setToolTip(tooltip)
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(_STYLE_BOUTON)
        b.setEnabled(active)
        b.clicked.connect(slot)
        return b

    def _bouton_attente_anime(self, tooltip: str) -> QToolButton:
        """Bouton « job en cours » désactivé, dont l'icône spinner tourne (animation).

        Le QTimer est enfant du bouton → il s'arrête et se nettoie quand la ligne est
        reconstruite (fin de job) ou la fenêtre fermée. Aucun timer orphelin."""
        b = self._bouton(_ICONE_WIP, tooltip, lambda: None, active=False)
        etat = {"angle": 0}
        timer = QTimer(b)

        def _tick() -> None:
            etat["angle"] = (etat["angle"] + 30) % 360
            b.setIcon(icone_glyphe_pivotee(_ICONE_WIP, 20, etat["angle"]))

        timer.timeout.connect(_tick)
        timer.start(80)
        return b

    # ── Chargement du listing ──────────────────────────────────────────────────

    def _dossier(self, est_reunion: bool) -> Path:
        cle = "dossier_reunions" if est_reunion else "dossier_journal"
        return Path(self._config.get(cle))

    def _recharger_tout(self) -> None:
        self._charger_liste(self._liste_reunions, est_reunion=True)
        self._charger_liste(self._liste_journal, est_reunion=False)

    def _recharger_actif(self) -> None:
        est_reunion = self._onglets.currentIndex() == 0
        liste = self._liste_reunions if est_reunion else self._liste_journal
        self._charger_liste(liste, est_reunion=est_reunion)

    def _charger_liste(self, liste: QListWidget, est_reunion: bool) -> None:
        selection = {p for p in self._chemins_selectionnes(liste)}
        liste.clear()

        fichiers = lister_enregistrements(self._dossier(est_reunion))
        if not fichiers:
            item = QListWidgetItem("Aucun enregistrement trouvé.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            liste.addItem(item)
            return

        job = self._gestionnaire.job_en_cours() if self._gestionnaire else None
        type_job = self._gestionnaire.type_job_en_cours() if self._gestionnaire else None
        un_job_tourne = job is not None
        for f in fichiers:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setToolTip(str(f))
            liste.addItem(item)
            ligne = self._construire_ligne(f, est_reunion, en_cours=(f == job),
                                           un_job_tourne=un_job_tourne, type_job=type_job)
            item.setSizeHint(ligne.sizeHint())
            liste.setItemWidget(item, ligne)
            if f in selection:
                item.setSelected(True)

    def _construire_ligne(self, chemin: Path, est_reunion: bool, *,
                          en_cours: bool, un_job_tourne: bool,
                          type_job: str | None = None) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(4)

        if est_reunion:
            self._ajouter_titre(lay, chemin)
        else:
            lay.addWidget(QLabel(chemin.name))

        audio = pistes_audio_existantes(chemin) if est_reunion else []
        locuteurs = chemin_locuteurs(chemin).exists() if est_reunion else False
        en_attente = transcription_en_attente(chemin) if est_reunion else False

        if est_reunion:
            if audio:
                lay.addWidget(self._indicateur("micro", "Audio retenu présent"))
            if en_attente:
                lay.addWidget(self._indicateur("attente", "À transcrire"))
            if locuteurs:
                lay.addWidget(self._indicateur("personnes", "Locuteurs générés"))

        lay.addStretch()

        # #1 Copier
        lay.addWidget(self._bouton(
            _ICONE_COPIER, "Copier la transcription",
            lambda _=False, c=chemin: self._copier(c, est_reunion)))

        # #2 Transcrire (audio seul, en attente) OU générer les locuteurs (réunions)
        if est_reunion:
            dispo = self._gestionnaire is not None and self._gestionnaire.disponible()
            if en_attente:
                # La transcription différée ne dépend QUE du moteur (pas du modèle pyannote).
                lay.addWidget(self._bouton_transcrire(
                    chemin, audio, dispo, en_cours, un_job_tourne, type_job))
            else:
                # La diarization exige en plus que le modèle pyannote soit configuré.
                prete = self._gestionnaire is not None and self._gestionnaire.diarization_prete()
                lay.addWidget(self._bouton_diarization(
                    chemin, audio, locuteurs, prete, en_cours, un_job_tourne, type_job))

        # #3 Ouvrir
        lay.addWidget(self._bouton(
            _ICONE_OUVRIR, "Ouvrir la transcription",
            lambda _=False, c=chemin: self._ouvrir(c)))
        # #4 Révéler
        lay.addWidget(self._bouton(
            _ICONE_REVELER, "Révéler dans le Finder",
            lambda _=False, c=chemin: self._reveler(c)))

        # #5 Supprimer l'audio (réunions)
        if est_reunion:
            lay.addWidget(self._bouton(
                _ICONE_SUPPR_AUDIO, "Supprimer l'audio (garde le débrief)",
                lambda _=False, c=chemin: self._supprimer_audio(self._liste_reunions, c),
                active=bool(audio)))

        # #6 Tout supprimer
        liste = self._liste_reunions if est_reunion else self._liste_journal
        lay.addWidget(self._bouton(
            _ICONE_TOUT_SUPPR,
            "Tout supprimer (transcription + locuteurs + audio)" if est_reunion
            else "Supprimer la transcription",
            lambda _=False, c=chemin, l=liste: self._tout_supprimer(l, c)))

        return w

    def _ajouter_titre(self, lay: QHBoxLayout, chemin: Path) -> None:
        """Colonne gauche d'une réunion : titre éditable + métadonnées (date · heure · durée)."""
        dh = date_heure_reunion(chemin)
        titre = titre_reunion(chemin)
        duree = formater_duree(duree_reunion(chemin))
        if titre:
            affiche = titre
            morceaux = [m for m in (
                dh.strftime("%d/%m/%Y") if dh else None,
                dh.strftime("%H:%M") if dh else None,
                duree,
            ) if m]
        else:
            affiche = dh.strftime("%d/%m/%Y %H:%M") if dh else chemin.stem
            morceaux = [duree]

        champ = _ChampTitre(affiche, titre or "",
                            on_commit=lambda t, c=chemin: self._renommer(c, t))
        lay.addWidget(champ)
        meta = QLabel(" · ".join(morceaux))
        meta.setStyleSheet("color: gray; font-size: 11px;")
        meta.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(meta)

    def _renommer(self, chemin: Path, titre: str) -> None:
        definir_titre(chemin, titre)
        # Rechargement différé : le widget du titre est détruit par le rechargement,
        # or on est encore dans son gestionnaire d'événement (editingFinished).
        QTimer.singleShot(
            0, lambda: self._charger_liste(self._liste_reunions, est_reunion=True))

    def _bouton_transcrire(self, chemin: Path, audio: list, dispo: bool,
                           en_cours: bool, un_job_tourne: bool, type_job: str | None) -> QToolButton:
        if en_cours and type_job == "transcription":
            return self._bouton_attente_anime("Transcription en cours…")
        actif = dispo and bool(audio) and not un_job_tourne
        tooltip = "Transcrire la réunion"
        if not audio:
            tooltip = "Aucun audio à transcrire"
        elif not dispo:
            tooltip = "Moteur de transcription indisponible"
        elif un_job_tourne:
            tooltip = "Une tâche est déjà en cours"
        return self._bouton(_ICONE_TRANSCRIRE, tooltip,
                            lambda _=False, c=chemin: self._transcrire(c), active=actif)

    def _bouton_diarization(self, chemin: Path, audio: list, locuteurs: bool, prete: bool,
                            en_cours: bool, un_job_tourne: bool, type_job: str | None) -> QToolButton:
        if en_cours and type_job == "diarization":
            return self._bouton_attente_anime("Génération des locuteurs en cours…")
        actif = prete and bool(audio) and not locuteurs and not un_job_tourne
        tooltip = "Générer les locuteurs"
        if locuteurs:
            tooltip = "Locuteurs déjà générés"
        elif not audio:
            tooltip = "Aucun audio retenu"
        elif not prete:
            tooltip = "Diarization non configurée — Préférences › Audio"
        elif un_job_tourne:
            tooltip = "Une génération est déjà en cours"
        return self._bouton(_ICONE_GENERER, tooltip,
                            lambda _=False, c=chemin: self._generer(c), active=actif)

    # ── Sélection ──────────────────────────────────────────────────────────────

    def _chemins_selectionnes(self, liste: QListWidget) -> list[Path]:
        out: list[Path] = []
        for it in liste.selectedItems():
            c = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(c, Path):
                out.append(c)
        return out

    def _cibles(self, liste: QListWidget, chemin: Path | None) -> list[Path]:
        """Cibles d'une action de suppression : la sélection si `chemin` en fait partie
        et qu'elle compte >1 élément ; sinon `chemin` seul (ou la sélection si appel clavier)."""
        selection = self._chemins_selectionnes(liste)
        if chemin is None:
            return selection
        if chemin in selection and len(selection) > 1:
            return selection
        return [chemin]

    # ── Actions simples (mono-ligne) ────────────────────────────────────────────

    def _copier(self, chemin: Path, est_reunion: bool) -> None:
        # Si un débrief locuteurs existe, on copie cette version (doc 09 §3.1).
        source = chemin
        if est_reunion:
            loc = chemin_locuteurs(chemin)
            if loc.exists():
                source = loc
        if not source.exists():
            return
        texte = source.read_text(encoding="utf-8")
        # Préfixe éventuel du prompt actif (cf. docs/12).
        from debrief_meet.core import prompts as _prompts
        contenu = _prompts.contenu_actif(
            self._config.get("prompts"), self._config.get("prompt_actif"))
        if contenu:
            texte = _prompts.prefixer(texte, contenu)
        if self._presse_papiers:
            self._presse_papiers.copier(texte)
        else:
            try:
                subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)
            except Exception:
                pass

    def _ouvrir(self, chemin: Path) -> None:
        if chemin.exists():
            subprocess.Popen(["open", str(chemin)])

    def _reveler(self, chemin: Path) -> None:
        if chemin.exists():
            subprocess.Popen(["open", "-R", str(chemin)])

    # ── Diarization (déléguée au gestionnaire persistant) ───────────────────────

    def _generer(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.diarization_prete():
            return
        if not pistes_audio_existantes(chemin):
            QMessageBox.information(
                self, "Diarization",
                f"Aucun audio retenu pour « {chemin.name} ».\n"
                "Activez la rétention audio dans les Préférences avant la réunion.")
            return
        if not self._gestionnaire.lancer(chemin):
            QMessageBox.information(self, "Diarization",
                                    "Une génération est déjà en cours.")

    def _transcrire(self, chemin: Path) -> None:
        if self._gestionnaire is None or not self._gestionnaire.disponible():
            return
        if not pistes_audio_existantes(chemin):
            QMessageBox.information(
                self, "Transcription",
                f"Aucun audio retenu pour « {chemin.name} ».")
            return
        if not self._gestionnaire.lancer_transcription(chemin):
            QMessageBox.information(self, "Transcription",
                                    "Une tâche est déjà en cours.")

    def _cabler_gestionnaire(self) -> None:
        if self._gestionnaire is None:
            return
        self._gestionnaire.demarre.connect(self._sur_diar_change)
        self._gestionnaire.termine.connect(self._sur_diar_change)
        self._gestionnaire.echoue.connect(self._sur_diar_echoue)

    @Slot(object)
    @Slot(object, object)
    def _sur_diar_change(self, *_args) -> None:
        # Démarrage ou fin : l'état WIP / les indicateurs changent → on recharge les réunions.
        self._charger_liste(self._liste_reunions, est_reunion=True)

    @Slot(object, str)
    def _sur_diar_echoue(self, _md: object, message: str) -> None:
        self._charger_liste(self._liste_reunions, est_reunion=True)
        if self.isVisible():
            QMessageBox.warning(self, "Diarization — échec",
                                f"La génération des locuteurs a échoué :\n{message}")

    # ── Suppressions ────────────────────────────────────────────────────────────

    def _supprimer_audio(self, liste: QListWidget, chemin: Path | None) -> None:
        cibles = [c for c in self._cibles(liste, chemin) if pistes_audio_existantes(c)]
        if not cibles:
            QMessageBox.information(self, "Audio retenu", "Aucun audio retenu à supprimer.")
            return
        rep = QMessageBox.question(
            self, "Supprimer l'audio retenu",
            f"Supprimer l'audio retenu de {len(cibles)} réunion(s) ?\n"
            "(Le débrief reste ; la diarization ne sera plus regénérable.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        for c in cibles:
            for p in pistes_audio_existantes(c):
                try:
                    p.unlink()
                except OSError:
                    pass
        self._charger_liste(liste, est_reunion=(liste is self._liste_reunions))

    def _tout_supprimer(self, liste: QListWidget, chemin: Path | None) -> None:
        cibles = self._cibles(liste, chemin)
        if not cibles:
            return
        est_reunion = liste is self._liste_reunions
        rep = QMessageBox.question(
            self, "Tout supprimer",
            f"Supprimer définitivement {len(cibles)} enregistrement(s) ?"
            + ("\n(Transcription + débrief locuteurs + audio retenu.)" if est_reunion else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        for c in cibles:
            self._supprimer_un(c, est_reunion)
        self._charger_liste(liste, est_reunion=est_reunion)

    def _supprimer_un(self, chemin: Path, est_reunion: bool) -> None:
        a_supprimer = [chemin]
        if est_reunion:
            a_supprimer.append(chemin_locuteurs(chemin))
            a_supprimer += pistes_audio_existantes(chemin)
        for p in a_supprimer:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    # ── Rafraîchissement live ────────────────────────────────────────────────────

    def _installer_surveillance(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        dossiers = {str(self._dossier(True)), str(self._dossier(False))}
        for d in dossiers:
            if Path(d).exists():
                self._watcher.addPath(d)
        self._watcher.directoryChanged.connect(self._sur_dossier_change)
        # Anti-rebond léger : absorbe les rafales (création de plusieurs fichiers).
        self._timer_refresh = QTimer(self)
        self._timer_refresh.setSingleShot(True)
        self._timer_refresh.setInterval(200)
        self._timer_refresh.timeout.connect(self._recharger_tout)

    def _sur_dossier_change(self, _chemin: str) -> None:
        self._timer_refresh.start()

    # ── Sélection programmatique (clic sur notification) ─────────────────────────

    def selectionner_reunion(self, chemin_md: Path | None) -> None:
        """Bascule sur l'onglet Réunions et sélectionne la ligne du `.md` donné."""
        self._onglets.setCurrentIndex(0)
        self._charger_liste(self._liste_reunions, est_reunion=True)
        if chemin_md is None:
            return
        liste = self._liste_reunions
        liste.clearSelection()
        for i in range(liste.count()):
            it = liste.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == Path(chemin_md):
                it.setSelected(True)
                liste.setCurrentItem(it)
                liste.scrollToItem(it)
                break
