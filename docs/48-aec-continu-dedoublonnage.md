# 48 — Écho non annulé & transcriptions en double (AEC continue + dédoublonnage)

> **Statut : 📋 SPEC à implémenter** — rédigée le 2026-08-06 après diagnostic terrain
> le jour même (3 réunions réelles sur le Mac de Sylvain + logs de Alix).
> **Besoin :** en réunion sans casque, la voix des correspondants sort des
> haut-parleurs, entre dans le micro, et l'AEC censée la retirer **ne retire rien**.
> Résultat : quasi toutes les phrases du correspondant sont transcrites **en double**
> (« Moi » puis « Participants »), la transcription est illisible et le CR Mistral
> travaille sur un texte pollué (attribution des propos fragilisée, cf. l'incident
> « Rob/Bastien » du CR un client).

---

## 1. Constat terrain (2026-08-06, mesures)

Méthode : corrélation d'enveloppe log-RMS (trames 50 ms) entre `moi.opus` et
`systeme.opus`, meilleure corrélation par fenêtre de 10-20 s sur un balayage de
délais ±1,5 s ; croisée avec les logs DEBUG de l'AEC (`att` par tranche de 30 s).

| Réunion (Mac Sylvain) | Décalage micro↔système mesuré dans les fichiers | Calibration AEC (logs) | Atténuation AEC |
|---|---|---|---|
| 10h04 — visio, haut-parleurs | **+300 → +450 ms**, dérive ~150 ms sur 20 min | +463 ms (plausible) | −0,17 à −1,06 dB |
| 11h01 — visio, haut-parleurs, 2 personnes en salle | **+700 ms constant** (57 fenêtres, zéro dérive) | **−358 ms** (verrou parasite : vrai décalage hors fenêtre ±600 ms) | −0,2 à −0,6 dB |
| 15h29 — appel téléphonique | quasi aucun recouvrement | « système silencieux » → passthrough | n/a |

Le poste Windows de Alix montre le même profil (calibration −333 ms, att
−0,2/−0,5 dB). Une AEC efficace retire 10 à 30 dB : **sur le terrain, la nôtre n'a
jamais rien annulé**. Convention de signe : décalage positif = le même contenu
apparaît sur la piste système *après* la piste micro.

Lecture des décalages :
- le décalage entre pistes **varie d'une réunion à l'autre** (300 à 700 ms) — course
  au démarrage entre les deux chaînes de capture (micro sounddevice vs helper SCK /
  loopback WASAPI), figée pour la durée de la réunion ;
- il **dérive en cours de réunion** (~150 ms/20 min à 10h04, ≈ 125 ppm) — horloges
  distinctes des deux chaînes ;
- éliminations vérifiées auprès de Sylvain : pas de 2ᵉ appareil dans la salle
  (un collègue sans micro ni HP), correspondant au casque → ni retour visio, ni écho
  distant. La duplication est bien la **fuite locale HP → micro**, que l'AEC laisse
  passer.

## 2. Causes racines

1. **Calibration one-shot** (`core/aec.py::_tenter_calibration`) : le délai est
   estimé une fois puis l'alignement est figé (sauts de début de buffers). Toute
   dérive ultérieure le périme — AEC3 n'absorbe la dérive fine qu'autour d'un
   alignement à peu près juste (< ~100 ms), pas 150 ms qui s'accumulent.
2. **Fenêtre de recherche ±600 ms** (`DELAI_MAX_MS`) : le décalage réel peut la
   dépasser (700 ms mesurés). La cross-corrélation trouve alors un pic secondaire
   (−358 ms), la porte qualité (pic/médiane ≥ 10) ne protège pas contre un pic
   *parasite* net, et l'alignement appliqué est faux.
3. **Décalage d'ingestion non maîtrisé** : les deux flux entrent dans l'AEC (et dans
   les écrivains Opus) avec un offset de démarrage jamais mesuré ni compensé — c'est
   lui qui consomme l'essentiel de la fenêtre de recherche et qui varie par réunion.

## 3. Objectifs / non-objectifs

**Objectifs :**
- O1 — plus aucune phrase dupliquée dans la transcription fusionnée, même quand
  l'acoustique fuit (étape A, indépendante de l'AEC) ;
- O2 — une AEC qui annule réellement (≥ 10 dB sur écho synthétique réaliste :
  délai 700 ms + dérive 125 ppm) et qui **journalise** son efficacité ;
- O3 — ne jamais dégrader la voix : en cas de doute, passthrough (principe existant,
  conservé tel quel).

**Non-objectifs :** diarization, séparation de sources, traitement du cas « écho
renvoyé par le poste d'en face » au niveau AEC (l'étape A le couvre de fait au
niveau texte), refonte du helper SCK.

## 4. Conception

### 4.1 Étape A — Dédoublonnage à la fusion Moi/Participants

Point d'entrée unique : `core/fichiers.py::_entrelaces` (utilisé par
`core/mistral/fusion.py` **et** `core/transcription_differee.py` — les deux
pipelines en bénéficient d'un coup).

Règle : avant l'entrelacement, pour chaque segment de la piste micro, s'il existe
sur la piste système un segment dont le début est à **±3 s** et dont le texte
normalisé (minuscules, ponctuation et espaces réduits) a une similarité
`difflib.SequenceMatcher.ratio() ≥ 0,8`, le segment **micro** est écarté.

- **Pourquoi écarter la copie micro** : le cas mesuré est la fuite HP→micro — la
  piste système est la source dédiée de la voix distante. Dans le cas symétrique
  (écho distant : sa propre voix revenant sur la piste système), les deux copies
  sont quasi identiques : en supprimer une, n'importe laquelle, donne le même texte
  final — la règle reste donc sûre.
- **Garde anti-faux-positifs** : ne s'applique qu'aux segments d'au moins
  **25 caractères** normalisés — « Oui. », « Ça marche. » prononcés par les deux
  camps à 2 s d'écart sont des répétitions légitimes, jamais écartées.
- La fenêtre ±3 s couvre le décalage inter-pistes mesuré (700 ms) + la granularité
  des segments Voxtral/Whisper (débuts de phrases coupés différemment) + marge.
- Journaliser en DEBUG chaque segment écarté (« doublon inter-pistes ») avec les
  deux timestamps — c'est la télémétrie de terrain de l'étape B.

### 4.2 Étape B — AEC : alignement continu

On garde AEC3/LiveKit, la marge de lead (40 ms) et toutes les portes de sécurité.
Trois changements dans `core/aec.py` :

1. **Fenêtre initiale élargie** : `DELAI_MAX_MS` 600 → **1500 ms**. Le commentaire
   actuel (« au-delà = faux verrou ») visait l'acoustique seule ; le décalage
   d'ingestion s'y ajoute et domine.
2. **Ré-estimation périodique** : à chaque tranche (30 s), ré-estimer le délai par
   cross-corrélation **d'enveloppe** (trames 50 ms — coût négligeable, quelques ms)
   sur les 12 dernières secondes, avec la même porte qualité. Si l'écart au délai
   courant dépasse **±80 ms** sur 2 estimations consécutives concordantes,
   ré-aligner (mêmes sauts amortis qu'à la calibration initiale) ; en deçà, laisser
   l'estimateur interne d'AEC3 absorber. Une estimation de mauvaise qualité ne
   change rien (on garde l'alignement courant).
3. **Télémétrie d'efficacité** : l'`att` par tranche existe déjà — ajouter un
   compteur : si la référence est active et que l'atténuation reste < 3 dB pendant
   5 tranches consécutives, logguer un WARNING unique « AEC inefficace (att
   moyenne X dB) — vérifier l'alignement » avec le délai courant. C'est ce qui nous
   a manqué pendant un mois : l'échec était dans les logs, mais en DEBUG et sans
   seuil.

### 4.3 Étape C — Mesurer (puis compenser) l'offset d'ingestion

Dans `core/reunion.py`, horodater le **premier échantillon reçu** de chaque piste
(micro, système) et logguer l'écart en DEBUG — sur la même base d'horloge
(`time.monotonic()`). Deux usages :
- vérifier sur les prochains diagnostics que l'offset mesuré dans les fichiers
  correspond bien à l'offset d'ingestion (validation du modèle §2.3) ;
- si confirmé, compenser à la source : jeter le backlog initial de la piste en
  avance (côté AEC) et **padder de silence** le début de la piste en retard (côté
  écrivains Opus) pour des fichiers alignés. La compensation est un 2ᵉ temps —
  la mesure seule suffit pour l'étape B.

## 5. Validation

- **Tests unitaires étape A** : paires de segments synthétiques (doublon net,
  doublon avec variantes de transcription type « Rob calme »/« Bastien calme »,
  répétition courte légitime, segments hors fenêtre) — aucun corpus réel en dépôt
  (les transcriptions réelles restent hors git, cf. règle de confidentialité).
- **Tests unitaires étape B** : écho synthétique (voix = bruit filtré) injecté à
  délai 700 ms + dérive 125 ppm → exiger att ≥ 10 dB après convergence ; délai hors
  fenêtre initiale puis revenu → re-calibration ; référence silencieuse →
  passthrough inchangé.
- **Validation terrain** : rejouer les paires `moi.opus`/`systeme.opus` du
  2026-08-06 (conservées sur le poste de Sylvain) dans un harnais hors-app
  (`spike/aec_terrain/`, à créer sur le modèle des spikes existants) : atténuation
  mesurée avant/après, et zéro doublon sur la fusion de la réunion de 11h01.

## 6. Ordre d'exécution & risques

Ordre : **A** (petit, gain immédiat, indépendant) → **C-mesure** (2 lignes de log)
→ **B** (AEC) → **C-compensation** (si le modèle est confirmé).

Risques et garde-fous :
- sur-suppression à la fusion → seuils conservateurs (0,8 / 25 caractères / ±3 s),
  tout écart journalisé ;
- ré-alignements intempestifs de l'AEC → hystérésis (2 estimations concordantes),
  et un ré-alignement au pire ramène au comportement actuel (pas d'annulation
  pendant la re-convergence, jamais de voix perdue) ;
- coût CPU : corrélation d'enveloppe sur 12 s en trames de 50 ms ≈ 240 points par
  lag — négligeable, mais tout tourne sur le MainThread (comme aujourd'hui) : à
  chronométrer dans les jalons DEBUG du démarrage/tick ;
- ne rien changer pour Dictée/Journal (AEC réunion uniquement, inchangé).

## 7. Questions ouvertes

1. Étape A : faut-il marquer les doublons écartés dans le `.md` (commentaire HTML)
   plutôt que les supprimer silencieusement ? (traçabilité vs lisibilité)
2. Étape B : faut-il persister le délai calé en config (par « profil » de sortie
   audio) pour accélérer la convergence des réunions suivantes ? À trancher après
   les mesures C (si l'offset est bien dominé par la course au démarrage, un délai
   persistant n'a pas de sens).
3. Le seuil de similarité 0,8 est-il robuste aux transcriptions très divergentes
   des deux captations (micro réverbérant) ? À ajuster sur les logs DEBUG de
   l'étape A avant de resserrer/relâcher.
