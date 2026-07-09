# Interco BlueMind — calendrier, invités, notifications de réunion

> **Statut : 🔄 implémentée (2026-07-09, Sonnet) — code + tests unitaires verts sans
> réseau (889 passed). Restent : tests d'intégration (`BM_TEST_URL/TOKEN/EMAIL`) et
> validation manuelle avec Sylvain sur serveur réel (§10).**
> Rédigée le 2026-07-08 (cadrage Sylvain + Fable).
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation (Sonnet).
> **Périmètre : brique commune (config, client REST, synchro calendrier offline) + 3
> fonctionnalités (association enregistrement ↔ réunion, mapping des locuteurs,
> notification de début de réunion). Multi-OS (pur Python + Qt, aucun code platform/).**
> Avant livraison : `make test` (tous les tests actuels + les nouveaux, tous verts,
> **sans réseau**).

---

## 1. Contexte et objectif

debriefMeet enregistre et transcrit des réunions ; BlueMind (messagerie collaborative,
employeur de l'utilisateur) connaît le calendrier : titres, horaires, **invités**
(nom + email + statut de réponse). L'interco enrichit les enregistrements avec ce
contexte, **nativement** dans l'app (pas de LLM ni de service tiers dans la boucle) :

1. **F1** — associer un enregistrement (existant ou en cours) à l'événement de calendrier
   qui lui correspond, et insérer en tête de transcription la liste des **invités
   (participants potentiels)** ;
2. **F2** — après diarization, aider à renommer `SPEAKER_00/01/…` avec les invités de la
   réunion associée ;
3. **F3** — notifier « la réunion X commence dans N min » avec démarrage de
   l'enregistrement en un clic, pré-associé à l'événement.

### 1.1 Contrainte transverse ABSOLUE : offline-first, jamais bloquant

C'est un critère d'acceptation, au même rang que la règle d'or des couches :

- **Toute I/O réseau vit dans un worker en tâche de fond** (jamais le thread UI),
  timeouts courts (connect 3 s, total 10 s). Échec réseau = log DEBUG + au plus un
  indicateur discret « dernière synchro : … » — **jamais de popup, jamais de spinner
  bloquant, jamais de retry agressif**.
- **Aucune fonctionnalité existante ne dépend du réseau** : l'Historique s'ouvre
  instantanément ; le matching (F1) et les notifications (F3) lisent la **réplique
  locale** du calendrier (§5), donc fonctionnent hors ligne sur les dernières données
  synchronisées.
- **BlueMind non configuré → interco invisible** : aucun bouton, aucune requête, aucun
  message. Strictement additif.
- Seules les actions **explicitement déclenchées par l'utilisateur** et impossibles sans
  réseau (ex. bouton « Tester la connexion » des Préférences) peuvent afficher une erreur
  — au clic, claire et actionnable.

## 2. Architecture

```
core/bluemind/            ← pur Python, aucun import OS-specific ni Qt (règle d'or OK)
├── __init__.py
├── client.py             # ClientBlueMind : httpx sync, auth X-BM-ApiKey, erreurs
├── identite.py           # résolution email → domain_uid/user_uid (au 1er usage, cachée)
├── sync.py               # SynchroCalendrier : changeset incrémental → store
├── store.py              # réplique locale SQLite (événements + méta de sync)
├── matching.py            # enregistrement (début, durée) → événements qui chevauchent
├── participants.py       # extraction invités d'un VEvent, bloc markdown, insertion idempotente
└── association.py        # sidecar <stem>.bluemind.json (lecture/écriture)

ui/
├── preferences_view.py   # + section « BlueMind » (§4)
├── capture_model.py      # + colonne/état « réunion associée » (F1)
├── actions_delegate.py   # + bouton « Associer à la réunion » (F1)
├── bluemind_association.py  # dialog choix événement + invités cochables (F1)
├── bluemind_mapping.py      # dialog mapping SPEAKER_XX → invités (F2)
└── tray.py               # + notifications de début de réunion (F3)

core/planificateur_reunions.py  # F3 : surveille la réplique, émet les notifications dues
```

- **HTTP : `httpx` en sync** (nouvelle dépendance, wheels purs, PyInstaller-friendly —
  à ajouter dans `[project].dependencies`). Les appels se font depuis des threads de
  fond (pattern QThread existant) ; pas d'asyncio dans une app Qt.
- Les workers Qt qui enveloppent `core/bluemind/` utilisent les helpers
  `arreter_thread`/`proteger_thread` de `core/arret_threads.py` (cf. docs/26) — un
  worker de sync ne doit jamais empêcher l'app de quitter.
- La réplique SQLite vit dans le dossier de données `platformdirs` (comme la config —
  **`appauthor=False`**, cf. CLAUDE.md), fichier `bluemind.sqlite3`.

## 3. Référence API BlueMind

- **Auth** : header `X-BM-ApiKey: <clé API personnelle>` sur toutes les requêtes.
  Base URL : `https://<serveur>/api` (le suffixe `/api` est **obligatoire** — valider à
  la saisie dans les Préférences).
- **Lib de référence** (lecture seule, ne PAS l'installer) :
***REMOVED***
  la bibliothèque Python interne de BlueMind, accessible aux salariés (dépôt interne).
  Compléments : le catalogue d'endpoints du projet frère
  `ENDPOINTS.md du projet frère bluemind-mcp` (mêmes conventions [réf]/[pressenti]).
- Endpoints utilisés ici :

| Op | Endpoint | Confiance |
|---|---|---|
| Identité : user par email | `GET users/{domain}/byEmail/{email}` ; fallback non-admin : `POST directory/{domain}/_search` (le `domain_uid` réel se déduit de `value.path`) | [réf] `bmapi/api.py:get_user` / `directory_search` |
| Calendriers de l'utilisateur | `POST containers/_manage/_list` (type `calendar`) ; défaut : `calendar:Default:{user_uid}` | [réf] `bmapi/api.py:get_user_calendars` |
| Événements par plage | `POST calendars/{cal_uid}/_search` avec `dateMin`/`dateMax` en BmDateTime `{iso8601, timezone, precision}` — retourne les VEventSeries **complets** (summary, dtstart/dtend, location, organizer, attendees avec `commonName`/`mailto`/`partStatus`, rrule) | [réf] `bmapi/models/calendar.py:search_events` |
| **Sync incrémentale** | changeset versionné du conteneur : `GET calendars/{cal_uid}/_changesetById?since={version}` → `{created, updated, deleted, version}` puis récupération des valeurs (`_mget` ou items complets) — **vérifier la forme exacte dans `bmapi/models/changeset.py` et `bmapi/directory/` (DirectorySync applique ce pattern)** | [pressenti] — **plan B** : re-`_search` complet de la fenêtre glissante (simple, correct, juste moins efficace) |

⚠️ Les événements **récurrents** : le `_search` par plage retourne les occurrences dans
la plage ; le changeset retourne les **séries**. En mode changeset, développer les
occurrences dans la fenêtre locale (rrule simple : FREQ/UNTIL/COUNT/BYDAY) ou, plus
simple, stocker les séries et interroger le store avec expansion à la lecture. Si trop
complexe en v1 : plan B (re-_search périodique) assumé — la correction prime.

## 4. Configuration (Préférences, section « BlueMind »)

Nouvelles clés `_DEFAUTS` (`core/config.py`) :

```python
"bluemind_url": "",            # https://bm.example.com/api — vide = interco désactivée
"bluemind_token": "",          # clé API personnelle
"bluemind_email": "",          # adresse de l'utilisateur
"bluemind_verifier_tls": True,
"bluemind_sync_minutes": 15,        # période du timer de sync (0 = triggers seuls)
"bluemind_fenetre_passe_jours": 90, # fenêtre de réplique : passé
"bluemind_fenetre_futur_jours": 30, #                        futur
"bluemind_notif_reunions": True,        # F3 : activer les notifications
"bluemind_notif_avance_min": 5,         # F3 : « commence dans N min »
"bluemind_notif_inclure_solo": False,   # F3 : événements sans autre invité
"bluemind_notif_inclure_refuses": False,# F3 : événements que j'ai refusés
"bluemind_notif_inclure_journee": False,# F3 : événements « journée entière »
```

UI Préférences : champs URL / email / clé API (masquée), case TLS, bouton
**« Tester la connexion »** (seul appel réseau autorisé à afficher une erreur — il
exécute la résolution d'identité §3 et affiche « Connecté : Prénom Nom <email> » ou
l'erreur), sous-section Notifications (filtres ci-dessus), et bouton
**« Réinitialiser la synchronisation »** (§5.1). La clé API est stockée dans
le JSON de config comme les autres réglages (fichier sous le profil utilisateur) —
pas de trousseau système en v1, documenter dans la notice.

## 5. Réplique locale du calendrier (`store.py` + `sync.py`)

Schéma SQLite :

```sql
CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT);       -- version changeset, derniere_sync, cal_uid
CREATE TABLE evenements (
  uid TEXT, cal_uid TEXT, debut_ms INTEGER, fin_ms INTEGER,  -- occurrence développée
  journee_entiere INTEGER, titre TEXT, lieu TEXT,
  organisateur_json TEXT, invites_json TEXT,                 -- [{nom, email, part_status, role}]
  mon_part_status TEXT,                                      -- statut de MA réponse (matché sur bluemind_email)
  serie_uid TEXT, json_complet TEXT,                         -- VEvent brut pour F1/F2
  PRIMARY KEY (uid, cal_uid, debut_ms)
);
CREATE INDEX idx_evt_plage ON evenements (debut_ms, fin_ms);
```

- **Périmètre v1 : le calendrier par défaut** de l'utilisateur (`calendar:Default:{uid}`).
  Extension multi-calendriers prévue par le schéma (`cal_uid`), pas d'UI en v1.
- **Déclencheurs de sync** (tous en fond, jamais bloquants) : ouverture de la fenêtre
  Historique ; démarrage d'un mode Réunion ; timer `bluemind_sync_minutes` ; clic
  « Tester la connexion ». Un seul worker à la fois (verrou — si une sync tourne, les
  déclencheurs sont ignorés).
- **Purge** : à chaque sync, supprimer les événements hors fenêtre glissante.
- Première sync = `_search` sur toute la fenêtre ; ensuite changeset (§3, avec plan B).

### 5.1 Reset total de la synchro

`SynchroCalendrier.reinitialiser()` : arrêter proprement un éventuel worker de sync en
cours (via le verrou §5), **supprimer toutes les lignes** (`evenements`, `meta` — y
compris version changeset, identité résolue en cache et registre anti-double-notification
de F3), puis relancer une première sync complète en tâche de fond si la config est
valide. Les sidecars `<stem>.bluemind.json` et les blocs déjà insérés dans les
transcriptions ne sont **pas** touchés (ce sont des données utilisateur, pas du cache).

Deux déclencheurs :
1. **Bouton « Réinitialiser la synchronisation »** dans les Préférences (§4), avec
   confirmation (« La réplique locale du calendrier sera effacée puis resynchronisée.
   Les transcriptions et associations existantes ne sont pas modifiées. ») — utile si
   la réplique semble incohérente ou après un gros changement côté serveur.
2. **Automatique** quand `bluemind_url` ou `bluemind_email` change dans les Préférences
   (changement de serveur ou de compte → la réplique et l'identité cachée sont
   invalides par construction). Un simple changement de clé API (renouvellement) ne
   reset pas.

Comme tout le reste : non bloquant — le reset vide le store immédiatement (opération
locale rapide), la resync se fait en fond ; entre les deux, l'app se comporte comme
« jamais synchronisé » (boutons F1 absents, pas de notifications F3).

## 6. F1 — Association enregistrement ↔ réunion, bloc invités

### 6.1 Matching (`matching.py`)

Pour un enregistrement : début = `date_heure_reunion(chemin)` et durée =
`duree_reunion(chemin)` (helpers existants de `core/fichiers.py`). Correspondance =
événements du store dont `[debut, fin]` **chevauche** `[début_enr, début_enr + durée]`
(tolérance ± 10 min pour les enregistrements lancés en avance/retard). Journées
entières exclues du matching. Plusieurs correspondances possibles → l'UI fait choisir.

### 6.2 UI Historique

- Détection **automatique et locale** (réplique) au chargement du modèle — aucun réseau
  sur ce chemin. Ligne avec correspondance ET sans association déjà faite → bouton
  **« Associer à la réunion »** dans la colonne actions (`actions_delegate.py`).
  Ligne déjà associée → indicateur discret (icône calendrier + titre en tooltip).
- Clic → dialog (`ui/bluemind_association.py`) : si plusieurs événements, liste de choix ;
  puis récapitulatif — titre, horaire, et **liste des invités cochables** (tous cochés
  par défaut ; l'utilisateur décoche les absents connus s'il veut). Boutons
  Valider / Annuler.

### 6.3 À la validation

1. Écrire le sidecar `<stem>.bluemind.json` (`association.py`) :
   ```json
   {"version": 1, "event_uid": "...", "cal_uid": "...", "titre": "...",
    "debut": "2026-07-08T14:00:00+02:00",
    "invites": [{"nom": "Jean Dupont", "email": "jean@ex.com", "part_status": "Accepted",
                  "organisateur": false, "coche": true}]}
   ```
   (source de vérité pour F2 et pour ne pas re-proposer le bouton).
2. **Insérer le bloc invités** en tête de `<stem>.md` **et** de `<stem>_locuteurs.md`
   s'il existe (sinon, il sera inséré à sa génération — hook dans le pipeline
   diarization) :

   ```markdown
   <!-- bluemind:invites v1 -->
   ## Invités à la réunion (participants potentiels — extrait du calendrier BlueMind, ne vaut pas liste de présence)
   Réunion : « Point projet X » — 2026-07-08 14:00
   - Sylvain Garcia <sylvain.garcia@bluemind.net> — organisateur
   - Jean Dupont <jean.dupont@example.com> — accepté
   - Marie Martin <marie.martin@example.com> — refusé
   - Paul Durand <paul.durand@example.com> — sans réponse
   <!-- /bluemind:invites -->
   ```

   ⚠️ L'en-tête « participants potentiels … ne vaut pas liste de présence » est
   **exigé explicitement** : un invité n'est pas forcément présent. Statuts traduits :
   `Accepted` → accepté, `Declined` → refusé, `Tentative` → provisoire,
   `NeedsAction` → sans réponse.
3. **Idempotence** : les marqueurs HTML `<!-- bluemind:invites -->` délimitent le bloc —
   re-valider remplace le bloc existant, jamais de doublon. Seuls les invités cochés
   sont écrits. Si le titre de la réunion est vide côté enregistrement (défaut = date),
   proposer d'appliquer le titre de l'événement via `definir_titre` (case cochée par
   défaut dans le dialog).

## 7. F2 — Mapping des locuteurs sur les invités

- **Point d'entrée** : après « Générer les locuteurs » (fin de la passe diarization),
  et action « Nommer les locuteurs » sur les lignes ayant un `_locuteurs.md`.
- Dialog (`ui/bluemind_mapping.py`) : une ligne par `SPEAKER_XX` détecté dans
  `_locuteurs.md`, avec ses 2-3 premières interventions en aperçu, et un combo éditable :
  invités du sidecar (F1) + « Moi (<bluemind_email>) » + saisie libre. Sans sidecar,
  saisie libre seule (le mapping reste utilisable sans BlueMind).
- **Heuristiques légères de pré-remplissage** (jamais silencieusement définitives,
  l'utilisateur voit et corrige) :
  - nb de locuteurs == nb d'invités « accepté » (+ organisateur) → pré-remplir dans
    l'ordre de temps de parole décroissant vs (organisateur, puis acceptés) ;
  - le locuteur au plus grand temps de parole → organisateur en première suggestion ;
  - 2 locuteurs et 1 seul autre invité accepté → « Moi » + cet invité.
- À la validation : réécriture de `_locuteurs.md` — chaque étiquette `SPEAKER_XX`
  remplacée par `Prénom Nom` (partout, y compris les horodatages de prise de parole).
  Le mapping est sauvé dans le sidecar (`"mapping": {"SPEAKER_00": "Jean Dupont", …}`)
  pour ré-affichage et ré-application si la diarization est relancée.

## 8. F3 — Notification de début de réunion

- `core/planificateur_reunions.py` : QTimer léger (tick 30 s, thread UI, lecture du
  store **locale et rapide** — pas de réseau au tick). À `debut - bluemind_notif_avance_min`,
  émettre une notification « "Point projet X" commence dans 5 min — cliquer pour
  enregistrer » (respecte le réglage global `notifications` ET `bluemind_notif_reunions`).
- **Filtre par défaut** : événements avec ≥ 1 autre invité, `mon_part_status != Declined`,
  hors journée entière — chaque exclusion étant débrayable par les clés
  `bluemind_notif_inclure_*` (§4).
- **Clic = démarrage immédiat** du mode Réunion, **pré-associé** : le sidecar
  `<stem>.bluemind.json` est écrit dès la création de l'enregistrement (invités tous
  cochés), le titre de l'événement est appliqué, et le bloc invités (§6.3) est inséré
  dans les fichiers dès leur création. F1 devient automatique pour ces enregistrements ;
  F2 a sa liste d'invités d'office.
- Ne jamais notifier deux fois le même (uid, occurrence) — table `meta` ou set persistant.
  Événement déjà commencé depuis > 5 min au moment du tick (app lancée en retard) → ne
  pas notifier. Si un mode est **déjà actif** au moment du clic : ne rien casser —
  notifier « un enregistrement est déjà en cours », ne pas démarrer.

### ⚠️ Piège — `messageClicked` de QSystemTrayIcon est ambigu

`tray.py:292` le documente déjà : le signal n'indique **pas quelle** notification a été
cliquée (et macOS n'offre pas de bouton d'action via Qt). Pattern imposé : le tray
mémorise `derniere_notif = ("reunion", event_uid, expire_ts)` à l'émission (expire =
début + 10 min) ; `_on_notification_cliquee` ne démarre l'enregistrement **que si** la
dernière notif est de type « reunion » et non expirée — sinon comportement actuel
(ouvrir le dernier job terminé). Toute autre notification émise ensuite écrase
`derniere_notif` (comportement voulu : on ne démarre jamais sur un clic douteux).

## 9. Pièges connus (hérités des projets frères, vérifiés)

- **`bluemind_url` doit finir par `/api`** — normaliser/valider à la saisie, message
  clair sinon (« l'URL de l'API BlueMind se termine par /api »).
- La résolution d'identité peut être **refusée à un non-admin** sur `users/byEmail` →
  fallback `directory/_search` obligatoire (§3) ; le `domain_uid` réel vient de
  `value.path`, pas de la partie droite de l'email.
- Dates BlueMind : le `_search` calendrier parle en **BmDateTime**
  `{iso8601, timezone, precision}` ; `precision: "Date"` (sans timezone) = journée
  entière. Convertir en epoch ms UTC pour le store, toujours comparer en UTC.
- Ne **jamais** faire d'I/O réseau dans les slots du thread UI — y compris « juste un
  HEAD » ; tout passe par les workers (§2).
- Workers : enregistrer via `proteger_thread`/`arreter_thread` (docs/26) — la sync ne
  doit pas retarder la fermeture de l'app.
- Le token dans la config JSON : fichier de profil utilisateur, ne jamais le logger
  (même en DEBUG — logger `X-BM-ApiKey: ***`).
- `httpx` avec `verify=False` émet des warnings — les filtrer proprement quand
  `bluemind_verifier_tls` est décoché.
- SQLite multi-threads : une connexion par thread (`check_same_thread` par défaut) —
  le worker de sync écrit, le thread UI lit ; WAL mode pour éviter les verrous.

## 10. Tests

`make test` (rapide, **sans réseau ni serveur**) :
- `matching.py` : chevauchements (avant/pendant/après, tolérance ±10 min, journée
  entière exclue, multi-correspondances) ;
- `participants.py` : bloc markdown (en-tête « participants potentiels » présent,
  statuts traduits, organisateur en premier), **insertion idempotente** (2 validations
  = 1 bloc), insertion dans les deux fichiers, fichiers absents ;
- `association.py` : sidecar lecture/écriture/version ;
- `store.py` + `sync.py` : appliquer un changeset simulé (created/updated/deleted),
  purge fenêtre, plan B re-_search ; serveur HTTP mocké (`respx` ou handler local) ;
- reset (§5.1) : store vidé (événements, version, registre notifs), sidecars et blocs
  insérés intacts, resync relancée ; reset auto sur changement d'URL/email mais **pas**
  sur changement de clé API ;
- heuristiques F2 : les 3 règles, et « aucune suggestion » quand rien ne colle ;
- planificateur F3 : dus/pas dus, filtres, double-notification interdite, expiration
  du clic ;
- client : mapping erreurs (401/403/404/timeout), URL sans `/api` refusée.

Marqueur `integration` (serveur BlueMind réel, variables `BM_TEST_URL/TOKEN/EMAIL`) :
résolution d'identité réelle, première sync + changeset réel, `_search` sur une plage
contenant un événement créé pour l'occasion.

**Validation manuelle** (avec Sylvain, serveur réel) : config Préférences + test de
connexion ; association d'un enregistrement existant ; bloc invités dans les 2 fichiers ;
mapping après diarization ; notification à H-5 et démarrage pré-associé en un clic ;
**débrancher le réseau et vérifier que tout l'existant + F1/F2 restent fonctionnels**.

## 11. Ordre d'implémentation

1. **Brique commune** : config §4 + section Préférences + `client.py` + `identite.py`
   + bouton « Tester la connexion ». → *Jalon : identité résolue contre le serveur réel.*
2. **Réplique** : `store.py`, `sync.py` (première sync `_search`, puis changeset avec
   plan B), déclencheurs + timer, worker protégé. → *Jalon : événements visibles dans
   le SQLite, sync coupée = app intacte.*
3. **F1** : `matching.py`, `association.py`, `participants.py`, bouton + dialog
   Historique, insertion. → *Jalon : bloc invités correct dans les 2 fichiers.*
4. **F2** : dialog mapping + heuristiques + réécriture `_locuteurs.md`.
5. **F3** : planificateur + notification + démarrage pré-associé (piège §8).
6. Finitions : notice utilisateur (README/docs), `make test` complet, passe
   d'intégration + validation manuelle.

## 12. Évolutions ultérieures — à spécifier séparément (hors périmètre v1)

- **Notifications natives avec boutons d'action** (« Enregistrer » / « Ignorer » sur la
  notification de début de réunion) : Qt/`QSystemTrayIcon.showMessage` ne sait pas le
  faire — nécessite une interface `Notifications` dans `platform/interfaces.py` + un
  adaptateur par OS (macOS : `UNUserNotificationCenter`, permission notification à
  demander, contrainte de signature/bundle id à vérifier vs docs/16 ; Windows : toasts
  WinRT). Lèvera aussi l'ambiguïté `messageClicked` (§8) puisque chaque action porte
  son identifiant. **À spécifier dans un doc dédié le moment venu** — la v1 (clic sur
  la notification + garde d'expiration) couvre le besoin en attendant.

## 13. Definition of Done

- Les 3 fonctionnalités opérationnelles sur macOS **et** Windows (aucun code
  platform-specific introduit) ;
- réseau coupé ou BlueMind non configuré : **zéro régression**, zéro dialogue d'erreur
  spontané ; sync et notifications silencieusement inertes ;
- bloc invités toujours porteur de la mention « participants potentiels … ne vaut pas
  liste de présence » ; insertion idempotente ;
- `make test` vert sans réseau ; tests d'intégration verts contre le serveur de test ;
- validation manuelle §10 faite avec l'utilisateur.
