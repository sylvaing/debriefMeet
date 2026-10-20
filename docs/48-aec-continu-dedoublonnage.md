# 48 — Écho non annulé & transcriptions en double (AEC continue + dédoublonnage)

> **Statut : 🔄 étapes A, B et C-mesure implémentées** (2026-08-06, 1323 passed) —
> dédoublonnage à la fusion (`_sans_doublons_inter_pistes`), AEC à ré-estimation
> périodique + WARNING d'écho résiduel, mesure de l'offset d'ingestion à la 1ʳᵉ
> tranche. **Validées en réunion réelle le 2026-08-10** (att médiane −6,5 dB, 0 doublon),
> après 2 correctifs sur retours terrain (`0eb4f19` concordance de dérive, `4840c81`
> faux positif du WARNING). **Rechute le 2026-08-18 → §8** : le délai calé se périme en
> cours de réunion et le suivi incrémental met 20 min à rattraper — désormais
> l'inefficacité constatée déclenche un **recalage complet**, et le dédoublonnage gagne un
> critère d'**inclusion directionnelle** (1423 passed). **Contre-analyse du même jour
> (§8.4)** : l'offset ne dérive pas, il **saute** (pertes d'échantillons de la chaîne
> micro) — comblement des trous par silence dans le callback micro (= la
> C-compensation, faite à la source) + exigence de qualité relevée pour bouger
> l'alignement. Reste : rejouer une réunion réelle avec l'ensemble.
> Spec rédigée le 2026-08-06 après diagnostic terrain le jour même (3 réunions
> réelles sur le Mac de Sylvain + logs de Alix).
> **Besoin :** en réunion sans casque, la voix des correspondants sort des
> haut-parleurs, entre dans le micro, et l'AEC censée la retirer **ne retire rien**.
> Résultat : quasi toutes les phrases du correspondant sont transcrites **en double**
> (« Moi » puis « Participants »), la transcription est illisible et le CR Mistral
> travaille sur un texte pollué (attribution des propos fragilisée, cf. l'incident
> « X/Y » d'un CR client du 2026-08-06).

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
  doublon avec variantes de transcription type « Rob calme »/« Bob calme »,
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
- **Méthode de diagnostic post-mortem** (éprouvée le 2026-08-18, §8.1, sans rien ajouter
  au dépôt) : `moi.opus` étant le micro **après AEC**, sa corrélation croisée avec
  `systeme.opus` par fenêtres de 60 s mesure directement l'échec (0,01 quand l'AEC marche,
  0,10-0,46 quand elle ne marche plus, et le lag réel en prime). Un FIR aux moindres carrés
  sur ce même micro nettoyé dit ensuite si l'écho restant était **linéairement** annulable
  — donc s'il s'agit d'un défaut d'alignement ou d'une non-linéarité — avec, comme contrôle
  négatif gratuit, une fenêtre où l'AEC fonctionnait (0,0 dB retirable).

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
3. ~~Le seuil de similarité 0,8 est-il robuste aux transcriptions très divergentes
   des deux captations (micro réverbérant) ?~~ **Répondu le 2026-08-18 (§8.3) : non.**
   Le problème n'est pas la divergence des mots mais celle du **découpage** — un segment
   est un fragment de l'autre et le ratio global s'écroule (0,74 et 0,38 mesurés sur des
   doublons manifestes). Le seuil de 0,8 est conservé tel quel et **complété** par un
   critère d'inclusion directionnel en mots. Nouvelle limite connue, elle aussi mesurée :
   un doublon à 0,70 d'inclusion et un tour légitime à 0,71 sont indiscernables — aucun
   critère lexical ne les séparera, seul le fait de ne pas avoir d'écho le fera.

## 8. Rechute du 2026-08-18 — le délai calé se périme en cours de réunion

Réunion de chantier avec un client (53 min, micro interne du MacBook Air, sortie sur
haut-parleurs). À partir de la ligne 260 de la transcription, la voix du
correspondant apparaît **sur les deux pistes** : le contenu reste complet mais
l'attribution ne vaut plus rien. Pas de rapport avec la diarisation — aucune n'a
tourné (mode distant, 2 pistes Voxtral).

### 8.1 Mesures

| créneau | 14:35 | 14:40 | **14:45** | 14:50 | 14:55 | **15:00** | **15:05** | **15:10** | **15:15** | 15:20 | 15:25 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| atténuation moyenne (dB) | 16,2 | 31,3 | 3,5 | 5,1 | 9,0 | **0,6** | **0,9** | **1,4** | **0,7** | 5,2 | 4,2 |

- Médiane sur la réunion : **1,7 dB** (contre −6,5 dB validés le 2026-08-10) ;
  46 tranches sur 107 sous 1 dB.
- Corrélation croisée micro **nettoyé** ↔ référence : 0,01 avant la minute 25, puis
  **0,10 à 0,46 à un décalage stable de ~25 ms** jusqu'à la minute 45, puis 0,01 —
  l'écho traverse l'AEC intact. ⚠️ Ce ~25 ms est mesuré **entre les fichiers**, or
  `moi.opus` a perdu 343 ms en tête (le saut micro de la calibration, §8.4) : en
  temps de capture, l'offset réel de cette fenêtre est **~315 ms**.
- Un FIR 256 taps aux moindres carrés retire encore **4 à 5,6 dB** du micro nettoyé
  dans cette fenêtre, contre **0,0 dB** à la minute 5 (contrôle négatif sur données
  réelles) : le résidu est **linéairement prédictible** depuis la référence, donc ce
  n'est ni une saturation ni une non-linéarité — c'est un défaut d'alignement.
- Confirmation indépendante : la détection de silences voit un bloc d'activité micro
  **continu de t=1557 s à t=2901 s** — le micro « parle » 22 minutes d'affilée.
- Densité de duplication : 0 % avant la ligne 250, puis 33 → 41 → **68 → 71 %**
  (lignes 350-450), retour à 0 % après la ligne 500.

### 8.2 Cause

Le délai est calé une fois, à la 1ʳᵉ tranche : **6135 éch (383 ms)**, qui est
l'offset d'ingestion mesuré au même instant (+373 ms) — et il était **juste** : les
tranches 4 à 22 (min 2-11) montrent −25 à −40 dB d'annulation, la preuve d'un verrou
correct (première lecture corrigée par §8.4 : le calage initial n'était pas prématuré).
Vers la minute 12, l'offset **saute de ~68 ms** (perte d'échantillons de la chaîne
micro, §8.4) : la référence se met à arriver ~28 ms **après** l'écho (la marge de lead
n'est que de 40 ms), le filtre devient non causal → **0 dB instantané**. Une AEC3
tolère une référence en avance de ~200 ms, pas 10 ms de retard. Le suivi de dérive (§4.2) ne rattrape pas — sa garde de
concordance, indispensable contre la fuite du 2026-08-07, exige deux mesures
consécutives concordantes à la cadence d'une tranche : **deux ré-alignements
seulement**, à 15:19 et 15:23 (6135 → 4462 → 1376 éch). Juste après, l'atténuation
remonte à 5,2 puis 4,2 dB de moyenne : le bon geste est arrivé 20 minutes trop tard.

Le WARNING « AEC inefficace » a bien été émis (15:03, −0,5 dB) — l'instrumentation de
§4.2 a fait son travail — mais **rien ne l'écoutait** : `recalibrer()` n'était appelé
que sur une reconnexion micro.

### 8.3 Correctifs

1. **`core/aec.py` — l'inefficacité déclenche un recalage complet.** Au bout de
   `ECHO_RESIDUEL_TRANCHES`, on ne se contente plus de journaliser : le délai est
   remesuré **sans partir du délai courant** (le suivi incrémental, lui, reste borné
   par sa garde de concordance). Coût : le rebut du reliquat des buffers (< 1 s de
   micro), payé au moment où l'AEC ne sert déjà plus à rien. Borné à
   `RECALIBRAGES_AUTO_MAX = 3`, après quoi un WARNING terminal constate que l'écho
   n'est pas un problème d'alignement. Le budget est neuf à chaque `demarrer()` et à
   chaque `recalibrer()` manuel (chemin d'écho réellement différent).
2. **`core/fichiers.py` — dédoublonnage par inclusion.** Le ratio global de §4.1 a
   écarté 42 doublons sur cette réunion et laissé passer les autres : Voxtral ne
   découpe pas l'écho aux mêmes frontières, donc un segment est souvent un **fragment**
   de l'autre (ratios mesurés 0,74 et 0,38 sur des doublons manifestes ; l'heuristique
   « junk » de difflib, active au-delà de 200 caractères, y contribue). S'ajoute donc
   un critère d'inclusion **en mots**, `autojunk=False`, **dans un seul sens** : la
   couverture du segment MICRO par le segment système. Mesurer celle du plus court des
   deux ferait jeter 34 mots de l'utilisateur parce que 7 sont revenus en écho depuis
   le poste d'en face (cas réel, réunions de juillet).
   Seuil **0,75**, calibré sur les 73 réunions du poste : 14 des 16 doublons de la
   fenêtre d'écho, **aucun tour légitime touché**. Ne pas descendre : un doublon manqué
   plafonne à 0,70 et un tour parfaitement légitime de la même réunion en fait 0,71 —
   indiscernables, et seul le second est irremplaçable.
3. **`packaging/build_ffmpeg.sh` — filtres `aselect`/`asetpts`.** Découvert en
   analysant ce diagnostic : la compaction des silences avant envoi à Voxtral
   **échouait systématiquement dans l'app livrée** (exit 234, « envoi intégral » dans le
   log), parce que le ffmpeg embarqué était compilé
   `--enable-filter=aresample,aformat,anull`. Invisible en dev, où c'est le ffmpeg
   Homebrew complet qui répond. Les deux filtres sont ajoutés, la validation du binaire
   les **exige** (un binaire qui en manque est reconstruit, pas réutilisé) et le build
   rejoue désormais les deux passes de `compacter_piste` avec la syntaxe exacte de
   l'app. Vérifié en réel : la commande qui échouait à 15:30 produit 26 min 14 s
   d'audio utile sur 53 min. Windows (build BtbN complet) et Linux (ffmpeg système) ne
   sont pas concernés.

### 8.4 Contre-analyse : l'offset ne dérive pas, il SAUTE (pertes d'échantillons micro)

Analyse croisée indépendante de la même réunion (fichiers + journal AEC), qui corrige
deux lectures de §8.1/§8.2 et ferme la question « dérive d'horloge » posée depuis §1.

**La comptabilité boucle.** `moi.opus` fait 3189,13 s et a perdu 343 ms en tête (saut
micro de la calibration) ; `systeme.opus` fait 3189,43 s → les deux chaînes ont livré
le même volume d'échantillons à **12 ppm près** sur 53 min (0 ppm sur la réunion
commerce du 17/08). **Il n'y a pas de dérive d'horloge** — la « dérive ~125 ppm » de
§1 était l'accumulation de sauts, pas une horloge. Confirmation : le verrou de
corrélation entre fichiers est **stable 20 min à −22/−34 ms** (min 26-45, qualités
jusqu'à 132) — une dérive à 108 ppm l'aurait déplacé de 123 ms.

**Trajectoire de l'offset de capture (micro↔système)** : 383 ms (calé, AEC à
−25/−40 dB min 2-11) → **saut −68 ms** vers min 12 (≈ 315 ms, causalité cassée → 0 dB,
la fenêtre d'écho de §8.1) → sauts **−105 ms** (min 46) et **−193 ms** (min 50, les
deux mesurés par le suivi de dérive, qui a donc bien traqué des marches réelles) →
~20-40 ms en fin de réunion ✓ = l'écart de durée des fichiers. Somme des marches
≈ 345 ms. Le sens est toujours le même : **la chaîne micro perd des paquets
d'échantillons**, la chaîne système jamais.

**Mécanisme candidat** : le callback PortAudio est du Python — quand le MainThread
tient le GIL (pousser AEC ~0,2 s/tranche, upload Mistral, UI), le wrapper du callback
attend, le buffer HAL de Core Audio déborde et PortAudio **jette**. Le helper SCK,
process séparé avec un pipe de 64 Ko, est immune — d'où l'asymétrie. À confirmer sur
le terrain (les trous devraient coïncider avec les fins de tranche).

**Correctifs (branche `aec-native`, complémentaires de §8.3 — aucun fichier commun) :**

1. **Comblement des trous à la source** (`platform/commun/micro_sounddevice.py`, les
   3 OS) : trou détecté par discontinuité de l'horodatage ADC des blocs
   (`time_info.inputBufferAdcTime` — pas `paInputOverflow`, non garanti par tous les
   host API et muet sur la taille), comblé par du silence de même durée. Le flux
   micro reste juste à l'échantillon : l'offset inter-pistes **ne peut plus sauter**,
   l'AEC ne se désaligne plus, et `moi.opus`/`systeme.opus` restent alignés (ce que
   le dédoublonnage ne fait que masquer). C'est la **C-compensation de §4.3, faite à
   la source**. Gardes : seuil 20 ms (gigue d'horodatage), plafond 10 s (horodatage
   aberrant → resynchronisation sans fabriquer de silence), jamais de comblement si
   l'API n'horodate pas, continuité remise à zéro à chaque nouveau flux. Incidents en
   WARNING, 1 ligne par tranche maximum. Le recalage de §8.3 reste le filet pour les
   autres causes de désalignement (changement de sortie, visio qui rebufferise).
2. **`QUALITE_CORR_CALAGE = 25`** pour **bouger** l'alignement (calibration, suivi) :
   mesuré sur cette réunion, sous une qualité ~25 les estimations de délai sont du
   bruit réparti sur tout ±1500 ms ; à ≥ 25 toutes concordent sur le vrai verrou.
   La **détection** d'écho résiduel (déclencheur du recalage §8.3) garde son seuil à
   10 — la rendre plus exigeante affaiblirait le correctif qu'elle déclenche.

**Au passage, deux métriques à lire avec précaution** : l'`att` par tranche est un
rapport de RMS sur 30 s — en double parole, la voix de l'utilisateur domine le RMS et
**masque l'annulation** (une médiane à −1,7 dB ne prouve pas un échec) ; les tranches
« micro audible → sous le seuil de silence » sont de l'**écho seul correctement
annulé** (−25/−40 dB, RMS système fort sur toutes), pas de la voix détruite.

### 8.5 Reste à faire

- Rebuild `.app` + `.dmg` pour que le ffmpeg corrigé arrive sur le poste (le binaire
  installé n'a pas les filtres).
- Valider en réunion réelle que le recalage automatique se déclenche et rétablit
  l'atténuation (chercher « recalage complet de l'alignement » dans le log) — et que
  les trous de capture sont bien comblés à la source (§8.4, chercher « trou(s) de
  capture comblé(s) ») : si les trous tombent à ~0, le recalage ne devrait plus
  jamais avoir à se déclencher.
- Rappel terrain indépendant du code : micro interne + haut-parleurs = écho garanti,
  un casque supprime le problème à la racine.

### 8.6 Terrain 2026-08-27 — le garde-fou accusait les flux à tort (casque)

Diagnostic Alix du 2026-08-27 (build `1cbbd5d`), deux réunions, **les deux** terminées
par « AEC DÉSACTIVÉE — l'offset entre les pistes a sauté de 771 / 1200 ms ». Le verdict
était faux, et l'instrumentation « Durées livrées » (ajoutée au même moment) le prouve.

**Ce que disent les mesures.** Écart micro−système par tranche de 30 s : **±5 à ±70 ms**,
quelques pointes à 140-219 ms, jamais de marche ; cumul **+1,20 s sur 1970 s** (~600 ppm,
dérive lente régulière d'une horloge Bluetooth). Le comblement des trous fonctionnait
(3 trous, 14 et 34 ms de déficit total) et le WARNING « comblement HORS SERVICE » que le
message incriminait n'a **jamais** été émis. Atténuation **−0,2 dB de bout en bout**.

**Ce qui sautait, c'est l'estimation, pas l'offset** : calages à −188, −12523, −6725,
−6913 puis −2859, +16349, +5218, +14334 éch — signes opposés, et une estimation à −23923
éch pile en butée de fenêtre (±24000). Alix était en **casque fermé** (écouteurs Bluetooth,
micro *et* sortie en WASAPI ; les semaines précédentes, micro Realtek + sortie BT —
même conclusion). Sans trajet acoustique il n'y a pas d'écho, donc **pas de vrai pic de
corrélation** : chaque calage tire un lag au hasard dans ±`DELAI_MAX_MS`, et
`QUALITE_CORR_CALAGE = 25` ne les filtre pas dans cette configuration. `_saut_offset_max`
lisait ces tirages successifs comme un offset qui bouge.

**À noter** : la branche « flux non synchronisables » n'a **aucun cas terrain confirmé**.
Le cas du 2026-08-26 qui l'avait motivée (§8.4, calages +11240/−9765/−19427/−11802) est
sorti par l'ancienne branche « casque recommandé » — l'instrumentation des durées livrées
n'existait pas encore ce jour-là, et l'utilisatrice portait déjà un casque. Rien ne
distingue rétrospectivement ce cas de celui du 27/08.

**Correctif — une preuve exigée avant d'accuser les flux.** Un saut d'offset RÉEL laisse
une trace dans les longueurs livrées : la tranche amputée arrive courte et déplace le
cumul micro−système d'autant. `ProcesseurAEC` tient donc son propre `_cumul_ecart_ech`
(même mesure que `core/reunion.py`, comptée dans `pousser()` **avant** toute sortie
anticipée) et mémorise sa valeur à chaque calage. `_saut_offset_max()` rend désormais
`(écart entre deux calages consécutifs, déplacement réel sur le même intervalle)`, et le
verdict terminal a deux sorties :

- déplacement réel > `SAUT_OFFSET_ECH` → WARNING actuel, qui cite la confirmation ;
- déplacement réel sous le seuil → **INFO** « AEC sans objet — aucun écho à annuler,
  pistes alignées, délais erratiques ». On cesse quand même de traiter (le micro brut
  *est* le bon résultat sans trajet acoustique, et renoncer rend le GIL, cf. §8.4).

Seuil : le même `SAUT_OFFSET_ECH`. En deçà de 300 ms de déplacement réel,
`_suivre_alignement` sait rattraper — c'est déjà ce que la constante encode.

`bilan()` distingue les deux cas de la même façon. Les deux tests de bout en bout figent
les deux terrains : délais erratiques à longueurs égales → INFO (27/08) ; mêmes délais
erratiques mais tranches micro amputées → WARNING (le cas que §8.4 décrit).

**Non traité, mesuré, sans conséquence** : la dérive Bluetooth de ~600 ppm (+1,2 s sur
33 min). Face à des tours de parole de plusieurs secondes, elle ne perturbe pas la fusion.

**Reste ouvert** : la branche de repli « écho résiste malgré des délais concordants »
conseille toujours un casque, ce qui reste faux pour quelqu'un qui en porte un (c'est ce
qui s'est produit le 25/08). Elle n'a pas le même discriminant à sa disposition — à
instruire séparément.
