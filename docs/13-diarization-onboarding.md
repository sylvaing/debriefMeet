# Spec — Onboarding diarization (token Hugging Face + assistant guidé)

> **Statut :** ✅ **TERMINÉ & VALIDÉ** (Lot 1 + Lot 2, 475 tests verts, validation
> manuelle in-app par l'utilisateur le 2026-06-29). Plomberie (token à la volée jamais
> stocké, `local_files_only` au chargement), gating (`diarization_prete`), section
> Préférences, assistant guidé 5 étapes avec **illustrations maison**
> (`ui/assets/diar_etape_{1..5}.svg`, rendues via `QSvgRenderer`).
> **Besoin :** n'activer la diarization que si l'utilisateur a **renseigné un token HF** et
> **téléchargé** le modèle pyannote ; et **guider visuellement** la création de compte,
> l'acceptation de la licence, la création et la copie du token.

---

## 1. État actuel

- Bouton « Générer les locuteurs » actif dès que le **moteur de transcription** existe (`GestionnaireDiarization.disponible()`), **sans** vérifier token ni modèle → échec à l'exécution si non configuré (`Pipeline.from_pretrained` → None → message d'erreur).
- Token lu via `HF_TOKEN` (env) ou cache HF (`huggingface_hub.get_token()`), dans `core/diarization.py::_token_hf`.
- Modèle gated : `pyannote/speaker-diarization-community-1`.

## 2. Décisions actées

1. **Token NON stocké, utilisé à la volée** : le token n'est nécessaire qu'au **téléchargement** du modèle gated. Saisi dans l'assistant, passé directement à `from_pretrained(repo, token=…)` pour peupler le cache, puis **oublié** (pas de `login()`, pas de clé config, pas de secret persistant). Le chargement ultérieur lit le **cache local en `local_files_only=True`**, sans réseau ni token.
2. **Guide** → **illustrations maison** (schémas des pages HF), stables dans le temps. Conçues et **validées en aperçu** (comme l'icône) avant intégration.
3. **Bouton non configuré** → **grisé + tooltip** « Diarization non configurée — Préférences › Audio ». Pas d'ouverture auto de l'assistant depuis ce bouton.
4. **Emplacement config** → **section « Diarization » dans l'onglet Audio** (proximité avec la rétention audio, son prérequis).

Détails actés :
- Barre de téléchargement **indéterminée** + libellé d'étape.
- La **transcription différée** ne dépend **pas** du token HF → son bouton garde la condition actuelle (`disponible()` = moteur Whisper).
- Le champ token de l'assistant peut être **pré-rempli** depuis `HF_TOKEN`/cache HF s'il existe déjà (confort), mais on ne l'écrit nulle part.

## 3. Détection / gating

- `core/diarization.py` :
  - `modele_telecharge() -> bool` : le pipeline est en cache (test : `from_pretrained(PYANNOTE_PIPELINE, local_files_only=True)` réussit, ou présence cache via `huggingface_hub`).
  - `telecharger(token, progression=None)` : `Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=token)` (peuple le cache complet, sous-modèles inclus) ; lève une erreur **typée** en cas de 401 / 403 / réseau.
  - `configuree() -> bool` = `modele_telecharge()` (le token n'entre plus dans la condition).
  - `DiarizationPyannote._charger` : passe à **`from_pretrained(repo, local_files_only=True)` sans token** (le modèle est déjà en cache après l'onboarding).
- `GestionnaireDiarization.diarization_prete() -> bool` = `disponible()` (moteur) **et** `diarization.configuree()`.
- `ui/historique.py::_bouton_diarization` utilise `diarization_prete` (et non plus `dispo`) ; tooltip dédié si non configurée. `_bouton_transcrire` inchangé.

## 4. Section Préférences (onglet Audio)

- Libellé d'état : **« Diarization : ✅ configurée »** / **« non configurée »**.
- Bouton **« Configurer la diarization… »** → ouvre l'assistant (§5).
- Si configurée : bouton secondaire **« Réinitialiser / retélécharger »** (optionnel).

## 5. Assistant guidé (wizard, étapes)

Fenêtre dédiée `ui/assistant_diarization.py` — une page par étape, chacune avec **illustration maison + texte court + bouton-lien cliquable** :

1. **Créer un compte** → `huggingface.co/join`
2. **Accepter la licence du modèle** (gated) → page `pyannote/speaker-diarization-community-1` (« cliquer *Agree and access* »)
3. **Créer un token** (rôle *read*) → `huggingface.co/settings/tokens`
4. **Coller le token** (champ) + bouton **« Vérifier et télécharger »**
5. **Téléchargement** (barre indéterminée, tâche de fond) → succès → **« Diarization activée ✓ »** (ferme l'assistant, rafraîchit l'état + le bouton Historique)

Navigation Précédent / Suivant ; les liens ouvrent le navigateur (via `openLink`/`QDesktopServices`).

## 6. Téléchargement + gestion d'erreurs

À « Vérifier et télécharger » (dans un `QThread`) : `diarization.telecharger(token)` (token à la volée, jamais stocké).
- **401** (token invalide) → « Token incorrect — vérifiez l'étape 3 ».
- **403** (licence non acceptée) → « Licence non acceptée — revenez à l'étape 2 ».
- **réseau** → message clair, possibilité de réessayer.
- succès → modèle en cache → diarization prête.

## 7. Fichiers touchés

| Fichier | Changement |
|---|---|
| `core/diarization.py` | `modele_telecharge()`, `telecharger(token)` (erreurs typées), `configuree()` ; `_charger` → `local_files_only=True` sans token |
| `ui/gestionnaire_diarization.py` | `diarization_prete()` |
| `ui/historique.py` | bouton diarization conditionné à `diarization_prete` + tooltip |
| `ui/preferences.py` | section Diarization (onglet Audio) + bouton « Configurer… » |
| `ui/assistant_diarization.py` (nouveau) | wizard guidé + illustrations + worker téléchargement |
| `ui/assets/` | illustrations de l'assistant (après validation en aperçu) |

## 8. Tests prévus

- `diarization` : `modele_telecharge` / `telecharger` / `configuree` avec **huggingface_hub & pyannote monkeypatchés** (succès, 401, 403, réseau) — aucun appel réseau réel ; `_charger` appelé avec `local_files_only=True`.
- gestionnaire : `diarization_prete()` (moteur × configuree).
- `historique` : bouton diarization **grisé + tooltip** si non prête, **actif** si prête (faux gestionnaire) ; bouton transcription **non affecté**.
- `assistant` : enchaînement des étapes ; « Vérifier » appelle `telecharger` (fake) ; mapping des erreurs 401/403/réseau → messages.

## 9bis. Découpe d'implémentation (Lot 1 / Lot 2)

**Lot 1 — autonome (cette passe)** : tout sauf les illustrations finales.
- `core/diarization.py` (`telecharger`, `modele_telecharge`, `configuree`, `_charger` en `local_files_only`)
- gating (`gestionnaire.diarization_prete`, bouton Historique grisé + tooltip ; transcription non affectée)
- section Préférences (onglet Audio) + bouton « Configurer… »
- assistant fonctionnel **avec placeholders visuels** (les étapes, la navigation, le champ token, le worker de téléchargement, le mapping d'erreurs 401/403/réseau marchent)
- **tous les tests unitaires** (huggingface_hub & pyannote monkeypatchés, zéro réseau) ; `make test` vert, sortie rapportée
- DoD habituelle : tests à chaque brique, pas de régression, docs mises à jour (statut de ce doc + README/01 si pertinent).

**Lot 2 — avec validation (plus tard)** : conception des **illustrations maison** de l'assistant (proposées en aperçu, validées une à une) puis intégration en assets ; + validation manuelle end-to-end par l'utilisateur (vrai compte HF, token, licence, téléchargement réel).

> Ne pas concevoir les illustrations finales en Lot 1 : placeholders suffisants. La validation réelle (token/licence/download) revient à l'utilisateur.

## 10. À confirmer à l'implémentation

- **Nombre de licences à accepter** pour community-1 : ✅ **RÉSOLU — une seule**. La
  `config.yaml` de `pyannote/speaker-diarization-community-1` embarque ses sous-modèles
  dans le **même dépôt** (`segmentation: $model/segmentation`, `embedding:
  $model/embedding`, `plda: $model/plda` — `$model` = ce dépôt). Pas de dépôt gated
  séparé comme l'ancien 3.1 (qui pointait vers `pyannote/segmentation-3.0` + embedding
  externe). Donc **l'étape 2 = une seule page de licence**, l'assistant est correct tel quel.
- Taille/temps du téléchargement (quelques centaines de Mo) → confirmer le ressenti de la barre indéterminée.
