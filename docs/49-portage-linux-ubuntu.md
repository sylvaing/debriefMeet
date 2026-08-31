# Phase 6 — Portage Linux (Ubuntu 26.04 LTS)

> **Statut : ✅ IMPLÉMENTÉ et VALIDÉ SUR LE TERRAIN** (spec rédigée le 2026-08-10,
> livraison validée chez l'utilisateur cible le 2026-08-13, fusionné dans `main`).
> Doc unique — le périmètre v1 (mode distant seul, sans raccourcis globaux) est assez
> réduit pour ne pas justifier l'éclatement en 6 docs comme la Phase 5 Windows
> (docs/30→35). Ordre d'exécution suivi : §8. Reste hors périmètre v1 : notice
> utilisateur, raccourcis globaux (portail XDG), mode local (§4.3).

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
| L7 | **Python système (3.14), sans PPA tiers** | Arbitré le 2026-08-10 après vérification sur le conteneur : la contrainte historique « PyInstaller ne supporte pas 3.14 » (qui a valu leur 3.13 aux chaînes macOS/Windows) **a expiré** — PyInstaller 6.22 accepte 3.14, et PySide6 est distribué en roue `cp310-abi3` donc compatible par construction. Le builder utilise donc `python3` d'Ubuntu 26.04 (3.14.4), ce qui **retire le PPA deadsnakes de la chaîne de build** : une source tierce en moins, interpréteur maintenu par la distro. macOS et Windows restent en 3.13 pour l'instant ; leur alignement est un chantier distinct, à faire d'un bloc et à valider par un vrai build sur chaque chaîne. |
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

**Spécification arrêtée après le spike** (les 3 passages ont mesuré chaque point ;
justifications détaillées dans « Résultats » ci-dessous) :

1. À `demarrer()` : résoudre la sortie par défaut avec **`pactl get-default-sink`**,
   en déduire le moniteur `<sink>.monitor`, et l'ouvrir parmi les périphériques
   d'entrée du **hostapi PulseAudio** (48 kHz, stéréo → downmix mono, même contrat
   que WASAPI). Si la résolution échoue, **journaliser en WARNING** — ne jamais
   retomber silencieusement sur « le premier moniteur venu » : sur le poste testé,
   ce repli aurait capturé une sortie HDMI inactive.
2. **Rafraîchir la table PortAudio** (`sd._terminate()` / `sd._initialize()`) avant
   toute (ré)ouverture : elle est figée à l'initialisation, donc le moniteur d'une
   sortie apparue en cours de réunion est sinon invisible (même piège que docs/25,
   déjà traité dans `micro_sounddevice.py`).
3. **Surveiller la sortie par défaut** en cours d'enregistrement (sondage `pactl` ou
   abonnement `pactl subscribe`) : à tout changement, rouvrir sur le nouveau
   moniteur. Indispensable — quand le son part ailleurs, le flux continue de livrer
   des **zéros parfaits**, indiscernables d'une réunion calme.
4. **Chien de garde sur l'arrivée des trames** : plus aucune trame pendant N ms ⇒
   flux mort (sink détruit), rouvrir. **Ne jamais se fier à `stream.active`**, qui
   reste `True` sur un flux gelé, ni attendre une exception ou un statut PortAudio :
   il n'en vient aucun.
5. **Repli silence** pendant toute coupure ou réouverture, à hauteur du temps
   réellement écoulé : l'horloge de la piste système ne doit jamais s'arrêter, sans
   quoi les deux pistes se décalent exactement de la durée de la panne (contrat
   AEC/fusion, docs/48).
6. Journaliser chaque bascule, chaque réouverture et chaque repli (L5 : les logs
   racontent la réunion).

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

#### Résultats du premier passage terrain (2026-08-12, poste Ubuntu du collègue)

Machine : Ubuntu, **Wayland/GNOME**, PipeWire, carte `sof-hda-dsp`, 4 sorties
(HDMI1/2/3 + Headphones), sortie par défaut **HDMI1**.

| Q | Réponse | Conséquence |
|---|---------|-------------|
| **Q1** ✅ | **4 sources `.monitor` visibles de PortAudio**, mais **uniquement sous le hostapi `PulseAudio`** (index 2) — pas sous ALSA. Noms techniques exacts : `alsa_output.<carte>.HiFi__HDMI1__sink.monitor`, jamais « Monitor of… ». | L'adaptateur **filtre sur le hostapi PulseAudio** et sur le suffixe `.monitor`. `soundcard` et l'API PipeWire native sont inutiles. |
| **Q2** ✅ | **`pactl` est nécessaire.** La sortie par défaut vue de PortAudio est `[9] 'default'` — un périphérique ALSA générique qui n'identifie **aucun** sink. `pactl get-default-sink` rend le nom exact, et le moniteur est **exactement** `<nom-du-sink>.monitor`. | **`Depends: pulseaudio-utils` confirmé.** Le repli « premier moniteur de la liste » aurait choisi HDMI3 sur ce poste, soit une piste système muette : il ne doit **pas** être un repli silencieux. |
| **Q3** ✅ | **2 canaux @ 48 000 Hz** (comme les sinks : `s24-32le 2ch 48000Hz`). | Contrat **identique à WASAPI** — downmix stéréo→mono, pas de rééchantillonnage propre à Linux. |
| **Q5** ✅ | Moniteur : RMS **0,125**, crête 0,68 sur 15 s pendant une vidéo. Micro simultané : RMS 0,169 (crête 0,99997 — micro proche de la saturation, à surveiller côté AEC). | La voie `.monitor` est validée. |
| **Q4** ✅ | Tranchée au second passage (2026-08-12 18:24, 798 s d'un seul tenant sur le moniteur de HDMI1, **jamais rouvert**). Voir le déroulé ci-dessous. | Surveillance active obligatoire, mais **aucune** gestion de flux mort. |

**Q4 — le déroulé mesuré** (flux ouvert à 18:25:11, taille du WAV exactement conforme
à 798 s ⇒ aucune interruption) :

| Fenêtre | Durée | Ce que rend le moniteur |
|---------|-------|-------------------------|
| 18:25:11 → 18:25:35 | 24 s | **Audible**, RMS 0,104 — le son joue sur HDMI1 |
| 18:25:35 → 18:38:15 | **760 s** | **Silence numérique parfait, 100 % d'échantillons nuls** — le son est parti sur le casque Bluetooth, HDMI1 passe `IDLE` |
| 18:38:19 → 18:38:29 | 10 s | **Audible à nouveau**, RMS 0,109 — le casque a été déconnecté, le son revient sur HDMI1 |

Trois conclusions, toutes actionnables :

1. **Le flux ne meurt jamais.** Il a survécu 13 minutes, dont un sink Bluetooth
   apparu puis disparu, sans une seule erreur ni un seul statut PortAudio.
2. **Il se « répare » tout seul** : le son est revenu sur le même flux, sans
   réouverture, dès que la sortie par défaut est redevenue HDMI1 — et **5 secondes
   avant** que l'utilisateur ne confirme l'action, ce qui exclut toute intervention
   du script. Un moniteur reste donc valide tant que son sink existe, même resté
   inactif un quart d'heure.
3. **Mais rien ne signale la bascule.** Pendant 760 s, le flux a rendu des zéros
   parfaits : indiscernable d'une réunion réellement silencieuse. L'adaptateur **ne
   peut pas** détecter le problème depuis l'audio.

Confirmé une seconde fois au troisième passage (2026-08-13, trace continue cette
fois) : 15 s audible → **260 s de silence** → 15 s audible, sur un flux jamais
rouvert.

⇒ **Surveiller activement la sortie par défaut** (`pactl get-default-sink`, ou
l'abonnement `pactl subscribe`) et rouvrir sur le nouveau moniteur. Tant que le sink
existe, aucune réouverture n'est nécessaire pour la *santé* du flux — c'est le
*choix* du moniteur qui devient obsolète, pas le flux. **Mais ce raisonnement ne vaut
que si le sink existe encore : voir Q6, qui impose un chien de garde.**

#### Q6 — le sink surveillé DISPARAÎT (phase 4, automatique, 2026-08-13)

Sink virtuel créé, moniteur ouvert, sink **détruit** sous le flux, puis 10 s
d'observation :

```
Avant destruction : 4440 rappels, 142080 trames, actif=True
+1s … +10s        : 4440 rappels,  142080 trames, actif=True, incidents=0
```

**Le flux gèle en silence.** Plus une seule trame en 10 secondes, **`stream.active`
reste `True`**, aucun statut PortAudio, aucune exception — et la fermeture se passe
sans erreur. C'est un comportement **radicalement différent** de Q4 :

| Cas | Le sink | Ce que fait le flux | Comment le détecter |
|-----|---------|---------------------|---------------------|
| Le son part ailleurs (Q4) | reste présent, passe `IDLE` | continue de livrer des **zéros** | `pactl` — le silence est indiscernable d'une réunion calme |
| **Le sink disparaît (Q6)** | **détruit** | **plus aucune trame**, gel total | **chien de garde sur l'arrivée des trames** |

Trois exigences pour l'adaptateur, dont deux que Q4 seule aurait fait manquer :

1. **`stream.active` n'est pas un indicateur de santé** — il valait `True` sur un flux
   mort. Ne jamais s'en servir.
2. **Chien de garde sur l'arrivée des trames** : aucune trame pendant N ms en cours
   d'enregistrement ⇒ le flux est mort, rouvrir sur le moniteur de la sortie par
   défaut courante. C'est le seul signal disponible : ni exception, ni statut.
3. **Combler le trou par du silence.** Pendant le gel, la piste système cesse
   d'avancer alors que la piste micro continue : sans rembourrage à hauteur du temps
   réellement écoulé, les deux pistes se décalent **exactement de la durée de la
   panne**. C'est précisément l'alignement inter-pistes que docs/48 s'emploie à
   maîtriser — le repli silence de docs/34 §2.3 (Windows) s'applique donc tel quel.

Le scénario est loin d'être théorique : c'est celui du casque Bluetooth qui se
déconnecte en pleine réunion, batterie vide ou sortie de portée — la piste système
gèlerait sans un mot dans les logs.

**Piège supplémentaire, trouvé au passage : PortAudio fige sa table de périphériques
à l'initialisation.** Le moniteur d'une sortie apparue *après* le démarrage (casque
BT allumé en cours de réunion) est invisible de `query_devices()` tant qu'on n'a pas
fait un cycle `sd._terminate()` / `sd._initialize()`. C'est exactement le piège déjà
rencontré côté micro sur macOS (docs/25) — et `micro_sounddevice.py` fait déjà ce
cycle ; la capture système devra faire de même.

**Le spike est terminé** (3 passages, 2026-08-12 et 13) : les 6 questions sont
tranchées, `capture_systeme_monitor.py` peut être écrit sans zone d'ombre.

> Historique des deux premiers passages, pour mémoire : le premier a été invalidé par
> un malentendu de protocole (« il te faut un casque » compris comme « connecte-le »)
> **et** par un bug du spike (moniteur résolu en phase 1 puis réutilisé 90 s plus
> tard, alors que la sortie par défaut avait changé). Le second par un veilleur qui
> cessait de journaliser après 45 s alors que la phase durait 13 min — la trace des
> transitions a dû être reconstituée depuis le WAV. Les trois sont corrigés.

---

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
- **`Depends`** : `ffmpeg`, **`libportaudio2`**, **`pulseaudio-utils`** (confirmé
  nécessaire par le spike — cf. §5.1 Q2 : sans `pactl`, impossible d'identifier le
  moniteur de la sortie active), plus le minimum Qt que le bundle PySide6 ne couvre
  pas (typiquement `libxcb-cursor0` ; liste exacte à figer au premier build en testant
  sur un conteneur nu).

  ⚠️ **`libportaudio2` n'est pas optionnel et se rate facilement.** Sous Linux,
  `pip install sounddevice` n'installe que le binding Python : la bibliothèque C
  PortAudio est un paquet système (contrairement à macOS/Windows, où la roue
  l'embarque). Son absence lève `OSError: PortAudio library not found` **à l'import**,
  donc avant tout code de l'app. Vécu le 2026-08-11 sur le poste du premier
  utilisateur du spike, sur une Ubuntu de bureau standard — c'est-à-dire exactement
  la machine cible. À vérifier explicitement à la fumée du `.deb` : PyInstaller ne
  garantit pas de collecter cette `.so` système.
- **Spec** : `packaging/linux/debriefMeet.spec` (dérivé du spec Windows, sans la
  section ffmpeg embarqué) + `packaging/linux/build_deb.sh` (arbre `DEBIAN/control`
  + `dpkg-deb --build`). `TestSpecLinux` miroir de `TestSpecWindows`.
- **MAJ** : réinstallation par-dessus (`dpkg -i` gère nativement l'upgrade) —
  cohérent avec « pas d'auto-update v1 ».

### 6.2 Conteneur LXC (à provisionner une fois)

**Provisionné le 2026-08-10** — `192.168.1.32`, root/SSH par mot de passe (a demandé
un `PermitRootLogin yes` : Ubuntu refuse root par mot de passe par défaut). Script
`scripts/provisionner_lxc_ubuntu.sh`, idempotent et rejouable.

- Ubuntu 26.04 LTS amd64, 2 vCPU, 5 Go RAM. Conteneur non privilégié standard — un
  build Python n'a besoin d'aucun nesting.
- **Python système, sans PPA** (décision L7) : `python3` = 3.14.4 d'Ubuntu, plus
  `python3-venv` (absent d'une image LXC minimale — sans lui `python3 -m venv` échoue
  sur « ensurepip is not available »).
- Paquets de build : `binutils` (requis par PyInstaller sur Linux), `dpkg-dev`,
  `fakeroot`, `git`, `rsync`.
- Paquets runtime : `ffmpeg` 8.0.1 (le `Depends` du `.deb`), `pulseaudio-utils`
  (`pactl`, lu par `infos_systeme`), `libportaudio2`, et les deps de PySide6
  nécessaires même en offscreen (`libgl1 libegl1 libxkbcommon0 libdbus-1-3
  libfontconfig1 libxcb-*`).
- **Gate pytest bloquante avant build** — `scripts/gate_pytest_lxc.sh` :
  `QT_QPA_PLATFORM=offscreen pytest -m "not integration"`.
  **Premier run vert le 2026-08-10 : 1141 passed, 21 skipped, 0 échec.**
  Exclusions, toutes pour cause de source non synchronisée (jamais pour masquer un
  échec) : `test_benchmark_*` et `test_spike_backends_*` (outils internes, pas le
  produit), `test_build.py` (à réintégrer avec `TestSpecLinux` quand
  `packaging/linux/` existera). `packaging/` **est** synchronisé —
  `test_generer_version.py` charge `packaging/windows/generer_version.py` par son
  chemin, sans quoi la collecte tombe en erreur.

### 6.3 Ce que la gate a révélé (2026-08-10)

Le premier passage a rendu 7 échecs et 7 erreurs. Aucun n'était un bug de
l'application — tous des hypothèses d'environnement implicites dans les tests, la
famille de trouvailles que la gate existe pour produire (docs/44 en avait révélé 2
sur Windows) :

| Symptôme | Diagnostic | Correctif |
|----------|------------|-----------|
| 7 erreurs de collecte `test_generer_version.py` | `packaging/` n'était pas synchronisé | Synchroniser `packaging/` (hors `vendor/`) |
| 4 erreurs de collecte `test_spike_backends_*` | Liste d'exclusions nominative incomplète (4 modules oubliés) | `--ignore-glob` plutôt qu'une énumération |
| `test_config::test_valeurs_defaut_presentes` | Le test codait « logs ON sur Windows uniquement » ; la décision L5 étend le défaut à Linux | Attendu élargi à Linux |
| 4 tests faisant `import sounddevice` | **L'import lui-même lève** `PortAudioError` sur une machine sans serveur audio — ce n'est pas une `ImportError`, donc `importorskip` ne l'attrape pas | Fixture `sounddevice_dispo` (conftest) qui saute proprement |

Le dernier point méritait une vérification côté application, faite : **l'app est
saine**. Tous ses imports de `sounddevice` sont paresseux (jamais au niveau module) et
`CaptureMicroSounddevice.disponible()` attrape déjà `Exception` — un poste dont le
démon audio n'est pas encore levé (cas réel : démarrage auto en tout début de session
graphique) obtient `False` et le repli, pas un crash. Aucun durcissement n'était
nécessaire ; c'est le genre de conclusion qu'il faut établir plutôt que supposer.

### 6.4 Première panne terrain du `.deb` (2026-08-13) — épuisement des descripteurs

**Symptôme** (premier lancement réel, poste de l'utilisateur cible) : ~35 s après le
début d'une réunion, cascade d'erreurs — `OSError: [Errno 24]` sur les SVG,
`sqlite3.OperationalError: unable to open database file`, `QWaylandShmBuffer:
failed: Too many open files`, tempête de `QPainter` — l'app devient inutilisable.
Toutes ces erreurs sont des **victimes** : les 1024 descripteurs du process (limite
Ubuntu par défaut) étaient épuisés.

**Cause, prouvée par la mesure** (churn isolé sur le conteneur : 8 → 284 fds en
500 appels, puis EMFILE) : `StoreCalendrier._connexion()` rendait une connexion
sqlite jamais fermée explicitement — **le `with` de sqlite3 ne gère que la
transaction, pas la fermeture** — et les connexions participent à des cycles de
références, donc seul le GC générationnel les libérait, par rafales (~270 en
attente en croisière, **3 fds chacune en WAL** : db + `-wal` + `-shm`).

**Pourquoi seulement sur Linux, et seulement en réunion** : la limite soft macOS est
~1 M (le même code fuit sur le Mac — mesuré — sans jamais se voir) ; et pendant
l'enregistrement, la ligne « en cours » de l'Historique s'anime, or ses délégués de
peinture interrogent le store BlueMind **à chaque frame** (`_etat_bluemind_pour` →
`evenements_dans_plage`), soit ~60 connexions/s. 35 s ont suffi.

**Correctif** : `_connexion()` devient un contextmanager qui `close()` en `finally`
(les 11 sites d'appel inchangés) + test de régression qui mesure les fds via
`/dev/fd` avec `gc.disable()` — le filet du GC retiré, la fuite est visible sur
tous les OS ; vérifié rouge sur l'ancien code, et 5 fds constants sur 12 000
opérations après correctif. Les icônes SVG relues à chaque frame ont été mesurées
innocentes (aucun fd).

**Leçon générale** : sur ce dépôt, toute ressource à descripteur (connexion,
fichier, socket) doit être fermée déterministiquement — le ramasse-miettes n'est
pas un mécanisme de fermeture, et macOS ne révélera jamais ce genre de fuite.

**Suite (2026-08-18)** : le test de régression, écrit autour de `os.listdir("/dev/fd")`,
a fait **échouer la gate VM Windows** — ce chemin n'existe pas là-bas, et ni la gate
Mac ni la gate LXC ne pouvaient le voir. Il a été scindé en deux : un test
**portable** qui vérifie l'invariant réel (`sqlite3.connect` tracé, toute connexion
créée doit lever `ProgrammingError` à l'usage, donc être fermée) et un test de
mesure du **symptôme** (comptage de descripteurs) gardé par
`skipif(not os.path.isdir("/dev/fd"))`. Les deux échouent bien sur le code d'avant
correctif. Rappel utile : **une gate verte sur deux OS ne dit rien du troisième**.

### 6.5 Intégration GNOME — 3 défauts d'interface (2026-08-14)

Relevés au premier usage réel, tous **invisibles sur macOS par construction** :

| Symptôme | Cause | Correctif |
|----------|-------|-----------|
| Icône du tray illisible (gris ardoise sur bandeau noir) | `TRAY_IDLE = #3D4351` est un « template » : macOS le **reteint** lui-même via `setIsMask(True)`, ce qui le rend correct en clair comme en sombre. **Sous Linux ce drapeau est ignoré** — la couleur est prise telle quelle. | `TRAY_IDLE_BARRE_SOMBRE = #FFFFFF`, icône **pleine** (un contour blanc de 6 % d'épaisseur reste illisible à 22 px) |
| Aucune action ni au clic gauche ni au clic droit | Le tray passe par **StatusNotifierItem** : l'hôte GNOME n'appelle jamais `Activate`, il affiche le menu **attaché**. Or `_construire_menu` évitait délibérément `setContextMenu()` — indispensable sur macOS, où un menu attaché s'ouvrirait aux deux clics. Résultat sous Linux : `activated` ne part jamais, l'utilisateur n'a accès à **rien**. | `setContextMenu()` sous Linux uniquement ; popup manuel neutralisé là-bas (il ouvrirait un second menu) |
| Fenêtre sans contour, invisible sur fond blanc | Sous Wayland, GNOME impose les décorations côté client et le plugin Qt `adwaita` **ne dessine aucune ombre portée**, contrairement aux applications GTK natives. Fond `#FFFFFF` sur fond blanc ⇒ plus de limite visible. | Liseré 1 px `C.BORDER` sur le widget central — indépendant du plugin de décoration, donc valable Wayland **et** X11 |

**Deux de ces correctifs ont dû être repris (2026-08-18, 2ᵉ passage)** — le premier
essai était vérifié par la feuille de style et non par le rendu :

* **L'icône est devenue un carré blanc uni.** `wavemark_icon` peint les barres en
  **blanc sur le carré coloré** : demander « plein » avec du blanc efface donc la
  marque. Il fallait garder le **contour**, simplement en blanc. Mesuré : 18 % de
  pixels opaques pour le contour contre **92 %** pour un plein — un test compare
  désormais cette proportion, il aurait suffi à l'attraper.
* **Le liseré n'était visible qu'en haut.** Le `border:` était bien posé, mais les
  marges du layout restaient à zéro : les widgets enfants peignaient par-dessus.
  Ajout de `setContentsMargins(1, 1, 1, 1)`, et couleur dédiée `CONTOUR_FENETRE`
  (`#B0B7C0`) — `C.BORDER` (`#E7E9EE`) était trop proche du blanc pour résoudre le
  problème qu'il devait résoudre. Un test relève maintenant la couleur des **quatre
  bords** du rendu.

> Leçon : pour un défaut **visuel**, un test qui lit la feuille de style ne prouve
> rien. Les deux régressions ont été rattrapées en rendant le widget (`grab()`) et en
> comptant des pixels. ⚠️ Rendre **sans `show()`** : une fenêtre laissée visible fait
> entrer un test ultérieur dans une boucle d'événements imbriquée dont il ne ressort
> pas (suite bloquée plus de 10 minutes).

⚠️ **La règle ne se dérive pas de `colorScheme()`.** La tentation serait de choisir la
couleur du tray d'après `QGuiApplication.styleHints().colorScheme()` : ce serait faux,
il rapporte la préférence claire/sombre de l'**application**, alors que le bandeau
supérieur d'Ubuntu est noir **y compris en thème clair**.

**`Depends` complétés** : `libgtk-3-0t64` et `adwaita-icon-theme`. Le bundle embarque
`platformthemes/libqgtk3.so`, qui lie `libgtk-3`/`libgdk-3`/`libgdk_pixbuf` — sans
elles, Qt ignore le thème d'icônes du bureau et le décorateur Wayland ne trouve plus
ses boutons (`Failed to find an svg icon for "window-close-symbolic"` dans le premier
diagnostic terrain). Elles étaient présentes par chance sur le poste cible, pas par
contrat.

**La gate LXC a de nouveau payé** : elle a fait tomber deux tests préexistants
(`test_pas_de_menu_contextuel_qt_attache`, `test_clic_droit_affiche_le_menu`) qui
encodaient la règle macOS comme universelle. Ils épinglent désormais explicitement la
plateforme simulée, plutôt que de dépendre de la machine d'exécution. Les trois
correctifs sont gatés par plateforme et couverts dans les deux sens (Linux **et**
autres), y compris une vérification **par les pixels** que l'icône du REPOS est bien
claire sur bandeau sombre.

#### 6.5.1 Le bandeau système reste sans contour — limite acceptée (2026-08-31)

Signalé par Sylvain sur capture d'écran : **la barre du haut** (titre « debriefMeet »
+ boutons − ▫ ×) n'a, elle, aucun contour — le liseré de §6.5 ne borde que la zone
*client*, 65 px plus bas. Le symptôme est donc identique à celui qu'il corrigeait,
simplement déplacé sur le bandeau.

**Ce n'est pas un oubli, c'est une frontière de code.** Sous Wayland/GNOME ce bandeau
est peint par le plugin de décoration côté client — `libadwaita.so`, embarqué dans le
`.deb` (`_internal/PySide6/Qt/plugins/wayland-decoration-client/`, vérifié sur
`debriefmeet_0.3.0+20260831.4f49d19_amd64.deb`) : il dessine le fond, les coins
arrondis et les boutons, **sans bordure extérieure ni ombre portée**, contrairement à
une application GTK qui peint son ombre dans ses propres marges. Aucune feuille de
style ni aucun `paintEvent` de l'application ne touche cette région : elle est hors du
widget central, donc hors de portée.

Les trois seules sorties, et pourquoi on n'en prend aucune :

| Sortie | Coût | Verdict |
|--------|------|---------|
| `FramelessWindowHint` + barre de titre maison (boutons − ▫ × dans la toolbar existante, `startSystemMove` / `startSystemResize`) | ~150 lignes + hit-testing des bords, validation manuelle du déplacement/redimensionnement | **Écarté** — seul moyen d'obtenir un contour complet, mais on réécrit la gestion de fenêtre pour un défaut cosmétique |
| `QT_QPA_PLATFORM=xcb` (XWayland) : GNOME reprend le cadre et dessine sa vraie bordure + son ombre | une ligne dans le `.desktop` | **Écarté** — on quitterait Wayland natif (flou en échelle fractionnaire, plus de DPI par écran) pour un liseré |
| Statu quo | néant | **Retenu** (décision de Sylvain, 2026-08-31) |

⚠️ **Ne pas rouvrir en croyant à un bug de style.** Le liseré `CONTOUR_FENETRE` est
bien posé et testé sur les quatre bords de la zone client ; ce qui manque est
structurellement inatteignable sans changer de stratégie de fenêtre.

### 6.6 Scripts (miroirs de l'existant Windows)

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

1. ✅ **Provisionner le LXC** (§6.2) + **gate pytest verte** en offscreen — c'est le
   smoke test de l'archi en couches. Fait le 2026-08-10 : **1141 passed, 21 skipped,
   0 échec** ; les 4 catégories de correctifs sont détaillées en §6.3.
2. ✅ **Spike `spike/capture_monitor_linux/`** (§5.1) — joué en 3 passages sur le poste
   du collègue (2026-08-12 et 13). **Les 6 questions sont tranchées** ; la
   spécification de l'adaptateur au §5.1 est arrêtée sur la base de ces mesures.
3. **Adaptateurs triviaux + retouches §5.5** : `presse_papiers`, `demarrage_auto`,
   `chemin_ffmpeg`, logs DEBUG, `infos_systeme` — et remplir `_linux()` dans la
   fabrique (schéma `_windows()` : WARNING + stub). Livrable : app lancée en mode
   distant sur un poste Linux graphique, réunion **micro seul** fonctionnelle de
   bout en bout (enregistrement → Voxtral → CR).
4. 🔄 **Capture système `.monitor`** (§5.1) — `platform/linux/capture_systeme_monitor.py`
   **écrit et testé** (25 tests, gate LXC 1166 passed). **Reste** : validation d'une
   réunion complète 2 pistes sur machine graphique réelle, et vérifs
   tray/notifications (§5.4) au passage.
5. ✅ **Packaging** (2026-08-13) : `packaging/linux/` (spec PyInstaller, `.desktop`,
   `build_deb.sh`, `build_app.sh`) + `scripts/build_app_linux_lxc.sh` +
   `scripts/fumee_deb_lxc.sh` + `TestSpecLinux` (7 tests). **Premier build réussi du
   premier coup** — PyInstaller 6.22 sur Python 3.14 confirmé en réel (décision L7
   validée par l'acte) : `debriefmeet_0.3.0+20260813.e5d38bd_amd64.deb`, **120 Mo**,
   gate pytest bloquante incluse au build. **Fumée verte** : Depends vérifiés
   (libportaudio2 nommément), install par apt, `--version`, réinstall, purge sans
   résidu. Le venv de build installe `.[linux,dev]` — l'extra `linux` est réduit à
   `livekit` (AEC3) : pas de faster-whisper dans le bundle v1 (~100 Mo épargnés,
   décision L1), paquets moteur en EXCLUDES du spec par ceinture-bretelles.
6. 🔄 **Livraison** — **validée sur le terrain le 2026-08-13** : le `.deb` corrigé
   (`…cd5620c…`, après le correctif §6.4) **fonctionne chez le collègue**. Le
   portage est donc opérationnel de bout en bout sur la machine cible, ce qui a
   justifié la fusion dans `main`. **Reste** : la notice utilisateur (install
   `apt install ./…`, où vivent les données, comment exporter un diagnostic —
   miroir allégé de docs/35), et l'usage en conditions réelles dans la durée.

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
| ~~Nom/visibilité de la source `.monitor` via PortAudio~~ | **Levé** par le spike du 2026-08-12 (§5.1) : visibles sous le hostapi PulseAudio, nom = `<sink>.monitor`, résolus via `pactl` |
| **Bascule de sortie silencieuse** : le moniteur d'un sink inactif rend du silence parfait sans erreur — indiscernable d'une réunion calme | Résolution par les **flux de lecture réels** (`pactl list sink-inputs`) + surveillance et réouverture (§5.1, §11) ; **jamais** de détection par exception ou par seuil de silence |
| ~~Un sink qui **disparaît** pourrait tuer le flux~~ | **Mesuré** (Q6) : le flux **gèle en silence**, `active` reste `True`, aucune exception → chien de garde sur les trames + repli silence (§5.1) |
| Tray absent si l'extension AppIndicator est désactivée sur le poste cible | Vérifier au déploiement ; documenter dans la notice (`gnome-extensions enable ubuntu-appindicators…`) |
| Casque Bluetooth : bascule de profil A2DP↔HFP quand le micro BT est utilisé (le monitor change de format) | Même famille que les cas BT Windows (docs/34 §2.3) : réouverture à chaud + logs ; recommander micro filaire/intégré en premier déploiement |
| Python 3.13 non packagé dans l'archive 26.04 | PPA deadsnakes (constat au provisionnement) |
| Liste `Depends` Qt incomplète → app qui ne démarre pas sur un poste nu | La fumée LXC part d'un conteneur sans deps de dev ; compléter `Depends` jusqu'à `--version` vert |

## 11. Le moniteur suit le son réel, pas la sortie *par défaut* (corrigé 2026-08-31)

### 11.1 Ce qui a été mesuré (terrain 2026-08-31, poste Ubuntu 26.04)

Réunion de 2 h 19 (`2026-08-31_09-15-44_COMEX`). `systeme.opus` est à **99,97 %
d'échantillons exactement nuls** — deux brèves bouffées seulement, vers 70 et 100 min.
`moi.opus`, elle, est saine de bout en bout (RMS −24,8 dB, parole continue).

Le log est sans ambiguïté :

```
09:15:44  Capture système ouverte sur 'alsa_output.pci-…HiFi__Speaker__sink.monitor' (index 20)
11:35:57  Liste des entrées MODIFIÉE : -['Logi Group Speakerphone Stéréo analogique']
```

L'application a donc surveillé les **haut-parleurs internes**, pendant que l'utilisateur
travaillait sur un **speakerphone Logitech USB** (débranché une minute après la fin de la
réunion). Aucune des deux gardes de §5.1 n'a rien signalé, et c'est logique :

* la garde « bascule de sortie » guette un **changement** de `pactl get-default-sink` —
  or la sortie par défaut n'a **jamais changé**, elle n'était simplement jamais utilisée ;
* la garde « flux gelé » guette l'**absence de trames** — or le moniteur d'un sink inactif
  livre des trames, pleines de zéros, indéfiniment.

Les deux gardes fonctionnent exactement comme spécifié. C'est la **prémisse** qui est
fausse : `sink_par_defaut()` suppose que le son de la réunion passe par la sortie par
défaut. Un flux routé par application (le navigateur ou le client visio qui pointe vers
un périphérique choisi dans sa propre interface) invalide cette prémisse sans rien
déclencher.

⚠️ **Ce jour-là le coût a été nul** — le micro du speakerphone captait toute la salle,
voix distantes comprises, donc la réunion était intégralement récupérable depuis
`moi.opus`. **En visio avec un casque, la même configuration perdrait définitivement les
voix distantes**, et le log dirait que tout va bien.

### 11.2 Correctif livré — résolution par `pactl list sink-inputs`

Le moniteur est désormais résolu depuis **où le son se trouve réellement**.
`sinks_en_lecture()` lit `pactl list sink-inputs`, retient le sink de chaque flux dont
`Corked: no` (un onglet en pause ne joue rien et ne doit désigner aucune sortie), et
`sink_a_surveiller(sd)` applique la politique — **du plus sûr au plus utile, jamais de
repli aveugle** :

| Situation | Sortie retenue | Pourquoi |
|---|---|---|
| Rien ne joue nulle part | **Sortie par défaut** | Réunion physique : il n'y a rien à capter et rien à deviner |
| La sortie par défaut porte un flux | **Elle** | Cas courant — comportement identique à avant le correctif |
| Une seule autre sortie porte des flux | **Elle** | Le cas de Dario |
| Plusieurs autres, et pas la sortie par défaut | **Sortie par défaut** + WARNING nommant les candidates | Départager au hasard est ce que `index_moniteur` s'interdit déjà |

Réponses aux cinq questions que posait la version précédente de cette section :

1. **Quel sink quand plusieurs jouent** — on ne tranche pas, et on le dit. Le journal
   nomme les candidates, ce qui suffit à diagnostiquer si le cas se présente en vrai.
   Il n'a jamais été observé.
2. **Quand résoudre** — à l'ouverture *et* dans la surveillance existante (2 s). C'est
   nécessaire : le cas nominal est que l'utilisateur lance l'enregistrement **avant** de
   rejoindre la visio, donc le flux de lecture n'existe pas encore au démarrage.
3. **Bascule en cours de réunion** — réouverture par le chemin existant, avec son
   comblement de silence (docs/48). Protégée par une **hystérésis** :
   `_CONFIRMATIONS_AVANT_BASCULE = 2` sondages concordants (≈ 4 s). Un flux disparaît
   brièvement à chaque pause ou renégociation ; sans confirmation, la capture ferait
   l'aller-retour et trouerait la piste à chaque fois.
4. **Table PortAudio non rafraîchie** — traitée par un **repli explicite** : si le
   moniteur de la sortie retenue est invisible de PortAudio (sortie apparue après le
   début de la réunion), on retombe sur la sortie par défaut avec un WARNING. Capturer
   la mauvaise sortie reste préférable à ne rien capturer, et c'est le comportement
   d'avant le correctif — **on ne régresse pas dessous**. La limitation de fond, elle,
   reste entière (cf. en-tête du module).
5. **Coût** — un `pactl` de plus par sondage, soit deux toutes les 2 s au lieu d'un.
   Non mesuré sur le poste cible ; à surveiller au premier retour terrain.

⚠️ **`LC_ALL=C` est désormais forcé dans `_pactl`.** On parse les étiquettes `Sink:` et
`Corked:`, or `pactl list` les traduit dans la locale de l'utilisateur — et le poste
terrain est en français. Sans cela le correctif serait muet précisément là où il sert.

⚠️ **Ne pas régler ça par un seuil de silence.** « La piste système est vide donc quelque
chose ne va pas » est faux : une réunion physique autour d'un speakerphone produit
légitimement une piste système vide, et c'est exactement le cas ci-dessus. Le verdict
vient du **routage**, jamais du niveau audio — même leçon que le garde-fou AEC de
docs/48 §8.6, qui accusait les flux à partir d'une mesure incapable de trancher.

### 11.3 Ce qui n'est pas couvert

- **Validation terrain** : le correctif est adossé au diagnostic du 2026-08-31 et à des
  tests, **pas** à un rejeu sur le poste de Dario. Le prochain diagnostic doit montrer
  « Le son ne passe pas par la sortie par défaut … — c'est elle qu'on capture ».
- **Le cas « plusieurs sorties jouent »** n'a aucun cas terrain : la branche existe, elle
  est testée, elle n'a jamais servi.
- **La table PortAudio non rafraîchie** reste la limitation de fond : une sortie apparue
  pendant la réunion demeure inouvrable, on la journalise et on tient la piste en silence.
