# Plan d'action — Mode « enregistrement seul » + transcription différée

> **Statut :** ✅ **implémenté & testé (macOS)** — 367 tests verts (+44), stable. Validation manuelle (vrai enregistrement audio-seul → transcription depuis l'Historique) restant à jouer par l'utilisateur.
> **Besoin :** une préférence pour **n'enregistrer que l'audio** pendant la réunion (pas de transcription live) ; puis, dans l'Historique, un **bouton « Transcrire »** sur les réunions qui n'ont que l'audio (en complément du bouton diarization existant).

---

## 1. Ce qui existe déjà (et qu'on réutilise)

- **Rétention audio** : `OrchestrateurReunion` streame déjà 2 pistes 16 kHz (Moi nettoyé AEC + Système) en Opus/WAV à côté du `.md` (`EnregistreurAudioReunion`, `chemins_audio_reunion`).
- **Re-transcription depuis fichiers** : `diarization._traiter_piste` fait déjà décoder (`decoder_audio_16k`) → normaliser (`normaliser_asr`) → `moteur.transcrire`. La transcription différée = ce pipeline **sans pyannote**, rendu en `.md` standard.
- **Entrelacement Moi/Participants** : `fichiers._entrelaces` (par timestamps de segments).
- **Job en arrière-plan persistant** : `GestionnaireDiarization` (un seul job lourd à la fois, signaux `demarre/termine/echoue`, survit à la fermeture de la fenêtre).
- **Listing & actions Historique** : `lister_enregistrements` (liste les `.md`), colonne d'actions par ligne, indicateurs audio/locuteurs.

→ Le besoin est surtout de l'**assemblage** + une **bifurcation** dans l'orchestrateur.

---

## 2. Décisions d'architecture (proposées — à valider §6)

### 2.1 Représentation d'une réunion « audio seul » dans l'Historique
Le listing repose sur le `.md`. Pour qu'une réunion non transcrite apparaisse :
- **A1 (proposé)** — créer quand même un **`.md` placeholder** au démarrage (en-tête + ligne marqueur `> ⏳ Enregistrement audio seul — transcription non générée.`). L'audio est à côté. Tout le listing/actions existant fonctionne tel quel. La transcription différée **remplace** le placeholder par la vraie transcription.
- A2 — lister aussi l'audio sans `.md` (listing hétérogène, pseudo-entrées). Plus complexe.

### 2.2 Détecter « non transcrit »
- Fonction `transcription_en_attente(md) -> bool` dans `fichiers.py` : vrai si le `.md` contient la ligne marqueur (pas encore de transcription). Sert à afficher le bouton « Transcrire » et l'indicateur.

### 2.3 Format de sortie de la transcription différée
- **C1 (proposé)** — timeline entrelacée Moi/Participants à partir des segments Whisper des 2 pistes (réutilise `_entrelaces`), en un `.md` au même format que le live (en-tête + blocs).
- C2 — re-découper en tranches de `intervalle_reunion` pour coller exactement au format live (plus de travail, intérêt limité en différé).

### 2.4 Où vit la logique
- Nouveau module cœur testable **`core/transcription_differee.py`** : `transcrire_reunion(md, moteur, langue)` — lit l'audio retenu, transcrit les 2 pistes, réécrit le `.md`. Symétrique de `diarization.generer_locuteurs`.
- **D1 (proposé)** — **unifier le job dans le gestionnaire existant** : il ne doit y avoir qu'**un seul job lourd à la fois** (transcription et diarization se battraient pour le moteur/GPU). On généralise `GestionnaireDiarization` (file unique) pour accepter aussi un job « transcription », OU on ajoute `lancer_transcription()` au même objet.
- D2 — gestionnaire séparé (risque de 2 jobs GPU simultanés). Écarté.

### 2.5 Comportement de l'orchestrateur en mode « audio seul »
- Lit `config.get("transcription_live")`. Si **False** :
  - **rétention audio forcée** (sans audio retenu, rien à transcrire après — on l'active de facto, indépendamment de la préférence rétention).
  - **AEC conservée** (nettoie le micro → bénéficie à la transcription différée ET à la diarization).
  - **pas de timer de transcription** : un timer léger appelle seulement la capture (AEC + streaming audio), **sans** lancer de worker de transcription.
  - `.md` placeholder créé au démarrage (A1).
  - à l'arrêt : finalise l'audio, **pas de transcription finale**, icône → REPOS directement (pas de phase TRANSCRIPTION orange).

---

## 3. Changements par fichier

| Fichier | Changement |
|---|---|
| `core/config.py` | + clé `transcription_live` (bool, défaut **True** = comportement actuel). Rétro-compatible (clé absente → défaut). |
| `ui/preferences.py` | + checkbox onglet Audio : « Transcrire pendant l'enregistrement » (décochée = audio seul, à transcrire après). Lue/sauvée dans `_appliquer`. |
| `core/reunion.py` | bifurcation `transcription_live` : timer « capture seule », pas de worker, `.md` placeholder, rétention forcée, arrêt direct REPOS. |
| `core/fichiers.py` | + `transcription_en_attente(md)` ; `EcrivainReunion.creer_placeholder()` (ou param) écrivant le marqueur. |
| `core/transcription_differee.py` (nouveau) | `transcrire_reunion(md, moteur, langue)` : décode l'audio retenu → transcrit 2 pistes → entrelace → réécrit le `.md`. |
| `ui/gestionnaire_diarization.py` | généralisé pour lancer aussi un job « transcription » (file unique partagée avec la diarization). |
| `ui/historique.py` | bouton « Transcrire » affiché ssi (audio présent && `transcription_en_attente` && aucun job) ; clic → gestionnaire ; indicateur « à transcrire ». |
| `__main__.py` | câblage (le gestionnaire reçoit déjà le moteur). ⚠️ fichier potentiellement touché par la session « bundle » → vigilance. |

---

## 4. Tests prévus (à chaque brique)

- `config` : présence + défaut `transcription_live` ; rétro-compat (vieux fichier sans la clé).
- `preferences` : checkbox présente, état lu/sauvé.
- `reunion` (mode audio seul) : **moteur jamais appelé** ; audio retenu présent ; `.md` placeholder créé + `transcription_en_attente` vrai ; arrêt → pas de phase TRANSCRIPTION.
- `fichiers` : `transcription_en_attente` (placeholder vrai / transcrit faux) ; format placeholder.
- `transcription_differee` : depuis 2 pistes audio fixtures + `MoteurFake` → `.md` attendu (Moi/Participants entrelacés), marqueur retiré.
- `gestionnaire` : `lancer_transcription`, un seul job à la fois, signaux ; pas de transcription + diarization concurrentes.
- `historique` : bouton « Transcrire » visible/masqué selon l'état ; clic lance le job ; recharge après.

---

## 5. Points actés (hors discussion)

- Rétention audio **forcée** en mode audio-seul.
- AEC **conservée** en mode audio-seul.
- Défaut `transcription_live = True` (aucun changement de comportement pour l'existant).
- Un seul job lourd à la fois (transcription **ou** diarization).

---

## 6. Décisions (tranchées)

1. **Représentation audio-seul** → **A1 : placeholder `.md`**.
2. **Bouton « Transcrire »** → **transcription seule** (la diarization reste lançable via son bouton existant ; deux boutons distincts).
3. **Format de sortie** → **C1 : timeline entrelacée** Moi/Participants (format `.md` standard).

---

## 7. Réalisé

- `config.py` : clé `transcription_live` (défaut `True`).
- `fichiers.py` : `MARQUEUR_EN_ATTENTE`, `transcription_en_attente()`, `EcrivainReunion.creer_placeholder()`.
- `core/transcription_differee.py` (nouveau) : `transcrire_reunion(md, moteur, langue)`.
- `reunion.py` : bifurcation audio-seul (`_sur_tick`/`_capturer_seulement`, rétention forcée, AEC conservée, placeholder, arrêt direct REPOS).
- `gestionnaire_diarization.py` : `lancer_transcription()` + `type_job_en_cours()` (file unique, un seul job lourd à la fois).
- `preferences.py` : case « Transcrire pendant l'enregistrement » (onglet Audio).
- `historique.py` : bouton **Transcrire** (glyphe `ecrire`) sur les réunions en attente, à la place du bouton diarization ; indicateur « À transcrire ».
- `__main__.py` : **inchangé** (le gestionnaire existant gère les deux types de jobs).

**Tests :** 367 verts (+44) — `transcription_differee`, placeholder/`en_attente`, config, réunion audio-seul (pas de transcription, rétention forcée, pas de phase TRANSCRIPTION), préférence, bouton Historique, gestionnaire `lancer_transcription`.

**Comment tester (manuel) :**
1. Préférences → onglet Audio → **décocher « Transcrire pendant l'enregistrement »**.
2. Réunion → parler → arrêter : un `.md` apparaît dans l'Historique avec l'indicateur **« À transcrire »** (icône sablier) et l'audio retenu.
3. Cliquer le bouton **Transcrire** (icône plume) → job en arrière-plan → à la fin, le `.md` contient la transcription Moi/Participants.
4. Le bouton **Générer les locuteurs** (diarization) redevient ensuite disponible sur cette réunion.
