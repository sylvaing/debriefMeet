# Phase 6 — Portage Linux (Ubuntu 26.04 LTS)

> **Statut : 📝 SPEC à implémenter** (rédigée le 2026-08-10, décisions arbitrées avec
> Sylvain le 2026-08-10). Doc unique — le périmètre v1 (mode distant seul, sans
> raccourcis globaux) est assez réduit pour ne pas justifier l'éclatement en 6 docs
> comme la Phase 5 Windows (docs/30→35). À exécuter dans l'ordre du §8.

---

## 1. Contexte et contrainte structurante

Cible : **un collègue BlueMind sur portable x86_64, en production** — même situation
que la Phase 5 Windows : le développeur est sur macOS, l'utilisateur est le banc de
test final, **les logs sont le seul canal de debug**.

Environnements :

| Rôle | Machine | Arch |
|------|---------|------|
| Dev quotidien | Mac (worktree habituel) + éventuellement VM UTM Ubuntu arm64 pour la validation graphique intermédiaire | arm64 |
| **Build + gate pytest + fumée** | **Conteneur LXC Ubuntu 26.04 sur le Proxmox** (à provisionner, cf. §6) | **amd64** |
| Validation finale + prod | Portable du collègue | amd64 |

⚠️ **L'architecture du builder = l'architecture du livrable** (PyInstaller ne
cross-compile pas). Un build UTM arm64 sert au dev, jamais à la livraison. De même,
le binaire est lié à la glibc du builder : LXC 26.04 → livrable pour 26.04 (et plus
récent), pas pour des Ubuntu antérieures — assumé, la cible est unique.

## 2. Décisions arbitrées (2026-08-10)

| # | Décision | Détail |
|---|----------|--------|
| L1 | **v1 = mode distant seul** | Opus + API Mistral (transcription Voxtral + CR), comme le défaut de l'app depuis docs/45. Pas de moteur local, pas de pyannote, pas de téléchargement de modèles. Le mode local (faster-whisper CPU, mutualisation du worker Windows) est prévu par l'architecture (§4.3) mais **hors périmètre v1**. |
| L2 | **Pas de raccourcis globaux en v1** | Ubuntu 26.04 = GNOME Wayland par défaut, où `XGrabKey` est mort ; la voie propre (portail XDG `org.freedesktop.portal.GlobalShortcuts`) est reportée. `RaccourcisStub` reste en place. Perte faible : en mode distant, dictée/journal sont déjà désactivés — seul le toggle réunion perd son raccourci, le tray suffit. |
| L3 | **Packaging `.deb` amd64** | PyInstaller onedir + `dpkg-deb`. Permet `Depends: ffmpeg` → **tout le chantier ffmpeg embarqué disparaît** (pas d'équivalent docs/41). Installation/désinstallation propres via apt. AppImage = plan B si multi-distro un jour ; Snap/Flatpak écartés (leur sandbox bride précisément ce dont on a besoin : sources `.monitor`, `~/Documents`, autostart). |
| L4 | **Build dans un LXC Ubuntu 26.04 amd64 sur le Proxmox** | Même mécanique que la VM Windows : tar over ssh, pytest bloquant (`QT_QPA_PLATFORM=offscreen`), build, rapatriement du `.deb`. Script `scripts/build_app_linux_lxc.sh` miroir de `build_app_windows_vm.sh`. La fumée SSH est plus simple que sur Windows (`dpkg -i`, `--version`, réinstall, `apt purge`) et **sans la limite `usPostUninstall`** de docs/37. |
| L5 | **Logs DEBUG par défaut sur Linux** | Même décision que Windows (docs/31 D5) et pour la même raison : utilisateur distant, logs = seul canal. macOS reste off par défaut. |
| L6 | **Désinstallation** | `apt remove` supprime l'app (`/opt/debriefmeet`). Config/logs (XDG) et `~/Documents/debriefMeet` ne sont **jamais** dans le paquet, donc jamais touchés par dpkg — le nettoyage config/logs est documenté dans la notice (pas de `postrm purge` agressif en v1). |

## 3. Périmètre fonctionnel v1 Linux

- **Réunion (enregistrement Opus 2 pistes + AEC)** ✅ — micro commun + capture
  système `.monitor` PipeWire
- **Transcription + CR via API Mistral** ✅ — `core/mistral/`, aucun code OS
- **Interco BlueMind** ✅ — `core/bluemind/`, aucun code OS (`tzdata` : présent
  d'office sur Ubuntu, le piège Windows de docs/44 est sans objet)
- **Lexique, prompts, historique, préférences, export diagnostic** ✅ — core/UI purs
- **Dictée / Journal** ❌ — désactivés par le mode distant (docs/45), rien à faire
- **Transcription locale + diarization** ❌ hors v1 (L1)
- **Raccourcis globaux** ❌ hors v1 (L2)
- **Démarrage automatique** ✅ — `.desktop` dans `~/.config/autostart/`

## 4. Architecture cible

### 4.1 Règle d'or (inchangée)

`core/` n'importe jamais de module OS-spécifique. Toute dépendance plateforme passe
par `platform/interfaces.py`. La branche `_linux()` de `platform/factory.py`
(aujourd'hui 100 % stubs) est remplie avec la même discipline que `_windows()` :
**repli stub loggé en WARNING avec l'exception d'origine, jamais un silence**
(docs/34 §0 — seul canal de debug une fois livré).

### 4.2 Arborescence à créer

```
src/debrief_meet/platform/linux/
├── __init__.py
├── capture_systeme_monitor.py  # CaptureAudioSysteme — source .monitor PipeWire (§5.1)
├── presse_papiers.py           # PressePapiers — QClipboard (copie de windows/)
├── demarrage_auto.py           # DemarrageAuto — ~/.config/autostart/debriefmeet.desktop
└── infos_systeme.py            # si besoin : RAM /proc/meminfo, distro, session
                                #   Wayland/X11, version PipeWire (sinon étendre
                                #   platform/infos_systeme.py directement)
```

Modules **réutilisés tels quels** :

- `platform/commun/micro_sounddevice.py` — PortAudio parle à PipeWire via la couche
  pulse ; porte déjà docs/20 (16 kHz constant) et docs/25 (hot-plug).
- `platform/commun/surveillant_peripheriques.py` — Qt Multimedia, cross-platform ;
  le filtre anti-parasites est déjà gaté `win32` (défaut False ailleurs).
- `ipc.py` — QLocalServer/QLocalSocket, cross-platform. **Pas de mutex** : le mutex
  nommé est un ajout Windows-only (consommé par Inno Setup) ; sous Linux le
  QLocalServer suffit, comme sur macOS.
- `core/redemarrage.py` — la branche non-win32 (`sh -c "sleep 1; exec …"`,
  `start_new_session=True`) est déjà correcte pour Linux.
- Les branches `xdg-open` existent déjà dans `journal_view`, `reunion_view`,
  `preferences_view`, `export_diagnostic` (`else` final des conditionnels OS).

### 4.3 Prévu mais hors v1 (mode local, v1.1)

Le worker `platform/windows/moteur_faster_whisper.py` + `_fw_worker.py` est
essentiellement portable (subprocess + faster-whisper CPU). Le jour du mode local
Linux : **remonter ces deux fichiers dans `platform/commun/`** et les référencer
depuis `_windows()` et `_linux()` — pas de copie. En v1, `_linux()` garde
`moteur=None` en distant (comportement docs/45) et `MoteurStub()` si un utilisateur
force `mode_transcription: local` (l'UI Préférences reste honnête : la transcription
locale ne marchera pas, comme aujourd'hui).

## 5. Spécification des adaptateurs

### 5.1 Capture système — `capture_systeme_monitor.py` (le seul vrai chantier)

Sous PipeWire (serveur audio d'Ubuntu depuis 22.10), chaque périphérique de sortie
expose une source moniteur (`<sink>.monitor`) **visible de PortAudio via la couche
pulse** → `sounddevice` suffit, pas besoin de la lib `soundcard` ni d'API PipeWire
native. Stratégie transposée de Windows (docs/34 §2.3) :

1. À `demarrer()` : résoudre le périphérique de sortie par défaut, ouvrir un
   `InputStream` sur sa source `.monitor` (48 kHz, stéréo downmixée — même contrat
   que WASAPI).
2. Surveiller le périphérique de sortie par défaut (changement casque/HDMI/BT) :
   réouverture à chaud sur le nouveau moniteur, **repli silence** (zéros au bon
   taux) pendant la coupure — l'horloge de la piste système ne doit jamais
   s'arrêter (contrat AEC/fusion, docs/48).
3. Journaliser chaque bascule et chaque repli (L5 : les logs racontent la réunion).

Résolution du nom du moniteur : par défaut PortAudio/pulse expose une entrée
« Monitor of <sink> » ; sinon interroger `pactl get-default-sink` (paquet
`pulseaudio-utils`, à mettre en `Depends`) — tranché par le **spike préalable**
ci-dessous, pas à l'aveugle pendant l'implémentation.

**Spike préalable — `spike/capture_monitor_linux/`** (règle du dépôt : exploration
isolée, aucune dépendance à l'app ni à `benchmark/`). Un script Python autonome
(`sonde_monitor.py`) lancé par `lancer.sh`, qui produit des **logs horodatés + WAVs**
à inspecter après coup :

1. **Inventaire** : liste des périphériques PortAudio (nom, canaux, taux) avec
   repérage des sources moniteur, croisée avec `pactl get-default-sink` /
   `pactl list short sinks`.
2. **Capture** : N secondes simultanées micro + moniteur du sink par défaut pendant
   qu'un son connu joue (`paplay` d'un WAV de référence) → 2 fichiers WAV + RMS
   loggé par tranche (le moniteur ne doit pas être silencieux).
3. **Bascule à chaud** : le script continue de capturer pendant qu'on change la
   sortie par défaut (casque USB/BT branché/débranché) et logge ce que devient le
   flux (erreur PortAudio ? silence ? suit tout seul ?) — c'est la réponse qui
   dimensionne la logique de réouverture à chaud de l'adaptateur.

**Le spike est un protocole guidé, pas un script muet.** Les phases 2 et 3
dépendent d'actions manuelles de l'utilisateur : le script les annonce
explicitement à l'écran, une à la fois (« ▶ Lance une musique sur la sortie par
défaut, puis Entrée », « ▶ Branche le casque USB maintenant, puis Entrée », « ▶
Reviens sur les haut-parleurs internes… »), attend la confirmation avant de
poursuivre, et **écrit chaque action confirmée comme un marqueur horodaté dans le
log** (`[ACTION 14:32:07] casque USB branché`). Sans ces marqueurs, impossible de
corréler après coup un silence ou une erreur PortAudio avec ce que l'humain venait
de faire. `lancer.sh` s'exécute sans argument et termine en rappelant où sont les
fichiers produits (log + WAVs) et quoi renvoyer pour analyse.

Questions auxquelles le spike doit répondre avant d'écrire `capture_systeme_monitor.py` :
nom exact et stabilité des entrées moniteur vues de PortAudio sur 26.04 ; `pactl`
nécessaire ou non (⇒ `Depends: pulseaudio-utils` ou pas) ; taux natif rendu ;
comportement au changement de sortie ; mono/stéréo (le downmix WASAPI
s'applique-t-il ?). Il tourne sur n'importe quelle Ubuntu 26.04 graphique — UTM
arm64 compris (comportement PipeWire indépendant de l'arch), poste amd64 pour
confirmer.

**Point d'attention docs/48** : micro et moniteur sont horlogés par le même démon
PipeWire — le décalage inter-pistes et la dérive devraient être plus sains que sur
Mac/Windows. Les mécanismes docs/48 (ré-estimation périodique du délai, log de
l'offset d'ingestion) restent actifs et diront la vérité ; ne rien désactiver.

### 5.2 Presse-papiers — `presse_papiers.py`

QClipboard (copie de l'implémentation Windows). Piège Linux classique neutralisé
par la nature de l'app : le contenu du presse-papiers appartient à l'app qui l'a
posé — comme debriefMeet est résidente en tray, le contenu survit. Wayland comme
X11 passent par Qt, rien de spécifique.

### 5.3 Démarrage auto — `demarrage_auto.py`

Fichier `~/.config/autostart/debriefmeet.desktop` (`Type=Application`,
`Exec=/opt/debriefmeet/debriefMeet`, `X-GNOME-Autostart-enabled=true`).
`est_active()` = le fichier existe ; `activer()`/`desactiver()` = créer/supprimer.
Trivial et testable sans OS réel (chemin injectable).

### 5.4 Tray, notifications, fenêtres — validation, pas de code attendu

- **Tray** : QSystemTrayIcon → protocole StatusNotifier ; Ubuntu GNOME active
  l'extension AppIndicator par défaut. ⚠️ GNOME ne distingue pas clic gauche/droit
  sur un indicateur : **tout doit être atteignable par le menu** — vérifier qu'aucune
  action ne repose sur `activated`/clic gauche seul.
- **Notifications** : `QSystemTrayIcon.showMessage` passe par les notifications
  GNOME via le portail — à vérifier visuellement, repli D-Bus `Notify` si besoin.
- **Wayland** : pas de positionnement global de fenêtres (sans impact connu),
  session X11 également supportée via le plugin Qt xcb.

### 5.5 Retouches hors `platform/`

- **`core/fichiers.chemin_ffmpeg()`** : en app figée, la branche non-Windows renvoie
  `vendor/ffmpeg` (macOS). Ajouter le cas Linux → `shutil.which("ffmpeg")` (garanti
  par `Depends: ffmpeg`). Une app lancée depuis GNOME a un PATH standard
  (`/usr/bin`), le piège « PATH minimal » de macOS/Windows ne s'applique pas.
- **`core/logs.py`** : étendre « DEBUG par défaut » à Linux (L5, aujourd'hui gaté
  Windows).
- **`platform/infos_systeme.py`** : en-tête de logs Linux — distro + version, session
  (`XDG_SESSION_TYPE`), RAM (`/proc/meminfo`), version PipeWire. Réutilisé par
  l'export diagnostic.
- **`ui/export_diagnostic.py`** : vérifier que la collecte couvre les chemins XDG —
  contrairement à Windows, config (`~/.config/debriefMeet`), logs
  (`~/.local/state/debriefMeet/log`) et data ne partagent **pas** une racine unique.
  Le caviardage des secrets (docs/44) est déjà en place, il s'applique tel quel.

## 6. Packaging `.deb` et conteneur de build

### 6.1 Paquet

- **Contenu** : PyInstaller onedir → `/opt/debriefmeet/`, lanceur
  `/usr/bin/debriefmeet` (symlink), `/usr/share/applications/debriefmeet.desktop`,
  icônes hicolor. Versionnement identique aux autres OS
  (`0.2.0+AAAAMMJJ.hashgit` — le `+` est valide en version deb).
- **`Depends`** : `ffmpeg`, `pulseaudio-utils` (si `pactl` retenu en §5.1), plus le
  minimum Qt que le bundle PySide6 ne couvre pas (typiquement `libxcb-cursor0` ;
  liste exacte à figer au premier build en testant sur un conteneur nu).
- **Spec** : `packaging/linux/debriefMeet.spec` (dérivé du spec Windows, sans la
  section ffmpeg embarqué) + `packaging/linux/build_deb.sh` (arbre `DEBIAN/control`
  + `dpkg-deb --build`). `TestSpecLinux` miroir de `TestSpecWindows`.
- **MAJ** : réinstallation par-dessus (`dpkg -i` gère nativement l'upgrade) —
  cohérent avec « pas d'auto-update v1 ».

### 6.2 Conteneur LXC (à provisionner une fois)

- Ubuntu 26.04 amd64, SSH activé, utilisateur dédié (même philosophie d'accès que
  la VM Windows). Conteneur non privilégié standard — un build Python n'a besoin
  d'aucun nesting.
- **Python 3.13 obligatoire** (PyInstaller ne supporte pas 3.14) : paquet
  `python3.13` de l'archive si présent, sinon PPA deadsnakes — à constater au
  provisionnement.
- Paquets de build : `binutils` (requis par PyInstaller sur Linux), `git`.
- Paquets pour la gate pytest offscreen (deps runtime de PySide6 même sans écran) :
  `libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1` + ce que le premier
  `pytest` réclamera — figer la liste dans le script de provisionnement.
- **Gate pytest bloquante avant build** : `QT_QPA_PLATFORM=offscreen pytest -m "not
  integration"`. Compte attendu à établir au premier run vert et à consigner dans
  CLAUDE.md (les échecs d'environnement connus : helper Swift, audio canonique).

### 6.3 Scripts (miroirs de l'existant Windows)

- `scripts/build_app_linux_lxc.sh` — tar over ssh, gate pytest, PyInstaller,
  `build_deb.sh`, rapatriement de `dist/debriefmeet_<version>_amd64.deb`. Session
  SSH gardée ouverte pendant le build (même piège que la VM Windows).
- `scripts/fumee_deb_lxc.sh` — dans le conteneur : `dpkg -i` (+ `apt-get -f install`
  pour les Depends), `debriefmeet --version`, réinstall par-dessus, `apt purge`,
  vérification que `/opt/debriefmeet` a disparu. Rejouable.

## 7. Transposition des correctifs macOS/Windows (filtre docs/33)

La plupart des exigences E-1→E-8 de docs/33 tombent d'elles-mêmes en v1 distante :
pas de moteur local → pas de workers MLX/faster-whisper à arrêter (docs/26), pas de
diarization (docs/29), pas de dictée/journal muets (docs/27). Restent applicables :

| Correctif | Transposition Linux |
|-----------|--------------------|
| docs/20/25 — micro 16 kHz + hot-plug | Hérité de `commun/` — **à valider** sous PipeWire (débrancher/rebrancher un casque USB/BT en cours de réunion) |
| docs/48 — AEC/décalage inter-pistes | Mécanismes actifs tels quels ; lire les logs de la première vraie réunion (offset d'ingestion, dérive) avant de conclure |
| docs/44 — caviardage secrets dans l'export diagnostic | Cross-platform, s'applique tel quel |
| docs/45 — garde IPC `--toggle*` en mode distant | Cross-platform, s'applique tel quel |

## 8. Ordre d'exécution

1. **Provisionner le LXC** (§6.2) + **gate pytest verte** en offscreen — c'est le
   smoke test de l'archi en couches ; consigner le compte attendu. Aucun code app
   à ce stade, seulement d'éventuels correctifs de tests non gardés (hypothèses
   macOS/Windows implicites, comme docs/44 en avait révélé 2).
2. **Spike `spike/capture_monitor_linux/`** (§5.1) sur une Ubuntu 26.04 graphique
   (UTM arm64 suffit) — parallélisable avec l'étape 1 (le LXC est headless, le
   spike a besoin d'une session audio). Sortie : réponses aux 5 questions du §5.1,
   consignées dans ce doc avant d'attaquer l'adaptateur.
3. **Adaptateurs triviaux + retouches §5.5** : `presse_papiers`, `demarrage_auto`,
   `chemin_ffmpeg`, logs DEBUG, `infos_systeme` — et remplir `_linux()` dans la
   fabrique (schéma `_windows()` : WARNING + stub). Livrable : app lancée en mode
   distant sur un poste Linux graphique, réunion **micro seul** fonctionnelle de
   bout en bout (enregistrement → Voxtral → CR).
4. **Capture système `.monitor`** (§5.1, informée par le spike) + validation réunion
   complète 2 pistes sur machine graphique réelle (UTM arm64 acceptable pour itérer,
   poste amd64 pour conclure). Vérifs tray/notifications (§5.4) au passage.
5. **Packaging** : spec + `build_deb.sh` + `build_app_linux_lxc.sh` + fumée SSH.
6. **Livraison** : notice utilisateur (install `dpkg -i`/`apt install ./…`, où sont
   les données, comment exporter un diagnostic — miroir allégé de docs/35),
   installation chez le collègue, première réunion réelle, lecture des logs.

## 9. Tests et Definition of Done

- Nouveaux tests unitaires : `test_demarrage_auto_linux.py` (chemin injecté),
  `test_capture_systeme_monitor.py` (sounddevice mocké : sélection du moniteur,
  bascule à chaud, repli silence), `test_presse_papiers_linux.py`,
  `TestSpecLinux`, extension `test_export_diagnostic` (chemins XDG).
- Gate LXC : compte pytest consigné, 0 échec hors environnement.
- Fumée `.deb` : 0 échec, rejouable.
- DoD v1 : une réunion réelle 2 pistes chez le collègue → transcription Voxtral +
  CR Mistral corrects, logs propres (pas de tempête de reconnexions, offset
  docs/48 dans les clous), désinstallation/réinstallation sans perte de données.

## 10. Risques et points ouverts

| Risque | Parade |
|--------|--------|
| Nom/visibilité de la source `.monitor` via PortAudio variable selon la config PipeWire | Spike `spike/capture_monitor_linux/` (§5.1, étape 2 du §8) avant toute ligne d'adaptateur ; repli `pactl` |
| Tray absent si l'extension AppIndicator est désactivée sur le poste cible | Vérifier au déploiement ; documenter dans la notice (`gnome-extensions enable ubuntu-appindicators…`) |
| Casque Bluetooth : bascule de profil A2DP↔HFP quand le micro BT est utilisé (le monitor change de format) | Même famille que les cas BT Windows (docs/34 §2.3) : réouverture à chaud + logs ; recommander micro filaire/intégré en premier déploiement |
| Python 3.13 non packagé dans l'archive 26.04 | PPA deadsnakes (constat au provisionnement) |
| Liste `Depends` Qt incomplète → app qui ne démarre pas sur un poste nu | La fumée LXC part d'un conteneur sans deps de dev ; compléter `Depends` jusqu'à `--version` vert |
