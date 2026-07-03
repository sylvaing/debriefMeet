# Spec — Changement de modèle à chaud (téléchargement + rechargement)

> **Statut :** ✅ **implémenté & testé** — `make test` vert (449 tests). Validation
> manuelle (changer de modèle dans les Préférences) restant à jouer par l'utilisateur.
> **Besoin :** quand l'utilisateur change le modèle Whisper dans les Préférences, le
> nouveau modèle doit être **téléchargé** (si absent du cache) **et pris en compte
> immédiatement**, sans redémarrer l'application.

---

## 1. Problème corrigé

Avant : valider un nouveau modèle dans les Préférences n'écrivait que la config. Le
moteur gardait ses workers préchargés sur l'**ancien** modèle, et `transcrire`
utilisait toujours `_nom_charge` (l'ancien). Le nouveau n'était ni téléchargé ni
utilisé **jusqu'au prochain lancement**, sans aucun retour visuel.

## 2. Comportement

À la validation des Préférences, si le modèle a **changé** :
1. **Téléchargement** si le modèle n'est pas en cache (`est_telecharge` faux) →
   `telecharger_modele` ; sinon on saute cette étape.
2. **Rechargement à chaud** du moteur (`recharger_modele`) : les workers de l'ancien
   modèle sont arrêtés et relancés avec le nouveau, préchargé.
3. Le tout dans un **QThread** (jamais sur le thread GUI), avec une **barre de
   progression indéterminée** (`QProgressDialog`). À la fin, la fenêtre se ferme.
4. **Échec** (réseau, etc.) → message clair ; la config est déjà sauvée donc le
   nouveau modèle sera de toute façon pris au prochain démarrage.

Si le modèle n'a pas changé → fermeture directe (aucun rechargement).

## 3. Implémentation

| Fichier | Changement |
|---|---|
| `platform/interfaces.py` | `MoteurTranscription.recharger_modele(nom)` (défaut : `terminer()` + `charger_modele()`) |
| `platform/macos/moteur_mlx.py` | `terminer()` **réinitialise `_n_workers`** → un rechargement repart d'un pool propre (pas de cumul d'anciens workers) |
| `ui/chargeur_modele.py` (nouveau) | `ChargeurModele` (QObject worker : télécharge si besoin puis recharge, mutualisé) ; `precharger_au_demarrage` (1er lancement) |
| `ui/preferences.py` | `_changer_modele` (QThread + `QProgressDialog`) ; param `moteur` ; slots `_sur_modele_charge`/`_sur_modele_echec` |
| `ui/tray.py` | param `moteur`, passé aux Préférences |
| `__main__.py` | `IconeTray(..., moteur=adaptateurs.moteur)` ; `precharger_au_demarrage(...)` après `tray.show()` (remplace le `charger_modele` silencieux) |

### Piège threads (corrigé)

Les signaux `fini`/`echec` du worker sont connectés à des **slots de `self`**
(`FenetrePreferences`, QObject du thread principal) et **non à des lambdas locales**.
Une lambda (récepteur non-QObject) aurait été exécutée **dans le thread worker** →
manipulation de la GUI hors thread principal → **blocage** (constaté puis corrigé).

## 3bis. Premier lancement (téléchargement initial visible)

Avant : au 1er lancement, `__main__` préchargeait le modèle **en silence** dans les
workers → la première transcription « gelait » le temps du download (~1 Go pour
large-v3), sans aucun retour. Pire, les **2 workers** pouvaient télécharger le même
modèle **en parallèle**.

Maintenant : le préchargement est **déplacé après l'affichage du tray**, dans
`ui/chargeur_modele.py::precharger_au_demarrage` :
- modèle **déjà en cache** → préchargement silencieux (comme avant) ;
- **absent** → fenêtre **« Téléchargement du modèle initial… »** (barre indéterminée,
  QThread + boucle d'événements imbriquée), téléchargé **une seule fois** puis workers
  préchargés depuis le cache (plus de double-download) ;
- **hors-ligne / échec** → message clair ; le tray est déjà affiché, l'app démarre
  quand même (transcription indisponible jusqu'au téléchargement, réessayable via les
  Préférences).

Le worker `ChargeurModele` est **mutualisé** entre ce flux et le changement de modèle
des Préférences (même garde-fou threads : aucune GUI hors du thread principal).

## 4. Limite connue

Changer de modèle **pendant** une réunion/dictée active arrêterait les workers en
cours d'usage (le worker se relance tout seul à la tranche suivante, mais c'est une
action à éviter). Cas normal : on change de modèle au repos.

## 5. Tests

- `moteur_mlx` : `terminer` remet `_n_workers` à 0 ; `recharger_modele` arrête
  l'ancien worker et relance `_TAILLE_POOL` workers du nouveau modèle.
- `preferences` : `recharger_modele` défaut (MoteurFake) ; `_ChargeurModele`
  (téléchargement si absent / pas si présent / échec → signal) ; `_appliquer` ne
  recharge pas si le modèle est inchangé, et télécharge+recharge s'il change
  (thread réel attendu jusqu'à sa fin).

## 6. Catalogue de modèles — à étendre : `large-v3-turbo`

> **Statut :** 🔲 planifié — spec dédiée : [19-ajout-modele-large-v3-turbo.md](19-ajout-modele-large-v3-turbo.md).

`large-v3-turbo` est un large-v3 distillé (décodeur réduit) : **~2× plus rapide**
bout-en-bout à qualité quasi équivalente, pour un poids plus léger (~1,6 Go en MLX).
Très intéressant pour la dictée et les tranches de réunion sur Apple Silicon.

L'architecture est **agnostique au modèle** : exposer `turbo` ne demande qu'une
entrée dans `core/modeles.py::TABLE_MLX` (repo `mlx-community/whisper-large-v3-turbo`)
et son équivalent faster-whisper (`large-v3-turbo`) pour Windows/Linux. Points à
couvrir lors de l'ajout :

- `core/modeles.py` : entrée `"large-v3-turbo"` dans `TABLE_MLX` (+ table faster-whisper aux Phases 5/6).
- `ui/preferences.py` : le sélecteur liste `NOMS_LOGIQUES` → apparaît automatiquement ; vérifier l'ordre/le libellé et la taille affichée au téléchargement.
- Tests : `test_modeles.py` (résolution + exhaustivité) et `test_build.py::test_table_mlx_complete`.
- Vérifier que diarization (passe finale) et AEC restent inchangés (ils ne dépendent pas du modèle de transcription).
