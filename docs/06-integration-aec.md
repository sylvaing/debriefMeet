# Cadrage — Intégration de l'AEC dans l'app (après spike GO)

> **Statut :** ✅ **intégrée** (macOS) — étapes 1-4 faites, validée en réel. Reste optionnel : ajustement fin de l'auto-vérif.
> Pré-requis : spike [`05-spike-aec-webrtc.md`](05-spike-aec-webrtc.md) = **option D GO**.
> Réglages validés : **LiveKit AEC3**, **NS désactivé**, **référence qui précède l'écho
> (~40 ms)**, **gate `_SEUIL_RMS` conservé**.

---

## 1. Objectif & contexte

Brancher l'AEC dans le flux réunion : nettoyer le **micro** avec l'audio **système** comme
référence **avant** de l'envoyer à Whisper, pour en retirer l'écho des participants
distants (haut-parleurs sans casque).

**Contexte d'usage = réunions hybrides** (cf. décision). Sur chaque piste :
- **Micro** = personnes **présentes dans la pièce** (toi + collègues) **+ écho des distants** ;
- **Système** = participants **distants** (mixés).

→ L'AEC retire l'écho distant du micro pour qu'il ne contienne **que les voix de la salle**.

> **L'AEC n'est pas un confort, c'est un prérequis.** En hybride, le micro nettoyé alimentera
> ensuite une **diarization** (cf. [`07-diarization.md`](07-diarization.md)). Sans AEC, l'écho
> des distants dans le micro créerait des **locuteurs fantômes** côté salle. La qualité de
> l'AEC (−22/−25 dB + gate `_SEUIL_RMS`) conditionne donc directement la qualité de la
> diarization du micro.

Ce document couvre **uniquement la couche live (AEC)**. La rétention audio et la passe finale
de diarization sont décrites dans [`07-diarization.md`](07-diarization.md).

Périmètre : **macOS uniquement** pour l'instant (la lib est cross-platform, mais la
capture système repose sur SCK). Aucune régression sur le mode dictée.

---

## 2. La contrainte clé : AEC à état vs pipeline par tranches

L'architecture actuelle (`OrchestrateurReunion`, [`core/reunion.py`](../src/debrief_meet/core/reunion.py)) :
- toutes les `intervalle_reunion` (30 s), un `QTimer` tire les échantillons **accumulés**
  du micro et du système (`recuperer_echantillons()`), puis transcrit les **deux pistes
  indépendamment** dans un `_WorkerTranche`.

Or l'**AEC3 est un filtre adaptatif à état** : il doit traiter l'audio **en continu,
trame par trame dans l'ordre**, en conservant l'état de son filtre sur **toute la
session**. On ne peut donc pas :
- ❌ instancier une AEC neuve par tranche (le filtre ne convergerait jamais) ;
- ❌ traiter les deux pistes sans les **aligner** (la référence doit précéder l'écho).

Il faut donc un **étage AEC persistant** entre les captures brutes et la transcription.

---

## 3. Architecture retenue

### `ProcesseurAEC` (nouveau module `core/aec.py`), à état, alimenté par tranche

Un objet vivant pour toute la session, qui :
- détient l'`AudioProcessingModule` LiveKit (créé une fois à `demarrer()`),
- détient un **buffer d'alignement** (ring buffer) micro + système,
- expose `pousser(micro_chunk, systeme_chunk) → micro_nettoyé` appelé à chaque tranche,
  en **conservant l'état** de l'AEC et l'alignement **d'une tranche à l'autre**.

**Pourquoi par tranche et pas un thread de polling dédié ?**
- Pas de 2ᵉ thread ni de conflit de propriété sur `systeme.recuperer_echantillons()`
  (le système est déjà tiré par l'orchestrateur pour la piste « Participants »).
- AEC3 se moque des frontières d'appel : lui passer 30 s d'un coup, trame par trame, en
  gardant l'état, est équivalent au temps réel (l'ordre des trames seul compte).
- Le coût est négligeable (spike : 0,007× temps réel) → traiter 30 s prend ~0,2 s.

**Alternative écartée** (notée pour mémoire) : un `CaptureMicroNettoye` qui s'intercale
à la place du micro. Plus élégant en théorie, mais il faudrait qu'il possède aussi la
capture système (consommée en parallèle par l'orchestrateur) → conflit de buffer. Rejeté.

### Flux de données

```
                      ┌─────────────────── ProcesseurAEC (état, session) ──────────────────┐
 micro brut  ───────► │ buffer micro (retardé de Δ+marge)                                   │
 (44,1 kHz)           │            ↓                                                        │
                      │   resample 16k → trames 10 ms → APM.process_stream  ───► micro 16k  │──► tranche « Moi »
 système brut ──┬───► │ buffer réf  → resample 16k → APM.process_reverse_stream  (nettoyé)  │     → Whisper
 (48 kHz)       │     └─────────────────────────────────────────────────────────────────────┘
                │
                └────────────────────────────────────────────────────────────────────────────► tranche « Participants »
                                                                                                  → Whisper (inchangé)
```

La piste « Participants » reste le système brut (inchangée). Seule « Moi » passe par l'AEC.

---

## 4. Alignement temps réel (marge + auto-vérif) — le cœur du sujet

En live, **pas de clap ni de cross-corrélation globale**. Trois mécanismes combinés :

1. **Mesure du délai** micro↔système (≈ −256 ms = le système arrive *après* le micro,
   différence de latence des pipelines SCK vs PortAudio) :
   - mesuré par cross-corrélation sur la **1ʳᵉ tranche** (≥1 personne parle → écho présent),
   - ou repris d'une **calibration stockée** (le délai est ~constant par machine/config).
2. **Marge de lead** : on **retarde le micro** de `|délai| + marge` (~40 ms) pour que la
   référence système **précède** l'écho — requis par le filtre causal d'AEC3
   (cf. spike §7). En pratique : un buffer de retard sur la piste micro.
3. **Auto-vérif & adaptation** (rend la marge non-fragile, cf. discussion) :
   - sur les fenêtres où le micro est faible (utilisateur silencieux), mesurer
     l'atténuation obtenue ;
   - si l'écho résiduel reste au-dessus de `_SEUIL_RMS` → **augmenter la marge** d'un cran
     (la marge en trop est gratuite jusqu'à la longueur du filtre AEC3) ;
   - laisser **l'estimateur de délai interne d'AEC3** affiner dans sa fenêtre + absorber
     la dérive d'horloge (validé spike Étape 2 : 0,1 ms/min).

→ On ne dépend d'aucune constante figée : le gros délai est mesuré, la marge s'auto-ajuste.

---

## 5. Points d'accroche (fichiers)

| Fichier | Changement |
|---|---|
| `core/aec.py` *(nouveau)* | `ProcesseurAEC` : APM LiveKit + buffers d'alignement + auto-vérif. |
| [`platform/factory.py`](../src/debrief_meet/platform/factory.py) | construire le `ProcesseurAEC` (si `aec_actif` & système dispo) et l'injecter. |
| [`core/reunion.py`](../src/debrief_meet/core/reunion.py) | dans `_transcrire_tranche`/`_arreter` : passer micro+système au `ProcesseurAEC`, transcrire le **micro nettoyé** au lieu du brut. État AEC réinitialisé à `_demarrer`. |
| [`core/config.py`](../src/debrief_meet/core/config.py) | nouvelles clés : `aec_actif` (bool, défaut True), `aec_marge_ms` (défaut 40), `aec_delai_ms` (calibration, défaut None). |
| `pyproject.toml` | ajouter la dépendance `livekit`. |
| [`platform/interfaces.py`](../src/debrief_meet/platform/interfaces.py) | éventuelle interface `ProcesseurEcho` (pour stub/tests + futurs OS). |

**Réglages figés dans `ProcesseurAEC`** : `echo_cancellation=True`, `noise_suppression=False`,
`high_pass_filter=True`. Le gate `_SEUIL_RMS=0.008` de [`moteur_mlx.py`](../src/debrief_meet/platform/macos/moteur_mlx.py) **reste** (filtre les hallucinations Whisper sur résidu faible).

---

## 6. Tests & validation

- **Unitaires** : `ProcesseurAEC` sur des signaux synthétiques (réutiliser les fakes du
  spike : écho retardé → atténuation sous seuil ; voix propre → inchangée). Continuité de
  l'état sur plusieurs `pousser()`. Buffer d'alignement (retard correct, pas de perte aux
  frontières de tranche).
- **Build/non-régression** : suite existante verte ; mode dictée intact ; réunion sans
  système (AEC désactivée proprement).
- **Validation réelle** : rejouer le banc de l'Étape 2 (YouTube) *via l'app* et vérifier
  dans le journal que « Moi » ne contient plus l'écho.

---

## 7. Risques / décisions ouvertes

- **Empreinte LiveKit (~19 Mo + protobuf/aiofiles)** dans le bundle de l'app. Acceptable ?
  Sinon → plan B `pywebrtc-audio` (cf. spike). **À trancher avant d'ajouter la dépendance.**
- **Latence ajoutée** sur « Moi » (~300 ms de buffer d'alignement) : sans impact pour un
  débrief (non interactif), à confirmer.
- **Calibration du délai** : 1ʳᵉ tranche vs valeur stockée — commencer par la mesure
  par tranche (plus simple, robuste au changement de machine).
- **Multi-OS** : à ce stade macOS seul ; l'interface `ProcesseurEcho` prépare le terrain.

---

## 8. Découpage proposé

**Ce chantier (AEC) :**
1. ✅ **`core/aec.py` + tests** (`ProcesseurAEC` à état : resample → calibration délai →
   marge de lead → lockstep ; moteur AEC injectable). 7 tests logique + 1 e2e LiveKit
   (`integration`). Suite : **170 passed**, 0 régression. App non touchée.
2. ✅ **Câblage `reunion` + `config` + `__main__`** : `OrchestrateurReunion` reçoit un
   `processeur_aec` injecté (None en tests → AEC off, LiveKit jamais chargé) ; `_capturer_tranche`
   nettoie le micro (réf = système) avant transcription ; clé config `aec_actif` (défaut True) ;
   `__main__` construit l'AEC (LiveKit lazy → repli sans écho si indisponible). APM **frais par
   réunion**. 4 tests de câblage. Suite : **174 passed**, 0 régression. App démarre sans charger LiveKit.
3. Validation réelle (banc YouTube via l'app) + ajustement auto-vérif. 🔵 **en cours** :
   - Run réel : séparation Moi/Participants **OK** (voix préservée, écho sous le seuil pendant les silences).
   - **Correctif calibration robuste** : on ne cale le délai que sur un **écho franc** (pic de
     cross-corrélation net + système qui joue) ; sinon **passthrough du micro brut** (voix
     jamais perdue). Corrige le cas « session courte / démarrage silencieux → Moi vide ». 11 tests AEC.
   - Reste : ajustement auto-vérif de la marge.
   - *(Hors AEC, corrigé)* collision de fichier journal si 2 réunions dans la même minute :
     `chemin_reunion()` suffixe `-2`, `-3`… (plus d'écrasement, mode « w »). 3 tests.
4. ✅ **Dépendance** : `livekit>=1.1` ajoutée à l'extra `macos` de `pyproject.toml` (LiveKit
   retenu ; plan B `pywebrtc-audio` documenté si l'empreinte ~19 Mo pose problème un jour).
   Réglage **`aec_actif` exposé dans les Préférences** (onglet Audio, effet à la prochaine
   réunion). Tests préférences + collision journal. Suite : **181 passed**.

**Séquençage global** (cible hybride complète) :
1. **AEC** *(ce document)* — socle, nettoie le micro.
2. **Rétention audio** des 2 pistes — petite brique, prérequis de la passe finale.
3. **Diarization** — passe finale post-réunion ([`07-diarization.md`](07-diarization.md)).
