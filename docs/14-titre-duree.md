# Spec — Titre éditable + durée dans l'Historique

> **Statut :** ✅ **implémenté & testé** — `make test` vert (441 tests). Validation
> manuelle (renommage inline + affichage durée) restant à jouer par l'utilisateur.
> **Besoin :** dans l'Historique, afficher pour chaque réunion un **titre libre éditable**
> (tout en gardant la **date** et l'**heure**) et la **durée** de la réunion.

---

## 1. Décisions actées

Le **nom de fichier reste l'identité stable** de la réunion (`AAAA-MM-JJ_HH-MM[-N].md`) :
il porte la date/heure **et** sert de base aux pistes audio (`_moi`, `_systeme`) et au
débrief locuteurs (`_locuteurs.md`). On n'y touche donc **jamais** — éditer un titre ne
renomme aucun satellite.

| Info | Source | Pourquoi |
|---|---|---|
| **Date + heure** | le **nom de fichier** | déjà canonique, jamais à migrer, garanti préservé |
| **Titre** (éditable) | le **H1 du `.md`** (`# …`) | éditer = réécrire une ligne, zéro renommage de satellites |
| **Durée** | commentaire **`<!-- duree_s: N -->`** en tête du `.md` | invisible au rendu ; écrit en fin de captation |

- **Pas de titre custom** = le H1 est le défaut `Réunion — <date>` → l'Historique affiche
  la date/heure (comportement antérieur). Un titre saisi remplace l'affichage.
- **Vider** le titre → restaure le H1 par défaut (`titre_reunion` renvoie de nouveau `None`).
- **Durée inconnue** (anciennes réunions sans commentaire) → repli : longueur de l'audio
  WAV retenu, sinon offset de la dernière tranche transcrite, sinon « — ».
- **Format durée** : `< 1 h → « 32 min »`, `≥ 1 h → « 1 h 05 »`.

## 2. Cœur (`core/fichiers.py`)

Fonctions pures, testables (aucune dépendance UI) :

| Fonction | Rôle |
|---|---|
| `date_heure_reunion(md) -> datetime \| None` | déduit la date/heure du **nom** (None si nom de journal) |
| `titre_reunion(md) -> str \| None` | H1 custom, ou None si défaut `Réunion — <date>` |
| `definir_titre(md, titre)` | réécrit le H1 (titre vide → restaure le défaut), reste du fichier intact |
| `duree_reunion(md) -> int \| None` | commentaire stocké → repli audio WAV → repli dernière tranche → None |
| `definir_duree(md, secondes)` | écrit/maj `<!-- duree_s: N -->` après le H1 (idempotent) |
| `formater_duree(secondes) -> str` | « 32 min » / « 1 h 05 » / « — » |

## 3. Écriture de la durée (`core/reunion.py`)

À l'arrêt d'une réunion (`_arreter`, branches **live** et **audio-seul**), la durée
écoulée (`datetime.now() - debut`) est écrite via `definir_duree` sur le `.md` finalisé
(`_enregistrer_duree`).

## 4. Préservation en transcription différée (`core/transcription_differee.py`)

`transcrire_reunion` **réécrit** tout le `.md` (placeholder → vraie transcription). Le
**titre custom** est déjà conservé (via `_titre`, qui relit le H1) ; la **durée** est
relue avant la réécriture puis ré-appliquée après (`definir_duree`).

## 5. UI Historique (`ui/historique.py`)

- Ligne réunion : **`_ChampTitre`** (titre éditable) + libellé **métadonnées grisé**
  (`date · heure · durée` si titre, sinon `durée` seule pour éviter la redite avec la
  date affichée comme titre).
- **`_ChampTitre`** : double-clic sur le libellé → `QLineEdit` ; **Entrée** valide,
  **Échap** annule (consommé pour ne pas fermer le `QDialog`). `on_commit` n'est appelé
  qu'en cas de changement réel. Anti-réentrance sur `editingFinished` (masquer le champ
  ré-émet le signal).
- `_renommer` : `definir_titre` puis rechargement **différé** (`QTimer.singleShot(0)`)
  car le widget du titre est détruit par le rechargement, or on est encore dans son
  gestionnaire d'événement.
- Le **Journal** garde son affichage actuel (nom de fichier, pas de titre/durée).

## 6. Tests

- `fichiers` : `date_heure_reunion` (nom valide / suffixe `-N` / journal / date invalide) ;
  `titre_reunion` (défaut date / défaut stem / custom / fichier absent) ; `definir_titre`
  (custom, vidage → défaut, durée préservée) ; `definir_duree` (commentaire, idempotence,
  marqueur en-attente conservé) ; `duree_reunion` (commentaire prioritaire, repli WAV,
  repli tranche, inconnue) ; `formater_duree`.
- `transcription_differee` : titre custom + durée conservés après réécriture.
- `historique` : titre custom affiché, date/heure affichée si pas de titre, durée affichée,
  `_renommer` écrit le titre, `_ChampTitre` (commit / sans changement / annulation).
