# Crash SIGABRT à l'arrêt — `QThread destroyed while thread is still running`

**Statut : fix appliqué, voir [`26-fix-crash-qthread-arret.md`](26-fix-crash-qthread-arret.md)**
(2026-07-03, 589 tests). La piste 1 ci-dessous était incomplète telle quelle (cf. encadré
ci-dessous) — le fix réellement livré ajoute un registre de tous les workers MLX + un kill
forcé avant tout « déblocage », cf. docs/26 §1.2 et §2.

> ⚠️ **Correction (2026-07-02, revue de code)** : la piste 1 ci-dessous est incomplète
> telle quelle — `MoteurMLX.terminer()` ne tue que les workers récupérables dans le pool ;
> un worker gelé en pleine transcription (sorti du pool) n'est jamais tué, donc le
> `read()` n'est pas débloqué. Voir docs/26 §1.2 pour le détail et le prérequis (registre
> de tous les workers + kill forcé).

## Symptôme

- EXC_CRASH (SIGABRT) dans l'app principale, à la **fermeture**, après qu'un mode Réunion a tourné.
- `liblivekit_ffi.dylib` chargé + threads tokio actifs (marqueur « une réunion avec AEC a eu lieu »,
  **pas** la cause — l'AEC tourne sur le thread principal et son `terminer()` est un no-op).
- Un thread worker (ex. Thread 23) encore en `QThread::exec()` au moment du crash.

Stack du thread 0 :

```
abort ← QMessageLogger::fatal ← QThread::~QThread()
  ← QThreadWrapper::~QThreadWrapper() ← SbkDeallocWrapperCommon
  ← subtype_dealloc ← _PyFrame_ClearExceptCode ← _PyEval_EvalFrameDefault
  ← pymain_run_module
```

Message Qt associé : *« QThread: Destroyed while thread is still running »* (section
Application Specific Information du rapport de crash).

## Chaîne causale

1. À la fermeture (`aboutToQuit`), `OrchestrateurReunion.terminer()`
   (`src/debrief_meet/core/reunion.py`) fait `self._thread.quit()` puis `self._thread.wait(10_000)`.
   Mais `quit()` n'est traité par la boucle d'événements du thread **qu'après le retour de
   `_WorkerTranche.transcrire()`**. Si la transcription en cours dépasse 10 s, le `wait` expire —
   et **sa valeur de retour (False) n'est vérifiée nulle part**.

2. La transcription peut largement dépasser 10 s, voire bloquer indéfiniment
   (`src/debrief_meet/platform/macos/moteur_mlx.py`) :
   - `self._pool.get(timeout=90)` — jusqu'à 90 s d'attente d'un worker MLX libre
     (pool de 2 ; la tranche finale de réunion en consomme 2 : micro + système en parallèle) ;
   - `self._proc.stdout.read(4)` — lecture **bloquante sans timeout** sous verrou : si le
     sous-processus MLX est gelé (vivant mais bloqué, `poll()` OK), le thread est coincé
     pour toujours.

3. Après le timeout, `app.exec()` rend la main, `sys.exit()` lève `SystemExit`, la frame de
   `_demarrer_app` (`__main__.py`) est nettoyée → la locale `orch_reunion` tombe à zéro
   référence → Shiboken détruit le QObject C++ → Qt détruit ses **enfants**, dont le
   `QThread(self)` encore en train de tourner → `QMessageLogger::fatal()` → `abort()`.

### Aggravant : ordre d'arrêt dans `__main__.py`

L'ordre « orchestrateurs d'abord, moteur ensuite » est volontaire (ne pas tuer Metal pendant
une transcription). Mais dans le cas pathologique c'est un cercle vicieux : si le worker MLX
est gelé, `orch_reunion.terminer()` attend 10 s pour rien, alors que c'est justement
`moteur.terminer()` (qui tue le sous-processus, donc débloque le `read()`) qui libérerait le
thread — et il n'est appelé qu'après.

## Même famille de bugs ailleurs

| Endroit | Problème |
|---|---|
| `core/reunion.py` — garde de sérialisation de `_lancer_worker` | `wait(10_000)` ignoré, puis **écrase `self._thread`** — l'ancien thread encore vivant reste parenté à l'orchestrateur → même abort à la destruction |
| `core/dictee.py`, `core/journal.py` — `terminer()` | même motif exact, `wait(10_000)` ignoré |
| `ui/gestionnaire_diarization.py` — `terminer()` | `wait(30_000)` ignoré — un job de diarization dépasse facilement 30 s |
| `ui/chargeur_modele.py` — `precharger_au_demarrage` | `QThread()` **sans parent, en variable locale**, `wait(2000)` ignoré — si le wait expire, le wrapper est GC'd à la sortie de la fonction (peu probable car `loop.exec()` attend `finished`, mais fragile) |
| `ui/preferences.py`, `ui/assistant_diarization.py` | `QThread(self)` parenté à un dialogue — si le dialogue est détruit pendant qu'un chargement/téléchargement tourne, même risque |

## Pistes de fix (par ordre de préférence)

1. **Traiter le timeout de `wait()`** dans `OrchestrateurReunion.terminer()` : si
   `wait(10_000)` renvoie False, appeler `moteur.terminer()` (tue les sous-processus →
   débloque le `read()` → le worker sort en erreur → le thread finit), puis re-`wait()`.
   Inverse localement l'ordre d'arrêt uniquement dans le cas pathologique où il est de
   toute façon inévitable.
2. **Borner la lecture du pipe MLX** (`moteur_mlx.py`) : timeout sur le `read()` (via
   `selectors` ou fd non bloquant) — tout gel du worker devient une erreur propre au lieu
   d'un blocage éternel. Bénéfice au-delà du crash.
3. **Filet de sécurité ultime** : si malgré tout le thread ne meurt pas, le dé-parenter
   (`setParent(None)`) et le fuir volontairement (référence module) plutôt que de laisser
   Qt le détruire vivant — un leak à l'exit vaut mieux qu'un SIGABRT.
4. Appliquer le même correctif aux autres sites (dictée, journal, diarization, chargeur).

## Reproduction / confirmation

Lancer une réunion avec le modèle large, arrêter la réunion (tranche finale = 2 transcriptions
parallèles sur le pool de 2) puis **quitter l'app immédiatement** — le `wait(10_000)` expire si
la tranche finale dépasse 10 s. Vérifier le message Qt dans le rapport de crash macOS.

## Note historique

Un premier diagnostic (2026-06-30) préconisait « stocker le QThread en attribut + quit/wait
dans le nettoyage » — c'était **déjà implémenté** au moment de l'analyse. Le bug résiduel est
le chemin de timeout décrit ci-dessus.
