# debriefMeet

Transcription de réunions, dictée et journal vocal — application de bureau pour
**macOS, Windows et Linux**, écrite en Python + PySide6 (Qt 6).

Elle enregistre deux pistes séparées pendant une visio (votre micro, le son des
participants), puis produit une transcription et un compte-rendu. Deux modes de
transcription, choisis dans les Préférences :

| Mode | Transcription | Compte-rendu | Ce qu'il faut |
|---|---|---|---|
| **Distant** (défaut) | API Mistral (Voxtral) | API Mistral | une clé API Mistral |
| **Local** | Whisper embarqué (mlx sur Apple Silicon, faster-whisper CPU sur Windows) + diarization « qui a parlé » (pyannote) | API Mistral | ~1,5 Go de modèle téléchargé au 1ᵉʳ lancement, un token Hugging Face pour la diarization |

Le mode Local ajoute la **Dictée** (vers le presse-papiers) et le **Journal** (une note
vocale par jour). Linux ne propose que le mode Distant en v1.

Autres fonctions : association d'une réunion à un événement du **calendrier BlueMind**
(titre, participants, biais de transcription), **lexique** de corrections « entendu →
à écrire » injecté dans les prompts, copie du compte-rendu **mise en forme** pour un
collage dans un éditeur riche (CRM, webmail), raccourcis globaux (macOS, Windows),
export de diagnostic (zip de logs, secrets caviardés).

Les fichiers vivent hors de l'app, dans `~/Documents/debriefMeet/` : un dossier par
réunion (`transcription.md`, `moi.opus`, `systeme.opus`, `CR.md`…) et un fichier par
jour pour le journal.

---

## Installer l'application (utilisateurs)

Les binaires sont produits par la CI GitHub Actions ([doc 52](docs/52-ci-github-actions.md)) :
sur une **Release** (tag `v*`), ou dans les **artefacts** d'un run lancé à la demande
(onglet Actions, conservés 30 jours).

| OS | Fichier | Installation |
|---|---|---|
| macOS 14.4+ (Apple Silicon) | `debriefMeet-<version>.dmg` | glisser dans Applications, puis voir « Premier lancement » ci-dessous |
| Windows 10/11 x64 | `debriefMeet-setup-<version>.exe` | double-cliquer ; met à jour une version existante en place |
| Ubuntu 26.04 amd64 | `debriefmeet_<version>_amd64.deb` | `sudo apt install ./debriefmeet_<version>_amd64.deb` (installe `ffmpeg` et les dépendances) |

Pas de mise à jour automatique : on réinstalle le nouveau fichier par-dessus. La
config et les réunions sont conservées.

### macOS — premier lancement d'un `.dmg` téléchargé

macOS affiche *« debriefMeet n'a pas pu être ouvert, Apple n'a pas pu vérifier qu'il ne
contient aucun logiciel malveillant »* et propose de le mettre à la corbeille.
**Ne pas le jeter** : l'app est signée avec le certificat local du projet, pas
notarisée par Apple, et macOS met en quarantaine tout fichier venu d'Internet. Un
build fait sur la machine n'a pas ce marquage, c'est pourquoi il se lance directement.

Pour autoriser l'app, une seule fois :

1. Dans la boîte de dialogue, cliquer **Terminé** (pas « Placer dans la corbeille »).
2. Ouvrir **Réglages Système → Confidentialité et sécurité**.
3. Descendre jusqu'à la ligne *« debriefMeet a été bloqué pour protéger votre Mac »*
   et cliquer **Ouvrir quand même**, puis confirmer avec le mot de passe de session.
4. Relancer debriefMeet depuis le dossier Applications.

Depuis macOS 15, le clic droit → **Ouvrir** ne suffit plus. Alternative en terminal :

```bash
xattr -dr com.apple.quarantine /Applications/debriefMeet.app
```

### macOS — permissions (une fois par machine)

- **Microphone** — demandé au premier enregistrement.
- **Enregistrement de l'écran** — demandé au premier mode Réunion (capture de l'audio
  des participants via ScreenCaptureKit).

Tous les builds, locaux comme CI, portent la **même identité de signature** : les
permissions accordées restent valables d'une version à l'autre
([doc 16](docs/16-packaging-macos.md), [doc 52 §6](docs/52-ci-github-actions.md)).

---

## Développer

### Prérequis

| Outil | Pourquoi | Installation |
|---|---|---|
| Python 3.11+ (3.14 en dev) | l'app | `brew install python` / python.org / `apt install python3-venv` |
| ffmpeg | encodage Opus, compaction et découpage audio (en dev : celui du système ; embarqué dans l'app livrée sur macOS et Windows) | `brew install ffmpeg` / `apt install ffmpeg` |
| Xcode Command Line Tools (macOS) | compiler le helper Swift de capture ScreenCaptureKit | `xcode-select --install` |
| make | les commandes ci-dessous | inclus avec Xcode CLT / `build-essential` |

### Installation

```bash
git clone https://github.com/sylvaing/debriefMeet.git
cd debriefMeet
make setup      # venv .venv + dépendances (extras selon l'OS) + helper Swift sur macOS
make test       # ~1 700 tests sans matériel, ~50 s
make run        # lancer l'app
```

`DEBRIEFMEET_MODE=local make run` ou `=distant` force le mode de transcription sans
toucher à la config.

### Commandes

```bash
make setup          # Installer l'environnement
make test           # Tests rapides (sans matériel)
make test-all       # Tous les tests, y compris ceux marqués `integration` (vrai micro, visio)
make run            # Lancer debriefMeet
make build-helpers  # Recompiler le helper Swift SCKAudioCapture (macOS)
make build-app      # Packaging macOS : dist/debriefMeet.app signé (ffmpeg LGPL compilé au 1ᵉʳ appel)
make dmg            # Packaging macOS : dist/debriefMeet-<version>.dmg
make clean          # Supprimer le venv et les artefacts
```

Les tests Qt tournent en `QT_QPA_PLATFORM=offscreen`. `make test` peut se terminer par
un `Segmentation fault` **après** le rapport pytest : c'est un défaut connu de
PySide6 au teardown de l'interpréteur, sans rapport avec le résultat des tests.

### Produire les binaires

| Cible | Où | Commande | Détails |
|---|---|---|---|
| macOS `.dmg` | en local, sur un Mac Apple Silicon | `make dmg` | nécessite `.venv-build` en Python **3.13** (PyInstaller ne supporte pas 3.14) et le certificat local « debriefMeet Local », créé une fois par `packaging/creer_certificat.sh` — [doc 16](docs/16-packaging-macos.md) |
| macOS `.dmg` | GitHub Actions | tag `v*`, ou `gh workflow run build.yml --ref main -f macos=true` | même identité de signature via les secrets du dépôt — [doc 52](docs/52-ci-github-actions.md) |
| Windows `.exe` | GitHub Actions | tag `v*`, ou `gh workflow run build.yml --ref main` | `packaging/windows/build_app.cmd` (PyInstaller + Inno Setup) — [doc 32](docs/32-phase5-packaging-cycle-de-vie.md) |
| Windows `.exe` | VM Windows locale, par SSH | `bash scripts/build_app_windows_vm.sh` | même script, build natif sur la VM — [doc 32](docs/32-phase5-packaging-cycle-de-vie.md), fumée : `scripts/fumee_setup_vm.sh` |
| Linux `.deb` | GitHub Actions | tag `v*`, ou `gh workflow run build.yml --ref main` | conteneur `ubuntu:26.04`, `packaging/linux/build_app.sh` — [doc 49](docs/49-portage-linux-ubuntu.md) |
| Linux `.deb` | conteneur LXC local, par SSH | `bash scripts/build_app_linux_lxc.sh` | fumée : `scripts/fumee_deb_lxc.sh` |

Chaque build rejoue la suite de tests et **refuse de produire un binaire si elle est
rouge**. Le tag d'une release doit être égal à la version déclarée dans
`pyproject.toml` et `src/debrief_meet/__init__.py`.

---

## Benchmark machine

Outil indépendant de l'app pour savoir si une machine cible fait tourner la
transcription locale, et dans quel mode (CPU int8, iGPU…). Il rejoue le pipeline
réel sur un audio de ~30 min et produit un seul `.zip` à transmettre. L'audio de
référence n'est **pas** versionné (enregistrements réels) : il faut fournir le sien,
cf. [doc 08](docs/08-benchmark.md) § « Audio de test ».

```bash
python -m benchmark.assembler_bundle --os windows --token hf_xxx   # assemble le bundle depuis le Mac
# côté utilisateur : dézipper, double-cliquer lancer.bat, renvoyer le zip de rapport
```

---

## Structure du projet

```
debriefMeet/
├── src/debrief_meet/
│   ├── core/              # logique métier pure : config, modes, réunions, Mistral, BlueMind, lexique
│   ├── ui/                # PySide6 : tray, fenêtre, Historique, Préférences, assistants
│   └── platform/          # interfaces + un adaptateur par OS (macos/, windows/, linux/)
├── helpers/macos/sck-audio/   # helper Swift de capture ScreenCaptureKit
├── packaging/             # PyInstaller : spec macOS, windows/ (Inno Setup), linux/ (.deb), ffmpeg LGPL
├── scripts/               # setup, builds distants (VM Windows, LXC Ubuntu), fumées
├── .github/workflows/     # CI : build.yml (tag v* ou à la demande)
├── benchmark/             # outil de benchmark cross-platform
├── spike/                 # explorations isolées (AEC, backends Windows, diarization, Mistral, Linux)
├── tests/                 # suite pytest
└── docs/                  # spécifications et journaux de chantier, numérotés
```

Règle d'architecture : `core/` n'importe jamais de module propre à un OS ; tout passe
par les interfaces de `platform/interfaces.py`.

---

## Documentation

Les docs sont numérotées dans l'ordre des chantiers. Points d'entrée :

| Sujet | Doc |
|---|---|
| Ce que fait l'app (modes, UI, formats de fichiers) | [01](docs/01-specifications-fonctionnelles.md) |
| Architecture, stack, choix par OS | [02](docs/02-specifications-techniques.md) |
| Phases et définition de « terminé » | [03](docs/03-phases-implementation.md) |
| Packaging macOS, certificat, ffmpeg embarqué | [16](docs/16-packaging-macos.md) |
| Portage Windows (chapeau [30](docs/30-phase5-architecture-windows.md), packaging [32](docs/32-phase5-packaging-cycle-de-vie.md), adaptateurs [34](docs/34-phase5-adaptateurs-windows.md)) | 30 → 37 |
| Interco calendrier BlueMind | [40](docs/40-interco-bluemind.md) |
| Interco Mistral : transcription Voxtral, compte-rendu, pannes terrain | [42](docs/42-mistral-api-cr.md) |
| Stockage : un dossier par réunion | [43](docs/43-organisation-reunions-dossiers.md) |
| Mode de transcription distant / local | [45](docs/45-mode-transcription-unifie.md) |
| Lexique de corrections | [46](docs/46-lexique-corrections.md) |
| Annulation d'écho et dédoublonnage des pistes | [48](docs/48-aec-continu-dedoublonnage.md) |
| Portage Linux Ubuntu | [49](docs/49-portage-linux-ubuntu.md) |
| Copie du compte-rendu mise en forme | [51](docs/51-copie-cr-mise-en-forme.md) |
| CI GitHub Actions | [52](docs/52-ci-github-actions.md) |

`CLAUDE.md` à la racine résume l'état du projet et ses pièges, chantier par chantier.

---

## Confidentialité

Aucun enregistrement, aucune transcription réelle, aucune donnée client n'entre dans
le dépôt (`.gitignore`). Les prénoms d'utilisateurs cités dans les docs et les tests
sont des pseudonymes. Le lexique par défaut est vide : le vocabulaire d'une
organisation se saisit dans les Préférences, jamais dans le code.

---

## Dépannage

| Problème | Solution |
|---|---|
| `python3: command not found` | installer Python 3.11+ (`brew install python`) |
| `xcrun: error: …` ou erreur de compilation Swift | `xcode-select --install`, puis `softwareupdate --all --install` |
| `ModuleNotFoundError: PySide6` | `make clean && make setup` |
| Mode Réunion silencieux en dev (macOS) | accorder « Enregistrement de l'écran » au **terminal** utilisé (Réglages Système → Confidentialité et sécurité) |
| « ffmpeg requis … mais introuvable » | installer ffmpeg (`brew install ffmpeg` / `apt install ffmpeg`) ; l'app livrée l'embarque sur macOS et Windows |
| Transcription ou CR Mistral en échec | Préférences → IA en ligne → « Tester la connexion » ; le verdict est aussi dans le log |
| Téléchargement au premier lancement en mode Local | le modèle Whisper (~1 Go) se télécharge une seule fois, avec une fenêtre de progression |
| `pip` refuse PySide6 6.12 | voulu : la borne `<6.12` évite un segfault de Qt Multimedia sans serveur audio ([doc 52](docs/52-ci-github-actions.md)) |
| Envoyer un diagnostic | Préférences → Journalisation → « Exporter les logs (.zip)… » (clés et tokens caviardés) |
