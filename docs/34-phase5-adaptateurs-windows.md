# Phase 5 — Adaptateurs Windows (specs d'implémentation)

> **Statut : 📝 SPEC à implémenter** (2026-07-03). Dépend de : docs/31 (règles de
> logging) et docs/33 (exigences E-1 à E-8, reprises ici section par section).
> Tout se développe et se teste **sur Mac** : chaque adaptateur a des tests sans
> matériel où les modules Windows (`winreg`, `soundcard`, `ctypes.windll`,
> `faster_whisper`) sont mockés. La validation réelle se fait sur la VM puis chez
> les utilisateurs (docs/35).
>
> Rappel architecture (docs/30 §4) : nouveaux modules sous
> `src/debrief_meet/platform/windows/`, la règle d'or `core/` reste intacte.

---

## 0. Fabrique — `platform/factory.py`

Remplacer `_windows()` (`factory.py:100-109`) par le motif de `_macos()` :

- moteur : `selection_backend.selectionner_backend(...)` → `MoteurFasterWhisper`
  (v1 : toujours) ; `ImportError` → `MoteurStub` + `logger.warning`.
- micro : `CaptureMicroSounddevice` (commun, identique à macOS).
- systeme : `CaptureAudioSystemeWasapi` ; `ImportError` → `SystemeStub` + WARNING.
- presse_papiers / demarrage_auto / raccourcis : adaptateurs Windows ci-dessous,
  repli stub + WARNING.

Sur Windows, **chaque repli stub est loggé en WARNING** avec l'exception d'origine :
dans un zip diagnostic, un stub silencieux serait indiscernable d'un bug.

## 1. Moteur — `moteur_faster_whisper.py` + `_fw_worker.py`

### 1.1 Architecture : worker subprocess (décision docs/30 §4.4)

Miroir structurel de `macos/moteur_mlx.py` + `_mlx_worker.py` : pool de workers
sous-processus, protocole pickle sur stdin/stdout, chargement paresseux, **registre
de tous les workers créés + kill forcé dans `terminer()`** (E-4). Reprendre le code
MLX comme référence de structure — les invariants docs/26 (worker sorti du pool
pendant une transcription gelée → kill via le registre) s'appliquent à l'identique.

Différences vs MLX :

- **Pool de 1 worker** (pas 2) : un modèle CT2 par process = ~1-3 Go de RAM ; les
  machines cibles ont 16 Go et l'app doit rester discrète. Le paramétrage reste une
  constante de module pour pouvoir l'ajuster.
- Le worker importe `faster_whisper.WhisperModel` :
  `WhisperModel(chemin_modele, device="cpu", compute_type="int8", cpu_threads=<cœurs physiques, borné à 8>)`.
  `int8` = le choix CPU du spike docs/18 (qualité quasi identique, 2-3× plus rapide
  que float32).
- **Mort avec le parent** (E-3) : le worker vit en boucle sur `stdin.read` — la mort
  du parent ferme le pipe → le worker sort. Vérifier que le worker ne spawn rien
  lui-même. (Même garantie que `_mlx_worker`.)

### 1.2 Contrat `MoteurTranscription`

- `acceleration` → `"CPU"` (v1).
- `charger_modele(nom_logique)` : démarre le pool paresseusement (comme MLX) ;
  logge INFO : modèle, chemin, `compute_type`, durée de chargement.
- `_transcrire_pret(audio, langue)` : envoie l'audio float32 16 kHz au worker ;
  reconstruit `ResultatTranscription` (texte, langue détectée, segments avec
  timestamps). Paramètres CT2 : `beam_size=5` (défaut), `vad_filter=False`
  (docs/33 §2.2 — comparabilité avec macOS), `language=langue` si fournie.
  **N'override jamais `transcrire()`** (E-5).
- logs DEBUG par tranche (E-1, complète docs/31 §3.7.2) : durée audio, durée de
  transcription, RTF, nombre de segments, longueur du texte — **jamais le texte**.
- `est_telecharge` / `telecharger_modele(nom, progression)` : cf. §1.3.
- `terminer()` : sémantique MLX post-docs/26 (pool vidé avec timeout, kill du reste
  du registre).

### 1.3 Modèles : correspondance et stockage

- Table `nom_logique → repo CT2` (constante de module, **reprendre les repos validés
  par le spike docs/18** — les vérifier dans `spike/` au moment de l'implémentation) :
  `small`/`medium`/`large-v3` → `Systran/faster-whisper-*` ;
  `large-v3-turbo` → le repo CT2 turbo utilisé par le spike.
- **`download_root` forcé** : `Path(platformdirs.user_data_dir(APP_NAME)) / "modeles"`
  (soit `%LOCALAPPDATA%\debriefMeet\modeles`) — jamais le cache HF global. C'est ce
  qui rend la désinstallation complète sûre (docs/32 §4). ⚠️ Aligner le chemin
  exact avec le `.iss` (les deux specs doivent pointer le même dossier).
- `est_telecharge` : présence du dossier du modèle avec ses fichiers essentiels
  (`model.bin`, `config.json`) dans `download_root`.
- `telecharger_modele` : via `huggingface_hub.snapshot_download(repo, local_dir=...)`
  avec relais de progression vers le callback (même UX que macOS dans les
  Préférences). Timeout et erreurs réseau → exception propagée, loggée WARNING.

### 1.4 Auto-sélection — `selection_backend.py`

```python
def detecter_materiel() -> dict      # cpu (nom/vendor), igpu: list[str], ram_go
def selectionner_backend(config) -> SelectionBackend  # dataclass: nom, options
```

- v1 : retourne **toujours** `SelectionBackend("faster-whisper", {"device": "cpu", "compute_type": "int8"})`.
  Clé config `"backend"` (défaut `"auto"`) : valeur non reconnue → WARNING + repli.
- `detecter_materiel()` est appelé et **loggé en INFO à chaque démarrage** même si le
  résultat ne change rien en v1 : ces logs (Bastien/Alix) rempliront la future table
  iGPU (docs/30 §4.3). Réutiliser `platform/windows/infos_systeme.py` (docs/31 §3.4)
  pour la détection GPU — ne pas dupliquer le code PowerShell.

### 1.5 Tests (sans matériel)

- Worker mocké (comme les tests MLX) : registre, kill des workers hors pool,
  `terminer()` idempotent.
- `transcrire` non overridé (E-5, test d'identité de méthode).
- Table des modèles : tous les `nom_logique` du sélecteur existant sont couverts.
- `selectionner_backend` : `"auto"`→CPU, valeur inconnue→repli+WARNING.
- `est_telecharge` sur arborescence fabriquée (tmp_path).

## 2. Capture système — `capture_systeme_wasapi.py`

### 2.1 Principe

Loopback WASAPI via **`soundcard`** (jamais `sounddevice` : PortAudio ne sait pas
faire le loopback — CLAUDE.md). Implémente `CaptureAudioSysteme` (48 kHz).

```python
mic = sc.get_microphone(sc.default_speaker().name, include_loopback=True)
with mic.recorder(samplerate=48_000, channels=2, blocksize=1024) as rec:
    bloc = rec.record(numframes=1024)   # ndarray float32 (1024, 2)
```

- **Toujours capturer en stéréo puis downmixer** (`bloc.mean(axis=1)`) — piège
  validé au benchmark : `soundcard` rend du bruit si on demande 1 canal explicite
  en loopback WASAPI (CLAUDE.md).
- Thread d'enregistrement dédié (`threading.Thread`, `name="capture-systeme"`,
  daemon) alimentant un buffer thread-safe — **reprendre le motif buffer/verrou de
  `micro_sounddevice.py`**, ne pas réinventer.
- ⚠️ `soundcard` exige `CoInitialize` dans le thread qui touche WASAPI : tous les
  appels `soundcard` (énumération comprise) se font **dans le thread de capture**,
  jamais dans le thread Qt.

### 2.2 Contrat et exigences docs/33

- `disponible()` : True si `import soundcard` réussit **et** un haut-parleur par
  défaut existe. Jamais d'exception.
- `demarrer()` **idempotent** (E-2) : si déjà démarré → WARNING + no-op. Test obligatoire.
- `arreter()` / `terminer()` (E-3) : positionne l'événement d'arrêt, joint le thread
  (timeout 5 s ; échec de join → WARNING loggé), ferme le recorder (context manager).
- `recuperer_echantillons()` : draine le buffer, mono float32 48 kHz (l'AEC et le
  mixage du cœur rééchantillonnent déjà — comportement identique à la capture SCK).
- Logs (E-8) : au démarrage, nom du haut-parleur par défaut capturé + taux ; chaque
  erreur du thread de capture → WARNING avec `exc_info`.

### 2.3 Changement de sortie en cours de réunion (cas BT du CLAUDE.md)

Le loopback est accroché au périphérique de sortie **au moment du `demarrer()`**. Si
l'utilisateur bascule la sortie (casque BT connecté en pleine réunion), le flux
capturé devient silencieux ou meurt.

Comportement spécifié v1 (pragmatique — les logs utilisateurs joueront le rôle du
spike prévu au CLAUDE.md) :

1. Le thread de capture **surveille à chaque itération** : (a) exceptions du
   `record()` ; (b) toutes les ~2 s, le nom du `default_speaker()` vs celui capturé.
2. Si le défaut a changé ou si `record()` lève : fermer le recorder, le rouvrir sur
   le nouveau haut-parleur par défaut, **sans vider le buffer** (miroir de
   `redemarrer()` du micro, docs/20). Log INFO : `sortie avant → sortie après`.
3. Trois échecs de réouverture consécutifs → la capture passe en « silence » (rend
   des tableaux vides), log ERROR une seule fois (pas de spam), la réunion continue
   avec le micro seul. **Jamais de crash de la réunion pour un problème de loopback.**

### 2.4 Tests (sans matériel, `soundcard` mocké via `sys.modules`)

- E-2 (double `demarrer`), E-3 (arrêt joint le thread), drainage du buffer,
  downmix stéréo→mono, bascule de sortie simulée (le mock change de
  `default_speaker` → réouverture + log), 3 échecs → mode silence sans exception.

## 3. Presse-papiers — `presse_papiers.py`

`PressePapiersWindows` via **Qt** : `QGuiApplication.clipboard().setText()/text()`.

- Justification : l'app est déjà PySide6, `QClipboard` gère l'Unicode et les
  subtilités Win32 (formats, verrous). Pas de ctypes ici.
- Contrainte : appels depuis le thread principal Qt uniquement — c'est déjà le cas
  (la copie est déclenchée par l'UI/orchestrateurs sur le thread principal, comme
  sur macOS avec pbcopy). Documenter dans la docstring.
- `copier` logge en DEBUG la **longueur** copiée (jamais le texte — docs/31 §3.7.1).
- Tests : avec `QGuiApplication` de la suite (les tests UI existants montrent le
  motif), copier/lire un aller-retour.

## 4. Démarrage automatique — `demarrage_auto.py`

`DemarrageAutoWindows` via **`winreg`** (stdlib) :

- Clé : `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valeur `debriefMeet`
  (REG_SZ) = chemin de l'exécutable **entre guillemets**.
- Chemin : `sys.executable` si `getattr(sys, "frozen", False)` (bundle PyInstaller —
  même logique que `demarrage_auto.py` macOS avec le `.app`) ; sinon (dev) ne rien
  faire et logger WARNING (pas de sens de lancer un venv au boot).
- `est_active()` : la valeur existe **et** pointe vers un fichier existant (une
  valeur orpheline après déplacement = considérée inactive).
- `activer()`/`desactiver()` : écriture/suppression, `OSError` → log WARNING +
  propagation (l'UI affiche déjà l'erreur côté Préférences).
- La désinstallation supprime aussi cette valeur (docs/32 §4) — le nom de valeur
  `debriefMeet` doit être **identique** dans le `.iss`.
- Tests : `winreg` mocké (module injecté dans `sys.modules`) — cycle
  activer/est_active/desactiver, valeur orpheline → False.

## 5. Raccourcis globaux — `raccourcis_win32.py` (E-6)

`RaccourcisGlobauxWindows`, réimplémentation Windows de docs/28 :

### 5.1 Mécanisme

- `user32.RegisterHotKey(None, id, modifiers, vk)` par combinaison, id séquentiel.
- Réception : `WM_HOTKEY` (0x0312) arrive dans la boucle de messages du thread
  appelant — sous Qt, l'intercepter avec un **`QAbstractNativeEventFilter`**
  (`installNativeEventFilter` sur l'application ; caster le message en `MSG` via
  `ctypes`). Le filtre tourne sur le thread principal Qt → le callback est invoqué
  directement (contrat de l'interface respecté, `interfaces.py:157`).
- Conversion `QKeySequence` portable → `(modifiers, vk)` :
  `Ctrl→MOD_CONTROL(0x2)`, `Alt→MOD_ALT(0x1)`, `Shift→MOD_SHIFT(0x4)`,
  `Meta→MOD_WIN(0x8)` ; lettres/chiffres → VK = code ASCII majuscule ; F1-F12 →
  VK_F1(0x70)+n. Combinaison non convertible → `False` + WARNING.
  Ajouter `MOD_NOREPEAT (0x4000)` pour éviter les répétitions en maintien.
- Échec `RegisterHotKey` (combo pris par une autre app) → `False` + WARNING avec
  `ctypes.get_last_error()` (même contrat que macOS). ⚠️ piège docs/28 rappelé :
  déclarer soigneusement `argtypes/restype` des fonctions ctypes (le bug `c_void_p`
  macOS s'applique pareil à user32).
- `desactiver_tous()` : `UnregisterHotKey` pour chaque id + retrait du filtre.

### 5.2 Défauts et config

- Défauts Windows : `Ctrl+Alt+D` / `Ctrl+Alt+R` / `Ctrl+Alt+J` (décision D3) —
  implémentés dans `core/config.py` avec les défauts conditionnels (docs/31 §3.1).
- Vigilance AZERTY (docs/33 §2.6) : `Ctrl+Alt` = AltGr — si un utilisateur signale
  un conflit de frappe, les combos sont paramétrables dans les Préférences
  (l'éditeur existant de docs/28 est réutilisé tel quel, il produit du
  `QKeySequence` portable).

### 5.3 Tests

- Conversion QKeySequence→(mod, vk) : table de cas, y compris non convertibles.
- `user32` mocké : enregistrement OK→True, échec API→False+WARNING,
  `desactiver_tous` désenregistre tout.
- Simulation d'un MSG WM_HOTKEY à travers le filtre → callback invoqué.

## 6. Instance unique — `instance_unique.py`

```python
def acquerir_instance_unique() -> bool:
    """CreateMutexW(None, False, "debriefMeet-instance").
    False si ERROR_ALREADY_EXISTS (une instance tourne déjà)."""
```

- Double rôle : (a) éviter deux instances (deux captures micro concurrentes) ;
  (b) **`AppMutex=debriefMeet-instance`** dans le `.iss` (docs/32 §3.3) — le nom doit
  être strictement identique des deux côtés (constante documentée).
- Câblage dans `__main__.py`, branche Windows uniquement, avant la création du tray :
  si `False` → log INFO « instance déjà active » + sortie code 0 (pas une erreur).
- Le handle reste ouvert toute la vie du process (référence module) ; l'OS le libère
  à la mort du process, y compris SIGKILL (E-3 : rien à nettoyer).
- Tests : `ctypes.windll` mocké — acquis/déjà existant.

## 7. AEC — vérification (pas un adaptateur)

`core/aec.py` est commun. Action Phase 5 (docs/30 §5.2) : vérifier sur PyPI que la
roue WebRTC/livekit utilisée existe en `win_amd64` cp313.

- Roue disponible → l'ajouter aux dépendances du build Windows, aucun code.
- Indisponible → au démarrage de la Réunion sur Windows, AEC désactivée + WARNING
  loggé « AEC indisponible sur cette plateforme — réunion sans annulation d'écho » ;
  l'UI n'affiche pas d'erreur (dégradation silencieuse pour l'utilisateur, visible
  dans les logs pour Sylvain).

## 8. Ordre d'implémentation suggéré (commits séparables)

1. `factory._windows()` + squelettes qui lèvent → replis stubs loggés (l'app
   « tourne » déjà sur Windows en mode stub).
2. §4 autostart + §3 presse-papiers + §6 mutex (petits, indépendants, testables).
3. §5 raccourcis.
4. §1 moteur (le plus gros — miroir MLX).
5. §2 capture système.
6. §7 vérification AEC + revue croisée E-1→E-8 (docs/33 §3 : chaque exigence a son
   test — cocher la table).

Chaque étape : suite `pytest -m "not integration"` verte sur Mac avant de passer à
la suivante.

## 9. Definition of Done

- [ ] Table E-1→E-8 (docs/33 §3) : chaque exigence tracée vers ≥ 1 test.
- [ ] `creer_adaptateurs()` sur Windows ne rend plus aucun stub (sauf ImportError réel).
- [ ] Suite verte Mac + VM.
- [ ] Aucun `except` silencieux dans `platform/windows/` (revue dédiée, docs/31 §3.7.4).
- [ ] CLAUDE.md : moteur Windows v1 = faster-whisper CPU int8 (table des moteurs).
