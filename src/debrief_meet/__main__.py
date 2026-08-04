from __future__ import annotations

import argparse
import os
import sys


class _FluxNul:
    """Flux d'écriture no-op — remplace `sys.stdout`/`sys.stderr` valant `None`.

    En app figée fenêtrée (PyInstaller `console=False`), `sys.stdout`/`sys.stderr`
    valent `None` : toute écriture (un `print`, ou surtout les barres de progression
    tqdm de `huggingface_hub` au téléchargement d'un modèle) lève alors
    `'NoneType' object has no attribute 'write'`. Bug observé sur Windows au premier
    lancement (2026-07-06). Rediriger vers ce flux neutralise toute la classe de
    crashs — le vrai canal de diagnostic reste `logging` + `faulthandler` (docs/31)."""

    def write(self, _texte: str) -> int:
        return 0

    def flush(self) -> None:
        pass


def _garantir_stdio() -> None:
    """Remplace `sys.stdout`/`sys.stderr` par un flux nul s'ils valent `None`.

    No-op quand les flux sont réels (dev, ou worker subprocess dont stdin/stdout
    sont de vrais pipes pour le protocole pickle) — d'où l'appel APRÈS le routage
    des workers dans `main()`."""
    if sys.stdout is None:
        sys.stdout = _FluxNul()
    if sys.stderr is None:
        sys.stderr = _FluxNul()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="debriefMeet",
        description="Transcription vocale locale — dictée, réunion, journal",
    )
    p.add_argument("--toggle", action="store_true", help="Toggle mode Dictée")
    p.add_argument("--toggle-reunion", action="store_true", help="Toggle mode Réunion")
    p.add_argument("--toggle-journal", action="store_true", help="Toggle mode Journal")
    p.add_argument("--list-devices", action="store_true", help="Lister les périphériques audio")
    p.add_argument("--version", action="store_true", help="Afficher la version")
    return p


def _commande_depuis_args(args: argparse.Namespace) -> str | None:
    if args.toggle:
        return "toggle"
    if args.toggle_reunion:
        return "toggle-reunion"
    if args.toggle_journal:
        return "toggle-journal"
    if args.list_devices:
        return "list-devices"
    return None


def _relais_interprete_figee() -> bool:
    """En app figée, `sys.executable` est le binaire debriefMeet, pas un interpréteur
    Python générique. Or `multiprocessing` (déclenché en interne par mlx/torch, ex.
    `resource_tracker`) relance parfois `sys.executable` en mode "python -c" pur :
    `-B -S -I -c "<code>"`. Sans interception, notre argparse reçoit ces flags et
    échoue avec "unrecognized arguments" (observé au 1er lancement réel de l'app
    packagée, cf. docs/16 §5.1 — inoffensif pour la transcription mais bruyant).
    On émule `python -c` : si `-c` est présent, exécute le code qui suit et
    retourne True (l'appelant ne doit rien faire d'autre)."""
    if "-c" not in sys.argv:
        return False
    idx = sys.argv.index("-c")
    code = sys.argv[idx + 1]
    sys.argv = ["-c", *sys.argv[idx + 2:]]
    exec(code, {"__name__": "__main__"})
    return True


def main() -> None:
    if _relais_interprete_figee():
        return

    # Mode worker MLX : en app figée, le binaire .app se relance lui-même comme
    # sous-processus de transcription (cf. moteur_mlx._commande_worker). On route
    # ici, avant toute init Qt/IPC, sinon le worker démarrerait une UI fantôme.
    if "--mlx-worker" in sys.argv:
        from debrief_meet.platform.macos._mlx_worker import main as _worker_main
        _worker_main()
        return

    # Idem pour le worker faster-whisper Windows (docs/34 §1).
    if "--fw-worker" in sys.argv:
        from debrief_meet.platform.windows._fw_worker import main as _fw_worker_main
        _fw_worker_main()
        return

    # App fenêtrée : neutralise stdout/stderr None (PyInstaller console=False) —
    # sinon les barres tqdm de huggingface_hub plantent le téléchargement de modèle.
    _garantir_stdio()
    # Ceinture + bretelles : couper aussi les barres de progression HF côté GUI
    # (comme le worker le fait déjà) — rien à rendre dans un flux nul.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    from debrief_meet import __version__

    args = _parser().parse_args()

    if args.version:
        print(f"debriefMeet {__version__}")
        return

    # QApplication doit exister avant QLocalSocket
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("debriefMeet")
    app.setApplicationVersion(__version__)

    from debrief_meet.ipc import envoyer_commande, instance_en_cours

    commande = _commande_depuis_args(args)

    if commande and commande == "list-devices":
        _lister_peripheriques()
        return

    if commande:
        if envoyer_commande(commande):
            return
        # Pas d'instance — démarre l'app et applique la commande après init

    if not commande and instance_en_cours():
        print("debriefMeet est déjà en cours d'exécution.")
        return

    _demarrer_app(app, commande)


def _lister_peripheriques() -> None:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            print(f"[{i:2d}] {d['name']}  ({d['max_input_channels']}in / {d['max_output_channels']}out)")
    except ImportError:
        print("sounddevice non installé — impossible de lister les périphériques.")


def _demarrer_app(app, commande_initiale: str | None) -> None:
    import logging

    from PySide6.QtWidgets import QSystemTrayIcon

    from debrief_meet.core import mode_transcription
    from debrief_meet.core.config import Config
    from debrief_meet.core.logs import configurer_logs, installer_traces_crash, journaliser_entete_session
    from debrief_meet.core.modes import MachineEtats, Mode
    from debrief_meet.ipc import ServeurIPC
    from debrief_meet.ui.icones import icone_application
    from debrief_meet.ui.polices import charger_polices
    from debrief_meet.ui.theme import charger_theme
    from debrief_meet.ui.tray import IconeTray

    # Polices + thème (refonte design) — avant toute création de widget.
    charger_polices(app)
    charger_theme(app)

    # Icône d'application (Dock / barre des tâches) : sans elle, macOS affiche l'icône
    # générique du lanceur Python dès qu'une fenêtre (Historique, Préférences) s'ouvre.
    app.setWindowIcon(icone_application())

    # Config
    config = Config()
    config.charger()

    # Mode de transcription (docs/45) — figé ici pour la durée du process, AVANT
    # configurer_logs (qui logge le mode en première ligne) et avant toute
    # construction gatée (fabrique, orchestrateurs, raccourcis, fenêtre, tray).
    mode_transcription.initialiser(config)

    # Logs
    configurer_logs(
        actifs=config.get("logs_actifs"),
        debug=config.get("logs_debug"),
    )
    installer_traces_crash()
    logger = logging.getLogger("debrief_meet")

    # Instance unique Windows (docs/34 §6) — mutex nommé, consommé aussi par
    # l'installeur Inno Setup (AppMutex) pour proposer de fermer l'app avant une
    # mise à jour. S'ajoute à l'IPC cross-platform (ci-dessous), pas un remplacement.
    if sys.platform == "win32":
        from debrief_meet.platform.windows.instance_unique import acquerir_instance_unique
        if not acquerir_instance_unique():
            logger.info("Instance debriefMeet déjà active — sortie")
            return

    # En-tête de session (docs/31 §3.4) : la collecte (PowerShell côté Windows) peut
    # prendre ~1 s — thread non bloquant pour ne pas retarder l'affichage du tray.
    def _journaliser_entete() -> None:
        from debrief_meet.platform.infos_systeme import collecter_infos_systeme
        journaliser_entete_session(collecter_infos_systeme())

    import threading
    threading.Thread(target=_journaliser_entete, daemon=True, name="entete-session").start()

    # Vérifier que le tray est supporté
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Erreur : aucune zone de notification système disponible.", file=sys.stderr)
        sys.exit(1)

    # IPC (instance unique)
    serveur_ipc = ServeurIPC()
    if not serveur_ipc.demarrer():
        print("Erreur : impossible de démarrer le serveur IPC.", file=sys.stderr)
        sys.exit(1)

    # Machine à états
    machine = MachineEtats()

    from pathlib import Path
    from debrief_meet.platform.factory import creer_adaptateurs
    from debrief_meet.core.dictee import OrchestrateurDictee

    adaptateurs = creer_adaptateurs()
    # Préchargement du modèle déplacé après l'affichage du tray (cf. plus bas) : au 1er
    # lancement, on télécharge avec une fenêtre de progression au lieu d'un gel silencieux.
    # Dictée et Journal n'existent pas en mode distant (docs/45) : aucun moteur local.
    orch_dictee = OrchestrateurDictee(
        machine=machine,
        micro=adaptateurs.micro,
        moteur=adaptateurs.moteur,
        presse_papiers=adaptateurs.presse_papiers,
        config=config,
    ) if mode_transcription.avec_dictee_journal() else None

    # Câblage commandes IPC
    def _executer_commande(cmd: str) -> None:
        # Le garde de mode est une question de justesse, pas de rangement : `--toggle`
        # peut encore arriver d'un raccourci bureau créé quand le mode était « local »,
        # après une bascule en « distant ». Sans lui, `MachineEtats` basculerait en
        # Mode.DICTEE sans orchestrateur à l'écoute — rien n'enregistre, le tray ne
        # rougit pas, et le mode Réunion reste ensuite refusé : verrouillage silencieux
        # de la seule fonctionnalité de l'app.
        if cmd in ("toggle", "toggle-journal") and not mode_transcription.avec_dictee_journal():
            logger.warning("Commande IPC %r indisponible en mode distant — ignorée", cmd)
        elif cmd == "toggle":
            machine.toggle_dictee()
        elif cmd == "toggle-reunion":
            machine.toggle_reunion()
        elif cmd == "toggle-journal":
            machine.toggle_journal()
        else:
            logger.warning("Commande IPC inconnue : %r", cmd)

    serveur_ipc.commande_recue.connect(_executer_commande)

    # Raccourcis clavier globaux (docs/28) — le partial est construit ici (le tray en a
    # besoin), mais l'enregistrement effectif n'a lieu qu'après l'affichage du tray.
    import functools
    from debrief_meet.core.raccourcis import appliquer_raccourcis

    reappliquer_raccourcis = functools.partial(appliquer_raccourcis, adaptateurs.raccourcis, config, machine)

    # Surveillant de périphériques (Phase 3.5) — reconnexion micro à chaud en réunion.
    surveillant = None
    try:
        from debrief_meet.platform.commun.surveillant_peripheriques import SurveillantPeripheriques
        surveillant = SurveillantPeripheriques()
    except Exception as exc:
        logger.warning("Surveillant de périphériques indisponible (%s)", exc)

    # AEC (annulation d'écho sans casque) — construite inconditionnellement (peu coûteuse,
    # moteur LiveKit chargé paresseusement à la 1ʳᵉ réunion). C'est l'orchestrateur qui lit
    # `aec_actif` à chaque réunion → le réglage des Préférences prend effet sans redémarrer.
    processeur_aec = None
    try:
        from debrief_meet.core.aec import ProcesseurAEC
        processeur_aec = ProcesseurAEC(
            sr_micro=adaptateurs.micro.taux_echantillonnage,
            sr_systeme=adaptateurs.systeme.taux_echantillonnage,
        )
    except Exception as exc:
        logger.warning("AEC non initialisée (%s) — réunion sans annulation d'écho", exc)

    from debrief_meet.core.reunion import OrchestrateurReunion
    orch_reunion = OrchestrateurReunion(
        machine=machine,
        micro=adaptateurs.micro,
        systeme=adaptateurs.systeme,
        moteur=adaptateurs.moteur,
        config=config,
        surveillant=surveillant,
        processeur_aec=processeur_aec,
    )

    from debrief_meet.core.journal import OrchestrateurJournal
    orch_journal = OrchestrateurJournal(
        machine=machine,
        micro=adaptateurs.micro,
        moteur=adaptateurs.moteur,
        dossier_journal=Path(config.get("dossier_journal")),
        config=config,
    ) if mode_transcription.avec_dictee_journal() else None

    # Gestionnaire de diarization persistant (survit à l'ouverture/fermeture de l'Historique).
    from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
    gestionnaire_diar = GestionnaireDiarization(adaptateurs.moteur, config)

    # Gestionnaire de CR Mistral persistant (docs/42) — no-op tant que non configuré
    # (clé API vide, §2). Même patron que gestionnaire_diar, ressource indépendante
    # (appel réseau externe, pas le moteur de transcription local).
    from debrief_meet.ui.generateur_cr_mistral import GestionnaireCRMistral
    gestionnaire_cr_mistral = GestionnaireCRMistral(config)

    # Interco BlueMind (docs/40) — no-op tant que non configurée (URL vide, §1.1).
    from debrief_meet.core.bluemind.sync import SynchroCalendrier
    synchro_bluemind = SynchroCalendrier(config)

    def _sur_mode_change_bluemind(mode: Mode) -> None:
        if mode is Mode.REUNION:
            synchro_bluemind.synchroniser_si_necessaire()

    machine.mode_change.connect(_sur_mode_change_bluemind)

    minutes_sync = int(config.get("bluemind_sync_minutes") or 0)
    timer_bluemind = None
    if minutes_sync > 0:
        from PySide6.QtCore import QTimer
        timer_bluemind = QTimer()
        timer_bluemind.setInterval(minutes_sync * 60_000)
        timer_bluemind.timeout.connect(synchro_bluemind.synchroniser_si_necessaire)
        timer_bluemind.start()

    # F3 — notification de début de réunion (docs/40 §8). Lit uniquement la réplique
    # locale (jamais de réseau au tick) : no-op tant que le store est vide.
    from debrief_meet.core.planificateur_reunions import PlanificateurReunions
    planificateur_bluemind = PlanificateurReunions(config, synchro_bluemind.store)
    planificateur_bluemind.demarrer()

    # Fenêtre principale (refonte design) — coquille unique Historique/Préférences/
    # Enregistrement, remplace les anciens dialogues indépendants.
    from debrief_meet.ui.fenetre_principale import FenetrePrincipale

    def _reappliquer_et_rafraichir_tray() -> list[str]:
        # `tray` n'existe pas encore à la définition de cette fermeture (construit
        # juste après `fenetre`, qui en a besoin) — capturé par closure, résolu au
        # premier appel réel (édition d'un raccourci dans les Préférences).
        echecs = reappliquer_raccourcis()
        tray.rafraichir_raccourcis()
        return echecs

    fenetre = FenetrePrincipale(
        machine, config, demarrage_auto=adaptateurs.demarrage_auto,
        presse_papiers=adaptateurs.presse_papiers, gestionnaire=gestionnaire_diar,
        moteur=adaptateurs.moteur, reappliquer_raccourcis=_reappliquer_et_rafraichir_tray,
        bluemind_reinitialiser_sync=synchro_bluemind.reinitialiser,
        bluemind_declencher_sync=synchro_bluemind.synchroniser_si_necessaire,
        bluemind_sur_ouverture=synchro_bluemind.synchroniser_si_necessaire,
        bluemind_store=synchro_bluemind.store,
        # L'objet complet (et pas seulement son store) : le flux CR Mistral force une
        # resync et **attend** sa fin avant de proposer une association (docs/42).
        bluemind_synchro=synchro_bluemind,
        gestionnaire_cr_mistral=gestionnaire_cr_mistral)

    # Tray
    tray = IconeTray(machine, config, fenetre_principale=fenetre, gestionnaire=gestionnaire_diar,
                     orch_reunion=orch_reunion)
    tray.show()

    # F3 (suite) — notification + démarrage pré-associé en un clic (§8).
    planificateur_bluemind.reunion_due.connect(tray.notifier_reunion_due)
    orch_reunion.reunion_demarree.connect(tray._sur_reunion_demarree)
    # docs/43 §9 — l'historique doit aussi surveiller le sous-dossier de la réunion
    # en cours (tranches ajoutées en direct, watcher racine insuffisant).
    orch_reunion.reunion_demarree.connect(fenetre.definir_reunion_active)

    echecs_raccourcis = reappliquer_raccourcis()
    if echecs_raccourcis:
        logger.warning("Raccourcis non enregistrés (déjà pris ?) : %s", ", ".join(echecs_raccourcis))

    orchestrateurs = [o for o in (orch_dictee, orch_reunion, orch_journal) if o is not None]
    for orch in orchestrateurs:
        orch.etat_visuel_change.connect(tray.definir_etat_visuel)
        orch.etat_visuel_change.connect(fenetre.definir_etat_visuel)
    orch_reunion.micro_perdu.connect(tray.notifier_micro_perdu)
    orch_reunion.micro_retabli.connect(tray.notifier_micro_retabli)
    orch_reunion.micro_muet.connect(tray.notifier_micro_muet)
    # `rien_entendu` n'existe que sur Dictée et Journal — connexions individuelles, une
    # boucle aveugle sur `orchestrateurs` lèverait sur OrchestrateurReunion.
    if orch_dictee is not None:
        orch_dictee.rien_entendu.connect(tray.notifier_rien_entendu)
    if orch_journal is not None:
        orch_journal.rien_entendu.connect(tray.notifier_rien_entendu)

    # Tray affiché → on (télé)charge le modèle : fenêtre de progression si absent du
    # cache (1er lancement), sinon préchargement silencieux des workers.
    if adaptateurs.moteur is not None:
        from debrief_meet.ui.chargeur_modele import precharger_au_demarrage
        precharger_au_demarrage(adaptateurs.moteur, config)
    else:
        # Gain le plus visible du mode distant (le défaut) : aucun modèle (~1,5 Go)
        # téléchargé au premier lancement, l'app est utilisable immédiatement (docs/45).
        logger.info("Aucun moteur local — pas de préchargement de modèle")

    # Arrêt propre à la fermeture — l'ordre est important :
    # 0. couper les raccourcis globaux en premier (plus aucun toggle ne doit arriver
    #    pendant que les orchestrateurs se terminent)
    # 1. arrêter les orchestrateurs (attend les QThread en cours → libère les workers MLX)
    # 2. puis terminer le moteur (tue les sous-processus Metal seulement quand ils sont libres)
    app.aboutToQuit.connect(adaptateurs.raccourcis.desactiver_tous)
    app.aboutToQuit.connect(orch_reunion.terminer)
    if orch_journal is not None:
        app.aboutToQuit.connect(orch_journal.terminer)
    if orch_dictee is not None:
        app.aboutToQuit.connect(orch_dictee.terminer)
    app.aboutToQuit.connect(gestionnaire_diar.terminer)  # attend le job avant de tuer le moteur
    app.aboutToQuit.connect(gestionnaire_cr_mistral.terminer)  # attend son éventuel job réseau
    app.aboutToQuit.connect(synchro_bluemind.terminer)
    app.aboutToQuit.connect(planificateur_bluemind.arreter)
    app.aboutToQuit.connect(adaptateurs.micro.terminer)
    app.aboutToQuit.connect(adaptateurs.systeme.terminer)
    if adaptateurs.moteur is not None:
        app.aboutToQuit.connect(adaptateurs.moteur.terminer)

    # Commande initiale (ex: --toggle sans instance existante)
    if commande_initiale:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: _executer_commande(commande_initiale))

    logger.info("debriefMeet démarré")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
