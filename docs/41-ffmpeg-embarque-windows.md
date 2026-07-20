# Embarquer ffmpeg dans le build Windows (rétention Opus garantie)

> **Statut : ✅ TERMINÉ** (2026-07-12) — implémenté et validé de bout en bout
> (gates 1→5 verts, cf. §6). Toutes les étapes A→J du plan ont été suivies.
> Périmètre : **Windows uniquement** (Phase 5). macOS hors scope (Phase 4, ffmpeg
> Homebrew présent sur la machine de dev ; à re-décider au moment du packaging mac).

---

## 1. Contexte et problème

L'app utilise le **CLI ffmpeg** à deux endroits, résolu via le PATH système
(`shutil.which("ffmpeg")`) :

| Usage | Fichier | Sans ffmpeg |
|-------|---------|-------------|
| Rétention audio réunion : encodage **Opus 16 kHz mono** en streaming | `src/debrief_meet/core/fichiers.py` (`_ffmpeg_present`, `_PisteWriter`) | repli **WAV** automatique (~115 Mo/h au lieu de ~7 Mo/h) |
| Transcription différée : décodage des fichiers non-WAV | `src/debrief_meet/core/audio.py` (`_decoder_ffmpeg`) | **lève** sur un fichier `.opus` |

Bastien et Alix n'auront pas ffmpeg sur leur PATH → rétention en WAV, disque
consommé, et impossibilité de relire un `.opus` venu d'une autre machine.
**Décision (Sylvain, 2026-07-12) : embarquer `ffmpeg.exe` dans le bundle Windows.**

Rien à changer dans le `.iss` : `[Files]` empaquette `dist\debriefMeet\*` en
`recursesubdirs`, donc tout ce que PyInstaller met dans le onedir part dans le setup.

## 2. Décisions figées (ne pas re-discuter)

1. **Source du binaire : builds BtbN** (github.com/BtbN/FFmpeg-Builds), variante
   **win64 `lgpl` statique, branche release** (nom d'asset de la forme
   `ffmpeg-n<X.Y>-latest-win64-lgpl-<X.Y>.zip`). **Jamais** les variantes `gpl`
   (licence), `shared` (DLLs à gérer), `master` (instable), ni win32/arm64.
   Les builds `lgpl` incluent `libopus` (licence BSD) — c'est vérifié par un check
   bloquant au build (§3, étape B).
2. **URL épinglée sur un tag daté** (`autobuild-AAAA-MM-JJ-…`), pas sur
   `releases/latest` (les assets du tag roulant sont remplacés → SHA instable).
   URL + SHA256 consignés dans le script de téléchargement, versionnés dans git.
3. **Le binaire n'est jamais commité** dans le dépôt (≈100 Mo). Il est téléchargé
   **sur la VM au moment du build**, mis en cache, vérifié par SHA256.
4. **Résolution côté code : embarqué d'abord, PATH en repli**, WAV en dernier
   recours (comportement actuel conservé). Un seul point de résolution dans
   `core/ressources.py` — la règle d'or du CLAUDE.md est respectée (aucun import
   OS-spécifique, juste `sys.platform`/`shutil`).
5. **`CREATE_NO_WINDOW` obligatoire** sur les deux appels subprocess : l'app v1 est
   buildée `console=False`, sans ce flag chaque lancement de `ffmpeg.exe` ferait
   flasher une fenêtre console (même piège déjà traité dans
   `src/debrief_meet/platform/infos_systeme.py:89` — reprendre ce motif `getattr`).
6. **La licence LGPL est livrée** : le `LICENSE.txt` du zip BtbN part dans le bundle
   à côté de `ffmpeg.exe` (obligation LGPL, et c'est gratuit).
7. Taille : `ffmpeg.exe` statique ≈ 90–120 Mo, mais LZMA2 (`SolidCompression`) le
   compresse fortement — setup attendu ~155–170 Mo (125 Mo aujourd'hui). Acceptable,
   consigner la taille réelle dans le journal (§6).

## 3. Étapes d'implémentation

### Étape A — épingler l'URL et le SHA256 (sur le Mac, réseau requis)

1. Récupérer la dernière release BtbN :
   `curl -s https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest`
   → noter `tag_name` (ex. `autobuild-2026-07-11-13-05`) et, dans `assets`, l'URL
   `browser_download_url` de l'asset dont le nom matche
   `^ffmpeg-n[0-9.]+-latest-win64-lgpl-[0-9.]+\.zip$` (exclure `-shared-`).
2. Télécharger ce zip dans le scratchpad, calculer `shasum -a 256`.
3. Reporter l'URL du **tag daté** (`releases/download/<tag_name>/<asset>`) et le
   SHA256 dans `telecharger_ffmpeg.cmd` (étape B).
4. Vérification locale avant de jeter le zip : `tar -tf <zip> | grep bin/ffmpeg.exe`
   (le zip contient `<racine>/bin/ffmpeg.exe` et `<racine>/LICENSE.txt`).

### Étape B — script de téléchargement VM : `packaging/windows/telecharger_ffmpeg.cmd`

Nouveau script batch, appelé par `build_app.cmd`, **idempotent et rejouable** :

```
Variables en tête :
  set FFMPEG_URL=<URL épinglée étape A>
  set FFMPEG_SHA256=<sha256 en minuscules>
  set CACHE_DIR=C:\Users\sylvaing\build\ffmpeg-cache
  set DEST_DIR=%~dp0ffmpeg          (= packaging\windows\ffmpeg\ sur la VM)

Logique :
  1. Si %DEST_DIR%\ffmpeg.exe existe ET %DEST_DIR%\ffmpeg.sha256 contient
     %FFMPEG_SHA256% → déjà en place, exit /b 0 (rebuild rapide).
  2. Si le zip n'est pas dans %CACHE_DIR% : curl.exe -L -o (curl.exe natif
     Windows 10+, PAS un alias PowerShell — on est en cmd, pas de piège).
  3. Vérifier le SHA : certutil -hashfile "<zip>" SHA256 → la 2e ligne de sortie
     est le hash ; comparer insensible à la casse, échouer (exit /b 1) si différent
     (supprimer le zip corrompu avant de sortir, pour retélécharger au run suivant).
  4. Extraire avec tar -xf (bsdtar natif Windows 10+ sait lire les zip) dans un
     dossier temporaire sous %CACHE_DIR%.
  5. Copier bin\ffmpeg.exe et LICENSE.txt vers %DEST_DIR%\ ; NE PAS copier
     ffprobe.exe/ffplay.exe (inutiles, ~200 Mo de plus).
  6. Check fonctionnel BLOQUANT :
       "%DEST_DIR%\ffmpeg.exe" -version                    → errorlevel 0
       "%DEST_DIR%\ffmpeg.exe" -encoders | findstr libopus → errorlevel 0
     Si libopus absent → message d'erreur explicite (« build BtbN sans libopus,
     vérifier la variante lgpl ») et exit /b 1.
  7. Écrire %FFMPEG_SHA256% dans %DEST_DIR%\ffmpeg.sha256 (marqueur d'idempotence).
```

Ajouter `packaging/windows/ffmpeg/` au `.gitignore` (le binaire ne rentre jamais
dans git — cf. mémoire « Git init & confidentialité »).

### Étape C — appel depuis `packaging/windows/build_app.cmd`

Insérer entre l'étape venv et la génération de version (le téléchargement ne dépend
pas du venv), renuméroter les étapes `[x/6]` :

```
echo [2/6] Telechargement/verification ffmpeg (lgpl, cache VM)...
call packaging\windows\telecharger_ffmpeg.cmd
if errorlevel 1 goto :error
```

Note : la sync tar depuis le Mac (`build_app_windows_vm.sh`) écrase les fichiers
synchronisés mais **ne supprime pas** les fichiers en plus sur la VM →
`packaging\windows\ffmpeg\` survit d'un build à l'autre, le marqueur SHA rend le
re-run instantané. Rien à changer dans `scripts/build_app_windows_vm.sh`.

### Étape D — spec PyInstaller : `packaging/windows/debriefMeet.spec`

Après la construction de `datas`/`binaries`, **échec dur** si le binaire manque
(le spec ne tourne que sur la VM, toujours après l'étape C) :

```python
FFMPEG_EXE = os.path.join(SPECPATH, "ffmpeg", "ffmpeg.exe")
FFMPEG_LICENCE = os.path.join(SPECPATH, "ffmpeg", "LICENSE.txt")
if not os.path.exists(FFMPEG_EXE):
    raise SystemExit(
        "[spec] ffmpeg.exe manquant — lancer packaging/windows/telecharger_ffmpeg.cmd "
        "(appelé normalement par build_app.cmd)")
binaries.append((FFMPEG_EXE, "ffmpeg"))
datas.append((FFMPEG_LICENCE, "ffmpeg"))
```

PyInstaller ≥ 6 place le tout sous `dist\debriefMeet\_internal\ffmpeg\` et
`sys._MEIPASS` pointe sur `_internal` → `chemin_ressource("ffmpeg", "ffmpeg.exe")`
résout correctement (même mécanique que les assets UI déjà embarqués).

### Étape E — résolution dans le code : `src/debrief_meet/core/ressources.py`

Ajouter (module core pur, aucun nouvel import lourd) :

```python
def chemin_ffmpeg() -> str | None:
    """Chemin du ffmpeg à utiliser : embarqué (bundle) d'abord, PATH en repli.

    Retourne None si aucun ffmpeg n'est disponible (l'appelant se replie en WAV
    ou lève, selon le contexte)."""
    import shutil
    nom = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    embarque = chemin_ressource("ffmpeg", nom)
    if embarque.exists():
        return str(embarque)
    return shutil.which("ffmpeg")
```

Le check `exists()` sans condition `est_figee()` : en dev le dossier n'existe pas
(repli PATH naturel), en bundle il gagne toujours — y compris si la VM/le poste a
un autre ffmpeg sur son PATH (déterminisme de version).

### Étape F — `src/debrief_meet/core/fichiers.py`

1. `_ffmpeg_present()` devient :
   ```python
   def _ffmpeg_present() -> bool:
       from debrief_meet.core.ressources import chemin_ffmpeg
       return chemin_ffmpeg() is not None
   ```
2. Dans `_PisteWriter.__init__` (branche `opus`), remplacer le littéral `"ffmpeg"`
   par le chemin résolu et masquer la console Windows :
   ```python
   from debrief_meet.core.ressources import chemin_ffmpeg
   ffmpeg = chemin_ffmpeg() or "ffmpeg"
   self._proc = subprocess.Popen(
       [ffmpeg, "-y", "-loglevel", "error", ...],
       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
   ```
3. Log d'observabilité (docs/31) : dans `EnregistreurAudioReunion.__init__`, un log
   DEBUG une fois le format choisi — chemin ffmpeg retenu ou « absent → WAV »
   (reprendre le logger utilisé ailleurs dans core ; s'il n'y en a pas dans ce
   module, `logging.getLogger(__name__)` suffit, la config racine est déjà en place).

### Étape G — `src/debrief_meet/core/audio.py`

Dans `_decoder_ffmpeg` : même substitution (`chemin_ffmpeg() or "ffmpeg"`) + même
`creationflags` sur le `subprocess.run`. Envelopper le `FileNotFoundError` pour
rendre l'erreur actionnable :

```python
except FileNotFoundError as exc:
    raise RuntimeError(
        f"ffmpeg introuvable (ni embarqué, ni sur le PATH) — impossible de décoder {chemin}"
    ) from exc
```

### Étape H — fumée automatisée : `scripts/fumee_setup_vm.sh`

Après l'étape « install + `--version` » existante, ajouter deux checks (mêmes
conventions que le reste du script — via `ssh_vm`, non interactif) :

1. Présence : `if exist "<dossier install>\_internal\ffmpeg\ffmpeg.exe"` → sinon échec.
2. Fonctionnel : `"<dossier install>\_internal\ffmpeg\ffmpeg.exe" -encoders | findstr libopus`
   → errorlevel 0 sinon échec.

(Le dossier d'installation est déjà connu du script — réutiliser sa variable.)

### Étape I — tests unitaires (Mac, sans réseau, sans ffmpeg requis)

Nouveaux tests, dans les fichiers existants (`tests/test_fichiers.py`, ou
`tests/test_ressources.py` s'il existe, sinon le créer) :

1. **`chemin_ffmpeg` — priorité embarqué** : monkeypatcher
   `debrief_meet.core.ressources._racine_ressources` vers un `tmp_path` contenant
   `ffmpeg/ffmpeg` (fichier vide, nom sans `.exe` hors Windows) → retourne ce chemin.
2. **`chemin_ffmpeg` — repli PATH** : racine vide + `shutil.which` monkeypatché vers
   `/usr/fake/ffmpeg` → retourne la valeur de `which` ; `which` → `None` → `None`.
3. **`_PisteWriter` opus utilise le chemin résolu + le flag** : monkeypatcher
   `chemin_ffmpeg` (→ `/chemin/embarque/ffmpeg`) et `subprocess.Popen` (fake qui
   capture `args`/`kwargs`) → vérifier `args[0][0] == "/chemin/embarque/ffmpeg"` et
   `kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)`.
   ⚠️ Patcher le nom **au point d'usage** (`debrief_meet.core.fichiers.…`), pas dans
   `ressources` (import local dans la fonction).
4. **`_decoder_ffmpeg` idem** avec `subprocess.run` monkeypatché.
5. **`_ffmpeg_present` suit `chemin_ffmpeg`** : monkeypatch → `None` ⇒ `False`,
   chemin ⇒ `True` (et `EnregistreurAudioReunion(format="auto")` bascule bien
   opus/wav en conséquence — étendre le test existant ligne ~52).

Les tests existants avec `pytest.skip("ffmpeg absent")` restent inchangés.

### Étape J — documentation

1. **CLAUDE.md** : ajouter la ligne au tableau « Docs de référence »
   (`docs/41` — ffmpeg embarqué Windows) ; dans la ligne Phase 5 du tableau des
   phases, ajouter docs/41 aux éléments faits une fois le build vert.
2. **docs/32** (§3 contenu du bundle) : une phrase — ffmpeg lgpl embarqué sous
   `_internal\ffmpeg\`, téléchargé/caché au build par `telecharger_ffmpeg.cmd`,
   jamais commité, licence livrée.
3. **En tête de ce doc** : passer le statut à ✅ avec la date, et remplir le
   journal §6.

## 4. Ordre d'exécution et gates (Definition of Done)

| # | Gate | Commande | Attendu |
|---|------|----------|---------|
| 1 | Étapes A→G + I + `.gitignore` faites | `make test` (Mac) | **vert** (889 + nouveaux tests, 0 régression) |
| 2 | Build VM complet (télécharge ffmpeg, spec, Inno) | `bash scripts/build_app_windows_vm.sh` | setup produit dans `dist/`, log `[2/6]` montre le check libopus OK |
| 3 | Rebuild immédiat (cache) | relancer le même script | étape ffmpeg quasi instantanée (marqueur SHA) |
| 4 | Fumée avec les nouveaux checks | `bash scripts/fumee_setup_vm.sh` | vert, y compris présence + `-encoders libopus` dans l'app installée |
| 5 | Taille consignée | `ls -lh dist/debriefMeet-setup-*.exe` | notée au §6 (attendu ≤ ~175 Mo) |

Garder la session SSH **ouverte** pendant le build (CLAUDE.md, règle connue).
Si la VM est injoignable au moment de la session : livrer quand même 1 (code+tests
Mac verts), consigner au §6 que les gates 2–5 restent à jouer, ne pas boucler.

## 5. Pièges connus (lire avant de coder)

- **`creationflags` n'existe pas hors Windows** → toujours
  `getattr(subprocess, "CREATE_NO_WINDOW", 0)` (motif de `infos_systeme.py:89`) ;
  la valeur 0 est inoffensive sur macOS/Linux, donc pas de branche par OS.
- **Imports paresseux** : `fichiers.py` et `audio.py` importent subprocess/shutil
  localement — conserver ce style (démarrage rapide de l'app).
- **certutil** : sortie sur 3 lignes, hash en 2e ligne, parfois avec espaces selon
  la version — normaliser (supprimer espaces, minuscules) avant comparaison.
- **`tar` Windows** : c'est bsdtar, il lit les `.zip` nativement ; ne pas installer
  7zip ni utiliser PowerShell `Expand-Archive` (lent, et on est en cmd).
- **Ne pas toucher `benchmark/`** : il a ses propres usages ffmpeg côté outillage
  interne, hors produit livré.
- **Ne pas épingler `releases/latest`** (§2.2) — SHA cassé au prochain autobuild.
- L'asset BtbN **`-shared-`** contient des DLLs et un exe non autonome — exclu.
- Le zip BtbN a un **dossier racine au nom variable** → extraire dans un temp et
  copier via un glob/`for /d`, ne pas coder le nom du dossier en dur.

## 6. Journal (implémentation du 2026-07-12)

- **URL/SHA épinglés** : tag daté `autobuild-2026-07-12-13-16`, asset
  `ffmpeg-n8.1.2-22-g94138f6973-win64-lgpl-8.1.zip` (branche release n8.1.2, pas
  master) — SHA256 `4fac2e7d7de89bb4354d8c661c968c988e3ccb82b96896803cfc133298eeddc6`,
  vérifié localement (Mac) puis re-vérifié par `telecharger_ffmpeg.cmd` sur la VM.
- **Taille** : `ffmpeg.exe` seul ≈ 108 Mo (113 542 656 octets décompressés).
  Setup avant (docs/32, 2026-07-04) : 125 Mo. Setup après (avec ffmpeg embarqué) :
  **159 Mo** — dans la fourchette attendue (155–170 Mo).
- **Résultat des gates 1–5** : tous verts.
  1. `make test` (Mac) : **938 passed** (0 régression, +9 tests docs/41).
  2. `bash scripts/build_app_windows_vm.sh` : ✅ — setup produit
     `dist/debriefMeet-setup-0.2.0+20260712.68c04e4.exe`, log `[2/6]` confirme le
     téléchargement + check `libopus` OK, gate pytest VM **780 passed**.
  3. Rebuild immédiat (même run suivant, cache) : `[2/6]` répond
     « Deja en place ... SHA256 verifie » — quasi instantané, confirmé par le
     2ᵉ run du script (pas de re-téléchargement).
  4. `bash scripts/fumee_setup_vm.sh` : ✅ vert, y compris les 2 nouveaux checks
     (« ffmpeg.exe present dans le bundle », « ffmpeg embarque : libopus present »).
  5. Taille consignée ci-dessus (159 Mo, ≤ 175 Mo attendu).
- **Surprises/écarts au plan** :
  - Le premier run VM a échoué à la collecte pytest à cause de deux fichiers
    **obsolètes** restés sur la VM (`tests/test_historique_diarization.py` et
    `src/debrief_meet/ui/historique.py`, supprimés du dépôt depuis la refonte UI
    — la sync tar n'efface jamais les fichiers en trop). Nettoyés manuellement
    sur la VM ; sans rapport avec ffmpeg.
  - Le run suivant a révélé un **bug pré-existant, indépendant de ffmpeg** :
    5 fichiers de tests BlueMind (`test_bluemind_association.py`,
    `test_bluemind_association_dialog.py`, `test_bluemind_mapping_dialog.py`,
    `test_bluemind_participants.py`, `test_tray.py`) écrivaient des fixtures
    `.md` accentuées via `Path.write_text(...)` **sans `encoding="utf-8"`** —
    invisible sur Mac (locale UTF-8 par défaut) mais cassant sur Windows (locale
    cp1252), alors que le code produit (`core/fichiers.py`) relit toujours en
    UTF-8 explicite. Vérifié que le code produit n'a **aucune** occurrence de ce
    problème (uniquement les fixtures de test). Corrigé en ajoutant
    `encoding="utf-8"` aux appels concernés (22 occurrences) ; gate pytest VM
    repassée au vert derrière ce correctif, aucune régression Mac (938 passed).
  - Le build BtbN retenu est la branche **n8.1.2** (release stable), pas la
    variante `ffmpeg-N-...` (= master, exclue par la règle §2.1).
- **Réconciliation avec le packaging macOS (docs/16, mergé dans `main` le
  2026-07-12)** : les deux branches avaient embarqué ffmpeg en parallèle avec des
  conventions différentes. Fusionné en unifiant sur celle de `main` — un **seul**
  point de résolution `chemin_ffmpeg()` **dans `core/fichiers.py`** (et non
  `ressources.py` comme le proposait l'Étape E), qui lève `ErreurFfmpegIntrouvable`
  quand ffmpeg manque en Opus. Fonction étendue pour sonder les deux layouts de
  bundle selon l'OS : `vendor/ffmpeg` (macOS) ou `ffmpeg/ffmpeg.exe` (Windows). Le
  flag `CREATE_NO_WINDOW` (§2.5) et le check `libopus` du build restent inchangés.
  Suite après merge : **947 passed** sur Mac (extras + `vendor/ffmpeg`), 0 échec.
