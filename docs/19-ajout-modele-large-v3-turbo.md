# Spec — Ajout du modèle `large-v3-turbo` au sélecteur (macOS)

> **Statut :** ✅ **implémenté et testé** (2026-06-30, 483 passed).
> **Besoin :** exposer `large-v3-turbo` dans le sélecteur de modèle des Préférences
> et en faire le **modèle par défaut**, sur la plateforme macOS (moteur MLX).
> Voir aussi [15-changement-modele.md](15-changement-modele.md) §6 (origine de la tâche).

---

## 1. Pourquoi

`large-v3-turbo` est un large-v3 distillé (décodeur réduit) : **~2× plus rapide** à
qualité quasi équivalente, pour un poids plus léger (**~1,6 Go** en MLX contre ~3 Go
pour large-v3). Idéal pour la dictée et les tranches de réunion sur Apple Silicon — on
le prend donc comme **défaut**.

Repo HuggingFace vérifié : `mlx-community/whisper-large-v3-turbo` (format MLX, 1,61 Go,
utilisable directement par `mlx_whisper`).

## 2. Périmètre

- **macOS uniquement** (moteur MLX). Le benchmark (`benchmark/modeles.py` :
  `TABLE_FASTER_WHISPER`, `TABLE_OPENVINO`, `SWEEP`) **n'est pas touché** — l'ajout
  côté faster-whisper / OpenVINO reste pour les Phases 5/6 (Windows/Linux).
- Architecture déjà **agnostique au modèle** : le sélecteur liste `NOMS_LOGIQUES`
  (dérivé de `TABLE_MLX`), donc une entrée dans la table suffit à le faire apparaître ;
  téléchargement HF au premier usage, résolution du repo et chargement dans les workers
  MLX suivent automatiquement.

## 3. Changements

| # | Fichier | Changement |
|---|---|---|
| 1 | `core/modeles.py` | Ajouter `"large-v3-turbo": "mlx-community/whisper-large-v3-turbo"` dans `TABLE_MLX`, **juste après `large-v3`** (ordre : du plus léger au plus précis, puis turbo). `NOMS_LOGIQUES` le reprend automatiquement. |
| 2 | `core/config.py` | Défaut `"modele"` : `large-v3` → **`large-v3-turbo`**. |
| 3 | `ui/preferences.py` | MAJ de la note sous le sélecteur (mention de turbo + correction des tailles). |

### Note du sélecteur (texte cible)

```
tiny et small sont rapides mais moins précis.
large-v3 offre la meilleure qualité (≈ 3 Go).
large-v3-turbo : qualité proche de large-v3, ~2× plus rapide (≈ 1,6 Go).
Le modèle est téléchargé au premier usage.
```

> Au passage on corrige le `≈ 1 Go` affiché pour large-v3, qui est faux (~3 Go).

## 4. Non-objectifs / inchangé

- **Pas** d'ajout côté benchmark / faster-whisper / OpenVINO (Phases 5/6).
- **Pas** de migration de config existante : un utilisateur qui a déjà choisi
  `large-v3` (ou autre) garde son choix ; seul le défaut des **nouvelles** installs
  devient turbo.
- Diarization (passe finale) et AEC **inchangés** — ils ne dépendent pas du modèle de
  transcription.
- Flux de téléchargement/rechargement à chaud **inchangé** (cf.
  [15-changement-modele.md](15-changement-modele.md)) : turbo en bénéficie tel quel.

## 5. Tests

- `tests/test_modeles.py` : résolution (`resoudre_mlx("large-v3-turbo")`) + exhaustivité
  — s'adapte à `NOMS_LOGIQUES`, vérifier qu'aucune liste figée ne casse.
- `tests/test_build.py::test_table_mlx_complete` : prend turbo automatiquement.
- Vérifier le défaut de config (`config.py`) si un test l'épingle.
- `make test` doit rester vert.

## 6. Validation manuelle

- Préférences → onglet Modèle : `large-v3-turbo` présent, sélectionné par défaut sur
  une install neuve, note à jour.
- Sélection de turbo → téléchargement (~1,6 Go) avec barre de progression, puis
  rechargement à chaud, puis transcription fonctionnelle.
