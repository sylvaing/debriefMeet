# Spike — AEC WebRTC (séparation Moi/Participants sans casque)

> **Statut :** ✅ **SPIKE TERMINÉ — option D RETENUE (GO).** Étapes 1 (offline) et 2 (temps réel) GO sur enregistrements réels.
> Moteur : **LiveKit AEC3, NS désactivé, référence avec marge de lead ~40 ms**. Détails & reproductibilité : [`spike/aec-webrtc/README.md`](../spike/aec-webrtc/README.md).
> **Type :** spike décisionnel **go/no-go**, isolé, à la manière de la Phase 0.5 (POC SCK).
> **Décide :** faut-il retenir l'**option D** (AEC logicielle WebRTC, cross-platform) pour annuler l'écho des haut-parleurs dans le micro quand l'utilisateur n'a pas de casque ?
> Références : `02-specifications-techniques.md §4.5bis`, discussion options A→E.

---

## 1. Contexte

Sans casque, le micro capte le son des haut-parleurs : la piste **« Moi »** se retrouve polluée par l'écho des participants (cf. réunion `2026-06-19_15-50.md`, où « Moi » duplique « Participants »). C'est une limite physique, pas un bug.

Parmi les options envisagées pour **garder la séparation Moi/Participants sans casque** :
- **C** — AEC native par OS (Voice Processing IO macOS, etc.) : qualité max mais 3 implémentations natives, conflit avec la capture SCK/sounddevice existante.
- **D** — AEC logicielle **WebRTC** (`webrtc-audio-processing`) : **une seule** implémentation cross-platform, alimentée par les deux flux qu'on capte **déjà** (micro = signal, système = référence). Alignée sur l'archi « cœur partagé ».

Ce spike valide la faisabilité de **D**. Risque principal à lever : **l'alignement temporel** micro ↔ référence, et la **disponibilité d'un binding Python** utilisable.

---

## 2. Objectif & question go/no-go

**Question unique :**
> En situation réelle sans casque, l'AEC WebRTC nourrie par (micro = signal, système = référence) supprime-t-elle l'écho au point que **(a)** l'atténuation soit mesurable **et (b)** la transcription Whisper de « Moi » devienne propre — sans alignement temporel impraticable ?

---

## 3. Décisions de cadrage (actées)

| Sujet | Décision |
|---|---|
| **Mode de test** | **Offline d'abord** (2 WAV pré-enregistrés, traités hors ligne) pour isoler la question AEC + alignement. **Puis** une **Étape 2 temps réel** obligatoire pour valider clairement le fonctionnement avant conclusion définitive (cf. §7). |
| **Périmètre OS** | **macOS seul** — la lib WebRTC étant cross-platform, la preuve vaut pour la suite. |
| **Critère GO** | **Les deux** : atténuation **signal** mesurée **ET** transcription **métier** propre (cf. §6). |

---

## 4. Tâche 0 — lever le risque « binding Python » (avant tout)

État des lieux (à confirmer en premier) :
- `webrtcvad` → VAD seulement, **pas d'AEC**.
- `webrtc-audio-processing` (wrapper du C++) → existe sur pip, build/maintenance **irréguliers** → à tester.
- `speexdsp-python` → AEC plus simple, pip-installable → **repli léger** si WebRTC ne se build pas.
- (PipeWire `module-echo-cancel` utilise webrtc-audio-processing sous le capot — la brique existe.)

**Ordre de préférence :** WebRTC (AEC3, meilleure qualité) **d'abord** ; `speexdsp` **uniquement en repli** si WebRTC ne s'installe/build pas.

**Sous-risque à vérifier en priorité — Python 3.14 :** le venv du projet est en **3.14** (très récent). Les wheels précompilées de `webrtc-audio-processing` peuvent **manquer** pour 3.14 → compilation depuis les sources requise (toolchain C++). C'est le point le plus susceptible de bloquer.

**Time-box tâche 0 : ~½ journée.** Au-delà, sans binding exploitable (ni WebRTC, ni speexdsp, ni shim C++ raisonnable) → **NO-GO immédiat**, avant même de tester la qualité.

> **Résultat (acté) : ✅ GO — en AEC3, via un moteur maintenu.** Moteur retenu : le **SDK [LiveKit](https://github.com/livekit/python-sdks)** (`livekit.rtc.AudioProcessingModule`), qui expose l'**APM WebRTC de production (AEC3)** en standalone. Avantage clé : wheel **`py3-none`** (binaire Rust/FFI) → `pip install livekit` **sans compilation sur Python 3.14 / Apple Silicon**, et porté par une société (commits quotidiens). Sur le cas démo synthétique : **−44 dB** d'atténuation (négligeable en CPU). Alternatives évaluées puis **écartées** (un seul moteur en prod = moins de maintenance) : [pywebrtc-audio](https://github.com/strands-labs/pywebrtc-audio) (AEC3, léger 796 Ko mais 1 dev / 3★, −17 dB) — gardé comme **plan B léger** si l'empreinte LiveKit gêne à l'intégration ; webrtc-audio-processing 0.1.3 (AEC1, build patché, −6 dB, mort depuis 2018) — abandonné. `speexdsp` non nécessaire. Compromis LiveKit : empreinte ~19 Mo (+ protobuf/aiofiles), à repeser à l'intégration.

---

## 5. Méthode (Étape 1 — offline)

1. **Binding** : installer/valider la lib d'AEC (tâche 0).
2. **Jeu de test reproductible avec vérité terrain** (~60 s, sans casque), conçu pour mesurer objectivement les deux côtés **et réutilisable plus tard pour comparer l'option C** (benchmark commun) :
   - **« Participants »** = un **audio/vidéo connu** (podcast/extrait) joué sur les haut-parleurs → contenu maîtrisé, pas une visio aléatoire.
   - **« Moi »** = **un texte lu par l'utilisateur** → sert de vérité terrain pour vérifier que sa voix survit à l'AEC.
   - **Phases minutées et annoncées** : alterner (a) « participants seuls » (utilisateur silencieux → mesure de l'écho pur et de son atténuation) et (b) « utilisateur parle » (voix à préserver). Timestamps des phases notés.
   - **Clap initial** : transitoire net présent dans les deux pistes → repère d'alignement.
   - Réutiliser les briques existantes : `CaptureMicroSounddevice` (micro) + `CaptureAudioSCK` (système).
3. **Chaîne de traitement AEC** (décisions techniques) :
   - Travailler en **16 kHz mono** (aligné sur ce qu'on envoie déjà à Whisper, plus léger) plutôt qu'à 48 kHz.
   - **Downmix** de la référence système (stéréo 48 k → mono 16 k).
   - **Alignement** : estimer le délai micro/référence par cross-corrélation (autour du clap) ; **mesurer la dérive** du délai sur les 60 s (horloges distinctes PortAudio ~44,1 k vs SCK 48 k) — critique surtout pour l'Étape 2 temps réel.
   - Appliquer l'AEC (référence = système aligné), sortir le **micro nettoyé**.
4. **Mesures** :
   - **Signal** : RMS de l'écho sur les phases « participants seuls » dans le micro **brut vs nettoyé** (cf. critère §6).
   - **Métier** : transcrire micro **brut** et micro **nettoyé** avec le moteur MLX existant → métriques objectives §6.
   - **Coût** : relever la charge CPU de l'AEC (sanity check, attendu négligeable).

---

## 6. Critères (les deux requis pour GO)

> **Hiérarchie à acter :** *préserver la voix de l'utilisateur prime sur supprimer l'écho.* Une AEC qui efface l'écho mais abîme « Moi » est un NO-GO.

**GO si :**
- **Signal** : sur les phases « participants seuls », l'écho résiduel dans le micro nettoyé **tombe sous le seuil RMS du gate anti-hallucination** (`_SEUIL_RMS = 0.008` dans `moteur_mlx.py`) — càd sous le niveau où Whisper ne le transcrirait de toute façon plus. Le délai d'alignement est **estimable et stable**.
- **Métier** (métriques objectives) :
  - *Suppression écho* — la **similarité floue** (`difflib`, comme l'option B) entre « Moi nettoyé » et « Participants » **chute fortement** vs le micro brut.
  - *Préservation voix* — le **WER** (taux d'erreur) de « Moi nettoyé » vs le texte lu **reste bas** (proche de celui d'un micro propre sans écho).

**NO-GO si :** binding inutilisable ; écho résiduel au-dessus du seuil RMS ; délai qui dérive/impraticable ; ou WER de la voix dégradé (artefacts destructeurs).

> **Résultat Étape 1 (acté, enregistrements réels, moteur LiveKit AEC3, NS désactivé) : ✅ GO sur tous les critères.**
> - **Signal** : RMS écho **0.01155 → 0.00089** (**−22,3 dB**), **sous** le seuil 0.008 → GO. Délai −259 ms, dérive 1,3 ms (stable).
> - **Suppression écho** : similarité Moi↔Participants **0.640 → 0.029**. Le micro brut se transcrit comme les participants ; le nettoyé restitue la voix réelle. « Moi » est bien isolé.
> - **L'AEC n'abîme PAS la voix (test décisif)** : micro propre brut WER **0.108** = micro propre passé dans l'AEC (réf silencieuse) WER **0.108**, transcription identique. La condition NO-GO « AEC destructrice » est écartée.
> - **Double-talk** : quand l'utilisateur parle *par-dessus* le podcast, WER **0.47** (vs 0.108 propre). L'écart vient du **masquage acoustique à la capture** (voix + écho superposés) — limite physique du « sans casque », commune à toute AEC, **non imputable** à l'option D. Le bug réellement signalé (« Moi duplique Participants » quand l'utilisateur est silencieux) relève du cas single-talk, lui **résolu**.
> - **Découverte de réglage** : le **débruitage (NS) dégradait la voix** (WER 0.60 → 0.47 en le coupant, écho toujours sous le seuil) → **NS désactivé par défaut** (`--ns` pour réactiver).
> - **Coût** : 0,008× temps réel (négligeable).
>
> **Conclusion offline : option D validée.** L'AEC supprime l'écho sans toucher à la voix ; le résidu double-talk est le prix physique du sans-casque. Reste l'**Étape 2 (temps réel, §7)** : tenue en continu + dérive d'alignement sur une vraie session live.

---

## 7. Étape 2 — validation temps réel (après GO offline)

Le GO offline **ne suffit pas** à conclure : il faut prouver que l'AEC tient en conditions réelles (dérive d'horloge entre les deux captures live, charge concurrente avec Whisper).

**Inconnue décisive : la dérive d'horloge sur la durée.** Micro (44,1 kHz, PortAudio) et système (48 kHz, SCK) ont des horloges distinctes ; sur plusieurs minutes le délai micro↔référence dérive. Question : reste-t-il dans la tolérance de l'AEC3 (qui a un estimateur de délai interne), ou l'écho réapparaît-il en fin de session ? En temps réel on **ne peut pas** faire la cross-corrélation globale de l'offline pour aligner : on donne un *hint* de délai initial et on laisse l'estimateur AEC3 suivre.

**Protocole (banc YouTube, sans casque).** Source far-end = YouTube sur les HP (équivalent acoustique d'une visio). Session longue (~4 min) en **N cycles alternés** : « participants seuls » (~15 s, utilisateur silencieux) → « moi parle » (~15 s, lecture par-dessus) → répété. Étalement → points de mesure début **et** fin de session.

**Outils.** `enregistrer.py --cycles N` (session longue alternée) ; `analyser_drift.py` :
- courbe **délai(t)** par cross-corrélation glissante → taux de dérive (ms/min) ;
- passe AEC en **mode temps réel** : hint de délai fixe, **sans** ré-alignement par fenêtre (estimateur AEC3 interne uniquement) ;
- **RMS écho résiduel par phase « participants seuls », début vs fin** → la suppression tient-elle dans la durée ?

**GO si** l'écho résiduel reste **sous le seuil du début à la fin** de la session ET la dérive reste absorbée par l'AEC3. **Conclusion définitive D = go/no-go** prononcée seulement après cette étape.

> **Résultat Étape 2 (acté, session live ~217 s, 7 cycles, YouTube sur HP) : ✅ GO.**
> - **Dérive d'horloge = non-problème** : 13 ms sur 217 s (+0,1 ms/min), absorbée par l'estimateur interne d'AEC3.
> - **Découverte critique — marge de lead** : l'alignement par cross-corrélation calé pile sur le pic donnait seulement **−5 dB** (l'écho passait dans la transcription : contenu YouTube transcrit sur 4/7 phases). Le filtre d'AEC3 est **causal** → la référence doit **précéder** l'écho. En l'avançant d'une marge (**~40 ms**, plateau stable de −20 à −60 ms), l'atténuation passe à **−13 à −34 dB** → résidu **sous le seuil 0.008 sur les 7 phases**. Correctif figé : `aligner_pour_aec()` / `MARGE_LEAD_AEC_MS=40`.
> - **Impact transcription** : avec le correctif, plus aucun contenu participants transcrit ; les rares hallucinations Whisper (« Merci… ») sont sur du résidu RMS < 0.008, donc **filtrées par le gate `_SEUIL_RMS` de l'app**.
> - **Coût** : 0,007× temps réel.
>
> **CONCLUSION DÉFINITIVE — option D RETENUE.** L'AEC WebRTC (LiveKit AEC3, NS off, référence avec marge de lead) supprime l'écho sous le seuil en continu, sans dériver et sans abîmer la voix. Le résidu double-talk reste la limite physique du sans-casque (cf. Étape 1). Réglages clés pour l'intégration : moteur LiveKit ; NS désactivé ; **référence calée pour précéder l'écho de ~40 ms** ; gate `_SEUIL_RMS` conservé.

---

## 8. Livrables

- Dossier `spike/aec-webrtc/` (isolé, hors app) : script de traitement offline (2 WAV → micro nettoyé), protocole d'enregistrement.
- **Rapport go/no-go** : binding retenu, délai mesuré + stabilité, atténuation (dB), transcriptions avant/après, coût CPU, verdict offline.
- (Étape 2) note de validation temps réel.
- **Aucune intégration dans l'app** tant que le verdict n'est pas GO.

---

## 9. Time-box (indicatif)

- **Étape 1 (offline)** : ~1–2 jours, dont la **tâche 0 (binding)** potentiellement le poste le plus long/risqué.
- **Étape 2 (temps réel)** : à cadrer seulement si l'étape 1 est GO.

> Spike **décisionnel** : on s'arrête dès qu'un NO-GO est atteint (binding, qualité, ou alignement), sans sur-investir.
