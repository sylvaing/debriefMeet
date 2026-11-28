# 54 — Refonte de l'interface : une seule activité, moins de boutons

> Spécifiée le 2026-11-28 à partir d'une maquette interactive (22 écrans) :
> <https://claude.ai/artifact/WZJP3YaasT4XyH1fMSnf2n> (privée, à partager depuis la page).
> Statut : **spec, rien n'est implémenté**. La maquette fait foi pour l'aspect ; ce
> document fait foi pour le comportement et les règles.

## 1. Pourquoi

L'interface a grossi par ajouts successifs depuis la refonte design v2 : interco
BlueMind (docs/40), Mistral (docs/42), copie mise en forme (docs/51), ⌘T, mise à jour
(docs/53). Chaque fonctionnalité a apporté son bouton ou son entrée de menu, jamais
une réorganisation. Inventaire au 2026-11-28 (mode distant / local) :

| Élément | Aujourd'hui |
|---|---|
| Onglets de la fenêtre | 1 / 3 (Réunion, Dictée, Journal) |
| Zones cliquables par ligne de réunion | 6 (3 boutons, 2 flèches, ⋯) + l'icône calendrier |
| Entrées du menu ⋯ d'une réunion | 8 à 12 / jusqu'à 14, dont des doublons des boutons |
| Entrées du menu du tray | 5 / 7 |
| Sections des Préférences | 10 |

Ce n'est **pas** un problème de technologie : une interface native par OS a été
envisagée puis écartée (3 UI à maintenir pour une équipe d'une personne, et aucune
des pannes terrain de 2026 n'était liée à Qt). On reste sur PySide6.

Ce n'est pas non plus un problème de style : deux variantes ont été dessinées puis
écartées (style du design system BlueMind de l'organisation, style « moderne » en
Geist et neutres chauds). **Le style actuel est conservé** : IBM Plex, indigo
`C.ACCENT`, formes arrondies. Pas de mode sombre.

## 2. Décisions (Sylvain, 2026-11-28)

| # | Décision | Raison |
|---|----------|--------|
| 1 | **Dictée et Journal supprimés** ; le **mode local est conservé** | fonctionnalités non utilisées ; le local reste utile pour les réunions (Whisper + locuteurs) |
| 2 | Écran unique **liste + panneau de détail**, **aucun bouton sur les lignes** | la colonne d'actions grossissait à chaque fonctionnalité (régression du 2026-08-24 comprise) |
| 3 | **Une action principale par état** de réunion : Transcrire → Générer le CR → Copier le CR | le prochain geste est toujours évident |
| 4 | Menu ⋯ ramené aux actions **rares ou destructrices** | les actions fréquentes ont un bouton, le menu ne les répète plus |
| 5 | Filtres (Toutes / Sans CR / Non associées), groupes par période, sélection multiple | retrouver ce qui reste à traiter |
| 6 | Association BlueMind par **3 portes d'entrée** (§4.6) | elle était invisible dans la première maquette |
| 7 | Préférences **10 → 5 sections** | regrouper par sujet, pas par historique |
| 8 | Erreurs de traitement **dans le panneau**, pas en dialogue | l'information survit au changement de réunion |
| 9 | Icône de tray : les flashs « terminé » / « erreur » sont relayés par des **pastilles persistantes** | un flash de 3 s est perdu si on ne regardait pas |
| 10 | Mise à jour : badge + choix **« Redémarrer maintenant » ou « À la fermeture »** | ne jamais forcer un redémarrage |
| 11 | Pas d'affichage de la transcription **en direct** pendant l'enregistrement | pas prioritaire |
| 12 | Notifications **avec boutons d'action** : hors périmètre de cette refonte | `QSystemTrayIcon` ne les sait pas (§6) |

## 3. Avant / après

| | Aujourd'hui | Cible |
|---|---|---|
| Pages de la fenêtre | 3 + Préférences | 1 + Préférences |
| Zones cliquables par ligne | 6 | 0 |
| Entrées du menu ⋯ | 8 à 14 | 1 à 4 |
| Menu du tray | 5 à 7 | 4 (5 avec une mise à jour) |
| Sections des Préférences | 10 | 5 |
| Raccourcis globaux | 1 à 3 | 1 |

## 4. Écrans

### 4.1 Fenêtre principale

Barre du haut, de gauche à droite : logo + « debriefMeet » + numéro de version (+ la
pastille « Sur cet ordinateur » en mode local), **badge de mise à jour** (§4.13),
recherche, bouton principal **« Démarrer une réunion »**, engrenage (Préférences).

Plus d'onglets. Les Préférences restent une page de la même fenêtre (docs/50),
ouverte par l'engrenage, avec un retour « ← Réunions ».

### 4.2 Liste des réunions (volet gauche)

- **Filtres** en puces avec compteur : *Toutes*, *Sans CR* (état ≠ CR disponible),
  *Non associées* (pas de `bluemind.json`).
- **Groupes par période** : *Cette semaine*, *Semaine dernière*, puis par mois.
- **Ligne** : icône (réunion, ou icône du job en cours teintée `C.JOB` — comportement
  du 2026-08-24 conservé), titre, `date · durée`, petite icône calendrier si associée,
  pastille d'état.
- **États** : *Audio seul*, *Transcrit*, *CR disponible*, *CR en cours*,
  *Transcription…*, *Échec* (nouveau, §4.8). La ligne « En cours » de
  l'enregistrement reste en tête (sentinelle `Path()`, docs/43).
- **Sélection multiple** : ⌘-clic / ⇧-clic (Ctrl sous Windows/Linux).
- **Recherche** : sur le titre, comme aujourd'hui.
- **Suppr** supprime la sélection (après confirmation), **⌘T / Ctrl+T** retranscrit,
  **F2** renomme : raccourcis conservés, en contexte `WidgetShortcut`.

### 4.3 Panneau de détail (volet droit)

**En-tête** : titre (crayon → édition en place, §4.7), date longue et durée, puis
soit les **participants** de l'événement associé (clic = changer d'événement), soit
un bouton **« Associer à un événement BlueMind · N correspond »**.

**Barre d'actions** :

| État | Action principale (bouton plein) | Flèche | Puis |
|---|---|---|---|
| Audio seul | Transcrire | — | 📁 ⋯ |
| Transcrit | Générer le CR | choix ponctuel du prompt (≥ 2 prompts) | Copier la transcription ▾, 📁, ⋯ |
| CR disponible | Copier le CR | Mis en forme / Texte brut / Markdown | Copier la transcription ▾, 📁, ⋯ |
| CR en cours / Transcription… | indicateur « … en cours » (pas de bouton) | — | 📁, ⋯ |
| Échec | Réessayer / Corriger la clé (§4.8) | — | selon l'état précédent |

- « Copier la transcription ▾ » : clic = texte brut ; flèche = *Texte* ou *Fichier
  transcription.md* (`PressePapiers.copier_fichier()`).
- 📁 = « Ouvrir le dossier » (bouton icône avec `aria-label`/infobulle).
- **Mode local**, bouton supplémentaire selon l'avancement des locuteurs :
  *Identifier les locuteurs* → indicateur « Identification… » → *Nommer les
  locuteurs (N)* → (disparaît une fois nommés). Si le modèle de diarization n'est pas
  installé, « Identifier » ouvre l'assistant Locuteurs (§4.15).
- **« Générer le CR » sans clé Mistral** ouvre l'assistant Mistral au lieu d'un
  bouton grisé.

**Onglets** *Compte-rendu* / *Transcription* sous la barre d'actions, avec à droite
« Régénérer… » (onglet CR, si un CR existe ; choix du prompt puis confirmation) et
« Ouvrir dans l'éditeur ». **Aperçu** du texte en dessous, défilant.

Transcription affichée : en mode distant, `Moi` / `Les autres` (deux pistes) ; en
mode local, `Locuteur 1, 2…` puis les prénoms une fois nommés.

**Menu ⋯** :

| État | Entrées |
|---|---|
| Transcrit, CR disponible | Retranscrire (⌘T) — *« Retranscrire avec Mistral » en local* · Renommer les locuteurs *(local, si nommés)* · ── · Supprimer l'audio (garde le texte) · Supprimer la réunion (⌫) |
| Audio seul, en cours | Supprimer la réunion |

Disparaissent du menu (devenues boutons, intégrées au panneau ou mortes) : Copier la
transcription, Copier le fichier, Générer le CR, Ouvrir la transcription, Ouvrir le
CR, Copier le CR ×2, Révéler dans le dossier, Associer, Générer les locuteurs.

### 4.4 Sélection multiple

Le panneau remplace le détail par : « N réunions sélectionnées », la durée cumulée,
la liste des titres, et 3 boutons — *Supprimer l'audio (garde le texte)*,
*Supprimer les N réunions*, *Tout désélectionner*. Mention « Transcrire, générer ou
copier : une réunion à la fois » (pas de file de jobs, comme ⌘T aujourd'hui).
La `BulkActionBar` disparaît.

### 4.5 Pendant l'enregistrement

- Bouton de la barre → **« Arrêter · 00:23:41 »** (rouge).
- Ligne « En cours » en tête de liste, sélectionnée.
- Panneau : titre éditable, participants si associée automatiquement (« Modifier »),
  **bandeau chrono** (grand chrono + « Arrêter »), **deux vu-mètres** *Mon micro* /
  *Son de la visio*, et le rappel « L'enregistrement continue, même fenêtre fermée ».
- Vu-mètres : **nouveau**, à brancher sur une mesure de niveau par piste (cf. §8).
- Renommer reste **interdit** pendant l'enregistrement (handles audio ouverts,
  WinError 32 — docs/43).

### 4.6 Association BlueMind

Trois portes d'entrée :

1. **Automatique** : la notification « commence dans 5 min » démarre une réunion déjà
   associée (comportement actuel de `IconeTray._evenement_pre_associe`).
2. **Sous le titre** : « Associer… », ou clic sur les participants pour changer.
3. **Avant le CR** : « Générer le CR » sur une réunion non associée propose d'abord
   l'événement qui chevauche l'enregistrement (docs/42 §4.1, inchangé), avec
   « Générer sans associer » et « Associer et générer ».

Feuille d'association (overlay enfant de la fenêtre, docs/50) :
- **Attente** « Recherche des événements du <jour> dans votre agenda… » pendant la
  resynchro (`attendre_sync`), au lieu de la petite fenêtre séparée actuelle.
- Liste des événements du jour, celui qui **chevauche** l'enregistrement marqué.
- Case « Renommer la réunion « <titre> » ».
- Participants cochables avec compteur `(n/N)`, pré-cochage à seuil
  (`SEUIL_PRECOCHAGE`, docs/50) inchangé.
- **Aucun événement** : message dédié + « Voir toute la journée » / « Générer sans
  associer » (avant CR).

Le dialogue « Événement associé » (`bluemind_details.py`) disparaît : les
participants sont dans l'en-tête du panneau.

### 4.7 Renommer

Crayon ou F2 → champ en place à la place du titre, ✓ / ✕, **Entrée** valide,
**Échap** annule. Mention « Le dossier de la réunion est renommé aussi ». Passe par
`core/fichiers.renommer_dossier_reunion` ; un job de fond en cours reste couvert par
`resoudre_chemin_reunion` (docs/43 §16).

### 4.8 Erreurs de traitement

Affichées **dans le panneau**, en bandeau au-dessus des actions, et **persistantes**
tant qu'elles ne sont pas résolues ; la ligne passe à *Échec*. Plus de dialogue
`avertir()` bloquant pour ces cas.

| Cause | Ton | Message | Actions |
|---|---|---|---|
| 429 (saturation / quota, après repli découpage) | ambre | « Mistral est saturé pour le moment » — rien n'est perdu | Réessayer · Copier le détail |
| 402 (paiement, docs/42 §10.9) | rouge | « Votre compte Mistral demande un paiement » | Ouvrir la console Mistral ↗ · Réessayer |
| 401 / 403 (clé refusée) | rouge | « La clé Mistral a été refusée » | Corriger la clé (assistant Mistral, étape 3) |
| Aucun audio retenu | gris | « Aucun son exploitable dans cette réunion » | Vérifier le micro · Supprimer la réunion |

« Copier le détail » met dans le presse-papiers le message d'erreur complet (code,
motif `detail_429`…), pour le support.

### 4.9 Dialogues

Tous en `DialogueGabarit` (overlay, docs/50) :

| Cas | Boutons |
|---|---|
| Supprimer « <titre> » ? / Supprimer N réunions ? | Annuler · Supprimer (rouge) |
| Supprimer l'audio ? (+ place libérée) | Annuler · Supprimer l'audio |
| Remplacer le compte-rendu ? (cite le prompt) | Annuler · Remplacer |
| Remplacer la transcription ? (les noms de locuteurs sont à refaire, le CR n'est pas modifié) | Annuler · Retranscrire |
| Envoyer cette réunion à Mistral ? (premier envoi seulement) | Annuler · Envoyer |
| Recherche dans l'agenda / Aucun événement | §4.6 |
| Redémarrage nécessaire | bandeau dans les Préférences (§4.11), plus de dialogue |

Proposé, **à valider** : « Une réunion est en cours d'enregistrement » à la commande
Quitter (Continuer · Arrêter et quitter).

### 4.10 États vides

- **Aucune réunion** (après installation) : volet liste « Aucune réunion pour
  l'instant », panneau « Votre première réunion » en 3 étapes (démarrer — ⌃⌥⌘R,
  arrêter, générer le CR) + encart « Connecter votre agenda BlueMind ».
- **Recherche sans résultat** : « Aucune réunion ne contient « … » » + Effacer.
- **Filtre vide** : « Tout a son compte-rendu » + Voir toutes les réunions.

### 4.11 Préférences — 5 sections

| Section | Contenu |
|---|---|
| **Général** | Lancer à l'ouverture de session · Notifications · **Langue des réunions** · Raccourci « Démarrer une réunion » (modifiable, vide = désactivé) · Dossier des réunions · Mises à jour (auto + Vérifier maintenant + version) |
| **Transcription** | Où transcrire (en ligne / sur cet ordinateur) + bandeau « redémarrage » · *en local :* modèle Whisper, Transcrire pendant l'enregistrement, Reconnaître qui parle (statut + assistant), Toujours transcrire avec Mistral · Compte Mistral (clé, Tester, « M'aider à obtenir une clé ») + **Réglages avancés** repliés (modèles, durée max) · Audio (micro, annulation d'écho) |
| **Comptes-rendus** | Modèles de CR (liste, édition, défaut) · Lexique (interrupteur + tableau entendu → à écrire) |
| **BlueMind** | Connexion (serveur, email, clé, Tester, « M'aider à me connecter ») + **Avancé** replié (certificat TLS) · Rappel avant une réunion (délai + « quelles réunions ») |
| **Diagnostic** | Exporter le diagnostic · Journal détaillé · Ouvrir / Vider le journal · Resynchroniser le calendrier BlueMind |

Correspondance avec les 10 sections actuelles : Général → Général ; Transcription +
IA en ligne + Audio → Transcription ; Prompts + Lexique → Comptes-rendus ; BlueMind →
BlueMind ; Dossiers + Raccourcis → Général ; Journalisation → Diagnostic.

**Réglages retirés de l'interface** (la clé de config reste avec sa valeur par défaut
sauf mention) :

| Réglage | Sort | Raison |
|---|---|---|
| Intervalle réunion (`intervalle_reunion`) | retiré de l'UI | technique, personne n'y touche ; 30 s par défaut |
| Réinitialiser les défauts (raccourcis) | retiré | un seul raccourci |
| Exporter les logs (.zip) | remplacé | le diagnostic (docs/31) contient déjà les logs, secrets masqués |
| Journalisation + Logs détaillés | fusionnés en « Journal détaillé » | à trancher : `logs_actifs` toujours vrai, la case pilote `logs_debug` (§8) |
| Utiliser ce prompt à la copie | supprimé | sans effet depuis le 2026-08-21 |
| Dossier Journal, raccourcis Dictée / Journal | supprimés | §5 |

Corrections de libellés au passage : les infobulles qui renvoient à « Préférences ›
IA distante » et « Préférences › Audio » (diarization) visent désormais
« Transcription ».

### 4.12 Tray

**Menu** (3 états) :
- Repos : Démarrer une réunion (⌃⌥⌘R) · Ouvrir debriefMeet · Préférences… · ── · Quitter.
- Mise à jour disponible : idem + « Installer la mise à jour X… ».
- Pendant une réunion : titre + chrono (non cliquable) · Arrêter la réunion · Ouvrir
  debriefMeet · ── · Quitter. Ni Préférences ni mise à jour.

« Exporter le diagnostic… » quitte le tray (→ Préférences › Diagnostic).
Contraintes de plateforme inchangées : `setContextMenu()` obligatoire sous Linux,
proscrit sous macOS ; « Quitter » en `QAction` simple sous Linux (2026-08-24).

**Icône** (7 états, priorité Enregistrement › Traitement › Erreur › Résultat à voir
› Repos) :

| État | Rendu | Durée |
|---|---|---|
| Repos | monochrome (`TRAY_IDLE`, blanc sur bandeau sombre GNOME) | — |
| Enregistrement | rouge `TRAY_RECORDING` | pendant l'enregistrement |
| Traitement | orange `C.JOB` | pendant le job |
| Terminé | flash vert 3 s | puis « Résultat à voir » |
| **Résultat à voir** (nouveau) | repos + pastille bleue `C.ACCENT` | jusqu'à l'ouverture de la réunion concernée |
| **Erreur** (nouveau) | repos + pastille rouge | jusqu'à l'ouverture de la réunion en échec |
| Mise à jour | rien sur l'icône | — |

À porter par `ArbitreEtatVisuel`, qui arbitre déjà la priorité (enregistrement
prioritaire, docs du 2026-08-21) : il faut y ajouter un ensemble de réunions « à
voir » / « en échec », vidé quand la réunion est sélectionnée.

### 4.13 Mise à jour

Reprend docs/53, côté interface :
- **Badge** dans la barre : « Mise à jour X » → « Téléchargement N % » →
  « Redémarrer pour mettre à jour » (vert). Clic = popover, jamais de fenêtre qui
  s'impose.
- Popover : versions installée/nouvelle, notes de la Release, *Plus tard* /
  *Télécharger et installer* ; une fois prêt : *À la fermeture* (**nouveau**) /
  *Redémarrer maintenant*.
- **Échec** (téléchargement ou signature) : badge rouge « Mise à jour impossible »,
  *Réessayer* / *Télécharger depuis le site ↗* ; l'app installée n'est pas touchée.
- **Linux** : *Ouvrir la page de téléchargement ↗* + la commande `apt install`.
- **Pendant une réunion** : badge inactif « X après la réunion », notification
  différée à l'arrêt (`_maj_en_attente`, inchangé).

« À la fermeture » : le handoff installeur de docs/53 tourne déjà **après
`app.exec()`** ; il suffit de mémoriser le choix et de le déclencher au Quitter.

### 4.14 Notifications

Une par événement, jamais pendant une réunion sauf alerte audio : rappel BlueMind
(5 min avant), *Compte-rendu prêt*, *Transcription terminée*, *Aucun son capté
depuis 2 min*, *Mise à jour disponible* (à l'arrêt si une réunion était en cours).
**Cette refonte n'ajoute pas de boutons** aux notifications : le clic déclenche
l'action principale (ouvrir la réunion, démarrer l'enregistrement…), comme
aujourd'hui. Les boutons dessinés dans la maquette demandent des notifications
natives (§6).

### 4.15 Premier lancement et assistants

**Premier lancement** (`ui/premier_lancement.py`) : 1. clé Mistral (requise,
« Vérifier » + lien « Me guider pas à pas ») ; 2. agenda BlueMind (facultatif,
« Connecter mon agenda… ») ; rappel du raccourci ; *Commencer*. Le mode local devient
un lien discret « Je préfère transcrire sur cet ordinateur » au lieu d'un choix
radio. Les assistants s'ouvrent **dans la carte de bienvenue** (pas de dialogue
empilé), avec un retour.

**Assistants** — un seul gabarit (`ui/assistant_etape.py`, existant) : barre de
progression, illustration, explication, lien externe, champ, test, succès.

| Assistant | Statut | Étapes | Points d'entrée |
|---|---|---|---|
| Mistral | existe (`assistant_mistral.py`, illustrations conservées) | compte → clé → coller et vérifier → succès | premier lancement · Préférences › Transcription · « Générer le CR » sans clé · clé refusée (étape 3 directe) |
| Locuteurs | existe (`assistant_diarization.py`) | compte HF → licence → token → télécharger → succès | Préférences › Transcription (local) · « Identifier les locuteurs » sans modèle |
| **BlueMind** | **nouveau** | ouvrir son compte → créer une clé → serveur + email + clé, tester → succès | premier lancement · Préférences › BlueMind · échec de « Tester » (étape 3) |

Assistant BlueMind : le champ serveur accepte l'adresse du webmail et **ajoute `/api`
lui-même** (l'erreur du diagnostic de Cyril, 2026-09-11) — changement côté client
BlueMind, pas seulement d'écran.

## 5. Retrait de la Dictée et du Journal

| Quoi | Où |
|---|---|
| Orchestrateurs | `core/dictee.py`, `core/journal.py` (importés seulement par `__main__`) |
| Vues | `ui/dictee_view.py`, `ui/journal_view.py` ; pages et boutons de `fenetre_principale.py` |
| Modes | `Mode.DICTEE`, `Mode.JOURNAL` dans `core/modes.py` ; `_LABELS_DEMARRER` de `capture_action_bar.py` ; paramètres de `RecordingController` |
| Prédicat | `mode_transcription.avec_dictee_journal()` |
| Modèle | `_ENTETES_JOURNAL`, `_LigneJournal` dans `capture_model.py` |
| Raccourcis globaux | Dictée et Journal dans `core/raccourcis.py` |
| CLI / IPC | `--toggle`, `--toggle-journal` dans `__main__.py` (garder `--toggle-reunion`) |
| Tray | entrées Démarrer/Arrêter Dictée et Journal |
| Préférences | éditeurs de raccourcis Dictée/Journal, dossier Journal, mention dans la note du mode local |
| Config | `dossier_journal`, `raccourci_dictee`, `raccourci_journal` |
| Tests | `test_dictee.py`, `test_dictee_view.py`, `test_journal.py`, `test_journal_view.py` supprimés ; à adapter : `test_capture_action_bar`, `test_config`, `test_fenetre_principale`, `test_maj_ui`, `test_mode_transcription`, `test_modes`, `test_preferences_view`, `test_raccourcis`, `test_recording_controller`, `test_reunion_view`, `test_tray` |

**Migration config v7** (`VERSION_COURANTE` 6 → 7) : retire les trois clés et
resauvegarde (comme v2). **Ne touche jamais au dossier du journal sur le disque** :
les fichiers `AAAA-MM-JJ.md` de l'utilisateur restent où ils sont.

Les raccourcis bureau créés avant (`--toggle`, `--toggle-journal`) doivent finir
silencieusement : la garde IPC de `__main__` les ignore déjà en mode distant, elle
les ignorera dans tous les modes.

## 6. Points techniques et pièges connus

- **La colonne d'actions disparaît** avec `ActionsDelegate` sur les réunions,
  `NB_BOUTONS_REUNION` / `NB_FLECHES_REUNION` et les tests de largeur associés
  (2026-08-24, docs/51). Les tests d'**effet** des actions (copier, générer, ⌘T)
  doivent être portés sur le panneau, pas supprimés.
- **`ReunionView.recharger()` reste le point de rechargement unique** (2026-08-24) :
  le panneau doit se rafraîchir par lui aussi, sinon il se périme au premier
  rechargement venu du watcher ou d'une association.
- **`PAIRES_FIN`** d'`ArbitreEtatVisuel` : les nouveaux états (à voir, échec) se
  câblent sur les mêmes paires de signaux, le test qui parcourt les vraies classes de
  gestionnaires reste le garde-fou.
- **Erreur persistante** : il faut un endroit où la mémoriser par réunion
  (`CaptureModel`, comme `definir_job_en_cours`) — voir §8 pour la durée de vie.
- **Notifications à boutons** : `QSystemTrayIcon.showMessage` n'envoie qu'un titre
  et un texte, et `messageClicked` ne dit même pas quelle notification a été
  cliquée (l'app mémorise la dernière, `_derniere_notif`). Des boutons demandent
  UNUserNotification (macOS), les toasts (Windows), le portail XDG (Linux) — chantier
  natif séparé.
- **Pastille sur l'icône de tray macOS** : l'icône n'est pas un « template » dès
  qu'elle est colorée ; il faut composer l'image (icône + pastille) nous-mêmes, pour
  chaque état et pour le bandeau sombre GNOME.
- **Rendre les écrans offscreen et les regarder** (méthode du 2026-09-02) : la
  plupart des défauts de cette famille sont invisibles à la lecture du code.

## 7. Découpage en chantiers

Chaque chantier est livrable et vert indépendamment, dans cet ordre :

1. **Retrait Dictée / Journal** + migration v7 — aucun autre changement visible.
2. **Liste + panneau de détail** : filtres, groupes, en-tête, barre d'actions, onglets
   et aperçu, menu ⋯ réduit, renommage en place, sélection multiple. Le cœur.
3. **Erreurs dans le panneau** + état *Échec* + dialogues revus (§4.8, §4.9).
4. **Préférences en 5 sections** + réglages remis/retirés + bandeau de redémarrage.
5. **Association** : feuille avec attente intégrée et cas « aucun événement ».
6. **Tray** : menu à 3 états, icône à pastilles.
7. **Mise à jour** : « À la fermeture », échec, Linux, pendant une réunion.
8. **Enregistrement** : bandeau chrono + vu-mètres.
9. **Premier lancement, états vides, assistants dans la carte**, puis assistant
   BlueMind (après relevé des libellés, §8).

## 8. Ouvert

- **Libellés du webmail BlueMind** (« Mon compte › Clés API ») : supposés, à relever
  sur un vrai serveur avant de dessiner les illustrations de l'assistant.
- **Vu-mètres** : vérifier qu'une mesure de niveau par piste existe déjà (celle qui
  alimente « Aucun son capté » ?) ou l'ajouter sans charger le callback audio
  (piège du GIL, docs/48 §8.4).
- **Journalisation** : une seule case dans l'UI pour deux clés (`logs_actifs`,
  `logs_debug`) — garder `logs_actifs` toujours vrai ?
- **Durée de vie de l'état *Échec*** : mémoire de session seulement, ou sidecar dans
  le dossier de la réunion (survit au redémarrage) ?
- **Propositions de la maquette non validées** : dialogue « Quitter pendant un
  enregistrement » ; libellé exact de l'état *Échec*.
- **Notifications natives** (boutons d'action) : à spécifier dans un document à part.

## 9. Références

Maquette : <https://claude.ai/artifact/WZJP3YaasT4XyH1fMSnf2n>. Docs liées : 31
(diagnostic), 40 (BlueMind), 42 (Mistral, §4.1 association avant CR, §10.9 erreur
402), 43 (dossiers, renommage pendant un job), 45 (mode de transcription), 46
(lexique), 50 (dialogues, pré-cochage), 51 (copie mise en forme), 53 (mise à jour).
