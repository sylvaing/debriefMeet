# Phase 5 — Packaging Windows et cycle de vie (install / mise à jour / désinstallation)

> **Statut : 🔄 Scripts écrits sur Mac (2026-07-03), build VM pas encore lancé.**
> Dépend de : docs/31 (`_version.py`), docs/34 (mutex `instance_unique.py` pour
> `AppMutex`) — tous deux ✅. Reste à faire : exécuter `scripts/build_app_windows_vm.sh`
> sur la VM Proxmox (`192.168.1.29`) et dérouler la checklist §6.
>
> ⚠️ Révise docs/03 : l'installeur (Inno Setup) entre dans le périmètre v1 (décision
> D1, cf. docs/30 §2). Le ZIP portable n'est plus le livrable.
>
> ⚠️ Piège découvert à l'implémentation (absent de la spec initiale) : `platformdirs`
> sans `appauthor=False` double le dossier sur Windows
> (`%LOCALAPPDATA%\debriefMeet\debriefMeet`) — corrigé dans `core/config.py`,
> `core/logs.py`, `platform/windows/moteur_faster_whisper.py`. Conséquence : config,
> logs et modèles partagent tous `%LOCALAPPDATA%\debriefMeet`, simplifiant §4
> ci-dessous à une seule entrée `[UninstallDelete]`. Voir CLAUDE.md § dédié.

---

## 1. Exigences (décisions D1/D4, arbitrées 2026-07-03)

1. Livrable = **un seul fichier** `debriefMeet-setup-<VERSION_COMPLETE>.exe`.
2. Installation **per-user, sans droits admin** (postes pro potentiellement verrouillés).
3. **Mise à jour = réinstaller par-dessus** : lancer un setup plus récent remplace la
   version installée ; config, transcriptions et modèles survivent.
4. **Désinstallation complète** via « Applications installées » de Windows : supprime
   app + config + logs + modèles + autostart ; **préserve `Documents\debriefMeet`**.
5. Pas de certificat Authenticode : avertissement SmartScreen assumé, documenté dans
   la notice utilisateur (docs/35).

## 2. Chaîne de build — vue d'ensemble

```
Mac                                VM Windows (192.168.1.29, ssh sylvaing)
────────────────────────────       ─────────────────────────────────────────
scripts/build_app_windows_vm.sh →  packaging/windows/build_app.cmd
  rsync des sources vers la VM       1. venv Python 3.13 + pip install (app + pyinstaller)
  ssh (session OUVERTE pendant       2. génération src/debrief_meet/_version.py
      tout le build, cf. CLAUDE.md)  3. pytest -m "not integration"  ← build refusé si rouge
  rapatrie le setup .exe             4. pyinstaller packaging/windows/debriefMeet.spec (onedir)
                                     5. ISCC.exe packaging/windows/debriefMeet.iss
                                     → dist/debriefMeet-setup-<version>.exe
```

S'inspirer directement de `scripts/build_spike_backends_vm.sh` + `spike_build.cmd`
(mêmes motifs : rsync, venv, session SSH maintenue, cache pip/HF déjà chaud sur la VM).

## 3. Fichiers à créer

### 3.1 `packaging/windows/generer_version.py`

Petit script (exécuté sur la VM, mais écrit en Python portable) :

- lit `__version__` dans `src/debrief_meet/__init__.py` ;
- calcule `VERSION_COMPLETE = f"{__version__}+{date AAAAMMJJ}.{git rev-parse --short HEAD}"`
  (le hash est transmis par le script Mac au moment du rsync — la copie sur la VM
  n'est pas un dépôt git : écrire le hash dans un fichier `BUILD_INFO` rsyncé) ;
- écrit `src/debrief_meet/_version.py` **et** `packaging/windows/version.iss`
  (fichier `#define MonAppVersion "..."` inclus par le script Inno) ;
- ⚠️ Inno Setup exige aussi une version numérique pour `VersionInfoVersion` :
  générer `#define MonAppVersionNum "0.2.0.0"` (partie numérique seule).

### 3.2 `packaging/windows/debriefMeet.spec` (PyInstaller)

- Mode **onedir** (pas onefile) : démarrage rapide, DLL lourdes (ctranslate2, Qt),
  et Inno gère très bien un dossier.
- S'inspirer de `packaging/debriefMeet.spec` (macOS) pour `datas`/`hiddenimports`
  (icônes, assets, ressources core), en retirant tout ce qui est macOS (helper SCK,
  mlx) et en ajoutant : `faster_whisper`, `soundcard`, `av` si requis par
  faster-whisper, plugins Qt Windows.
- `console=False` (app tray) — **mais** prévoir une variante debug
  `console=True` activable par un flag du script de build : tant qu'on débogue à
  distance, un utilisateur peut lancer `debriefMeet.exe` depuis un terminal et voir
  la sortie. v1 livrée en `console=False` ; le flag existe pour générer un build
  de diagnostic si besoin.
- Icône : `packaging/windows/debriefMeet.ico` à générer depuis l'icône existante
  (`scripts/generer_icone.py` à étendre pour produire un `.ico` multi-tailles).
- Exclure les gros modules inutiles (`mlx`, `pyannote`, `torch`…) : vérifier la
  taille du dist — cible < 500 Mo hors modèles.

### 3.3 `packaging/windows/debriefMeet.iss` (Inno Setup)

Points imposés du script :

```ini
#include "version.iss"
[Setup]
AppId={{B7E8...GUID-FIGÉ-UNE-FOIS-POUR-TOUTES...}}   ; générer 1 GUID, ne JAMAIS le changer
AppName=debriefMeet
AppVersion={#MonAppVersion}
VersionInfoVersion={#MonAppVersionNum}
DefaultDirName={localappdata}\Programs\debriefMeet
PrivilegesRequired=lowest                              ; per-user, pas d'UAC admin
OutputBaseFilename=debriefMeet-setup-{#MonAppVersion}
AppMutex=debriefMeet-instance                          ; cf. docs/34 §6 — même nom que le mutex de l'app
CloseApplications=yes
SetupIconFile=debriefMeet.ico
[Files]
Source: "..\..\dist\debriefMeet\*"; DestDir: "{app}"; Flags: recursesubdirs replacesameversion
[Icons]
Name: "{userstartmenu}\debriefMeet"; Filename: "{app}\debriefMeet.exe"
[Run]
Filename: "{app}\debriefMeet.exe"; Description: "Lancer debriefMeet"; Flags: postinstall nowait skipifsilent
```

- **`AppId` figé** : c'est lui qui fait que réinstaller = mettre à jour (et que la
  désinstallation retrouve tout). Le générer une fois, le commiter, ne plus y toucher —
  l'équivalent du bundle id macOS `com.sylvaingarcia.debriefmeet`.
- **`AppMutex`** : l'app crée au démarrage un mutex Win32 nommé `debriefMeet-instance`
  (docs/34 §6). Inno détecte ainsi l'app en cours d'exécution et propose de la fermer
  avant mise à jour — sinon fichiers verrouillés → installation corrompue.
- **Autostart** : rien à installer (géré par l'app via le Registre), mais à **nettoyer
  à la désinstallation** (§4).

### 3.4 Scripts de build

- `packaging/windows/build_app.cmd` (côté VM) : étapes 1→5 du §2. Échec de n'importe
  quelle étape = arrêt immédiat avec code retour ≠ 0 (`if errorlevel 1 exit /b 1`
  après chaque commande — piège cmd classique).
- `scripts/build_app_windows_vm.sh` (côté Mac) : miroir de `build_windows_vm.sh`
  (rsync sources + `BUILD_INFO` avec le hash git, ssh `build_app.cmd`, rapatriement
  de `dist/debriefMeet-setup-*.exe` dans `dist/` local).
- **Prérequis VM à documenter dans le script (bloc d'en-tête)** : Python 3.13 x64,
  Inno Setup 6 (`ISCC.exe` — installer une fois via
  `winget install JRSoftware.InnoSetup` ou téléchargement manuel), chemin ISCC
  détecté ou passé en variable.

## 4. Désinstallation complète (D4)

Section `[UninstallDelete]` + section `[Code]` si besoin :

| Donnée | Emplacement | Sort |
|--------|-------------|------|
| Application | `{localappdata}\Programs\debriefMeet` | ✅ supprimée (standard Inno) |
| Config | `%APPDATA%\debriefMeet` (`platformdirs.user_config_dir`) | ✅ supprimée |
| Logs | `%LOCALAPPDATA%\debriefMeet\Logs` (`platformdirs.user_log_dir`) | ✅ supprimés |
| Modèles | `%LOCALAPPDATA%\debriefMeet\modeles` (docs/34 §1 — `download_root` forcé) | ✅ supprimés (plusieurs Go rendus) |
| Autostart | valeur `debriefMeet` dans `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | ✅ supprimée (`[Registry]`/`[Code]`) |
| **Transcriptions + audio** | `Documents\debriefMeet` | ❌ **préservées** (décision D4) |

- ⚠️ Vérifier lors de l'implémentation les chemins exacts rendus par `platformdirs`
  sur Windows (`user_config_dir` et `user_log_dir` ne donnent pas les mêmes racines
  Roaming/Local) et les figer dans le `.iss` en conséquence.
- Le stockage des modèles dans `%LOCALAPPDATA%\debriefMeet\modeles` (et pas le cache
  HF global `~/.cache/huggingface`) est ce qui rend leur suppression **sûre** : on ne
  touche jamais à un cache partagé avec d'autres applications.

## 5. Mise à jour par-dessus — comportement attendu

1. L'utilisateur télécharge le nouveau setup, double-clique, SmartScreen (2 clics,
   cf. notice docs/35), Inno détecte l'app qui tourne (AppMutex) → propose la fermeture.
2. Les fichiers de `{app}` sont remplacés. Config/logs/modèles/transcriptions : hors
   de `{app}`, non touchés.
3. Migration de config si nécessaire : mécanisme **déjà en place**
   (`Config._migrer`, `core/config.py:78-82`) — toute évolution de schéma passe par
   `VERSION_COURANTE` + migration, jamais par une suppression de config à l'install.
4. Premier lancement post-MAJ : l'en-tête de session (docs/31) logge la nouvelle
   `VERSION_COMPLETE` — la preuve dans les logs que la MAJ est effective.

## 6. Tests et validation

**Automatisés (Mac, sans Windows)** : néant pour le `.iss` lui-même (pas de test
unitaire pertinent) ; `generer_version.py` testé unitairement (format, fichiers émis).

**Sur la VM (checklist manuelle, à dérouler à chaque évolution du packaging)** :

1. Build complet depuis Mac → setup produit, nom conforme.
2. Install neuve → app démarre, tray visible, en-tête session dans
   `%LOCALAPPDATA%\debriefMeet\Logs\debriefMeet.log`.
3. Modifier une préférence, relancer le setup (même version rebuildée) → app fermée
   proprement par Inno, préférence conservée.
4. Désinstaller depuis « Applications installées » → tableau §4 respecté (vérifier
   chaque chemin, y compris la clé Registre) ; `Documents\debriefMeet` intact.
5. Réinstaller après désinstallation → repartir de zéro fonctionne (config par
   défaut, modèle retéléchargé).

## 7. Definition of Done

- [ ] `bash scripts/build_app_windows_vm.sh` produit `dist/debriefMeet-setup-<version>.exe`
      sans intervention manuelle (hors session SSH ouverte).
- [ ] pytest vert sur la VM intégré au build (étape bloquante).
- [ ] Checklist §6 déroulée entièrement une fois sur la VM.
- [ ] GUID `AppId` commité et documenté (ne plus jamais changer).
- [ ] docs/03 et CLAUDE.md mis à jour (installeur v1, commandes de build Windows).
