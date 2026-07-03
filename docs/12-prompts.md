# Spec — Prompts de copie (onglet Préférences + préfixe à la copie)

> **Statut :** ✅ **implémenté & testé** — 410 tests verts (+21), stable. Validation manuelle (onglet Prompts + copie préfixée depuis l'Historique) restant à jouer par l'utilisateur.
> **Besoin :** gérer des **modèles de prompt** éditables dans les Préférences ; un prompt
> **actif** est ajouté **en tête** lors de la copie d'une transcription / d'un débrief
> locuteurs depuis l'Historique, pour coller directement le tout dans un LLM.

---

## 1. Décisions actées

1. **Prompt actif par défaut** → **« CR simple »** (actif dès le 1er lancement).
2. **Périmètre du préfixe** → **Historique uniquement** : boutons « Copier » des réunions (transcription `.md`) **et** des débriefs locuteurs (`_locuteurs.md`). La copie auto du mode Dictée reste **brute**.
3. **UI** → **liste éditable + case « actif »** : la sélection dans la liste sert à éditer ; une case/radio « utiliser à la copie » désigne l'actif (indépendant de l'édition).

Détails actés (mineurs) :
- **Aucun actif possible** (`prompt_actif = null`) → copie brute (comme aujourd'hui).
- **Préfixe** = `contenu_du_prompt.rstrip()` + `"\n\n"` + transcription.
- Supprimer le prompt actif → `prompt_actif = null` (l'utilisateur réactive).
- Titres **libres** (non uniques) ; identification par **index** dans la liste.

---

## 2. Stockage (config.json)

Deux nouvelles clés (ajoutées aux `_DEFAUTS`, rétro-compatibles : clé absente → défaut) :

| Clé | Type | Défaut |
|---|---|---|
| `prompts` | liste de `{ "titre": str, "contenu": str }` | `[ CR simple ]` (cf. §6) |
| `prompt_actif` | index `int` dans `prompts`, ou `null` | `0` (le CR simple) |

> Une config antérieure sans ces clés récupère donc **CR simple actif** au prochain chargement (cohérent avec la décision 1).

Le prompt par défaut vit dans un module dédié `core/prompts.py` (constante + `prompts_par_defaut()`), importé par `config.py` pour le défaut.

---

## 3. Onglet Préférences « Prompts »

- **Liste** des prompts (titres) + boutons **＋** (ajouter) / **−** (supprimer).
  - Ajouter → nouveau prompt « Nouveau prompt » / contenu vide, sélectionné pour édition.
  - Supprimer → retire le prompt sélectionné (ajuste `prompt_actif`).
- **Édition** : sélectionner une ligne → champs **titre** (`QLineEdit`) et **contenu** (`QPlainTextEdit`, multi-lignes) éditables.
- **Actif** : une case **« Utiliser ce prompt à la copie »** (ou indicateur ✓ dans la liste) désigne le prompt actif ; un seul à la fois. Décochable → aucun actif.
- Persistance au clic **OK** (comme les autres réglages).

---

## 4. Comportement à la copie (Historique)

Dans `ui/historique.py::_copier(chemin, est_reunion)` :
- source = `_locuteurs.md` si présent, sinon le `.md` (logique actuelle inchangée) ;
- si un prompt est actif → presse-papiers = `prefixer(transcription, contenu_actif)` ;
- sinon → copie brute.

Fonction pure testable `core/prompts.py::prefixer(transcription, contenu)`.

---

## 5. Fichiers touchés

| Fichier | Changement |
|---|---|
| `core/prompts.py` (nouveau) | constante `CR_SIMPLE`, `prompts_par_defaut()`, `prefixer(transcription, contenu)`, helper `prompt_actif(config) -> str | None` |
| `core/config.py` | + clés `prompts`, `prompt_actif` (défauts depuis `core/prompts`) |
| `ui/preferences.py` | + onglet « Prompts » (liste, édition, case actif, ＋/−), lecture/sauvegarde |
| `ui/historique.py` | `_copier` préfixe avec le prompt actif |

---

## 6. Tests prévus

- `config` : défauts (`prompts` contient CR simple, `prompt_actif == 0`) ; rétro-compat (config sans les clés) ; persistance.
- `prompts` : `prefixer` (préfixe + double saut de ligne + transcription) ; `prompt_actif(config)` (index valide / null / hors borne → None).
- `historique` : copie **avec** prompt actif → presse-papiers préfixé (via `PressePapiersFake`) ; **sans** actif → brut ; **diarization** (`_locuteurs.md`) → préfixé.
- `preferences` : onglet présent ; ajouter/supprimer ; case actif lue/sauvée ; édition titre/contenu persistée.

---

## 7. Prompt par défaut « CR simple » (contenu intégral)

```
Tu es un assistant spécialisé dans la rédaction de comptes-rendus au format markdown de réunion professionnels. À partir de la transcription que je te fournis, génère un CR concis et structuré en respectant les règles suivantes :

Format
- Titre : "CR — [Sujet] — [Date]"
- Participants listés sous le titre
- Séparateurs --- entre les sections
- Sections en gras et numérotées
- Listes à tirets pour les sous-points

Contenu
- Une section courte "Contexte" (1-2 phrases max) pour poser le cadre
- Une section "Points discutés" numérotés, chacun avec un titre en gras et un paragraphe court suivi de tirets si nécessaire
- Une section "Actions" listant uniquement les tâches concrètes avec le responsable, sans reformuler ce qui a déjà été dit plus haut

Règles de rédaction
- Phrases courtes et directes, pas de style administratif lourd
- Ne pas paraphraser inutilement : si un chiffre ou un terme technique est mentionné, le conserver tel quel
- Ne pas inventer de décisions ou d'actions qui ne sont pas explicitement dans la transcription
- Ignorer les apartés, problèmes techniques de connexion et digressions sans rapport avec le sujet

Voici la transcription :
```
