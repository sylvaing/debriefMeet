# Phases d'implémentation — debriefMeet

> Document à donner **séquentiellement** à une IA pour coder. Chaque phase est une **tranche verticale exécutable** (jamais des couches inertes) et respecte la **Definition of Done** du Bloc 5 technique.
> Références : `01-specifications-fonctionnelles.md`, `02-specifications-techniques.md`.

---

## Principes de découpage

- **macOS d'abord** (machine de l'utilisateur → validation manuelle immédiate), puis **Windows**, puis **Linux**. Le cœur métier étant partagé, les portages n'ajoutent **que des adaptateurs** : ils réutilisent **la même suite de tests cœur**, ce qui *prouve* la portabilité.
- **Le mode Réunion est le plus utilisé** → il est traité **en priorité haute**, juste après une fondation Dictée minimale qui valide à moindre coût la chaîne moteur+micro. (Faire Réunion *strictement* en premier signifierait attaquer le mode le plus complexe — 2 flux, tranches, écriture incrémentale — sans moteur validé.)
- **Le risque #1 du projet (Core Audio taps macOS) est isolé en Phase 0.5**, un spike avec décision **go/no-go** avant tout le reste.
- **Chaque phase se termine par la Definition of Done** : code + **`pytest` lancé et vert** + pas de régression + **livrable qui se lance** + notice « Comment tester ».
- L'agent **exécute les tests unitaires lui-même** avant livraison et **rapporte la sortie**. Les tests d'intégration (vrai micro/visio/permission) sont validés **manuellement par l'utilisateur**.

### Rappel Definition of Done (à appliquer à CHAQUE phase)

1. Code conforme aux specs. 2. Tests unitaires écrits **et exécutés** (`pytest -m "not integration"` vert, sortie rapportée). 3. Aucune régression (suite complète relancée). 4. Livrable **exécutable** de bout en bout. 5. Notice « **Comment tester** » manuelle. 6. Tests d'intégration joués où c'est possible.

---

## Phase 0 — Socle projet & architecture exécutable

**Objectif :** poser le squelette, l'archi en couches, l'outillage de test, et une app qui **se lance déjà**.

**Contenu :**
- `pyproject.toml` (deps de base : PySide6, sounddevice, scipy/soxr, platformdirs ; extras moteurs par OS), structure `src/debrief_meet/` (`core/`, `ui/`, `platform/`).
- **Interfaces ABC** (`platform/interfaces.py`) : `MoteurTranscription`, `CaptureMicro`, `CaptureAudioSysteme`, `PressePapiers`, `DemarrageAuto` (+ `RaccourcisGlobaux` déclarée, non implémentée).
- **Fabrique** (`factory.py`) avec détection OS (matériel : stub).
- `core/config.py` (JSON + `platformdirs`, défauts, champ `version`), `core/logs.py` (logging + rotation, off par défaut).
- **Machine à états des modes** (`core/modes.py`) : `Mode` (un seul mode actif, toggles, exclusivité) **+ `EtatVisuel`** (état d'activité pilotant la couleur de l'icône — cf. §5.1 fonctionnel / 1.8 technique) — sur adaptateurs **fake**.
- **UI minimale** : `ui/tray.py` (menu + **grisage exclusif** des modes incompatibles + `definir_etat_visuel()`), `ui/icones.py` (**icône carré arrondi+onde dessinée programmatiquement**, contour/plein par `EtatVisuel`, `REPOS`=template macOS), fenêtre **Préférences** vide, **À propos**.
- **Instance unique + IPC** (`QLocalServer`/`QLocalSocket`) + CLI (`--toggle*`, `--list-devices`, `--version`).
- **Outillage tests** : `tests/`, `conftest.py`, **faux adaptateurs** (`tests/fakes/`), `pytest`/`pytest-qt`/`pytest-cov`, commande unique.

**Livrable :** l'app démarre, le tray apparaît (icône carré arrondi+onde au repos, qui s'adapte à la barre), Préférences s'ouvre, « Quitter » marche, l'instance unique empêche les doublons, démarrer un mode grise les autres et passe l'icône en rouge.

**Tests :** *Unitaires* — config (défauts/save/load/migration), logs (on/off, rotation, pas de contenu sensible), machine à états (un seul mode, toggle, refus si autre mode actif), **icônes (rendu par `EtatVisuel`, `REPOS`=template, couleurs distinctes)**. *Manuel* — lancer, voir le tray, ouvrir Préférences, vérifier l'instance unique, vérifier le grisage et la couleur rouge en enregistrement.

---

## Phase 0.5 — POC capture audio système (spike, go/no-go) ✅ TERMINÉ

**Objectif :** lever **le risque le plus élevé du projet** avant de construire quoi que ce soit d'autre. Phase courte, isolée, **décisionnelle**.

**Contenu réalisé :**

Deux approches ont été implémentées et testées sur une vraie visio avec AirPods :

| Approche | Haut-parleurs intégrés | AirPods / Bluetooth | Verdict |
|---|---|---|---|
| **Core Audio taps** (`AudioTapPOC.swift`, macOS 14.2+) | ✅ | ❌ silencieux | Abandonné |
| **ScreenCaptureKit** (`SCKAudioPOC.swift`, macOS 13+) | ✅ | ✅ | **Retenu** |

Core Audio taps échoue sur les périphériques Bluetooth parce que le tap global n'intercepte pas le pipeline audio BT séparé. ScreenCaptureKit capture au-dessus du routage → device-agnostic.

**Résultat (SCK) :**
- Audio des participants capturé proprement ✅
- Fonctionne avec AirPods ✅
- Permission requise : **« Enregistrement de l'écran »** (accordée au terminal en dev, attachée au `.app` en production)
- Micro non capturé par ce binaire (attendu : c'est un flux d'entrée séparé, géré par `sounddevice` en Phase 2)
- Format de sortie : PCM float32 48 kHz stéréo interleaved sur stdout, logs sur stderr

**Livrables :**
- `helpers/macos/poc-audio-tap/SCKAudioPOC.swift` — helper Swift ScreenCaptureKit
- `helpers/macos/poc-audio-tap/build.sh` — script de compilation + signature ad-hoc
- `helpers/macos/poc-audio-tap/test_tap.py` — orchestrateur Python + rapport go/no-go
- `helpers/macos/poc-audio-tap/entitlements.plist` — entitlements audio-input

**GO pour la Phase 2 (mode Réunion).** `SCKAudioPOC.swift` sera restructuré en `helpers/macos/sck-audio/SCKAudioCapture.swift` à la Phase 2 pour l'intégration production.

**Tests :** *Manuel (intégration)* — validé sur une vraie visio avec haut-parleurs intégrés et AirPods. Pas de test unitaire (spike, le helper sera testé via l'adaptateur Python en Phase 2).

---

## Phase 1 — Mode Dictée (macOS) — fondation moteur ✅ TERMINÉ

**Objectif :** établir **à moindre coût** la chaîne moteur+micro+presse-papiers, en livrant un mode utile.

**Livrables :**
- `src/debrief_meet/core/audio.py` — `BufferAudio` thread-safe + `reechantillonner()` (scipy resample_poly, stéréo→mono, float32 16 kHz)
- `src/debrief_meet/core/modeles.py` — `TABLE_MLX` (tiny→large-v3), `NOMS_LOGIQUES`, `resoudre_mlx()`
- `src/debrief_meet/core/dictee.py` — `OrchestrateurDictee(QObject)` + `_WorkerTranscription(QObject)` ; worker Qt thread → transcription asynchrone → presse-papiers ; états visuels ENREGISTREMENT/TRANSCRIPTION/TERMINE/ERREUR/REPOS
- `src/debrief_meet/platform/macos/moteur_mlx.py` — `MoteurMLX` via mlx-whisper (Apple Silicon), imports paresseux, repli stub si absent
- `src/debrief_meet/platform/macos/presse_papiers.py` — `PressePapiersMaxOS` via pbcopy/pbpaste
- `src/debrief_meet/platform/commun/micro_sounddevice.py` — `CaptureMicroSounddevice` (sounddevice PortAudio, buffer thread-safe, import paresseux)
- `platform/interfaces.py` — propriété `taux_echantillonnage → 44_100` ajoutée à `CaptureMicro`
- `platform/factory.py` — `_macos()` instancie les vraies implémentations (MoteurMLX sur arm64, sinon stub ; repli ImportError pour chaque adaptateur)
- `__main__.py` — `OrchestrateurDictee` câblé : `etat_visuel_change → tray.definir_etat_visuel`
- `tests/test_audio.py` — 8 tests (BufferAudio, reechantillonner)
- `tests/test_modeles.py` — 4 tests (résolution, ValueError, exhaustivité)
- `tests/test_dictee.py` — 5 tests (flux complet, audio vide, erreur)

**Résultats tests :** `pytest -m "not integration"` → **84 passed** (67 Phase 0 + 17 nouveaux).

**Comment tester (intégration manuelle) :**
1. `make run` — l'app démarre
2. Cliquer « Dictée » dans le menu tray — icône passe en rouge (ENREGISTREMENT)
3. Parler
4. Cliquer à nouveau « Dictée » — icône passe en orange (TRANSCRIPTION) puis vert (TERMINE)
5. Coller (`⌘V`) dans n'importe quelle app — le texte transcrit apparaît

Note : au premier lancement, macOS demande l'accès au **microphone**. mlx-whisper télécharge le modèle (≈1 Go) au premier usage — s'assurer d'être connecté.

---

## Phase 2 — Mode Réunion (macOS) — **mode prioritaire** ✅ TERMINÉ

**Objectif :** livrer le mode le plus utilisé. Réutilise le moteur (Phase 1) + le helper validé (Phase 0.5).

**Livrables :**
- `src/debrief_meet/platform/macos/capture_systeme.py` — `CaptureAudioSCK` : lance `SCKAudioPOC` en subprocess, lit PCM float32 48kHz stéréo sur stdout (thread daemon), parse `FORMAT:<sr>:<ch>` sur stderr, retourne `(N, ch)` depuis `recuperer_echantillons()`. **Démarrage paresseux** : le subprocess SCK n'est créé qu'au premier `demarrer()` (pas au `__init__`) pour éviter l'indicateur de capture d'écran permanent. **`arreter()` termine le processus** (QUIT + wait) — l'indicateur disparaît à chaque fin de réunion.
- `src/debrief_meet/platform/macos/moteur_mlx.py` — **pool de 2 sous-processus isolés** (`_WorkerSubprocess` + `queue.Queue`) : chaque worker a son propre contexte Metal (fix crash SIGBUS/Bus error: 10 lié au contexte Metal partagé entre threads). Protocole stdin/stdout length-prefixed pickle. `charger_modele()` précharge les 2 workers en background au démarrage — aucun cold start à la première réunion. `transcrire()` fait `pool.get(timeout=90)` → `pool.put()` pour la sérialisation.
- `src/debrief_meet/core/reunion.py` — `OrchestrateurReunion(QObject)` + `_WorkerTranche(QObject)` : 2 buffers séparés, `QTimer` par intervalle, **transcription micro + système en parallèle** (`ThreadPoolExecutor(max_workers=2)`) dans un `QThread`, icône rouge pendant toute la session, `TERMINE` uniquement à l'arrêt final. `terminee = Signal(object, object)` émet les `ResultatTranscription` complets (avec segments).
- `src/debrief_meet/core/fichiers.py` — `EcrivainReunion` : crée `AAAA-MM-JJ_HH-MM.md`, en-tête, warning repli micro-seul, blocs `## HH:MM (MM:SS)`. **Entrelacement par timestamp** : les segments Whisper (avec `debut`/`fin`) des deux pistes sont triés par heure et regroupés par locuteur → alternance naturelle `**Moi :**`/`**Participants :**` dans l'ordre chronologique réel.
- `platform/interfaces.py` — propriété concrète `taux_echantillonnage → 48_000` ajoutée à `CaptureAudioSysteme`
- `platform/factory.py` — `_macos()` utilise `CaptureAudioSCK` (fallback `SystemeStub` si `ImportError`)
- `__main__.py` — `OrchestrateurReunion` câblé : `etat_visuel_change → tray.definir_etat_visuel` ; `adaptateurs.moteur.charger_modele(config.get("modele"))` appelé au démarrage pour précharger les workers MLX.
- `tests/test_fichiers.py` — 10 tests (en-tête, repli, format tranche, skip vide, incrémental, MM:SS)
- `tests/test_reunion.py` — 6 tests (démarrage, création fichier, TERMINE, timer, repli micro-seul, rouge pendant)

**Résultats tests :** `pytest -m "not integration"` → **39 passed**.

**Comment tester (intégration manuelle) :**
1. Accorder « Enregistrement de l'écran » au terminal : Réglages Système → Confidentialité → Enregistrement de l'écran
2. Rejoindre une visio (Teams, Jitsi, Meet…)
3. `make run` → menu tray → Réunion → parler + écouter les participants
4. Arrêter Réunion → fichier `.md` créé dans `~/Documents/debriefMeet/reunions/`
5. Ouvrir le fichier : blocs horodatés `Moi` / `Participants` toutes les 30 s

Note : si SCKAudioPOC n'est pas compilé → `make build-helpers` d'abord.

---

## Phase 3 — Journal + Préférences + Historique (macOS) ✅ TERMINÉ

**Objectif :** compléter les fonctions restantes et la configuration graphique.

**Contenu :**
- `core/journal.py` (+ format Journal §12.2 : fichier du jour, append, horodatage). Câblage `--toggle-journal`.
- **Fenêtre Préférences** fonctionnelle : modèle (téléchargement/cache/suppression, accélération affichée), micro, dossiers de sortie (création auto, validation), langue (auto/forcée), intervalle réunion, autostart, logs, notifications.
- `platform/macos/demarrage_auto.py` (**LaunchAgent**).
- **Fenêtre Historique** (§5.5) : liste **réunions + journal** des dossiers configurés, tri par date, actions **Copier la transcription / Ouvrir / Révéler / Supprimer**.

**Livrable :** macOS **complet** — les 3 modes + Préférences + Historique.

**Tests :** *Unitaires* — append Journal + format exact ; listing/actions Historique (copier via `PressePapiersFake`, suppression) ; persistance préférences ; bascule autostart (via `AutostartFake`). *Manuel* — entrée de journal → `.md` ; changer un dossier ; activer autostart → vérifier LaunchAgent ; copier depuis l'Historique.

---

## Phase 3.5 — Robustesse audio macOS : reconnexion micro à chaud ✅ TERMINÉ

**Objectif :** détecter **instantanément** un changement de périphérique d'entrée pendant une réunion (ex. retrait des AirPods → bascule sur le micro intégré) et **reprendre la capture micro à chaud**, sans perdre la réunion. Voir le plan détaillé `04-plan-detection-peripherique-audio.md`.

**Décision technique :** **Qt Multimedia** (`QMediaDevices.audioInputsChanged`) — signal événementiel instantané, cross-platform, aucune dépendance ajoutée. Alternatives (CoreAudio ctypes, PyObjC) analysées et écartées — cf. doc technique §4.5bis.

**Livrables :**
- `src/debrief_meet/platform/commun/surveillant_peripheriques.py` — `SurveillantPeripheriques(QObject)` : encapsule `QMediaDevices`, émet `change` après **anti-rebond** (300 ms) pour absorber les rafales d'événements d'un retrait.
- `platform/interfaces.py` — `CaptureMicro.redemarrer(index)` ajoutée (**concrète no-op par défaut**, comme `terminer()`).
- `platform/commun/micro_sounddevice.py` — `redemarrer()` : ferme l'ancien flux et rouvre sur le nouveau périphérique **en préservant le buffer** déjà capté (le glitch du warm-up est jeté). Helper `_ouvrir_flux()` partagé avec `demarrer()` (repli sur défaut si l'index échoue).
- `core/reunion.py` — `OrchestrateurReunion` reçoit un `surveillant` optionnel ; au signal `change`, si la réunion est active et le micro présent, appelle `micro.redemarrer(micro_index)` → **rebascule sur le micro préféré** s'il est revenu, sinon repli défaut. Échec total → poursuite sans micro.
- `__main__.py` — instancie `SurveillantPeripheriques` (repli `None` si Qt Multimedia indisponible) et le câble à l'orchestrateur réunion.

**Périmètre :** **mode Réunion uniquement** (Dictée/Journal sont trop courts). Capture système (SCK) **non concernée** (device-agnostic).

**Résultats tests :** `pytest -m "not integration"` → **163 passed** (152 + 11 nouveaux : anti-rebond du surveillant, `redemarrer()` préserve-buffer + repli, câblage orchestrateur — redémarrage sur signal, rebascule préférence, garde hors-réunion, échec → sans micro).

**Comment tester (intégration manuelle) :**
1. `make run` → rejoindre une visio avec des **AirPods** (audio + micro sur les AirPods).
2. Menu tray → **Réunion** → parler quelques secondes.
3. **Retirer les AirPods** en cours de réunion → macOS bascule sur le micro intégré.
4. Continuer à parler, puis arrêter la réunion.
5. Ouvrir le `.md` : les tranches **après** le retrait doivent toujours contenir des blocs **« Moi »** (le micro a suivi). Avant le correctif, seul « Participants » apparaissait.
6. Bonus : remettre les AirPods en cours de réunion → le micro doit rebasculer dessus.

---

## Phase A — Annulation d'écho (AEC) sans casque ✅ INTÉGRÉE (macOS)

> Branche **qualité audio** insérée après le cœur macOS (hors plan initial). Née de l'écho des haut-parleurs dans le micro (« Moi » duplique « Participants » quand l'utilisateur n'a pas de casque).

- **Spike :** [`05-spike-aec-webrtc.md`](05-spike-aec-webrtc.md) → **option D (AEC logicielle WebRTC) = GO** (offline + temps réel validés). Moteur retenu : **LiveKit AEC3**, **NS désactivé**, **référence avec marge de lead ~40 ms**, **gate `_SEUIL_RMS` conservé**.
- **Cadrage intégration :** [`06-integration-aec.md`](06-integration-aec.md) — nouveau `core/aec.py` (`ProcesseurAEC` à état, alimenté par tranche) → câblage `factory`/`reunion`/`config`. Contexte hybride : l'AEC nettoie le micro pour qu'il ne contienne **que les voix de la salle** (prérequis de la diarization du micro).
- **Statut :** ✅ **intégrée (macOS)**. `core/aec.py` (`ProcesseurAEC` + calibration robuste : passthrough tant qu'aucun écho franc → voix jamais perdue) ; câblage `reunion`/`config`/`__main__` ; réglage **`aec_actif` dans les Préférences** ; dépendance `livekit>=1.1` (extra `macos`). Validée en réel (séparation Moi/Participants OK). **Suite : 181 passed.** Reste optionnel : ajustement fin de l'auto-vérif de la marge. Détail : doc 06.

---

## Phase D — Diarization (qui a parlé) ✅ IMPLÉMENTÉE (macOS)

> Remontée de la **roadmap post-v1**, dans la foulée de l'AEC (partage la rétention audio).

- **Cadrage :** [`07-diarization.md`](07-diarization.md) — **passe finale post-réunion** (option B, pas de labels en direct), **diarize micro + système puis fusion** des timelines, **« Moi » si une seule voix au micro sinon « Présent N »** (pas d'enrôlement de voix). Moteur retenu : **pyannote** (community-1).
- **Prérequis :** **rétention audio** des 2 pistes + AEC (Phase A) pour un micro diarizable. ✅ faits.
- **Livrables :** `core/diarization.py` (interface `MoteurDiarization` + `DiarizationPyannote` ; fonctions pures `etiqueter`/`attribuer`/`fusionner`/`rendre_locuteurs_md` ; orchestration `generer_locuteurs` ; CLI), `decoder_audio_16k` (`core/audio.py`), `_WorkerDiarization` + bouton **« Générer les locuteurs »** et **suppression audio** dans `ui/historique.py`, toggle rétention dans `ui/preferences.py`, dépendance `pyannote.audio>=4` (`pyproject.toml`).
- **Tests :** `test_diarization.py` + `test_historique_diarization.py` (suite globale **475 passed** au 2026-06-29, croissante).
- **Statut :** ✅ codée, testée **et validée manuellement** (macOS, 2026-06-26). **Distribution du modèle gated RÉSOLUE** via l'**onboarding** (l'utilisateur télécharge community-1 avec son propre token HF, à la volée et jamais stocké) — cf. [`docs/13`](13-diarization-onboarding.md). Plus besoin de bundler les poids ni de repli sherpa pour la v1.
- **Régression 2026-07-02 → ✅ fixée** : le chargement offline du pipeline utilisait
  `local_files_only=True`, paramètre supprimé en pyannote 4.x → `TypeError` systématique
  (diarization inutilisable en réel malgré la validation du 2026-06-26, faite avant la
  montée de version). Fix root-cause + erreur lisible dans [`docs/29`](29-fix-diarization-pyannote4.md)
  (2026-07-02, 576 tests) — **diarization fonctionnelle en réel confirmée offline**.

---

## Phase 4 — Packaging macOS (livrable installable) 🟡 EN COURS

> Détail d'avancement + point de reprise autoporteur : [`16-packaging-macos.md`](16-packaging-macos.md).

**Objectif :** une app **installable** sur Mac, avec permissions **stables**.

**Contenu :**
- **PyInstaller → `.app`**, **helper Swift embarqué**, `Info.plist` (`NSMicrophoneUsageDescription` + `NSAudioCaptureUsageDescription`), cible **arm64 / 14.4+**.
- **Icône de l'app** : **`AppIcon.icns` déjà générée** (`scripts/generer_icone.py` → `src/debrief_meet/ui/assets/AppIcon.icns`, multi-résolution 16→1024). À référencer dans l'`Info.plist` (`CFBundleIconFile` / `CFBundleIconName`).
- **Signature auto-signée stable** (certificat local) → permission audio persistante entre rebuilds. Génération du **`.dmg`**.
- Vérifier autostart **en contexte bundle** et l'attachement TCC au bundle.

**Livrable :** un `.dmg` installable ; après install, les 3 modes marchent et les permissions ne se redemandent pas.

**Tests :** *Unitaires* inchangés (verts). *Manuel* — installer le `.dmg`, accorder les permissions une fois, relancer → conservées ; 3 modes depuis l'app installée ; autostart.

---

## Phase B — Benchmark machine cross-platform ✅ OUTIL PRÊT

**Objectif :** avant les ports, mesurer si une machine Windows/Linux fait tourner le soft et dans quel mode, pour décider les choix d'archi sur des données réelles (les spikes n'ont tourné que sur Mac).

**Contenu :** outil `benchmark/` autonome qui rejoue le pipeline réel (transcription faster-whisper en sweep `small→medium→large-v3` + diarisation comparative sherpa/pyannote) sur un audio canonique ~30 min, avec sondes capture audio guidées (WASAPI/PipeWire, AEC livekit, Bluetooth) et sondes accélérateurs (CUDA/cuDNN, Intel, AMD/Vulkan). Distribué en **bundle portable sans installation** assemblé depuis le Mac (`assembler_bundle.py`). Sortie = **un seul `.zip`** par machine.

**Livrable :** outil + bundles Windows/Linux. Spécifié et documenté dans [`08-benchmark.md`](08-benchmark.md) (schéma rapport + guide d'interprétation).

**Tests :** suite `tests/test_benchmark_*.py` (matériel, moteurs, qualité/WER, pipeline avec fakes, sondes robustesse, rapport/verdict, doc garde-fou) ; baseline mlx validée sur Mac. **Statut :** outil prêt ; les rapports Windows/Linux seront exploités à réception pour alimenter les Phases 5/6.

---

## Phase 5 — Portage Windows

**Objectif :** parité Windows. **Aucune logique métier nouvelle** — adaptateurs + packaging.

> **Périmètre v1 — RÉVISÉ le 2026-07-03** (specs complètes : [`30-phase5-architecture-windows.md`](30-phase5-architecture-windows.md), docs 30→35) :
> - modes **Dictée + Réunion avec AEC + Journal** ; **pas de diarization** en v1 (inchangé) ;
> - **installeur Inno Setup inclus en v1** (remplace le ZIP portable) : livraison = `.exe` installable,
>   MAJ par réinstallation par-dessus, désinstallation complète — contrainte : pas de machine Windows
>   de dev, les utilisateurs installent eux-mêmes ([`32`](32-phase5-packaging-cycle-de-vie.md)) ;
> - **moteur v1 = faster-whisper CPU** ; l'accélération iGPU devient un second moteur enfichable,
>   activé quand le rapport spike (docs/18) sera rendu — le spike n'est **plus bloquant** pour démarrer ;
> - **raccourcis globaux inclus** (`RegisterHotKey`, défauts `Ctrl+Alt+D/R/J`) ;
> - **logs DEBUG par défaut sur Windows** + export diagnostic ([`31`](31-phase5-observabilite-debug.md)) —
>   les logs utilisateurs sont le seul canal de debug.

**Préalable — Spike backends :** [`18-spike-backends-windows.md`](18-spike-backends-windows.md).
Les machines cibles (Bastien AMD, Alix Intel) n'ont **pas de NVIDIA** et des iGPU différents : faster-whisper
CPU/CUDA ne les exploite pas. Le spike compare **4 backends** (faster-whisper · OpenVINO · DirectML ·
Vulkan/whisper.cpp) × **4 modèles** (small · medium · large-v3 · large-v3-turbo) sur les 2 machines, et
décide **quels backends embarquer + la règle d'auto-sélection** par profil matériel.
*(Révision 2026-07-03 : le spike ne bloque plus le démarrage — le moteur v1 est faster-whisper CPU,
le spike décidera du moteur iGPU ajouté ensuite derrière la même interface, cf. docs/30 §4.3.)*

> **État (2026-06-30) :** code spike **terminé** (505 tests). Build bundle VM en attente — lancer
> `bash scripts/build_spike_backends_vm.sh` puis copier le zip sur Bastien et Alix.

**Préalable — durcissement cœur (audit externe R3,
[`audits-externes/21`](audits-externes/21-audit-recommandations.md)) :** dans
`OrchestrateurReunion._demarrer()` (`core/reunion.py`), `self._systeme.demarrer()`
n'est pas protégé (contrairement à la branche micro). Si l'adaptateur lève *après*
que `disponible()` a répondu vrai, l'exception est avalée par le slot Qt →
`_actif=True` sans timer démarré = mode Réunion zombie. Rare sur macOS (SCK),
mais les nouveaux adaptateurs Windows rendent ce chemin d'échec réaliste.
**À corriger avant de coder `platform/windows/`** : try/except autour de la
séquence de démarrage avec rollback (nettoyage type `_arreter()` partiel) en cas
d'échec. ~20 min + test unitaire sur fake qui lève.

**Contenu :**
- `platform/windows/` : **un module par backend retenu** par le spike, derrière une **auto-sélection** au
  démarrage (iGPU Intel→… / iGPU AMD→… / sinon CPU `int8`) + **repli en cascade**.
- `platform/windows/capture_systeme.py` : **loopback WASAPI via `soundcard`** (sounddevice/PortAudio n'expose
  aucun flag loopback — impasse upstream), avec `CoInitializeEx` par thread ; `presse_papiers.py` (Win32),
  `demarrage_auto.py` (**clé Run du Registre**).
- **Packaging** : PyInstaller onedir + **Inno Setup en v1** (révision 2026-07-03, cf. docs/32), non signé
  (SmartScreen documenté) ; DLL accélérateur embarquées plus tard, selon backends retenus par le spike.

**Livrable :** `debriefMeet-setup-<version>.exe` — app fonctionnelle sur Windows (Dictée + Réunion+AEC + Journal),
CPU universel en v1 ; iGPU via le(s) backend(s) retenu(s) en incrément suivant.

**Tests :** *Unitaires* — **toute la suite cœur relancée sur Windows** (prouve la portabilité) + adaptateurs Windows où faisable. *Manuel* — Dictée + Réunion (loopback `soundcard` + AEC), autostart.

---

## Phase 6 — Portage Linux

**Objectif :** parité Linux (PipeWire, X11/Wayland).

**Contenu :**
- `platform/linux/moteur_faster.py` (faster-whisper CUDA + CPU), détection matérielle.
- `platform/linux/capture_systeme.py` (**moniteur PipeWire** via sounddevice ; repli `pw-record`), `presse_papiers.py` (wl-copy/xclip selon session), `demarrage_auto.py` (**systemd --user**).
- **Packaging** : PyInstaller → **AppImage** + `.desktop` + unit systemd.

**Livrable :** app fonctionnelle et portable sur Linux (3 modes).

**Tests :** *Unitaires* — suite cœur relancée sur Linux. *Manuel* — 3 modes ; capture PipeWire ; autostart systemd ; AppImage sur ≥1 distro.

---

## Incréments UX (macOS, post-Phase 3) ✅

Améliorations livrées **en parallèle** des phases ci-dessus (cœur stable dès la Phase 3), chacune spécifiée dans son doc dédié, testée et validée manuellement :

| Incrément | Doc | Résumé |
|---|---|---|
| Refonte Historique | [09](09-refonte-historique.md) | colonne d'actions, jobs de fond persistants, sélection multiple, rafraîchissement live |
| Transcription différée | [10](10-transcription-differee.md) | mode « enregistrement seul » + bouton Transcrire a posteriori |
| Spinner animé | [11](11-spinner-anime.md) | icône « job en cours » qui tourne |
| Prompts de copie | [12](12-prompts.md) | onglet Prompts + préfixe à la copie depuis l'Historique |
| Onboarding diarization | [13](13-diarization-onboarding.md) | assistant guidé (token HF à la volée, jamais stocké) + illustrations |
| Titre éditable + durée | [14](14-titre-duree.md) | titre libre (H1) + durée dans l'Historique |
| Modèle à chaud + DL initial | [15](15-changement-modele.md) | changement de modèle sans redémarrage + téléchargement initial visible |
| Identité d'icône | — | carré arrondi + ondes ; tray + `AppIcon.icns` |

---

## Roadmap post-v1 (hors périmètre, déjà prévue dans l'archi)

- **whisper.cpp-Vulkan** (GPU AMD/Intel) — après POC (Bloc 2 §2.6).
- ~~**Raccourcis globaux natifs** dans l'app + redéfinition en préférences~~ → **fait pour macOS**, cf. [`28-raccourcis-globaux.md`](28-raccourcis-globaux.md). Reste hors v1 pour Windows/Linux (interface déjà déclarée, adaptateur à écrire).
- ~~**Diarisation** des réunions (`Participant 1/2/3`)~~ → **remontée en Phase D**, cadrée dans [`07-diarization.md`](07-diarization.md).
- **Génération de compte-rendu via LLM** depuis l'Historique.
- **CI multi-OS** (GitHub Actions, `pytest -m "not integration"`).
- **Signature/notarisation** (macOS) + **Authenticode** (Windows) si distribution élargie.

### Améliorations en cours (near-term)

- **Modèle `large-v3-turbo`** (large-v3 distillé, décodeur réduit : ~2× plus rapide bout-en-bout, qualité quasi équivalente, ~1,6 Go en MLX) :
  - côté **macOS/MLX** — ✅ **implémenté** (2026-06-30) : [`19-ajout-modele-large-v3-turbo.md`](19-ajout-modele-large-v3-turbo.md) — `TABLE_MLX`, **modèle par défaut**, note du sélecteur corrigée, **505 passed** ;
  - côté **Windows** — évalué dans le spike backends [`18`](18-spike-backends-windows.md) (faster-whisper/OpenVINO/DirectML/Vulkan).

---

## Vue d'ensemble

| Phase | Cible | Livrable | Dépend de |
|---|---|---|---|
| 0 | Tous | App lançable (tray, prefs vides, IPC) | — |
| 0.5 | macOS | POC Core Audio taps + go/no-go ⚠️ | 0 |
| 1 | macOS | Dictée (fondation moteur) ✅ | 0 |
| 2 | macOS | **Réunion** (mode prioritaire) ✅ | 1, 0.5 |
| 3 | macOS | Journal + Préférences + Historique ✅ | 2 |
| 3.5 | macOS | Reconnexion micro à chaud (Qt Multimedia) ✅ | 2 |
| **A** | macOS | **AEC sans casque** ✅ intégrée — [05](05-spike-aec-webrtc.md)/[06](06-integration-aec.md) | 2 |
| **D** | macOS | **Diarization** (passe finale) ✅ implémentée — [07](07-diarization.md) | A + rétention audio |
| 4 | macOS | `.dmg` installable, permissions stables 🟡 en cours — [16](16-packaging-macos.md) | 3 |
| 5 | Windows | Dictée + Réunion+AEC (spike backends → [18](18-spike-backends-windows.md) → moteur) | 3 (cœur) |
| 6 | Linux | AppImage Linux | 3 (cœur) |

> Phases 5 et 6 dépendent du **cœur** (stable dès la Phase 3) et peuvent être menées **en parallèle** une fois macOS validé.
