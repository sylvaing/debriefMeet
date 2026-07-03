# Robustesse micro face aux changements de périphériques (hot-plug)

> **Statut :** ✅ implémenté (2026-07-02, 542 tests passent — 530 + 12 nouveaux).
> Plan initial rédigé le 2026-07-02 (session de diagnostic).
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation (Sonnet).
> **Périmètre : 4 correctifs ciblés + tests de non-régression. Rien d'autre.**
> Avant livraison : `make test` (attendu : les 530 tests actuels + les nouveaux, tous verts).

---

## 1. Contexte — le diagnostic du 2026-07-02

### Symptômes observés (machine de dev, macOS)

1. **5 réunions consécutives sans piste micro** (14h50 → 14h54) : les fichiers
   `_systeme.opus` existent, **aucun `_moi.opus`**, icône systray rouge « enregistrement »
   pendant toute la durée. Testé avec le micro interne du MacBook ET des AirPods :
   même échec. Terminal :

   ```
   ||PaMacCore (AUHAL)|| Warning on line 521: err=''!obj'', msg=Unknown Error
   ||PaMacCore (AUHAL)|| Warning on line 441: err=''!obj'', msg=Unknown Error
   ||PaMacCore (AUHAL)|| Error on line 1322: err='-10851', msg=Audio Unit: Invalid Property Value
   ```
   (répété 5 fois — une rafale par tentative de démarrage de réunion)

2. **Après relance de l'app** : le micro remarche… puis pendant la réunion suivante,
   plusieurs branchements/débranchements USB-C ont fait mourir la capture **sans aucun
   signe visible** : icône toujours rouge, mais plus rien d'enregistré.

### Cause racine

**PortAudio fige sa liste de périphériques à `Pa_Initialize`** (déclenché au premier
`import sounddevice` du process) et **ne gère pas le hot-plug**. Dans un process
long-vivant comme debriefMeet (app tray), chaque connexion/déconnexion Bluetooth ou
USB-C rend cette table un peu plus fausse : les entrées référencent des
`AudioObjectID` CoreAudio qui n'existent plus.

- `'!obj'` = `kAudioHardwareBadObjectError` : PortAudio parle à un objet CoreAudio mort.
- Le `-10851` qui suit n'est que la conséquence — d'où l'échec **quel que soit le
  micro physique** choisi (ce n'est PAS une résurgence du bug AirPods 24 kHz de
  docs/20 : `samplerate=None` était bien dans le code qui tournait).
- Relancer l'app reconstruit la table → tout remarche. C'est la parade actuelle,
  inacceptable en usage réel.

Le seul moyen connu de resynchroniser PortAudio sans relancer le process :
`sd._terminate()` puis `sd._initialize()` (ré-exécute `Pa_Terminate`/`Pa_Initialize`).
API privée de sounddevice, mais c'est le mécanisme standard de la communauté pour ce
problème connu de PortAudio.

### Défauts aggravants dans notre code (tous dans `core/reunion.py`)

- **Panne silencieuse** : échec du micro au démarrage → simple `logger.warning`,
  la réunion continue « sans micro », l'icône passe quand même au rouge, aucune
  notification (`_demarrer`, lignes ~149-156).
- **Perte définitive** : un échec de `redemarrer()` pose `_avec_micro = False`
  (ligne ~384) et `_sur_changement_peripherique` early-return sur
  `not self._avec_micro` (ligne ~364) → **plus aucune tentative de reconnexion
  jusqu'à la fin de la réunion**, même si l'utilisateur rebranche le micro.
- **Détection de changement non fiable** : la comparaison de noms via
  `resoudre_peripherique` (lignes ~366-373) lit la même table PortAudio périmée →
  un vrai changement peut être jugé « micro inchangé — ignoré », et l'app garde un
  flux mort dont le callback ne livre plus jamais d'échantillons.

---

## 2. Correctif 1 — rafraîchir la table PortAudio avant chaque ouverture

**C'est le fix racine.** Les 3 autres correctifs sont des filets de sécurité.

### Fichier
`src/debrief_meet/platform/commun/micro_sounddevice.py`

### Règle absolue
`sd._terminate()` **tue tous les flux PortAudio ouverts du process**. Le refresh ne
doit JAMAIS s'exécuter tant qu'un flux existe encore — y compris le flux en
**fermeture différée** (voir piège ci-dessous).

### ⚠️ Piège préalable — la fermeture différée d'`arreter()`

`arreter()` ne ferme pas le flux tout de suite : il le confie à un thread
`_fermer_flux` qui attend `DELAI_FERMETURE_S = 0.3 s` (glitch inaudible, cf.
docstring). Séquence dangereuse :

```
arreter()  →  thread de fermeture armé (flux encore ouvert 300 ms)
demarrer() →  refresh PortAudio  ← Pa_Terminate avec un flux ouvert → état indéfini
```

**Correction préalable requise** : conserver la référence du thread de fermeture
(`self._thread_fermeture`, aujourd'hui le thread est anonyme) et ajouter une méthode
privée `_attendre_fermeture_differee()` :

```python
def _attendre_fermeture_differee(self) -> None:
    self._fermer_event.set()          # réveille _fermer_flux immédiatement
    t = self._thread_fermeture
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
    self._thread_fermeture = None
```

### Implémentation du refresh

Nouvelle méthode privée :

```python
@staticmethod
def _rafraichir_portaudio(sd) -> None:
    """Resynchronise la table de périphériques PortAudio (figée à Pa_Initialize,
    pas de hot-plug — cf. docs/25). À n'appeler QUE quand aucun flux n'est ouvert."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception as exc:  # API privée : ne jamais casser la capture pour un refresh
        import logging
        logging.getLogger(__name__).debug("Refresh PortAudio impossible (%s)", exc)
```

### Points d'appel

- **`demarrer()`** : après le garde double-start existant (qui ferme un éventuel
  `self._stream` résiduel) et après `_attendre_fermeture_differee()`, juste avant
  `_ouvrir_flux()`.
- **`redemarrer()`** : après la fermeture de l'ancien flux (`ancien.stop()/close()`)
  et `_attendre_fermeture_differee()`, juste avant `_ouvrir_flux()`.
- **`resoudre_peripherique()` : NE PAS rafraîchir ici** — cette méthode peut être
  appelée pendant qu'un flux est ouvert. (Elle devient d'ailleurs inutilisée par la
  réunion après le correctif 2 — la laisser telle quelle, l'interface la garde.)
- `terminer()` / `arreter()` : aucun refresh (on ferme, on n'ouvre rien).

### Limitation à documenter en commentaire

Après un refresh, PortAudio peut **renuméroter les index**. Un `micro_index` stocké
en config peut donc viser un autre périphérique. Le repli existant de `_ouvrir_flux`
(échec sur index → périphérique par défaut) couvre l'échec franc ; le vrai fix
(stocker le *nom* du périphérique en config plutôt que l'index) est **hors périmètre**
— le noter en commentaire, ne pas l'implémenter. NB : sur la machine de dev
`micro_index` est `null` (défaut), le cas nominal n'est pas affecté.

---

## 3. Correctif 2 — ne jamais désarmer la reconnexion (réunion)

### Fichier
`src/debrief_meet/core/reunion.py` — `_sur_changement_peripherique` (lignes ~355-384)
et `_demarrer` (lignes ~148-156).

⚠️ **Règle d'or du projet** : `core/` n'importe jamais `sounddevice` ni aucun module
OS-spécifique. Toute la récupération passe par l'interface `CaptureMicro`
(`demarrer`/`redemarrer`/`recuperer_echantillons`), qui a déjà des implémentations
par défaut dans `platform/interfaces.py` — **aucun changement d'interface ni de
stubs n'est nécessaire**.

### Changements

1. **Le garde** devient : `if not self._actif: return` (supprimer `not self._avec_micro`).
2. **Supprimer la comparaison de noms** (`resoudre_peripherique` / `_micro_resolu`) :
   elle repose sur la table périmée, elle est donc pire qu'inutile. Toujours tenter
   la reconnexion à chaque signal `change` (déjà dé-rebondi à 300 ms par
   `SurveillantPeripheriques`). Coût : un trou de warm-up de 200 ms lors
   d'événements qui ne concernent pas notre entrée — accepté. Supprimer aussi
   l'attribut `_micro_resolu` et son affectation dans `_demarrer`.
3. **Deux cas dans le handler** :
   - `self._avec_micro` est True → `self._micro.redemarrer(micro_index)` (préserve
     le buffer, comportement actuel). Échec → `_avec_micro = False`, log warning,
     émettre `micro_perdu` (correctif 4). **Ne rien désarmer** : le prochain signal
     `change` retentera.
   - `self._avec_micro` est False → **tentative de récupération** :
     `self._micro.demarrer(micro_index)`. Succès → `_avec_micro = True`, activer la
     piste Moi si rétention (voir ci-dessous), émettre `micro_retabli`. Échec → log
     **debug** (pas warning : ne pas spammer à chaque événement tant que rien n'est
     branché), rester sans micro.
   - AEC : comportement actuel conservé (recalibrer après un `redemarrer` réussi si
     `self._aec` est actif). Si la réunion a démarré sans micro puis le récupère en
     cours de route, **ne pas démarrer l'AEC en cours de session** — limitation
     acceptée, la noter en commentaire.
4. **Factoriser** la logique de reconnexion dans une méthode privée
   `_recuperer_micro()` — elle sera aussi appelée par le watchdog (correctif 3).

### Piste Moi activable en cours de réunion

Aujourd'hui `EnregistreurAudioReunion` est construit avec `base_moi=None` quand le
micro est absent au démarrage → une récupération tardive n'aurait nulle part où
streamer. **Attention** : `_PisteWriter` lance ffmpeg **dès son constructeur** — il
ne faut donc PAS créer la piste Moi « au cas où » au démarrage (fichier vide + process
ffmpeg orphelin), mais l'activer paresseusement au moment de la récupération.

Dans `src/debrief_meet/core/fichiers.py`, ajouter à `EnregistreurAudioReunion` :

```python
def activer_moi(self, base: Path) -> None:
    """Attache la piste Moi en cours de session (récupération tardive du micro,
    cf. docs/25). No-op si la piste existe déjà."""
    if self._moi is None:
        self._moi = _PisteWriter(base, self.format, self._debit_kbps)
        self.chemin_moi = self._moi.chemin
```

(Il faudra conserver `debit_kbps` en attribut dans `__init__` — aujourd'hui il n'est
pas stocké.)

Côté orchestrateur : dans `_demarrer`, conserver `self._base_moi` (déjà calculé via
`chemins_audio_reunion(fichier)`) même quand `_avec_micro` est False, pour pouvoir
appeler `self._enregistreur.activer_moi(self._base_moi)` à la récupération (si
`self._enregistreur is not None`).

### Limitation acceptée (à noter en commentaire, pas à corriger)

L'en-tête du `.md` (`EcrivainReunion.creer(avec_micro=False)`) reste celui du
démarrage : une réunion démarrée sans micro puis récupérée gardera un en-tête
« sans micro ». Sans impact fonctionnel (la transcription des tranches suivantes
inclut bien le micro).

---

## 4. Correctif 3 — watchdog « tranche muette » (flux mort non détecté)

### Fichier
`src/debrief_meet/core/reunion.py` — `_capturer_tranche` (lignes ~250-273) et le
chemin des ticks.

### Principe

Un micro physiquement muet livre quand même des trames (des zéros). Un buffer
**vide** après une tranche entière (30 s par défaut) signifie que le callback
PortAudio n'a jamais été appelé → flux mort (cas typique : changement de
périphérique jugé à tort « inchangé » par l'ancienne logique, ou périphérique
disparu sans événement Qt). C'est le filet de sécurité derrière le correctif 2.

### Implémentation

- Dans `_capturer_tranche`, mesurer `n_micro = len(audio_micro)` **immédiatement
  après** `recuperer_echantillons()`, **avant** le passage AEC (l'AEC transforme le
  signal, la mesure doit porter sur le brut).
- Si `self._actif and self._avec_micro and n_micro == 0` → appeler
  `self._recuperer_micro()` (la méthode factorisée du correctif 2) : tentative de
  `redemarrer`, et en cas d'échec `_avec_micro = False` + `micro_perdu`.
- **Ne déclencher le watchdog QUE sur le chemin des ticks**, jamais depuis
  `_arreter()` (la dernière tranche peut être légitimement vide si l'utilisateur
  arrête juste après un tick). Implémentation suggérée : paramètre
  `surveiller: bool = False` sur `_capturer_tranche`, passé à True uniquement
  depuis `_sur_tick` (les deux branches : `_transcrire_tranche` et
  `_capturer_seulement`).
- Anti-boucle : aucune temporisation supplémentaire nécessaire — le watchdog ne
  peut se déclencher qu'une fois par tranche (30 s), c'est un rythme de retry sain.

---

## 5. Correctif 4 — rendre la panne visible (notifications)

**C'est le correctif qui aurait évité 5 réunions perdues** : l'icône rouge disait
« j'enregistre » alors que la piste Moi était morte.

### Fichiers
`src/debrief_meet/core/reunion.py`, `src/debrief_meet/ui/tray.py`,
`src/debrief_meet/__main__.py`.

### Implémentation

1. **Deux nouveaux signaux Qt** sur `OrchestrateurReunion` :

   ```python
   micro_perdu = Signal(str)     # message descriptif
   micro_retabli = Signal(str)
   ```

   Émissions :
   - `_demarrer` : échec de `self._micro.demarrer()` → `micro_perdu.emit(...)`
     (« Réunion démarrée sans micro — seule l'autre partie sera enregistrée »).
   - `_recuperer_micro` : échec de reconnexion après perte → `micro_perdu.emit(...)`
     (une seule fois par perte : ne pas ré-émettre si `_avec_micro` était déjà False) ;
     reconnexion réussie → `micro_retabli.emit(...)`.
2. **Tray** (`ui/tray.py`) : deux slots suivant le pattern des notifications de
   diarization (`_on_diar_termine`/`_on_diar_echoue`, lignes ~151-163) :
   `showMessage(titre, message, icone_pour_etat(EtatVisuel.ERREUR), 8000)` pour la
   perte, `EtatVisuel.TERMINE` pour le rétablissement. **Respecter
   `config.get("notifications")`** — vérifier ce que font les notifs diar : si elles
   ne testent pas ce réglage, ajouter le test dans les deux nouveaux slots seulement
   (ne pas toucher aux notifs diar, hors périmètre).
3. **Câblage** dans `__main__.py`, à côté des connexions `etat_visuel_change`
   existantes (lignes ~203-205).

### Hors périmètre (extension future, ne pas faire)

Icône systray distincte « enregistrement dégradé » (orange / rouge barré) — demande
un nouvel asset et un nouvel `EtatVisuel` ; la notification suffit pour cette passe.

---

## 6. Tests de non-régression (pytest, sans matériel)

Les tests existants utilisent des fakes (`tests/fakes/adapters.py`) et des
monkeypatch du module `sounddevice`. Suivre les patterns de
`tests/test_micro_sounddevice.py` et `tests/test_reunion.py`.

### `tests/test_micro_sounddevice.py`

1. `demarrer()` appelle `_terminate` puis `_initialize` sur le module sd factice,
   **avant** la création de l'`InputStream`.
2. `redemarrer()` : l'ancien flux est `stop()`/`close()` **avant** l'appel à
   `_terminate` (ordre vérifiable avec une liste d'événements partagée).
3. Séquence `arreter()` puis `demarrer()` immédiat : le flux en fermeture différée
   est fermé (event + join) avant le refresh — aucun flux vivant au moment de
   `_terminate`.
4. Module sd factice **sans** `_terminate`/`_initialize` (AttributeError) →
   `demarrer()` fonctionne quand même (le refresh est best-effort).

### `tests/test_reunion.py`

5. Signal `change` alors que `_avec_micro` est False (échec précédent) → une
   tentative `demarrer()` est faite sur le fake micro (plus de désarmement
   définitif) ; en cas de succès `_avec_micro` redevient True.
6. Réunion démarrée sans micro (fake qui lève à `demarrer`), puis récupération →
   `activer_moi` est appelé sur l'enregistreur avec le bon chemin, et les tranches
   suivantes streament la piste Moi.
7. Tranche vide au tick avec `_avec_micro` True → `redemarrer` tenté ; si le fake
   échoue → `micro_perdu` émis une seule fois.
8. Tranche vide lors de `_arreter()` → **aucune** tentative de reconnexion.
9. `micro_perdu` émis quand `_demarrer` échoue sur le micro ; `micro_retabli` émis
   à la récupération.
10. Plus de dépendance à `resoudre_peripherique` : deux signaux `change` successifs
    déclenchent deux `redemarrer` (la comparaison « inchangé — ignoré » a disparu).
    Adapter/supprimer les tests existants qui vérifiaient l'ancien comportement
    d'ignorance (chercher « inchangé » / `_micro_resolu` dans les tests).

### `tests/test_fichiers.py`

11. `activer_moi` après construction avec `base_moi=None` : la piste est créée
    (format wav en test, sans ffmpeg), `ecrire`/`terminer` fonctionnent,
    `chemin_moi` est renseigné. Second appel → no-op.

---

## 7. Critères de livraison

- `make test` : suite complète verte (530 tests actuels + les nouveaux). Rapporter
  la sortie.
- Aucun import OS-spécifique ni `sounddevice` dans `core/` (règle d'or, vérifiable
  par `grep -rn "sounddevice" src/debrief_meet/core/`).
- `platform/interfaces.py` et `platform/stubs.py` inchangés.
- Mettre à jour le tableau des docs dans `CLAUDE.md` (statut docs/25 → implémenté)
  et l'état des phases si pertinent.

## 8. Tests manuels post-livraison (Sylvain, hors CI)

1. Réunion en cours → débrancher/rebrancher le dock USB-C plusieurs fois →
   `_moi.opus` continue après chaque changement, notification en cas de perte.
2. App laissée ouverte plusieurs heures avec changements de périphériques
   (AirPods on/off, USB-C) → lancer une réunion → le micro démarre **sans relancer
   l'app** (c'était le scénario des 5 échecs du 2026-07-02).
3. Réunion démarrée sans aucun micro → notification « sans micro » → brancher un
   micro en cours de réunion → notification « rétabli » + piste Moi présente.
4. Les 2 tests manuels AirPods encore en attente de docs/20 (validation du taux natif).
