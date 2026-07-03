# Spécifications techniques — debriefMeet

> **Statut :** en cours de rédaction, **validé bloc par bloc**.
> Base : specs fonctionnelles figées (`01-specifications-fonctionnelles.md`).
> **Stack retenue : Python + PySide6 (Qt 6)**, moteurs de transcription optimisés par OS derrière une interface commune.
>
> Plan : Bloc 1 — Architecture & interfaces · Bloc 2 — Moteurs par OS · Bloc 3 — Capture audio système · Bloc 4 — Structure projet, config, logs, packaging · Bloc 5 — Tests, qualité & livrables par phase.

---

## Bloc 1 — Architecture & interfaces

### 1.1 Principe : cœur partagé, plateforme isolée

L'application est découpée en **3 couches**. Tout ce qui est métier/UI est **partagé entre les 3 OS** ; seules les briques qui touchent le système ont une implémentation par OS, **derrière des interfaces abstraites**.

```
┌──────────────────────────────────────────────────────────────┐
│  COUCHE PRÉSENTATION (UI) — PySide6 / Qt, partagée            │
│  • Icône tray + menu contextuel + états visuels                │
│  • Fenêtres : Préférences, Historique, À propos                │
│  • Notifications (QSystemTrayIcon.showMessage)                 │
└───────────────────────────┬──────────────────────────────────┘
                            │ signaux Qt (thread-safe)
┌───────────────────────────▼──────────────────────────────────┐
│  COUCHE APPLICATION (cœur métier) — Python pur, partagée       │
│  • Machine à états des modes (un seul mode actif)              │
│  • Orchestration Dictée / Réunion / Journal                    │
│  • Écriture des fichiers .md (formats §12 fonctionnel)         │
│  • Configuration, logs, gestion des modèles                    │
│  • AUCUNE dépendance OS / Qt directe                           │
└───────────────────────────┬──────────────────────────────────┘
                            │ interfaces abstraites (ports)
┌───────────────────────────▼──────────────────────────────────┐
│  COUCHE PLATEFORME (adaptateurs) — 1 implémentation par OS      │
│  MoteurTranscription · CaptureMicro · CaptureAudioSysteme      │
│  PressePapiers · RaccourcisGlobaux · DemarrageAuto             │
└────────────────────────────────────────────────────────────────┘
```

**Règle d'or :** la couche application ne connaît que les **interfaces** (types abstraits). Elle n'importe jamais `mlx_whisper`, `AppKit`, `ctypes`, ni un module spécifique à un OS. Le choix de l'implémentation se fait **une seule fois au démarrage** (cf. 1.4).

### 1.2 Les interfaces (ports) à définir

Chaque interface est une classe abstraite (ABC) ; chaque OS en fournit une implémentation concrète.

| Interface | Rôle | Partie OS-dépendante |
|---|---|---|
| `MoteurTranscription` | `transcrire(audio, langue) -> texte` ; `charger_modele(nom)` ; propriétés (accélération active, modèle chargé) | mlx-whisper / faster-whisper / whisper.cpp — **Bloc 2** |
| `CaptureMicro` | démarrer/arrêter la capture du micro, fournir les échantillons | **Partagé** via `sounddevice` (PortAudio) sur les 3 OS |
| `CaptureAudioSysteme` | capturer le son de sortie (loopback) pour le mode Réunion | ScreenCaptureKit / WASAPI / PipeWire — **Bloc 3** |
| `PressePapiers` | `copier(texte)` | macOS/Windows/Linux (voir 1.5) |
| `RaccourcisGlobaux` *(interface prévue, **non implémentée en v1**)* | enregistrer/désenregistrer des raccourcis, émettre un événement au déclenchement | natif par OS — **reporté** (voir 1.5) |
| `DemarrageAuto` | activer/désactiver/interroger le lancement au login | LaunchAgent / Registre / systemd — **Bloc 4** |

> `Notifications` n'est **pas** une interface dédiée : Qt fournit `QSystemTrayIcon.showMessage()` de façon cross-platform. On reste sur Qt, avec repli éventuel si besoin.

### 1.3 Modèle de threads (critique pour Qt)

L'UI Qt vit sur le **thread principal** et ne doit **jamais** être bloquée (sinon l'app « gèle »).

- **Transcription** (lourde, plusieurs secondes) → exécutée dans un **worker** (`QThread` / `QThreadPool` + worker objet), résultat renvoyé à l'UI via **signaux Qt** (thread-safe).
- **Capture audio** → callbacks PortAudio sur leur propre thread ; les échantillons sont accumulés dans un buffer protégé.
- **Mode Réunion** → un timer déclenche la transcription d'une tranche toutes les N secondes **sans bloquer** la capture qui continue.
- **Modèle gardé en mémoire** entre deux usages (réactivité, cf. exigence fonctionnelle) : chargé paresseusement au premier usage, conservé ensuite.

### 1.4 Sélection de l'implémentation par OS (fabrique)

Au démarrage, une **fabrique** (`platform/factory.py`) lit `sys.platform` (et la détection matérielle pour le moteur) et instancie les bonnes implémentations, **injectées** dans la couche application. Le cœur reçoit ses dépendances par injection — aucun `if macOS:` dispersé dans le métier.

```
créer_adaptateurs() -> Adaptateurs(
    moteur            = sélection selon OS + matériel (Bloc 2),
    capture_micro     = CaptureMicroSounddevice(),      # partagé
    capture_systeme   = sélection selon OS (Bloc 3),
    presse_papiers    = sélection selon OS,
    raccourcis        = sélection selon OS,
    demarrage_auto    = sélection selon OS,
)
```

### 1.5 Instance unique & raccourcis globaux (remplace le hack socket Unix de l'existant)

L'existant utilisait un **socket Unix** pour que `--toggle` parle à l'instance en cours (non portable Windows). On le remplace par les primitives **cross-platform de Qt** :

- **Instance unique** : `QLocalServer` / `QLocalSocket` (fonctionne sur les 3 OS). Si une instance tourne déjà, le nouveau lancement lui transmet la commande (ex. `toggle-dictee`) puis se ferme.
- **Commandes `--toggle` / `--toggle-journal`** : conservées comme point d'entrée CLI ; elles passent par ce canal local au lieu d'un socket Unix brut. **C'est le mécanisme de raccourci de la v1** : l'utilisateur câble ces commandes via les outils natifs de l'OS (app Raccourcis / KDE-GNOME / AutoHotkey). Si l'app n'est pas lancée, la commande la démarre puis exécute l'action.
- **Raccourcis globaux natifs dans l'app — REPORTÉS (hors v1).** Qt ne capte pas les raccourcis **globaux** (hors focus) ; il faudrait une implémentation **native par OS** derrière l'interface `RaccourcisGlobaux` (prévue mais non implémentée) :
  - macOS : `RegisterEventHotKey` via `pyobjc` (permission Accessibilité requise).
  - Windows : `RegisterHotKey` (Win32) via `ctypes`.
  - Linux : capture X11 (`Xlib`) / portail Wayland — **point le plus fragile** (variabilité Wayland), principale raison du report.
  - Repli envisageable plus tard : lib tierce (`pynput`/`keyboard`), à évaluer.

### 1.6 Découpage en modules (vue d'ensemble — détaillé au Bloc 4)

```
debrief_meet/
├── core/            # métier partagé : modes, machine à états, fichiers .md, config, logs
├── ui/              # PySide6 : tray, fenêtres préférences/historique/à-propos
├── platform/        # interfaces (ports) + fabrique
│   ├── interfaces.py
│   ├── factory.py
│   ├── macos/       # implémentations macOS
│   ├── windows/     # implémentations Windows
│   └── linux/       # implémentations Linux
└── app.py           # point d'entrée, parsing CLI, instance unique
```

### 1.7 Décisions de ce bloc (à valider)

1. **Architecture en 3 couches** avec adaptateurs OS derrière des interfaces, injection au démarrage. ✅/❓
2. **`CaptureMicro` partagé** via `sounddevice` (PortAudio) sur les 3 OS — seul l'audio **système** est par-OS. ✅/❓
3. **Instance unique + IPC via `QLocalServer`/`QLocalSocket`** (remplace le socket Unix). ✅/❓
4. **Raccourcis : v1 via les outils de l'OS sur `--toggle` (IPC local) ; capture clavier native dans l'app REPORTÉE** (interface `RaccourcisGlobaux` prévue mais non implémentée). ✅/❓
5. **Notifications via Qt** (`QSystemTrayIcon.showMessage`), pas d'interface dédiée. ✅/❓
   > ⚠️ Limite constatée : sur macOS, `showMessage()` exige que l'app soit enregistrée auprès du Centre de notifications (effectif après packaging signé) ; en développement non packagé, l'appel échoue silencieusement. Ne **pas** s'appuyer dessus pour un retour critique. L'exclusivité des modes est donc portée par le **grisage** des entrées de menu (cf. 1.8), pas par une notification.
6. **Transcription en worker thread**, modèle gardé en mémoire. ✅/❓

### 1.8 Icône du tray & états visuels (implémenté en Phase 0)

- **Forme** : **carré arrondi** (bulle, sans queue) + onde vocale (5 barres), dessiné **programmatiquement** dans `ui/icones.py` (repère logique 100×100, `QPainterPath`), aucun asset. Cf. **§5.1 fonctionnel** pour le visuel et la justification.
- **La couleur encode l'état d'activité, pas le mode** — énumération **`EtatVisuel`** dans `core/modes.py` : `REPOS`, `ENREGISTREMENT` (🔴), `TRANSCRIPTION` (🟠), `TERMINE` (🟢 bref), `ERREUR` (⚪ bref). API d'entrée : `IconeTray.definir_etat_visuel(etat)`.
- **REPOS = template** : `QIcon.setIsMask(True)` → macOS recolore selon le thème de la barre (clair/sombre). Les états colorés sont non-template (`setIsMask(False)`), carré plein + ondes blanches en réserve.
- **Icône d'application** (Dock/Finder, distincte du tray) : même motif **en couleur** — carré arrondi bleu système (dégradé) + ondes **blanches** directement dessus, marges macOS ~80 %, **sans ombre intégrée** (macOS l'ajoute). Rendu SVG via `dessiner_icone_app()` ; le **`.icns`** multi-résolution est produit par `scripts/generer_icone.py` → `ui/assets/AppIcon.icns` (branché au bundle en Phase 4 via `CFBundleIconFile`).
- **Exclusivité des modes par grisage** : pendant qu'un mode est actif, les entrées des autres modes sont désactivées (`QAction.setEnabled(False)`) et l'entrée active passe à « ⏹ Arrêter X ». Pas de notification d'erreur (cf. limite `showMessage` ci-dessus).
- **Câblage par phase** : en Phase 0 (stubs), seul `REPOS ↔ ENREGISTREMENT` est piloté ; `TRANSCRIPTION`/`TERMINE`/`ERREUR` sont émis par la chaîne de transcription à partir de la Phase 1.
- **Réunion** : reste `ENREGISTREMENT` toute la session (la transcription par tranches ne change pas la couleur), `TERMINE` bref à l'arrêt.

---

## Bloc 2 — Moteurs de transcription par OS

### 2.1 Objectif

Fournir, derrière **une seule interface `MoteurTranscription`**, **le meilleur moteur disponible selon l'OS et le matériel**, avec un **repli robuste** et une **gestion claire des erreurs** (l'existant souffrait précisément de problèmes CUDA non gérés).

### 2.2 Matrice moteur ↔ matériel

| Contexte détecté | Moteur retenu | Accélération | Notes |
|---|---|---|---|
| **macOS Apple Silicon** (arm64) | **mlx-whisper** | Metal / Neural Engine | Le plus rapide sur M-series. Lib Python. |
| **GPU NVIDIA** (Win/Linux) | **faster-whisper** (CTranslate2) | CUDA | Référence en débit. `compute_type=float16`. |
| **GPU AMD / Intel** (Win/Linux) | *(v1 : repli CPU)* — **whisper.cpp Vulkan en v2** | CPU puis Vulkan | **Hors v1.** En v1, ces machines tournent en CPU. Accélération Vulkan ajoutée après POC (2.6). |
| **CPU** (repli, tout OS) | **faster-whisper** `int8` | CPU | Excellent rapport perf/CPU. Repli universel — **et seul mode pour AMD/Intel en v1**. |
| macOS **Intel** (x86_64) | faster-whisper CPU (ou whisper.cpp) | CPU | mlx ne fonctionne que sur Apple Silicon. |

### 2.3 Interface `MoteurTranscription`

Classe abstraite ; chaque moteur l'implémente. Le cœur métier ne manipule **que** cette interface.

```python
@dataclass
class Segment:
    debut: float          # secondes
    fin: float
    texte: str

@dataclass
class ResultatTranscription:
    texte: str                    # texte complet nettoyé
    langue_detectee: str | None   # pour les logs / l'UI
    segments: list[Segment]       # nécessaire au mode Réunion + future diarisation

class MoteurTranscription(ABC):
    @property
    @abstractmethod
    def acceleration(self) -> str: ...        # "Metal" | "CUDA" | "Vulkan" | "CPU"
    @property
    @abstractmethod
    def modele_charge(self) -> str | None: ...

    @abstractmethod
    def charger_modele(self, nom_logique: str) -> None: ...
        # idempotent ; garde le modèle en mémoire (réactivité)

    @abstractmethod
    def transcrire(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription: ...
        # audio = float32 mono 16 kHz (normalisé par le cœur, cf. 2.4)
        # langue=None => auto-détection ; sinon code ISO ("fr", "en"...)

    # gestion des modèles
    @abstractmethod
    def est_telecharge(self, nom_logique: str) -> bool: ...
    @abstractmethod
    def telecharger_modele(self, nom_logique: str, progression=None) -> None: ...
```

> **Pourquoi `segments` dans le résultat ?** Le mode Réunion en a besoin pour l'horodatage, et la **diarisation future** (hors v1) s'appuiera dessus. On le prévoit dès maintenant sans surcoût.

### 2.4 Format audio normalisé

- Le cœur fournit toujours l'audio en **float32 mono 16 kHz** (format attendu par Whisper).
- La capture micro se fait au taux du périphérique puis est **rééchantillonnée à 16 kHz** (via `scipy`/`soxr`) **dans le cœur**, avant d'atteindre le moteur. Les moteurs reçoivent donc un format uniforme.
- Cas particulier whisper.cpp (binaire) : son adaptateur **écrit un WAV temporaire 16 kHz** en interne, le passe au binaire, puis le supprime. Transparent pour le cœur.

### 2.5 Noms de modèles : un nom logique → un artefact par moteur

L'utilisateur choisit un **nom logique** (`tiny`/`base`/`small`/`medium`/`large-v2`/`large-v3`). Chaque moteur le **résout** vers son propre artefact :

| Nom logique | mlx-whisper (HF) | faster-whisper | whisper.cpp (GGUF) |
|---|---|---|---|
| `large-v3` | `mlx-community/whisper-large-v3-mlx` | `large-v3` (Systran, auto) | `ggml-large-v3.bin` (ggerganov/whisper.cpp) |
| `medium` | `mlx-community/whisper-medium-mlx` | `medium` | `ggml-medium.bin` |
| … | … | … | … |

→ Une **table de correspondance** par moteur, isolée dans son adaptateur. Le cœur ne connaît que le nom logique.

### 2.6 Détection matérielle & sélection (fabrique moteur)

Au démarrage (`platform/factory.py`), dans l'ordre :

1. macOS + arch `arm64` → tenter **mlx-whisper**.
2. Sinon, **GPU NVIDIA présent** (test : `ctranslate2.get_cuda_device_count() > 0`, ou `nvidia-smi`) → tenter **faster-whisper CUDA**.
3. Sinon → **faster-whisper CPU (`int8`)**. *(C'est ici que tombent les machines AMD/Intel en v1.)*

> **Étape Vulkan prévue mais désactivée en v1 :** un cran « GPU Vulkan présent → whisper.cpp Vulkan » s'insérera **entre 2 et 3** en v2. La fabrique est conçue pour l'accueillir sans refonte (un moteur de plus derrière `MoteurTranscription`).
>
> ⚠️ **POC à mener avant la v2 :** la voie **whisper.cpp + Vulkan en Python** (binding `pywhispercpp` compilé Vulkan, *ou* binaire whisper.cpp pré-compilé Vulkan embarqué + appel subprocess). C'est la partie la moins mûre ; mlx et faster-whisper sont éprouvés. **Ne bloque pas la v1.**

### 2.7 Stratégie de repli (robustesse)

- L'init d'un moteur peut **échouer** (lib CUDA absente, Vulkan indisponible, etc. — le talon d'Achille de l'existant). En cas d'échec, on **descend la chaîne** vers le moteur suivant, **jusqu'au CPU** qui doit toujours fonctionner.
- Chaque bascule de repli est **loggée** et, si elle dégrade l'expérience (ex. GPU attendu → CPU), **signalée à l'utilisateur** par une notification non bloquante.
- L'**accélération réellement active** est exposée (propriété `acceleration`) et affichée dans les préférences (§10.1 fonctionnel) — l'utilisateur sait toujours sur quoi il tourne.

### 2.8 Gestion des modèles (téléchargement & cache)

- **Téléchargement au 1er lancement** si le modèle configuré est absent du cache : fenêtre de progression (worker thread + boucle imbriquée), une seule fois, avant de précharger les workers — `ui/chargeur_modele.py::precharger_au_demarrage`. Sinon préchargement silencieux. Hors-ligne : message, l'app démarre quand même.
- **Changement de modèle à chaud** : `MoteurTranscription.recharger_modele(nom)` (télécharge si besoin puis arrête/relance les workers) — appliqué à la validation des Préférences, **sans redémarrage**. Cf. [`docs/15`](15-changement-modele.md).
- Emplacements de cache :
  - mlx-whisper & faster-whisper : cache Hugging Face (`~/.cache/huggingface/hub`).
  - whisper.cpp : fichiers `ggml-*.bin` dans le **dossier cache applicatif** (cf. Bloc 4).
- Les préférences affichent l'**espace occupé** (en agrégeant les deux emplacements) et permettent de **supprimer un modèle**.
- Échec de téléchargement (réseau) : message clair + réessayer / choisir un modèle plus léger.

### 2.9 Dépendances par plateforme

Pour ne pas embarquer des libs inutiles, **chaque installeur OS ne bundle que le(s) moteur(s) pertinent(s)** :

| OS | Moteurs embarqués |
|---|---|
| macOS (Apple Silicon) | mlx-whisper (+ faster-whisper CPU en repli) |
| Windows | faster-whisper (CUDA + CPU). *whisper.cpp-Vulkan ajouté en v2.* |
| Linux | faster-whisper (CUDA + CPU). *whisper.cpp-Vulkan ajouté en v2.* |

> **En v1, whisper.cpp n'est pas embarqué** : on n'ajoute ses dépendances/binaires qu'en v2, une fois le POC Vulkan validé.

> Les imports moteurs sont **paresseux** : la fabrique n'importe que le moteur sélectionné, évitant qu'une lib absente fasse planter le démarrage.

### 2.11 Isolation subprocess et pool de workers (macOS MLX)

> **Décision issue de la Phase 2.** MLX s'exécute sur Apple Silicon avec un contexte Metal partagé entre tous les threads Python. Appeler `mlx_whisper.transcribe()` depuis deux threads simultanés provoque un **Bus error: 10 (SIGBUS)** + fuite de sémaphores — le processus entier crashe sans récupération possible.

**Solution : un pool de sous-processus isolés.**

Chaque worker MLX est un **sous-processus Python indépendant** (`_mlx_worker.py`) qui :
1. Charge le modèle Whisper une seule fois en mémoire via `MLX_WORKER_REPO` (variable d'env).
2. Écoute des requêtes sur **stdin** (protocole length-prefixed pickle) et répond sur **stdout**.
3. Signale sa disponibilité via `READY` sur stderr (attendu au démarrage, timeout 60 s).

Le moteur `MoteurMLX` gère un **pool de 2 workers** (`queue.Queue`) :
- `charger_modele()` démarre 2 workers en background dès le lancement de l'app — le modèle est prêt avant la première réunion (pas de cold start de 3-7 s à l'usage).
- `transcrire()` fait `pool.get(timeout=90)` → utilise le worker → `pool.put()` : la sérialisation par file d'attente évite tout accès concurrent au pipe.
- Le pool de 2 permet à `_WorkerTranche` de transcrire micro et audio système **en parallèle** (via `ThreadPoolExecutor(max_workers=2)`).
- Si un worker meurt (crash subprocess), il est redémarré automatiquement au prochain `transcrire()`.

**Format du protocole pipe :**
```
stdin  → [4 bytes big-endian longueur] + [pickle({"audio_bytes", "repo", "langue"})]
stdout ← [4 bytes big-endian longueur] + [pickle({"ok", "texte", "segments", "langue", "erreur"})]
stderr → lignes de log + "READY" à l'init
```

### 2.10 Décisions de ce bloc (à valider)

1. **Matrice moteur/matériel — v1** : mlx (Apple Silicon) / faster-whisper CUDA (NVIDIA) / **faster-whisper CPU pour tout le reste, y compris AMD-Intel**. whisper.cpp-Vulkan = **v2** (interface et fabrique déjà prêtes à l'accueillir). ✅/❓
2. **Interface `MoteurTranscription`** renvoyant texte + langue détectée + **segments** (pour Réunion et diarisation future). ✅/❓
3. **Audio normalisé float32 mono 16 kHz** par le cœur. ✅/❓
4. **Nom logique → artefact par moteur** via table de correspondance interne. ✅/❓
5. **Repli en cascade jusqu'au CPU**, loggé et notifié si dégradation. ✅/❓
6. **whisper.cpp-Vulkan = reporté en v2**, conditionné à un POC (binding compilé Vulkan vs binaire+subprocess). Ne bloque pas la v1. ✅/❓

---

## Bloc 3 — Capture audio système (mode Réunion)

### 3.1 Objectif

En mode Réunion, capturer **deux flux audio en parallèle** :

- **Micro** → étiqueté **« Moi »** (capture partagée `CaptureMicro`, via `sounddevice`/PortAudio, déjà couverte au Bloc 1).
- **Audio système (loopback)** → étiqueté **« Participants »** (interface `CaptureAudioSysteme`, **implémentation par OS**).

Les deux flux sont **transcrits séparément** par tranche pour produire l'étiquetage `Moi` / `Participants` du fichier `.md` (§12.1 fonctionnel). C'est la raison pour laquelle on garde **deux buffers distincts** et non un mixage.

### 3.2 Interface `CaptureAudioSysteme`

```python
class CaptureAudioSysteme(ABC):
    @abstractmethod
    def disponible(self) -> bool: ...
        # True si la plateforme + la permission permettent la capture

    @abstractmethod
    def demarrer(self) -> None: ...
    @abstractmethod
    def arreter(self) -> None: ...

    @abstractmethod
    def recuperer_echantillons(self) -> "np.ndarray": ...
        # vide et renvoie les échantillons accumulés depuis le dernier appel
        # float32 mono 16 kHz (rééchantillonné dans l'adaptateur ou le cœur)
```

- Modèle **identique à la capture micro** : un thread interne accumule les échantillons dans un **buffer thread-safe** ; l'orchestrateur Réunion le **draine à chaque tick** du timer (intervalle §8 fonctionnel).
- Sortie normalisée **float32 mono 16 kHz** (cohérent avec le Bloc 2).

### 3.3 Implémentation macOS — ScreenCaptureKit (helper Swift, validé Phase 0.5)

> **Décision issue du POC Phase 0.5.** Deux approches ont été évaluées :
> 1. **Core Audio taps** (`CATapDescription` + `AudioHardwareCreateProcessTap`, macOS 14.2+) — fonctionne pour les haut-parleurs intégrés et le casque filaire, **mais ne capture pas l'audio Bluetooth** (AirPods). Raison : les périphériques BT utilisent un pipeline audio séparé que le tap global n'intercepte pas. **Abandonné.**
> 2. **ScreenCaptureKit** (macOS 13+) — capture au-dessus du pipeline de routage, donc **device-agnostic** (built-in, AirPods, USB, tout). **Retenu.**

- **API : ScreenCaptureKit**, `SCStream` avec `capturesAudio = true`, macOS **13.0+**.
- **Principe** : un **petit binaire Swift compilé** (`SCKAudioCapture.swift`, embarqué dans le bundle) qui :
  1. crée un `SCContentFilter` sur le display principal (toutes les applis),
  2. configure `SCStreamConfiguration` audio-only (48 kHz stéréo, vidéo réduite au minimum),
  3. intercepte les callbacks audio (`SCStreamOutput`) et **écrit du PCM float32 interleaved sur stdout**.
- L'adaptateur Python lance ce binaire en **subprocess**, lit stdout en continu, remplit le buffer.
- **Permission : « Enregistrement de l'écran »** (`Screen Recording`, clé `NSScreenCaptureUsageDescription` dans l'`Info.plist`). Prompt déclenché au **premier démarrage du mode Réunion**, attaché au bundle `.app` (cf. Bloc 4). En **développement non packagé**, accorder la permission au terminal (iTerm2, Terminal.app…).
- **Micro séparé** : SCK capture uniquement le flux de **sortie** (participants). Le micro (flux d'entrée = « Moi ») est capturé par `CaptureMicro` (sounddevice) et transcrit séparément — les deux flux sont **mixés avant envoi à Whisper** (cf. §3.1).
- **macOS 13.0 minimum** (disponibilité SCK audio). La cible de déploiement reste 14.4+ pour les autres raisons (cf. Bloc 4).
- **Démarrage paresseux** : le sous-processus SCK n'est **pas** lancé au `__init__` de l'adaptateur. Il est démarré à la demande au premier appel à `demarrer()`. Cela évite que l'indicateur système « Enregistrement de l'écran » apparaisse en permanence dans la barre de menu dès le lancement de l'app.
- **`arreter()` termine le processus** : contrairement à une simple pause (commande STOP), `arreter()` envoie QUIT et tue le sous-processus. L'indicateur d'enregistrement disparaît immédiatement à la fin de chaque réunion. Le prochain `demarrer()` recrée le processus transparentement.

### 3.4 Implémentation Windows — WASAPI loopback

- Capture du **périphérique de sortie en mode loopback** via **WASAPI**, exposé par **`sounddevice`/PortAudio** (`sd.WasapiSettings(loopback=True)` sur le périphérique de sortie par défaut). → on reste sur **la même lib que le micro**, pas de dépendance supplémentaire.
- Alternative si limites PortAudio : lib `soundcard` (loopback WASAPI natif). À confirmer à l'implémentation.
- **Aucune permission spéciale** sous Windows.

### 3.5 Implémentation Linux — PipeWire

- Cible **PipeWire uniquement** (décision §8 fonctionnel ; PulseAudio repoussé).
- Capture du **moniteur du sink par défaut** (`<sink>.monitor`). Deux voies possibles :
  1. Via **`sounddevice`/PortAudio** : la source *monitor* apparaît comme un périphérique d'entrée → même mécanisme que le micro (préféré pour l'uniformité).
  2. Repli : **`pw-record`** (ou `parec` via pipewire-pulse) en **subprocess** vers un pipe, si la voie PortAudio est instable selon la distro.
- Détection du sink par défaut et de sa source monitor au démarrage du mode.

### 3.6 Détection & permissions (résumé)

| OS | Mécanisme | Permission | Demandée quand |
|---|---|---|---|
| macOS **13.0+** | ScreenCaptureKit (helper Swift) | **« Enregistrement de l'écran »** (`NSScreenCaptureUsageDescription`) | 1ʳᵉ Réunion |
| Windows | WASAPI loopback (sounddevice) | Aucune | — |
| Linux | Moniteur PipeWire | Accès session PipeWire (généralement OK) | — |

- `disponible()` renvoie `False` si la plateforme ne peut pas capturer (helper absent, permission refusée, pas de monitor) → l'UI réagit en conséquence (3.7).

### 3.7 Robustesse & dégradation

- **Permission refusée / capture système indisponible** : on **ne bloque pas la réunion**. Comportement proposé :
  - Notification claire (« audio système indisponible — voir permissions »).
  - **Repli micro-seul** : la réunion continue, le `.md` ne contient que les prises **« Moi »**, avec une mention en tête de fichier indiquant que l'audio système était indisponible.
- **Périphérique de sortie changé en cours de réunion** (casque branché/débranché) : tenter de re-souscrire au nouveau monitor/loopback ; si échec, repli micro-seul + notification, **sans perdre le fichier**.
- Toute erreur de capture est **loggée** (§17.2 fonctionnel) sans interrompre l'écriture du `.md`.

### 3.8 Limite connue : écho en haut-parleurs

- Si l'utilisateur écoute la visio sur **haut-parleurs** (pas au casque), le **micro capte aussi les participants** → risque de doublon (« Moi » contient la voix des participants).
- Limite **inhérente** (déjà présente dans l'existant). Recommandation produit : **utiliser un casque**. Mention possible dans la doc utilisateur. Pas de traitement d'annulation d'écho en v1.

### 3.9 Décisions de ce bloc (à valider)

1. **Deux buffers séparés** (micro = « Moi », système = « Participants »), transcrits indépendamment par tranche. ✅/❓
2. **macOS** : helper Swift **ScreenCaptureKit** (macOS 13+), permission **« Enregistrement de l'écran »**. Validé en Phase 0.5 : fonctionne avec tous les périphériques (intégré, AirPods, USB). Core Audio taps évalué et abandonné (échec Bluetooth). ✅
3. **Windows** : WASAPI loopback via `sounddevice` (même lib que le micro), sans permission. ✅/❓
4. **Linux** : moniteur PipeWire via `sounddevice` (repli `pw-record`). ✅/❓
5. **Repli micro-seul** si l'audio système est indisponible (réunion non bloquée, mention dans le `.md`). ✅/❓
6. **Pas d'annulation d'écho** en v1 ; reco casque documentée. ✅/❓

---

## Bloc 4 — Structure du projet, configuration, logs, packaging

### 4.1 Arborescence du projet

```
debriefMeet/
├── pyproject.toml              # métadonnées, dépendances (extras par OS), point d'entrée
├── README.md
├── docs/                       # specs (ce dossier)
├── src/debrief_meet/
│   ├── __main__.py             # point d'entrée : CLI, instance unique, bootstrap, injection
│   ├── core/                   # MÉTIER PARTAGÉ — aucune dépendance OS / Qt
│   │   ├── modes.py            # Mode (machine à états, un seul actif) + EtatVisuel (état d'activité → couleur icône)
│   │   ├── dictee.py           # orchestration Dictée
│   │   ├── reunion.py          # orchestration Réunion (2 flux, tranches, écriture incrémentale, durée)
│   │   ├── journal.py          # orchestration Journal
│   │   ├── fichiers.py         # écriture des .md (formats §12) + métadonnées titre/durée (docs 14)
│   │   ├── audio.py            # buffers thread-safe, rééchantillonnage 16 kHz mono, normaliser_asr
│   │   ├── aec.py              # annulation d'écho (ProcesseurAEC, LiveKit AEC3) — docs 06
│   │   ├── transcription_differee.py  # (ré)écrit le .md d'une réunion « audio seul » — docs 10
│   │   ├── diarization.py      # « qui a parlé » (pyannote) + onboarding modèle gated — docs 07/13
│   │   ├── prompts.py          # modèles de prompt, préfixe à la copie — docs 12
│   │   ├── config.py           # chargement/sauvegarde des préférences
│   │   ├── logs.py             # journalisation (§17.2 fonctionnel)
│   │   └── modeles.py          # résolution nom logique → repo par moteur
│   ├── ui/                     # PYSIDE6 — partagé
│   │   ├── tray.py             # icône + menu + grisage exclusif + definir_etat_visuel()
│   │   ├── icones.py           # rendu carré arrondi+onde par EtatVisuel (REPOS=template) ; icône .app ; glyphes Tabler
│   │   ├── preferences.py      # onglets Modèle/Audio/Dossiers/Prompts/Général/Journalisation
│   │   ├── historique.py       # listing + colonne d'actions + titre éditable/durée — docs 09/14
│   │   ├── gestionnaire_diarization.py  # jobs de fond persistants (transcription/diarization)
│   │   ├── assistant_diarization.py     # assistant guidé d'activation diarization — docs 13
│   │   ├── chargeur_modele.py  # téléchargement + (re)chargement modèle à chaud — docs 15
│   │   ├── apropos.py
│   │   └── assets/             # tabler-icons.ttf, AppIcon.icns, diar_etape_{1..5}.svg
│   └── platform/               # ADAPTATEURS — 1 sous-dossier par OS
│       ├── interfaces.py       # ABC : MoteurTranscription, CaptureMicro, CaptureAudioSysteme,
│       │                       #       PressePapiers, DemarrageAuto, (RaccourcisGlobaux: v2)
│       ├── factory.py          # détection OS + matériel → instancie les adaptateurs
│       ├── commun/             # CaptureMicro (sounddevice) partagé
│       ├── macos/              # moteur mlx, tap audio, pbcopy, LaunchAgent
│       ├── windows/            # faster-whisper, WASAPI loopback, clipboard, autostart
│       └── linux/              # faster-whisper, monitor PipeWire, clipboard, systemd
├── helpers/macos/sck-audio/        # helper ScreenCaptureKit (validé Phase 0.5, embarqué au build)
│   └── SCKAudioCapture.swift
└── packaging/
    ├── macos/                  # Info.plist, entitlements, script .dmg
    ├── windows/                # script installeur (Inno Setup / MSI)
    └── linux/                  # AppImage / .desktop / unit systemd
```

### 4.2 Configuration (préférences persistées)

- **Format : JSON** (zéro dépendance — `json` stdlib ; les préférences sont gérées par l'UI, pas éditées à la main). *(TOML possible si on veut un fichier lisible/éditable, au prix d'une petite dépendance d'écriture.)*
- **Emplacement : via `platformdirs`** (résout proprement les conventions par OS) :
  - macOS : `~/Library/Application Support/debriefMeet/config.json`
  - Windows : `%APPDATA%\debriefMeet\config.json`
  - Linux : `~/.config/debriefMeet/config.json`
- **Premier lancement** : fichier absent → valeurs par défaut (modèle `large-v3`, dossiers `~/reunions` et `~/activites_quotidiennes`, langue auto, autostart off, logs off, intervalle 30 s).
- **Migrations** : un champ `version` dans le fichier pour gérer l'évolution du schéma.
- Contenu typique : modèle choisi, périphérique micro, dossiers de sortie, langue (auto/forcée), intervalle réunion, autostart, logs on/off, notifications on/off.

### 4.3 Logs (cf. §17.2 fonctionnel)

- **Module `core/logs.py`** basé sur `logging` stdlib + `RotatingFileHandler` (rotation par taille, ex. 1–2 Mo, 1–2 backups).
- **Emplacement : `platformdirs` user log/cache** :
  - macOS : `~/Library/Logs/debriefMeet/debriefMeet.log`
  - Windows : `%LOCALAPPDATA%\debriefMeet\logs\`
  - Linux : `~/.local/state/debriefMeet/` (ou `~/.cache/debriefMeet/logs/`)
- **Désactivés par défaut** ; activables dans les préférences. Boutons « Ouvrir le fichier » / « Vider ».
- **Jamais de contenu transcrit ni d'audio** dans les logs (métadonnées + erreurs seulement).

### 4.4 Cache des modèles

- mlx-whisper & faster-whisper : cache **Hugging Face** (`~/.cache/huggingface/hub`) — géré par les libs.
- whisper.cpp (v2) : `ggml-*.bin` dans `platformdirs` user cache (`.../debriefMeet/models/`).
- Les préférences agrègent l'espace des deux emplacements et permettent la suppression (§10.1 fonctionnel).

### 4.5 Démarrage automatique au login (impl. par OS — interface `DemarrageAuto`)

| OS | Mécanisme | Détail |
|---|---|---|
| macOS | **LaunchAgent** | Écrire/supprimer `~/Library/LaunchAgents/<bundle-id>.plist`, pointant sur l'exécutable du bundle. |
| Windows | **Clé Run du Registre** (`HKCU\...\Run`) | Plus simple et fiable que le Planificateur ; valeur ajoutée/retirée selon la préférence. |
| Linux | **systemd `--user`** | Générer/activer une unit `debriefMeet.service` (`systemctl --user enable/disable`). |

- Opt-in (désactivé par défaut). Activer/désactiver depuis les préférences = écrire/retirer proprement l'entrée.

### 4.5bis Détection du changement de périphérique audio (Phase 3.5)

**Problème :** en cours de réunion, le périphérique d'entrée par défaut peut changer (retrait des AirPods → bascule sur le micro intégré). Le flux ouvert ne suit pas → micro muet jusqu'à la fin (la capture système SCK, elle, est device-agnostic et n'est pas affectée).

**Décision retenue : Qt Multimedia — `QMediaDevices.audioInputsChanged`.** Signal événementiel **instantané** (pas de polling), intégré à la boucle Qt, **cross-platform** (une seule implémentation pour macOS/Windows/Linux, dans `platform/commun/`), **aucune dépendance ajoutée** (inclus dans PySide6). Anti-rebond de 300 ms pour absorber les rafales d'événements. Reprise par **redémarrage à chaud** du flux micro (`CaptureMicro.redemarrer`) avec préservation du buffer ; on retente l'index préféré (rebascule si l'AirPod revient), sinon repli défaut. **Périmètre : mode Réunion.**

**Angle mort assumé :** `audioInputsChanged` ne se déclenche pas sur un changement de *défaut* sans changement de *liste* (ex. deux micros restent branchés et l'utilisateur change le défaut dans les Réglages) — cas marginal, non couvert en v1.

**Alternatives écartées (traçabilité — réévaluables) :**

| Option | Pourquoi écartée | Quand reconsidérer |
|---|---|---|
| **CoreAudio natif (ctypes)** — listener sur `kAudioHardwarePropertyDefaultInputDevice` | macOS-only (réimpl. Windows/Linux) ; ~100 lignes de ctypes fragiles | Si l'angle mort ci-dessus devient bloquant. Aucune dépendance à ajouter. |
| **PyObjC** — même cible CoreAudio, bindings typés | macOS-only **+** grosse dépendance (`pyobjc`, hooks PyInstaller) qu'aucun autre module n'utilise | Si PyObjC est adopté ailleurs et mutualisable. |

> Détail complet : `04-plan-detection-peripherique-audio.md`.

### 4.6 Interface en ligne de commande (CLI)

L'essentiel des réglages passe par l'UI, mais on conserve une CLI minimale (utile pour les raccourcis OS et le diagnostic) :

| Commande | Effet |
|---|---|
| `--toggle` | Bascule Dictée (via IPC instance unique ; démarre l'app si absente) |
| `--toggle-journal` | Bascule Journal |
| `--toggle-reunion` | Bascule Réunion |
| `--list-devices` | Liste les périphériques audio puis quitte |
| `--version` | Affiche la version |

> Plus de `--model` / `--device` / `--output` en usage courant (remplacés par les préférences) ; éventuellement gardés comme overrides ponctuels de debug.

### 4.7 Packaging & distribution par OS

**Objectif :** un livrable **installable sans venv ni Python préinstallé** — on **embarque le runtime Python** et les dépendances. C'est l'amélioration majeure vs l'existant.

- **Outil recommandé : PyInstaller** (+ outillage installeur par OS). Raison : on a des **dépendances natives lourdes** (libs CUDA, Metal/mlx, binaire Swift embarqué) que PyInstaller gère avec plus de contrôle que Briefcase. *(Briefcase reste une alternative si on préfère ses installeurs clés-en-main.)*

| OS | Build | Installeur | Spécificités |
|---|---|---|---|
| **macOS** | PyInstaller → `.app` | `.dmg` | Embarquer le **helper Swift compilé** ; `Info.plist` avec `NSMicrophoneUsageDescription` + **`NSAudioCaptureUsageDescription`** ; cible **arm64** (14.4+). **Signature : voir posture v1 ci-dessous.** |
| **Windows** | PyInstaller → dossier/`.exe` | **Inno Setup** ou **MSI** | Embarquer les **DLL CUDA** (cuBLAS/cuDNN) pour faster-whisper GPU. **Non signé en v1** → SmartScreen « Exécuter quand même ». |
| **Linux** | PyInstaller | **AppImage** (portable) + `.desktop` | Fournir l'**unit systemd** pour l'autostart ; dépendances PipeWire présentes sur la cible. Pas de signature requise. |

- **Dépendances par extra** (dans `pyproject.toml`) : `mlx-whisper` seulement pour le build macOS ; `faster-whisper` pour tous ; on ne bundle pas ce qui est inutile à l'OS.

#### Posture signature/distribution — v1 (usage perso, pas de certificats payants)

- **Décision v1 :** usage personnel, **pas de compte Apple Developer ni de certificat Windows** ; **pas d'auto-update** (re-téléchargement manuel).
- **macOS — astuce importante :** même sans compte Apple Developer, signer le `.app` avec un **certificat auto-signé local stable** (créé une fois dans le trousseau). Pourquoi : les permissions TCC (micro, **capture audio**) s'attachent à l'identité de signature ; une identité **stable** évite que la permission audio **se redemande à chaque rebuild/mise à jour**. Un `.app` **ad-hoc** (`codesign -s -`) change d'identité à chaque build → re-prompts pénibles. → **Self-sign stable recommandé même en perso.** Gatekeeper se contourne au premier lancement (clic droit → Ouvrir), à documenter.
- **Windows :** non signé ; « Exécuter quand même » au premier lancement, à documenter.
- **Évolutif :** la structure `packaging/` est conçue pour **brancher signature Developer ID + notarisation (macOS) et Authenticode (Windows) plus tard sans refonte**, si BlueMind décide de distribuer (les moyens de signature restent à vérifier côté BlueMind).

### 4.8 Dépendances principales (récap)

| Domaine | Lib |
|---|---|
| UI | **PySide6** |
| Capture micro / loopback Windows | **sounddevice** (PortAudio) |
| Rééchantillonnage | **scipy** ou **soxr** |
| Moteur macOS | **mlx-whisper** |
| Moteur NVIDIA/CPU | **faster-whisper** |
| Téléchargement modèles | **huggingface_hub** (tiré par les moteurs) |
| Emplacements OS | **platformdirs** |
| Helper audio macOS | binaire **Swift** (Core Audio taps), compilé au build |

### 4.9 Décisions de ce bloc (à valider)

1. **Structure cœur/ui/platform** avec `src/debrief_meet/` et adaptateurs par OS. ✅/❓
2. **Config JSON via `platformdirs`** (TOML en option), avec champ `version` pour migrations. ✅/❓
3. **Logs `logging` + rotation** dans l'emplacement standard par OS. ✅/❓
4. **Autostart** : LaunchAgent (macOS) / clé Run Registre (Windows) / systemd user (Linux). ✅/❓
5. **CLI réduite** aux toggles + `--list-devices` + `--version`. ✅/❓
6. **Packaging PyInstaller** + installeurs par OS (.dmg / Inno-MSI / AppImage), **Python embarqué**. ✅/❓
7. **Signature/distribution — TRANCHÉ (v1 = usage perso)** : pas de certificats payants, pas d'auto-update. macOS **auto-signé stable** (pour la stabilité de la permission audio) ; Windows non signé ; structure `packaging/` prête à brancher notarisation/Authenticode plus tard. ✅

---

## Bloc 5 — Stratégie de tests, qualité & livrables par phase

> **Exigence :** tout code livré l'est **avec ses tests unitaires**, **rejouables à tout moment** par une seule commande. **Chaque phase produit un livrable testé (tests verts) ET testable manuellement par l'utilisateur.**

### 5.1 Ce qui rend l'app testable : l'architecture en couches

Le cœur métier ne dépend que des **interfaces** (Bloc 1). En test, on injecte des **faux adaptateurs** à la place des implémentations OS :

| Interface | Faux (test) — comportement |
|---|---|
| `MoteurTranscription` | `MoteurFake` : renvoie un texte/segments **prédéfinis**, sans modèle ni GPU |
| `CaptureMicro` | `MicroFake` : rejoue un **WAV fixture** ou un buffer en mémoire |
| `CaptureAudioSysteme` | `SystemeFake` : idem, + simulation « indisponible » pour tester le repli micro-seul |
| `PressePapiers` | `PressePapiersFake` : mémorise le dernier texte « copié » (assertions) |
| `DemarrageAuto` | `AutostartFake` : état en mémoire |

→ **Toute la logique métier se teste sans matériel ni permission**, sur n'importe quel OS, en quelques secondes.

### 5.2 Pyramide de tests

1. **Tests unitaires** (majorité, rapides, sans matériel) — cœur métier :
   - Machine à états des modes (un seul mode actif ; toggles ; refus si un autre mode tourne).
   - Écriture des `.md` : **formats exacts** Réunion/Journal (§12 fonctionnel) — en-tête, horodatage, append, étiquetage `Moi`/`Participants`, repli micro-seul.
   - `config.py` : valeurs par défaut, chargement/sauvegarde, **migration de schéma** (champ `version`).
   - `modeles.py` : **résolution nom logique → artefact** par moteur, détection « déjà téléchargé ».
   - `logs.py` : activation/désactivation, **absence de contenu transcrit** dans les logs, rotation.
   - `audio.py` : rééchantillonnage vers 16 kHz mono, gestion des buffers.
   - Flux complets via faux adaptateurs : *Dictée* (record→transcrit→presse-papiers), *Journal* (append entrée), *Réunion* (2 flux→tranches→fichier).
2. **Tests UI** (ciblés) avec **`pytest-qt`** : le menu tray reflète l'état, signaux émis, fenêtres Préférences/Historique se peuplent.
3. **Tests d'intégration** (marqués, **optionnels selon l'environnement**) : vrai moteur sur un **WAV fixture court**, vrai presse-papiers, détection matérielle. Marqués `@pytest.mark.integration` / `requires_audio` / `requires_gpu` pour être **désactivables** là où le matériel/permission manque.

### 5.3 Outils & commande unique

- **`pytest`** + **`pytest-qt`** (UI) + **`pytest-cov`** (couverture).
- **Une seule commande pour tout rejouer** : `pytest` (ou un raccourci `make test` / script `scripts/test`). Les tests lents/matériels s'excluent via marqueurs (`pytest -m "not integration"`).
- **Fixtures** : petits fichiers WAV de référence (phrases connues) dans `tests/fixtures/`.
- **Objectif de couverture** sur le **cœur métier** (pas l'UI ni les adaptateurs OS) : élevé et significatif (cible indicative ~80 %+ du `core/`).

### 5.4 Organisation des tests

État implémenté en Phase 0 (layout **plat**, suffisant tant que le nombre de fichiers reste modeste) :

```
tests/
├── conftest.py            # fixtures + injection des faux adaptateurs
├── fakes/adapters.py      # MoteurFake, MicroFake, SystemeFake, PressePapiersFake, DemarrageAutoFake
├── test_config.py         # défauts, save/load, JSON invalide, migration
├── test_logs.py           # on/off, niveaux, rotation, pas d'écriture si désactivé
├── test_modes.py          # machine à états : exclusivité, toggles, signaux (pytest-qt)
└── test_icones.py         # rendu par EtatVisuel, REPOS=template, couleurs distinctes (pytest-qt)
```

Cible à mesure que la suite grossit (regroupement par nature — à introduire quand utile, sans dogmatisme) :

```
tests/
├── conftest.py · fakes/   # fixtures + faux adaptateurs
├── unit/                  # cœur métier (modes, fichiers, config, modeles, logs, audio)
├── ui/                    # pytest-qt (tray, icônes, fenêtres)
├── integration/           # marqués, matériel réel (optionnels)
└── fixtures/              # WAV de référence, exemples .md attendus
```

### 5.5 Définition de « terminé » (Definition of Done) — par phase

Chaque phase n'est **livrée** que si **tout** ce qui suit est vrai :

1. **Code** de la phase implémenté selon les specs.
2. **Tests unitaires** correspondants **écrits ET exécutés par l'agent avant livraison** : `pytest -m "not integration"` est **réellement lancé**, **tous verts**, et la **sortie est rapportée** dans la livraison. Un test rouge ⇒ on corrige avant de livrer ; **on ne livre jamais une phase avec des tests en échec**.
3. **Pas de régression** : toute la suite unitaire des phases précédentes est **relancée** et reste verte.
4. **Livrable exécutable** : l'app (ou l'incrément) **se lance réellement** et la fonctionnalité de la phase est **utilisable de bout en bout**.
5. **Notice de test manuel** : un court « **Comment tester** » (étapes concrètes) pour que **tu** valides la phase à la main — surtout pour ce que les tests auto ne couvrent pas (vrai micro, vraie visio, permissions, rendu UI).
6. **Tests d'intégration** de la phase exécutés **là où c'est possible** (sur ta machine), résultats rapportés.

> Conséquence sur le **découpage en phases** (doc suivant) : chaque phase est une **tranche verticale qui tourne**, pas une couche horizontale inerte. Ex. la Phase « socle » livre déjà une app lançable avec un mode minimal testable ; on ne livre jamais « juste des interfaces » non exécutables.

### 5.6 (Plus tard) Intégration continue

- Hors v1 perso, mais prévu : un workflow **CI** (ex. GitHub Actions) lançant `pytest -m "not integration"` sur les 3 OS à chaque modification. La structure de tests est déjà compatible (pas de matériel requis pour l'unitaire).

### 5.7 Décisions de ce bloc (à valider)

1. **Faux adaptateurs** injectés via les interfaces → cœur métier testé **sans matériel**. ✅/❓
2. **pytest (+ pytest-qt, pytest-cov)**, une **commande unique** rejouable, marqueurs pour les tests matériels. ✅/❓
3. **Definition of Done par phase** : code + tests verts + livrable exécutable + notice « Comment tester ». ✅/❓
4. **Phases = tranches verticales exécutables** (jamais des couches inertes). ✅/❓
5. **CI multi-OS** prévue mais **hors v1**. ✅/❓

---

## Bloc 6 — Environnement de développement & procédures de build

> **Objectif :** permettre à n'importe quel développeur (ou à une IA) de reprendre le projet et de l'exécuter **sans aide extérieure**, à partir du seul clone du dépôt.

### 6.1 Prérequis

| Outil | Version min | Comment l'installer |
|---|---|---|
| **Python** | 3.11 | Homebrew : `brew install python` / python.org |
| **Xcode Command Line Tools** (macOS) | SDK macOS 14+ | `xcode-select --install` |
| **make** | n'importe | inclus avec Xcode CLT sur macOS |

> Sur macOS, tout le reste (venv, deps Python, helpers Swift) est installé **automatiquement** par les scripts ci-dessous.

### 6.2 Premier démarrage — de zéro à l'app qui tourne

```bash
# 1. Cloner le dépôt
git clone <url> debriefMeet && cd debriefMeet

# 2. Installation complète (venv + deps + helpers Swift + tests)
bash scripts/setup.sh

# 3. Lancer l'app
make run
```

`scripts/setup.sh` vérifie les prérequis, crée `.venv/`, installe les dépendances selon l'OS, compile les helpers Swift, et lance les tests unitaires pour confirmer que tout est en ordre.

### 6.3 Commandes quotidiennes

| Commande | Effet |
|---|---|
| `make setup` | Installation/réinstallation complète |
| `make test` | Tests unitaires rapides — **sans matériel**, ~5 s |
| `make test-all` | Tous les tests (y compris `integration`) |
| `make build-helpers` | Recompiler les helpers Swift uniquement |
| `make run` | Lancer debriefMeet depuis le venv |
| `make clean` | Supprimer `.venv/` et tous les artefacts |

> `make test` est la commande à lancer après chaque modification de code. Elle exclut les tests marqués `integration` (qui nécessitent un vrai micro ou la permission Screen Recording).

### 6.4 Structure des scripts de build

```
debriefMeet/
├── Makefile                          # point d'entrée principal (toutes les commandes)
├── scripts/
│   └── setup.sh                      # installation complète avec vérification prérequis
└── helpers/macos/
    └── poc-audio-tap/
        └── build.sh                  # compilation + signature du helper SCK
```

- **`Makefile`** — orchestrateur ; appelle les scripts sous-jacents. C'est le seul fichier à connaître.
- **`scripts/setup.sh`** — script d'installation détaillé, avec couleurs et messages d'erreur explicites. Accepte `--deps-only` pour être appelé par le Makefile sans relancer les tests.
- **`helpers/macos/poc-audio-tap/build.sh`** — compile `SCKAudioPOC.swift` avec `swiftc` + signature ad-hoc. À lancer séparément si seul le helper change.

### 6.5 Permissions macOS (une fois par machine)

Deux permissions système sont requises, accordées **une seule fois** dans Réglages Système → Confidentialité et sécurité :

| Permission | Pour quoi | Quand demandée |
|---|---|---|
| **Microphone** | Mode Dictée, Réunion | Au premier enregistrement |
| **Enregistrement de l'écran** | Mode Réunion (capture audio système via SCK) | Au premier démarrage du mode Réunion |

**En développement (app non packagée)** : la permission "Enregistrement de l'écran" doit être accordée au **terminal** (Terminal.app, iTerm2…), pas à l'app elle-même. Aller dans Réglages Système → Enregistrement de l'écran → activer le terminal utilisé.

**En production (`.app` packagé)** : la permission s'attache au bundle signé et **persiste entre les mises à jour** si la signature reste stable (cf. §4.7 — signature auto-signée stable recommandée).

### 6.6 Rebuild des helpers Swift

Les helpers Swift sont des **binaires pré-compilés** embarqués dans le projet. Ils ne se recompilent pas automatiquement à chaque `make test` — seulement si leur source est modifiée.

```bash
# Recompiler après modification de SCKAudioPOC.swift
make build-helpers

# Ou directement :
bash helpers/macos/poc-audio-tap/build.sh
```

Le binaire compilé (`SCKAudioPOC`) est versionné dans le dépôt pour éviter d'imposer Xcode à tous les contributeurs qui ne modifient que le Python.

### 6.7 Dépannage courant

| Problème | Cause probable | Solution |
|---|---|---|
| `python3: command not found` | Python non installé | `brew install python` |
| `xcrun: error: …` | Xcode CLT manquant | `xcode-select --install` |
| `ModuleNotFoundError: PySide6` | Venv non activé / setup non fait | `make setup` |
| Tests pytest échouent sur l'import | Installation incomplète | `make clean && make setup` |
| `[ERREUR] Stream arrêté` (SCK) | Permission "Enregistrement de l'écran" refusée | Réglages Système → Enregistrement de l'écran → activer le terminal |
| `swiftc: error: …` lors du build | SDK macOS trop ancien | Mettre à jour Xcode CLT : `softwareupdate --all --install` |
