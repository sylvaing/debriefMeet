# Fix du crash SIGABRT à l'arrêt — « QThread destroyed while thread is still running »

> **Statut : ✅ TERMINÉ (2026-07-03, 589 tests).** Les 4 correctifs ci-dessous sont
> appliqués : registre des workers MLX + `tuer()` forcé (`moteur_mlx.py`), helper
> `core/arret_threads.py` (`arreter_thread`/`proteger_thread`), câblage dans
> `reunion.py`/`dictee.py`/`journal.py`/`gestionnaire_diarization.py`/`chargeur_modele.py`,
> dé-parentage des `QThread` dans `preferences.py`/`assistant_diarization.py`.
> 13 tests de non-régression ajoutés (`tests/test_arret_threads.py` + compléments
> `test_moteur_mlx.py`/`test_reunion.py`/`test_dictee.py`/`test_journal.py`) ; suite complète
> passée de 576 à 589 tests, tous verts (`pytest -m "not integration"`).
>
> Diagnostic complet : [`24-crash-qthread-arret.md`](24-crash-qthread-arret.md). Ce doc le
> **corrige sur un point** (voir §1.2) et le transforme en plan d'implémentation.

---

## 1. Contexte

### 1.1 Rappel du bug (docs/24, vérifié dans le code le 2026-07-02)

À la fermeture de l'app, `OrchestrateurReunion.terminer()`
(`src/debrief_meet/core/reunion.py:414-420`) fait `self._thread.quit()` puis
`self._thread.wait(10_000)` **sans vérifier la valeur de retour**. Si la transcription en
cours dépasse 10 s (ou bloque pour toujours — `self._proc.stdout.read(4)` sans timeout,
`platform/macos/moteur_mlx.py:88`), le wait expire silencieusement. Ensuite `app.exec()`
rend la main, la frame de `_demarrer_app` (`__main__.py`) est nettoyée, la locale
`orch_reunion` (créée ligne 176) tombe à zéro référence → Shiboken détruit le QObject C++
→ Qt détruit ses enfants, dont le `QThread(self)` (`reunion.py:313`) **encore en train de
tourner** → `QMessageLogger::fatal()` → `abort()` → rapport de crash macOS visible par
l'utilisateur final.

Sites touchés par le même motif (tous vérifiés) :

| Site | Problème |
|---|---|
| `core/reunion.py:414-420` — `terminer()` | `wait(10_000)` ignoré |
| `core/reunion.py:300-302` — garde de sérialisation de `_lancer_worker` | `wait(10_000)` ignoré puis `self._thread = thread` **écrase** — l'ancien thread vivant reste enfant de l'orchestrateur |
| `core/dictee.py:121-126`, `core/journal.py:129-133` — `terminer()` | motif identique (et tout aussi atteignable : une longue dictée/un long journal transcrit tout d'un bloc à l'arrêt, > 10 s facile) |
| `ui/gestionnaire_diarization.py:182-187` — `terminer()` | `wait(30_000)` ignoré — une diarization dure facilement plusieurs minutes |
| `ui/chargeur_modele.py:69-83` — `precharger_au_demarrage` | `QThread()` sans parent en variable locale, `wait(2000)` ignoré → GC possible d'un thread vivant |
| `ui/preferences.py:488`, `ui/assistant_diarization.py:255` | `QThread(self)` parenté à un dialogue, **aucun** code n'attend le thread à la destruction du dialogue (pas de `closeEvent`/`done()` override) — quitter l'app pendant un téléchargement de modèle reproduit le même abort |

### 1.2 ⚠️ Correction du diagnostic — la piste 1 de docs/24 ne marche pas telle quelle

docs/24 propose : « si `wait(10_000)` échoue, appeler `moteur.terminer()` qui tue les
sous-processus → débloque le `read()` ». **C'est faux dans le cas gelé** :

`MoteurMLX.terminer()` (`moteur_mlx.py:218-238`) ne tue que les workers qu'il récupère
**dans le pool** (`self._pool.get(timeout=15)`, `break` sur `Empty`). Or un worker gelé en
pleine transcription est *sorti* du pool : le `finally: self._pool.put(worker)`
(`moteur_mlx.py:188-189`) ne s'exécute que si `worker.transcrire()` retourne ou lève. Si
le `read(4)` bloque pour toujours, le worker ne revient jamais dans le pool →
`terminer()` abandonne après 15 s **sans tuer le sous-processus gelé** → le QThread reste
coincé → crash quand même.

**Le prérequis de tout le reste est donc le Correctif 1** : `MoteurMLX` doit garder un
registre de *tous* les workers créés et, en fin d'arrêt, `kill()` ceux jamais rendus au
pool. Le kill ferme le pipe → `read(4)` rend `b""` → `RuntimeError("pipe fermé")`
(`moteur_mlx.py:89-90`) → le worker Python sort en erreur → signal `erreur` →
`thread.quit` → le QThread se termine proprement.

### 1.3 Pourquoi le crash est intermittent (observation utile, pas un correctif)

Dans le cas « lent mais pas gelé », après l'expiration du `wait(10_000)`, l'exécution des
handlers `aboutToQuit` continue jusqu'à `moteur.terminer()` (`__main__.py:223`), qui
bloque lui-même jusqu'à 15 s en attendant le retour du worker au pool. Si la transcription
finit dans cette fenêtre, le thread sort de son event loop (le `quit()` explicite a déjà
posé le flag d'exit) avant le nettoyage de frame → pas de crash. C'est un sauvetage
accidentel, avec une course résiduelle (le worker émet encore ses signaux quand le kill
arrive). Le cas gelé, lui, crashe à coup sûr.

---

## 2. Correctif 1 — `MoteurMLX` : registre des workers + arrêt forcé

**C'est le fix racine — sans lui, aucun « déblocage » n'est possible.**

### Fichier
`src/debrief_meet/platform/macos/moteur_mlx.py`

### 2.1 `_WorkerSubprocess.tuer()` — kill direct, sans handshake

`terminer()` (ligne 97) tente d'abord un « quit » poli par stdin — inutilisable sur un
worker gelé (et le kill n'arrive qu'après 5 s de `wait`). Ajouter une méthode brutale :

```python
def tuer(self) -> None:
    """Kill immédiat, sans handshake stdin. Idempotent. Ferme le pipe → tout
    thread bloqué dans stdout.read() est libéré (lit b"" → RuntimeError)."""
    proc = self._proc
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait()
    except Exception:
        pass
    self._proc = None
```

Ne PAS prendre `self._lock` dans `tuer()` : c'est précisément le thread bloqué dans
`read()` qui le détient.

### 2.2 Registre de tous les workers

Dans `MoteurMLX.__init__`, ajouter :

```python
self._workers: list[_WorkerSubprocess] = []   # TOUS les workers créés (pool + sortis)
```

Dans `_creer_worker` (ligne 242), après `w.demarrer()` réussi, enregistrer le worker
**sous `self._n_workers_lock`** (les créations sont concurrentes, threads
`mlx-worker-init`) :

```python
with self._n_workers_lock:
    self._workers.append(w)
self._pool.put(w)
```

### 2.3 `terminer()` — balayage final des workers non rendus

À la fin de `terminer()` (après la boucle `for w in workers: w.terminer()` existante,
avant la remise à zéro de `_n_workers`), tuer tout worker du registre — `tuer()` est
idempotent, donc pas besoin de distinguer ceux déjà arrêtés poliment :

```python
with self._n_workers_lock:
    restants = list(self._workers)
    self._workers.clear()
for w in restants:
    w.tuer()
```

**Piège — le timeout du pool :** garder le `self._pool.get(timeout=15)` existant pour
l'arrêt poli (ne pas tuer Metal pendant une transcription qui progresse), mais après le
timeout le balayage tue le gelé. Comportement final : arrêt poli ≤ 15 s par slot pour ce
qui progresse, kill immédiat pour ce qui est gelé.

**Piège — conséquence côté thread bloqué :** après le kill, le thread réveillé exécute le
`finally: self._pool.put(worker)` (ligne 188) et remet un worker *mort* dans le pool.
C'est inoffensif : `_WorkerSubprocess.transcrire()` redémarre un worker mort
(`poll() is not None` → `demarrer()`, ligne 76-78), et `terminer()` a remis
`_n_workers = 0` donc un `charger_modele()` ultérieur repart proprement. Ne rien
complexifier ici — juste le savoir pour ne pas s'étonner en debug.

---

## 3. Correctif 2 — helper partagé `arreter_thread()`

### Fichier (nouveau)
`src/debrief_meet/core/arret_threads.py`

`core/` importe déjà PySide6 (cf. `core/dictee.py`) — pas de violation de la règle d'or
(qui ne vise que les modules OS-spécifiques : mlx, AppKit, ctypes…).

```python
"""Arrêt robuste des QThread — traite le timeout de wait() au lieu de l'ignorer.

Stratégie en 3 temps (docs/26) :
1. quit() + wait(timeout)                          → cas nominal
2. si échec et `debloquer` fourni : l'appeler      → tue ce qui bloque le thread
   (ex. MoteurTranscription.terminer) puis re-wait
3. si toujours vivant : dé-parenter le thread et le fuir volontairement
   (référence module) — un leak à l'exit vaut mieux qu'un SIGABRT.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

# Threads abandonnés (étape 3) — la référence les garde vivants côté Python pour que
# Shiboken ne détruise jamais un QThread qui tourne encore. Jamais purgé : par
# construction on n'arrive ici qu'à l'arrêt de l'app ou sur un worker gelé.
_threads_fuites: list[tuple] = []


def arreter_thread(
    thread: QThread | None,
    timeout_ms: int,
    debloquer: Callable[[], None] | None = None,
    timeout_deblocage_ms: int = 5_000,
    garder: tuple = (),
) -> bool:
    """Arrête `thread` proprement ; True si le thread est fini au retour.

    `garder` : objets à maintenir vivants avec le thread s'il est fui (typiquement
    le worker qui a été moveToThread() — sinon son wrapper Python peut être GC'd
    et son C++ détruit pendant que le thread l'exécute → SIGSEGV).
    """
    if thread is None or not thread.isRunning():
        return True
    thread.quit()
    if thread.wait(timeout_ms):
        return True
    if debloquer is not None:
        logger.warning("Thread toujours vivant après %d ms — déblocage forcé", timeout_ms)
        try:
            debloquer()
        except Exception:
            logger.exception("Échec du déblocage forcé")
        if thread.wait(timeout_deblocage_ms):
            return True
    logger.error(
        "Thread impossible à arrêter — fuite volontaire (leak > SIGABRT, docs/26)")
    thread.setParent(None)
    _threads_fuites.append((thread, garder))
    return False
```

Notes d'implémentation :
- `setParent(None)` doit être appelé depuis le thread propriétaire du QThread (le thread
  principal) — c'est le cas partout ici (`terminer()` tourne sur `aboutToQuit`, la garde
  de sérialisation sur le thread principal).
- Ne pas essayer de `terminate()` le QThread : Qt le déconseille et le worker MLX bloqué
  détient des verrous (`_WorkerSubprocess._lock`).

---

## 4. Correctif 3 — appliquer le helper aux orchestrateurs et gestionnaires

### 4.1 `core/reunion.py` — `terminer()` (lignes 414-420)

```python
from debrief_meet.core.arret_threads import arreter_thread

def terminer(self) -> None:
    self._timer.stop()
    if self._thread is not None and self._thread.isRunning():
        logger.debug("OrchestrateurReunion : attente fin du thread de transcription…")
        arreter_thread(
            self._thread, 10_000,
            debloquer=self._moteur.terminer,     # tue les sous-processus MLX → débloque read()
            garder=(self._worker,),
        )
    # … suite inchangée (enregistreur, processeur AEC)
```

`self._moteur.terminer` est sûr comme callback : l'interface `MoteurTranscription.terminer()`
(`platform/interfaces.py:50`) est un no-op par défaut, et `MoteurMLX.terminer()` est
idempotent (le second appel par `aboutToQuit`, `__main__.py:223`, trouvera `_n_workers == 0`
et un registre vide). On inverse localement l'ordre « orchestrateurs puis moteur »
uniquement dans le cas pathologique où le moteur est de toute façon condamné.

### 4.2 `core/reunion.py` — garde de sérialisation de `_lancer_worker` (lignes 300-302)

```python
if self._thread is not None and self._thread.isRunning():
    self._thread.quit()
    if not arreter_thread(self._thread, 10_000, garder=(self._worker,)):
        # Thread gelé abandonné : couper ses signaux pour qu'une éventuelle fin
        # tardive n'écrive pas une tranche périmée dans l'écrivain.
        try:
            self._worker.disconnect()
        except Exception:
            pass
```

**Volontairement SANS `debloquer` ici** : en cours de session, `moteur.terminer()` tuerait
aussi le worker sain de l'autre tranche (et ceux de la dictée/du journal si partagés). On
fuit le thread gelé (le pool MLX est dégradé à 1 worker jusqu'au prochain
`charger_modele`, acceptable) et la session continue. À l'arrêt de l'app, c'est le
`terminer()` du §4.1 qui fera le déblocage complet.

### 4.3 `core/dictee.py` et `core/journal.py` — `terminer()`

Motif identique au §4.1 :

```python
def terminer(self) -> None:
    if self._thread is not None and self._thread.isRunning():
        logger.debug("Orchestrateur… : attente fin du thread de transcription…")
        arreter_thread(self._thread, 10_000,
                       debloquer=self._moteur.terminer, garder=(self._worker,))
```

(Vérifier le nom de l'attribut moteur dans chaque classe — les deux ont `self._moteur`.)

### 4.4 `ui/gestionnaire_diarization.py` — `terminer()` (lignes 182-187)

```python
def terminer(self) -> None:
    if self._thread is not None and self._thread.isRunning():
        logger.debug("GestionnaireDiarization : attente fin du job…")
        arreter_thread(self._thread, 30_000,
                       debloquer=(self._moteur.terminer if self._moteur is not None else None),
                       garder=(self._worker,))
```

Nuance : un job pyannote (diarization pure, torch) n'est pas débloqué par
`moteur.terminer()` — dans ce cas c'est l'étape 3 (fuite volontaire) qui protège. Un job
de *transcription différée*, lui, passe par le moteur et est bien débloqué.

### 4.5 `ui/chargeur_modele.py` — `precharger_au_demarrage` (lignes 69-83)

Remplacer `thread.wait(2000)` par :

```python
arreter_thread(thread, 2_000, garder=(chargeur,))
```

Le `garder=` répond exactement au risque noté dans docs/24 : si le wait expire, le
wrapper local était GC'd à la sortie de la fonction ; ici la référence module le garde
vivant.

---

## 5. Correctif 4 — dialogues : dé-parenter les QThread (préférences, assistant)

### Fichiers
`src/debrief_meet/ui/preferences.py` (ligne 488), `src/debrief_meet/ui/assistant_diarization.py` (ligne 255)

### Problème
`QThread(self)` parenté au dialogue : si le dialogue est détruit pendant qu'un
chargement/téléchargement tourne (quit de l'app, fermeture de la fenêtre), Qt détruit un
thread vivant → abort. Aucun `terminer()` n'est branché sur ces dialogues, et en ajouter
un ne couvrirait pas la destruction par cascade parent→enfant à l'exit.

### Solution — supprimer la relation parent→enfant, garder la vie par référence

Ajouter dans `core/arret_threads.py` :

```python
def proteger_thread(thread: QThread, *garder: object) -> None:
    """Enregistre (thread, worker…) dans un registre module tant que le thread
    tourne — pour les QThread SANS parent Qt : le registre remplace le parent
    comme garantie de survie des wrappers Python. Auto-retiré sur `finished`."""
    entree = (thread, garder)
    _threads_vivants.append(entree)
    thread.finished.connect(lambda: _retirer(entree))


_threads_vivants: list[tuple] = []


def _retirer(entree: tuple) -> None:
    try:
        _threads_vivants.remove(entree)
    except ValueError:
        pass
```

Puis dans les deux dialogues, remplacer :

```python
self._thread_modele = QThread(self)          # preferences.py:488
```
par
```python
self._thread_modele = QThread()              # PAS de parent : la destruction du
proteger_thread(self._thread_modele, self._chargeur)  # dialogue ne tue plus le thread
```

(idem `assistant_diarization.py:255` avec `self._thread` / `self._worker`).

Comportement obtenu : si le dialogue meurt pendant un téléchargement, le thread finit sa
tâche dans son coin (les connexions vers les slots du dialogue détruit sont coupées par
Qt automatiquement), puis se termine et sort du registre. Plus de crash, pas de wait
bloquant à la fermeture du dialogue.

**Piège PySide :** la lambda connectée à `finished` est exécutée dans le thread émetteur ;
`list.remove` est atomique sous GIL, pas de verrou nécessaire. Ne pas capturer `self`
d'un dialogue dans cette lambda.

---

## 6. Hors périmètre (assumé)

- **Borner le `read()` du pipe MLX** (piste 2 de docs/24, via `selectors`) : bénéfice réel
  (tout gel devient une erreur propre en cours de session, pas seulement à l'arrêt) mais
  chantier distinct — toucher au hot-path de transcription mérite son propre cycle de
  test. À ouvrir dans un doc dédié si un gel en pleine session est observé un jour.
- `ui/historique.py` et autres usages de threads non listés dans docs/24 : non audités ici.

---

## 7. Tests (pytest, sans matériel — `make test`)

Créer `tests/test_arret_threads.py` :

1. **Cas nominal** : worker qui finit vite → `arreter_thread` rend True, thread fini,
   registre `_threads_fuites` vide.
2. **Timeout + déblocage** : worker bloqué sur un `threading.Event` ; `debloquer=event.set`
   → rend True après le déblocage.
3. **Fuite volontaire** : worker bloqué, pas de `debloquer` (ou déblocage inopérant),
   timeouts courts (50 ms) → rend False, `thread.parent() is None`, le tuple
   `(thread, garder)` est dans `_threads_fuites`. **Nettoyer en fin de test** (débloquer
   l'event, `thread.wait()`, purger la liste) pour ne pas polluer les tests suivants.
4. **`proteger_thread`** : le tuple est présent pendant l'exécution, retiré après
   `finished` (utiliser `qtbot.waitSignal` ou une boucle d'attente courte).

Compléter `tests/test_moteur_mlx.py` :

5. **`tuer()` idempotent** : sur un `_WorkerSubprocess` avec un faux `Popen`
   (monkeypatch), `tuer()` appelle `kill()` + `wait()` et remet `_proc = None` ; second
   appel = no-op.
6. **Balayage de `terminer()`** : un worker enregistré dans `self._workers` mais PAS dans
   le pool (simule le gelé sorti du pool) → après `terminer()`, son `kill()` a été appelé
   et le registre est vide. Utiliser les fakes existants du fichier.

Compléter `tests/test_reunion.py` / `test_dictee.py` / `test_journal.py` :

7. **`terminer()` passe le bon déblocage** : monkeypatcher
   `debrief_meet.core.arret_threads.arreter_thread` (attention : patcher le nom *importé
   dans le module testé*, ex. `debrief_meet.core.reunion.arreter_thread`) et vérifier
   qu'il est appelé avec `debloquer == moteur.terminer` quand un thread tourne.
8. **Garde de sérialisation sans déblocage** : même technique sur `_lancer_worker`,
   vérifier `debloquer` absent/None.

Les tests existants qui appellent `terminer()` sur des orchestrateurs avec de vrais
QThread courts doivent rester verts sans modification (le chemin nominal est inchangé).

---

## 8. Validation manuelle (après `make test`)

Reproduction de docs/24 : lancer une réunion avec le modèle large (pas turbo — il faut
que la tranche finale dépasse 10 s), arrêter la réunion puis **quitter l'app
immédiatement**. Avant le fix : rapport de crash macOS « QThread: Destroyed while thread
is still running ». Après : l'app se ferme (éventuellement après le délai de déblocage),
aucun rapport de crash, et le log contient au plus le warning « déblocage forcé ».

---

## 9. Clôture

- Mettre à jour le statut de [`24-crash-qthread-arret.md`](24-crash-qthread-arret.md) :
  « fix appliqué, voir docs/26 » + noter la correction de la piste 1 (§1.2 ci-dessus).
- Mettre à jour la ligne docs/24 du tableau « Docs de référence » de `CLAUDE.md`
  (elle dit « fix à faire ») et ajouter la ligne docs/26.
- Mettre à jour le compte de tests attendu dans `CLAUDE.md` (« Suite attendue »).
