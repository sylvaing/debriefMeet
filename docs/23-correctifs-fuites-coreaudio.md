# Correctifs fuites CoreAudio — capture micro & capture système

> **Statut :** ✅ implémenté (2026-07-02) — 530 passed.
> **Origine :** enquête système menée dans `un dossier hors dépôt` (session Claude dédiée).
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation.
> **Périmètre : 2 correctifs ciblés + 1 test de non-régression chacun. Rien d'autre.**

---

## 1. Contexte — pourquoi ces correctifs

Une enquête sur la machine de dev a mis en évidence une **fuite de ressources dans
`coreaudiod`** (le démon CoreAudio de macOS) : accumulation de ~150 buffers de mémoire
partagée par jour (ring buffers audio de 816 KiB, jusqu'à ~423 Mo orphelins), de
sémaphores Mach (×2 par buffer) et de ports, sur 12 jours d'uptime.

Preuve : `sudo killall coreaudiod` a fait retomber le namespace de **7564 → 1131 ports**
(1821 buffers → 0, 4004 sémaphores → 18) avec les **mêmes clients audio reconnectés**.
L'accumulation était donc pure fuite.

Attribution : la fuite est alimentée par les clients audio qui ouvrent des connexions
HAL sans les fermer. Le contributeur dominant est WebKit.GPU (hors de notre périmètre),
mais **debriefMeet est un contributeur identifié** (`org.python.python` présent dans le
roster des clients coreaudiod, 587 événements CoreAudio sur les captures).

**Signature clé observée : les buffers fuités appartiennent à des process VIVANTS**
(0 dead-name côté debriefMeet). Cela pointe vers des flux audio ouverts puis
*abandonnés sans fermeture* pendant la vie du process — pas vers des crashs.

L'audit du code audio (2026-07-02) a trouvé deux défauts qui produisent exactement
cette signature.

---

## 2. Correctif 1 — double-start du micro fuit l'ancien flux

### Fichier
`src/debrief_meet/platform/commun/micro_sounddevice.py`

### Défaut
`CaptureMicroSounddevice.demarrer()` (lignes ~93-107) écrase `self._stream` par le
nouveau flux **sans fermer un flux éventuellement déjà ouvert** :

```python
def demarrer(self, index_peripherique: int | None = None) -> None:
    import sounddevice as sd
    with self._verrou:
        self._buffer = []
    self._stream = self._ouvrir_flux(sd, index_peripherique)   # ← écrase sans fermer
    ...
```

Si `demarrer()` est appelé alors qu'un flux est déjà actif — deux orchestrateurs qui
démarrent le micro (`core/dictee.py:70`, `core/journal.py:73`, `core/reunion.py:150`),
ou un re-start sans `arreter()` préalable — l'ancien `sd.InputStream` (PortAudio) n'est
**jamais `stop()`/`close()`**. Côté coreaudiod, son IOProc, son ring buffer partagé et
ses sémaphores restent alloués **tant que le process debriefMeet vit**.

À noter : `redemarrer()` (lignes ~109-144) fait déjà le bon geste — il ferme l'ancien
flux avant d'ouvrir le nouveau. `demarrer()` doit avoir la même protection.

### Correctif attendu
Au début de `demarrer()`, si `self._stream` n'est pas `None`, fermer l'ancien flux
(`stop()` + `close()`, exceptions avalées comme le fait `redemarrer()`), avant d'ouvrir
le nouveau. Loguer un warning (`logging`) : un double-start est un bug d'appelant qu'on
veut voir dans les logs, même si on le neutralise.

Points d'attention :
- Ne pas casser le contrat existant : buffer vidé, warm-up appliqué, `_sr_flux` mis à
  jour à partir du **nouveau** flux.
- Penser au flux en cours de fermeture différée (`arreter()` lance `_fermer_flux` en
  arrière-plan avec `DELAI_FERMETURE_S = 0.3`) : après `arreter()`, `self._stream` est
  déjà `None`, donc pas de conflit — le correctif ne concerne que le cas où `_stream`
  est encore non-None (vrai double-start).

### Test de non-régression attendu
Dans `tests/test_micro_sounddevice.py` (réutiliser le `FakeSounddevice` existant) :
- **`demarrer()` deux fois sans `arreter()`** → le premier flux doit avoir reçu
  `stop()` et `close()` ; le second flux est celui actif ; pas d'exception.
- Le fake doit permettre de vérifier l'état fermé de chaque instance créée (le fake
  actuel garde-t-il trace des instances ? sinon l'étendre a minima).

---

## 3. Correctif 2 — SIGKILL du helper SCK court-circuite stopCapture()

### Fichier
`src/debrief_meet/platform/macos/capture_systeme.py`

### Défaut
`CaptureAudioSCK.arreter()` et `terminer()` (lignes ~49-58 et ~70-79) envoient `QUIT`
puis, si le process helper ne sort pas en 3 s :

```python
except subprocess.TimeoutExpired:
    self._proc.kill()        # ← SIGKILL immédiat
    self._proc.wait()
```

`SIGKILL` tue le helper **sans lui laisser exécuter `stream.stopCapture()`**
(`helpers/macos/sck-audio/SCKAudioCapture.swift`, ligne ~138). Le SCStream et ses
objets audio côté coreaudiod/replayd sont alors relâchés brutalement — churn et
résidus côté démon à chaque fin de réunion qui timeouterait.

Le helper Swift gère **proprement SIGTERM** (ligne ~112 : `signal(SIGTERM, …)` →
`gShouldExit = true` → sortie de boucle → `stopCapture()` → exit 0).

### Correctif attendu
Dans les deux méthodes (`arreter()` et `terminer()` — factoriser si naturel), remplacer
l'escalade actuelle par : `QUIT` → `wait(3 s)` → si timeout, **`terminate()` (SIGTERM)**
→ `wait(2 s)` → si encore timeout, `kill()` (SIGKILL) en dernier recours + `wait()`.

Points d'attention :
- Conserver le comportement existant : `self._proc = None` à la fin, tolérance aux
  pipes cassés (`_envoyer_commande` avale déjà `BrokenPipeError`/`OSError`).
- Ne pas allonger le chemin nominal : quand QUIT fonctionne (cas normal), rien ne change.

### Test de non-régression attendu
Dans le fichier de tests approprié (chercher les tests existants de
`CaptureAudioSCK` ; en créer un sinon), avec un faux process (`Mock` de `Popen`) :
- QUIT répond dans les temps → ni `terminate()` ni `kill()` appelés.
- QUIT timeout, SIGTERM répond → `terminate()` appelé, `kill()` **pas** appelé.
- QUIT et SIGTERM timeout → `kill()` appelé en dernier.

---

## 4. Hors périmètre (contexte, ne rien faire)

- **Cycle de vie du helper SCK** : le `.swift` est conçu « persistant » mais le côté
  Python le tue à chaque fin de réunion — c'est un **choix délibéré** (ne pas laisser
  l'indicateur de capture d'écran actif entre les réunions). On ne change pas ça.
- **WebKit.GPU / Safari** : contributeur dominant de la fuite coreaudiod, hors de
  notre code.
- Le palliatif système (`sudo killall coreaudiod`) est documenté côté enquête, pas ici.

## 5. Critères d'acceptation

1. Les deux correctifs implémentés, comportement nominal inchangé.
2. Les nouveaux tests passent ; **toute la suite `pytest` passe**.
3. Aucun autre fichier modifié que les deux modules cités + leurs tests.
4. Vérification manuelle optionnelle (si un humain est dispo) : démarrer/arrêter
   plusieurs enregistrements et vérifier que le nombre de ports de `coreaudiod`
   (`top -l1 -pid $(pgrep -x coreaudiod) -stats ports`) revient à son niveau
   d'avant-enregistrement après chaque arrêt.

## 6. Suivi d'implémentation (2026-07-02)

- Correctif 1 : `CaptureMicroSounddevice.demarrer()` ferme désormais un flux déjà
  ouvert (warning loggé) avant d'en ouvrir un nouveau — `src/debrief_meet/platform/commun/micro_sounddevice.py:93`.
- Correctif 2 : `CaptureAudioSCK.arreter()`/`terminer()` escaladent QUIT → SIGTERM
  (2 s) → SIGKILL via `_attendre_ou_escalader()` (factorisé) —
  `src/debrief_meet/platform/macos/capture_systeme.py:49`.
- Tests ajoutés : `tests/test_micro_sounddevice.py::test_demarrer_deux_fois_ferme_lancien_flux`,
  `tests/test_capture_systeme_sck.py` (3 cas d'escalade).
- Suite complète : **530 passed**. Aucun autre fichier touché.
- Vérification manuelle terrain (§5 point 4) : **non faite**, à faire par un humain.
