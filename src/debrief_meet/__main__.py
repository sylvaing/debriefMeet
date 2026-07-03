from __future__ import annotations

import argparse
import sys


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


def main() -> None:
    # Mode worker MLX : en app figée, le binaire .app se relance lui-même comme
    # sous-processus de transcription (cf. moteur_mlx._commande_worker). On route
    # ici, avant toute init Qt/IPC, sinon le worker démarrerait une UI fantôme.
    if "--mlx-worker" in sys.argv:
        from debrief_meet.platform.macos._mlx_worker import main as _worker_main
        _worker_main()
        return

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

    from debrief_meet.core.config import Config
    from debrief_meet.core.logs import configurer_logs, installer_traces_crash, journaliser_entete_session
    from debrief_meet.core.modes import MachineEtats
    from debrief_meet.ipc import ServeurIPC
    from debrief_meet.ui.icones import icone_application
    from debrief_meet.ui.tray import IconeTray

    # Icône d'application (Dock / barre des tâches) : sans elle, macOS affiche l'icône
    # générique du lanceur Python dès qu'une fenêtre (Historique, Préférences) s'ouvre.
    app.setWindowIcon(icone_application())

    # Config
    config = Config()
    config.charger()

    # Logs
    configurer_logs(
        actifs=config.get("logs_actifs"),
        debug=config.get("logs_debug"),
    )
    installer_traces_crash()
    logger = logging.getLogger("debrief_meet")

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
    orch_dictee = OrchestrateurDictee(
        machine=machine,
        micro=adaptateurs.micro,
        moteur=adaptateurs.moteur,
        presse_papiers=adaptateurs.presse_papiers,
        config=config,
    )

    # Câblage commandes IPC
    def _executer_commande(cmd: str) -> None:
        if cmd == "toggle":
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
    )

    # Gestionnaire de diarization persistant (survit à l'ouverture/fermeture de l'Historique).
    from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization
    gestionnaire_diar = GestionnaireDiarization(adaptateurs.moteur, config)

    # Tray
    tray = IconeTray(machine, config, demarrage_auto=adaptateurs.demarrage_auto,
                     presse_papiers=adaptateurs.presse_papiers, gestionnaire=gestionnaire_diar,
                     moteur=adaptateurs.moteur, reappliquer_raccourcis=reappliquer_raccourcis)
    tray.show()

    echecs_raccourcis = reappliquer_raccourcis()
    if echecs_raccourcis:
        logger.warning("Raccourcis non enregistrés (déjà pris ?) : %s", ", ".join(echecs_raccourcis))

    orch_dictee.etat_visuel_change.connect(tray.definir_etat_visuel)
    orch_reunion.etat_visuel_change.connect(tray.definir_etat_visuel)
    orch_journal.etat_visuel_change.connect(tray.definir_etat_visuel)
    orch_reunion.micro_perdu.connect(tray.notifier_micro_perdu)
    orch_reunion.micro_retabli.connect(tray.notifier_micro_retabli)
    orch_dictee.rien_entendu.connect(tray.notifier_rien_entendu)
    orch_journal.rien_entendu.connect(tray.notifier_rien_entendu)

    # Tray affiché → on (télé)charge le modèle : fenêtre de progression si absent du
    # cache (1er lancement), sinon préchargement silencieux des workers.
    from debrief_meet.ui.chargeur_modele import precharger_au_demarrage
    precharger_au_demarrage(adaptateurs.moteur, config)

    # Arrêt propre à la fermeture — l'ordre est important :
    # 0. couper les raccourcis globaux en premier (plus aucun toggle ne doit arriver
    #    pendant que les orchestrateurs se terminent)
    # 1. arrêter les orchestrateurs (attend les QThread en cours → libère les workers MLX)
    # 2. puis terminer le moteur (tue les sous-processus Metal seulement quand ils sont libres)
    app.aboutToQuit.connect(adaptateurs.raccourcis.desactiver_tous)
    app.aboutToQuit.connect(orch_reunion.terminer)
    app.aboutToQuit.connect(orch_journal.terminer)
    app.aboutToQuit.connect(orch_dictee.terminer)
    app.aboutToQuit.connect(gestionnaire_diar.terminer)  # attend le job avant de tuer le moteur
    app.aboutToQuit.connect(adaptateurs.micro.terminer)
    app.aboutToQuit.connect(adaptateurs.systeme.terminer)
    app.aboutToQuit.connect(adaptateurs.moteur.terminer)

    # Commande initiale (ex: --toggle sans instance existante)
    if commande_initiale:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: _executer_commande(commande_initiale))

    logger.info("debriefMeet démarré")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
