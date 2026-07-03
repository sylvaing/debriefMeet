# Phase 5 — Observabilité et debug à distance (logs « boîte noire »)

> **Statut : 📝 SPEC à implémenter** (2026-07-03). Dépend de : rien (premier chantier
> de la Phase 5, cf. docs/30 §6). Se développe et se teste entièrement sur le Mac.
>
> **Pourquoi c'est le chantier n°1 :** aucune machine Windows de dev. Quand Bastien ou
> Alix diront « ça ne marche pas », le zip de diagnostic sera l'unique matière pour
> comprendre. Chaque adaptateur écrit ensuite (docs/34) devra logger selon les règles
> posées ici.

---

## 1. État actuel (vérifié dans le code le 2026-07-03)

- `core/logs.py` : `configurer_logs(actifs, debug)` — rotation 1 Mo × 3, format
  `%(asctime)s %(name)s %(levelname)s %(message)s`, destination
  `platformdirs.user_log_dir("debriefMeet")`.
- `core/config.py:_DEFAUTS` : `"logs_actifs": False`, `"logs_debug": False` —
  **les logs sont éteints par défaut**, sur tous les OS.
- Câblage : `__main__.py:107-108` applique la config au démarrage ;
  `ui/preferences.py:489/560-562` expose les cases à cocher.
- Version : `__init__.py` → `__version__ = "0.1.0"`, statique, **aucun numéro de
  build** — impossible d'associer un log reçu à un exécutable livré.
- Aucun hook d'exception globale, pas de `faulthandler` : un crash brutal ne laisse
  aucune trace.

## 2. Cibles

1. Logs **DEBUG activés par défaut sur Windows** (macOS inchangé) — décision D5.
2. **Identifiant de build** unique dans chaque log et dans le nom de l'installeur.
3. **En-tête de session** riche à chaque démarrage (machine, audio, backend).
4. **Trace des crashs** (exceptions Python non rattrapées + crashs natifs).
5. **Export diagnostic en un clic** depuis le tray — décision D6.
6. **Règle vie privée** : jamais de texte transcrit dans les logs.

## 3. Spécifications

### 3.1 Défauts de config dépendants de l'OS — `core/config.py`

Rendre deux valeurs de `_DEFAUTS` conditionnelles à la plateforme :

```python
_WINDOWS = sys.platform == "win32"
_DEFAUTS = {
    ...
    "logs_actifs": _WINDOWS,   # True sur Windows (D5), False ailleurs
    "logs_debug": _WINDOWS,
    ...
}
```

- ⚠️ `sys.platform` est un test **stdlib**, autorisé dans `core/` (la règle d'or
  interdit les *modules* OS-spécifiques, pas la détection d'OS).
- Les raccourcis par défaut deviennent aussi conditionnels (décision D3, détail
  docs/34 §5) : `"raccourci_dictee": "Ctrl+Alt+D"` sur Windows,
  `"Meta+Alt+Ctrl+D"` sinon (idem R/J).
- L'utilisateur Windows peut toujours couper les logs dans les Préférences ; le
  défaut reste ON tant que la Phase 5 n'est pas déclarée stable.
- Tests : monkeypatcher `debrief_meet.core.config._WINDOWS` (ou recharger le module
  avec `sys.platform` mocké) et vérifier les deux jeux de défauts.

### 3.2 Identifiant de build — `_version.py` généré

**Format :** `<__version__>+<AAAAMMJJ>.<git-hash-court>` — ex. `0.2.0+20260703.a1b2c3d`.

- Nouveau fichier **généré par le script de build** (docs/32 §3, jamais commité,
  ajouté au `.gitignore`) : `src/debrief_meet/_version.py` contenant
  `VERSION_COMPLETE = "0.2.0+20260703.a1b2c3d"`.
- `src/debrief_meet/__init__.py` :

```python
__version__ = "0.2.0"
APP_NAME = "debriefMeet"
try:
    from debrief_meet._version import VERSION_COMPLETE
except ImportError:           # exécution depuis les sources, hors build
    VERSION_COMPLETE = __version__ + "+dev"
```

- Ce même identifiant nomme l'installeur (`debriefMeet-setup-0.2.0+20260703.a1b2c3d.exe`,
  docs/32) et le zip diagnostic (§3.6) : **un log reçu ↔ un exécutable livré ↔ un
  commit git**, sans ambiguïté.
- Passer `__version__` à `"0.2.0"` à la première livraison Windows.

### 3.3 Refonte de `core/logs.py`

1. **Rotation** : `_TAILLE_MAX = 5_000_000` (5 Mo), `_SAUVEGARDES = 5` — le DEBUG est
   bavard, 1 Mo × 3 ne couvrirait que quelques minutes de réunion.
2. **Format** enrichi du thread (les bugs d'arrêt/capture sont des bugs de threads) :
   `"%(asctime)s %(threadName)s %(name)s %(levelname)s %(message)s"`.
3. **Nouvelle fonction** `journaliser_entete_session(infos: dict) -> None` : logge en
   INFO, au niveau du root logger `debrief_meet`, un bloc balisé :

```
===== SESSION debriefMeet 0.2.0+20260703.a1b2c3d =====
os: Windows-11-10.0.26100-SP0
machine: AMD64 | cpu: AMD Ryzen 5 PRO 5675U ... | cœurs: 12 | ram_go: 16.0
gpu: AMD Radeon Graphics (driver 31.0.x)
python: 3.13.2 | pyside6: 6.9.x | sounddevice: x.y | faster_whisper: x.y
peripheriques_audio_entree: [0] Microphone (Realtek) 48000Hz 2ch | ...
peripheriques_audio_sortie: [3] Haut-parleurs (Realtek) 48000Hz 2ch [défaut] | ...
backend: faster-whisper (CPU int8) | modele: large-v3-turbo
config: intervalle_reunion=30 aec_actif=True transcription_live=True ...
======================================================
```

   La collecte des infos est fournie par l'appelant (§3.4) — `logs.py` ne collecte
   rien lui-même et reste sans dépendance OS.
4. **`configurer_logs`** : inchangée dans sa signature ; ajouter en fin de fonction
   `root.info("Logs activés (debug=%s) — %s", debug, VERSION_COMPLETE)`.

### 3.4 Collecte des informations système — `platform/infos_systeme.py`

Nouveau module **dans `platform/`** (règle d'or : la collecte OS-spécifique n'entre
pas dans `core/`) :

```python
def collecter_infos_systeme() -> dict:
    """OS, CPU, RAM, GPU, versions libs, périphériques audio. Ne lève jamais :
    chaque rubrique en échec vaut "indisponible (<exc>)"."""
```

- **Commun (stdlib)** : `platform.platform()`, `platform.machine()`,
  `platform.processor()`, `os.cpu_count()`, versions Python/libs via
  `importlib.metadata.version(...)` (PySide6, sounddevice, numpy, faster-whisper,
  soundcard — chacune dans un try/except).
- **Périphériques audio** : `sounddevice.query_devices()` — nom, host API, taux par
  défaut, canaux in/out, marqueurs périphérique par défaut. C'est la rubrique la
  plus précieuse : les bugs micro/loopback (docs/20/25) se diagnostiquent d'abord là.
- **Windows** (branche `sys.platform == "win32"`, imports paresseux) :
  - RAM : `ctypes.windll.kernel32.GlobalMemoryStatusEx` (struct `MEMORYSTATUSEX`).
  - GPU + driver : `powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json"`
    (subprocess, timeout 10 s, `CREATE_NO_WINDOW`).
  - Build Windows précis : `platform.platform()` suffit (inclut 10.0.xxxxx).
- **macOS/Linux** : rubriques RAM/GPU = `"non collecté"` (l'en-tête sert le debug
  Windows ; ne pas sur-investir ailleurs).
- **Câblage** : dans `__main__.py`, juste après `configurer_logs(...)` (ligne ~107),
  appeler `journaliser_entete_session(collecter_infos_systeme() | infos_app)` où
  `infos_app` = version complète, backend/modèle (fournis après création des
  adaptateurs — l'en-tête peut être loggé en deux temps : machine d'abord,
  `backend/modele` au chargement du moteur).
- La collecte complète peut prendre ~1 s (PowerShell) : l'exécuter dans un thread
  **non bloquant** pour le démarrage du tray, le bloc étant loggé dès qu'il est prêt.

### 3.5 Trace des crashs — `core/logs.py` (extension)

Nouvelle fonction `installer_traces_crash() -> None`, appelée par `__main__.py`
immédiatement après `configurer_logs` :

1. `sys.excepthook` : logge l'exception en CRITICAL (avec traceback) **puis** rappelle
   le hook précédent.
2. `threading.excepthook` : idem pour les threads (les workers Qt/transcription).
3. `faulthandler.enable(fichier)` vers un fichier dédié
   `<dossier logs>/debriefMeet-crash.log` (mode `"a"`, garder le handle ouvert au
   niveau module) : un SIGSEGV/abort natif (DLL, driver) y écrit les stacks Python
   au moment du crash.
4. Qt : installer `qInstallMessageHandler` pour router les messages Qt
   (qWarning/qCritical) vers le logger `debrief_meet.qt` — les erreurs de plugins
   Qt Windows (styles, multimedia) apparaissent là et nulle part ailleurs.

### 3.6 Export diagnostic — tray + `core/diagnostic.py`

Nouveau module `core/diagnostic.py` :

```python
def exporter_diagnostic(dossier_cible: Path, infos_systeme: dict) -> Path:
    """Crée debriefMeet-diagnostic-<VERSION_COMPLETE>-<AAAAMMJJ-HHMMSS>.zip
    dans dossier_cible et retourne son chemin."""
```

Contenu du zip :

| Fichier | Source |
|---------|--------|
| `debriefMeet.log` (+ `.1` à `.5`) | dossier de logs (tous les fichiers de rotation présents) |
| `debriefMeet-crash.log` | s'il existe |
| `infos_systeme.json` | `collecter_infos_systeme()` fraîchement ré-exécutée |
| `config.json` | copie intégrale de la config (aucun secret dedans ; les chemins et réglages sont précieux pour comprendre) |

- **Dossier cible : le Bureau** (décision D6) — `Path.home() / "Desktop"` avec repli
  `Path.home()` si inexistant. (Pas de résolution du Bureau localisé/OneDrive en v1 ;
  le repli couvre le cas.)
- **Entrée tray** : dans `ui/` (menu du tray), item « Exporter le diagnostic… » →
  appelle `exporter_diagnostic`, puis notification/boîte de dialogue « Diagnostic
  exporté sur le Bureau : <nom du zip> — envoyez ce fichier à Sylvain ». En cas
  d'échec, boîte d'erreur avec le message (c'est le seul canal qui doive marcher
  même quand tout le reste est cassé : le code doit être trivial et sans dépendance
  au moteur).
- Le module est **cross-platform** (utile aussi sur macOS) — `infos_systeme` lui est
  injecté, il n'importe rien d'OS-spécifique.

### 3.7 Règles de contenu des logs (s'imposent à docs/34)

1. **Jamais le texte transcrit** — ni texte de segments, ni presse-papiers. Logger
   uniquement : longueur en caractères, nombre de segments, langue détectée.
   *Action lors de l'implémentation : `grep` de tous les `logger.` existants pour
   vérifier qu'aucun ne logge `resultat.texte` ou équivalent ; corriger le cas échéant.*
2. **Chaque tranche audio transcrite** logge en DEBUG : durée audio, RMS avant/après
   normalisation, décision de la porte anti-silence (transcrit / écarté), durée de
   transcription, RTF. (Prolonge docs/27 ; c'est aussi la sonde du risque
   hallucinations docs/22 : silence transcrit + texte long = signature détectable
   à distance.)
3. **Chaque transition d'état** (démarrage/arrêt de mode, changement de périphérique,
   redémarrage à chaud, rechargement de modèle) logge en INFO avec les identifiants
   de périphériques avant/après.
4. **Toute exception rattrapée-et-avalée** logge au minimum en WARNING avec
   `exc_info=True`. Interdiction des `except: pass` silencieux dans le code Windows.
5. Les adaptateurs Windows loggent leurs appels d'API natifs qui échouent avec le
   code d'erreur Win32 (`ctypes.get_last_error()` / `winreg` exceptions).

## 4. Fichiers créés / modifiés (récapitulatif pour l'implémentation)

| Fichier | Action |
|---------|--------|
| `src/debrief_meet/core/config.py` | défauts conditionnels OS (`logs_actifs`, `logs_debug`, raccourcis) |
| `src/debrief_meet/__init__.py` | `VERSION_COMPLETE` avec repli `+dev` |
| `src/debrief_meet/_version.py` | généré au build — ajouter au `.gitignore` |
| `src/debrief_meet/core/logs.py` | rotation 5 Mo × 5, threadName, `journaliser_entete_session`, `installer_traces_crash` |
| `src/debrief_meet/platform/infos_systeme.py` | nouveau — collecte OS/CPU/GPU/RAM/audio |
| `src/debrief_meet/core/diagnostic.py` | nouveau — `exporter_diagnostic` |
| `src/debrief_meet/__main__.py` | câblage : traces crash + en-tête session |
| `ui/` (tray) | item « Exporter le diagnostic… » |

## 5. Tests (tous sans matériel, `pytest -m "not integration"`)

- Défauts de config : Windows → logs ON/DEBUG + `Ctrl+Alt+D` ; macOS → inchangés.
- `VERSION_COMPLETE` : repli `+dev` sans `_version.py` ; lecture si présent.
- `journaliser_entete_session` : bloc présent dans le log, contient la version.
- `installer_traces_crash` : une exception levée après installation apparaît en
  CRITICAL dans le log ; le hook précédent est bien rappelé.
- `collecter_infos_systeme` : ne lève jamais (mocker `sounddevice.query_devices`
  qui lève → rubrique `"indisponible"`), rubriques attendues présentes.
- `exporter_diagnostic` : zip créé avec les 4 types de contenus, nom conforme ;
  dossier logs vide → zip quand même produit (avec `infos_systeme.json` seul).
- Rotation : paramètres 5 Mo/5 appliqués au handler.

## 6. Definition of Done

- [ ] Suite complète verte (Mac).
- [ ] Sur macOS en dev : `make run` + activer les logs → en-tête de session visible.
- [ ] `exporter_diagnostic` produit un zip valide (test manuel Mac).
- [ ] Règles §3.7 relues et appliquées aux logs existants (audit `grep`).
- [ ] CLAUDE.md : table des docs mise à jour.
