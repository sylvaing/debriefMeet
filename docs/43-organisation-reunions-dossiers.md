# docs/43 — Réorganisation : 1 dossier par réunion

> **Statut : ✅ EXÉCUTÉ, fusionné dans `main` et validé manuellement (2026-07-27).**
> Plan rédigé puis implémenté le même jour (commits `1ed3b17`, `009badb`). Toutes les
> décisions de conception avaient été validées avec Sylvain avant rédaction (cf. §1).
> La migration a tourné sur les **données réelles** (23 réunions → dossiers, collision
> `09-56`/`09-56-2` correctement séparée) et Sylvain a validé l'UI : listing complet,
> pas de ligne dupliquée pendant l'enregistrement, renommage du dossier sur changement
> de titre. 1113 tests passent sur `main`.
>
> Bilan d'exécution, écarts au plan et pièges rencontrés : **§15** en fin de document.
>
> **Correctif du 2026-08-28 — renommage pendant un job de fond (§6.4 et §16).** Le
> renommage du dossier est interdit pendant un *enregistrement* (§6.3, piège Windows),
> mais rien ne l'empêchait pendant un **job a posteriori** (CR Mistral, transcription
> différée, diarization), qui dure des minutes en tenant le chemin capturé à son
> lancement : 5 échecs réels entre le 2026-07-29 et le 2026-08-26, dont un CR perdu
> qu'il a fallu relancer à la main. Corrigé côté job — `resoudre_chemin_reunion`
> retrouve le dossier par son préfixe horodaté — et non par un verrou d'UI, l'association
> restant le geste que le flux pré-CR encourage à ce moment précis. Commits `01e2b8a`
> et `85fd33d`, +15 tests, 1599 passed.

---

## 0. Contexte & objectif

Aujourd'hui les réunions sont stockées **à plat** dans `~/Documents/debriefMeet/reunions/`.
L'identité d'une réunion = le **nom du `.md`** (`AAAA-MM-JJ_HH-MM[-N]`, précision minute) ;
tous les artefacts dérivés sont des fichiers frères nommés par dérivation du *stem* :

| Fichier (existant) | Rôle |
|---|---|
| `2026-07-02_15-01.md` | transcription (= identité) |
| `2026-07-02_15-01_moi.opus` / `..._systeme.opus` | pistes audio (`.opus` ou `.wav`) |
| `2026-07-02_15-01_locuteurs.md` | débrief diarization |
| `2026-07-02_15-01_CR.md` | compte-rendu Mistral (docs/42) |
| `2026-07-02_15-01.bluemind.json` | sidecar association BlueMind (docs/40) |

**Deux problèmes** :

1. **Suppression fragile.** `reunion_view._supprimer_un` supprime une **liste codée en dur**
   de suffixes ([reunion_view.py:570](../src/debrief_meet/ui/reunion_view.py)). Le CR est
   déjà couvert (commit `53ec1a4`), mais tout nouvel artefact dérivé — ou un cas limite de
   nommage — deviendrait orphelin. Motivation initiale de Sylvain : « quand on supprime tout
   d'une réunion il reste les CR ».
2. **Encombrement.** ~40 fichiers dérivés pour une poignée de réunions dans un seul dossier.

**Objectif** : **1 dossier par réunion**. La suppression devient `rmtree(dossier)` — plus
aucune classe d'artefact ne peut être orpheline. Les fichiers internes prennent des **noms
génériques** ; l'horodatage (et le titre) vivent dans le **nom du dossier**.

**Hors périmètre** : le **journal** (`AAAA-MM-JJ.md`, 1 fichier/jour) et la **dictée**
(presse-papiers, non stockée) restent inchangés.

---

## 1. Décisions verrouillées (validées avec Sylvain)

| # | Décision |
|---|---|
| **Format dossier** | `AAAA-MM-JJ_HH-MM-SS` — et `AAAA-MM-JJ_HH-MM-SS_<slug-titre>` si un événement/titre est associé. Précision **seconde** pour les nouvelles réunions. |
| **Fichiers internes** | noms **génériques** : `transcription.md`, `moi.opus`/`moi.wav`, `systeme.opus`/`systeme.wav`, `locuteurs.md`, `CR.md`, `bluemind.json`. |
| **Renommage** | le dossier est renommé à **chaque changement de titre** : association BlueMind **et** édition manuelle du H1. Titre vidé / dissociation → le dossier **revient** à l'horodatage seul. |
| **Migration** | ~~automatique au 1er démarrage (one-shot, idempotente)~~ — a tourné une fois, **code retiré depuis** (§7). |
| **Suppression** | supprimer une réunion = `shutil.rmtree(dossier)`. Fin de la liste de suffixes. |
| **Slug titre** | espaces → tirets ; accents **conservés** ; caractères interdits retirés ; tronqué à ~60 caractères. |

---

## 2. Grammaire des noms de dossier

### 2.1 Format cible

```
<dossier_reunions>/
  2026-07-27_15-30-45/                       ← réunion sans titre
  2026-07-27_16-05-12_Point-commerce-Bastien/  ← réunion avec titre associé
```

Grammaire : `<date>_<heure>[_<slug>]` avec
- `<date>` = `AAAA-MM-JJ` (toujours) ;
- `<heure>` = `HH-MM-SS` — **les secondes sont obligatoires** (cf. §7 : les dossiers
  legacy en `HH-MM` issus de la migration ont été normalisés en `HH-MM-00`) ;
- `<slug>` = titre slugifié (§3), présent seulement si un titre est associé.

Le séparateur entre le bloc horodaté et le slug est **`_`** ; à l'intérieur de chaque bloc,
le séparateur est **`-`**. Le slug peut lui-même contenir `-` (espaces convertis) mais
**jamais** `_` en tête (voir §3 : les `_` du titre original sont conservés dans le slug — le
parsing de date n'en dépend pas, cf. §2.3).

### 2.2 Collision

Deux réunions ne peuvent pratiquement pas partager la **seconde** → collision quasi
impossible pour les nouvelles. Filet de sécurité : si le dossier cible existe déjà (création
ou renommage), suffixer `-2`, `-3`, … **à la toute fin** du nom.

### 2.3 Parsing de la date depuis le nom de dossier

Règle robuste, insensible au contenu du slug :

```python
tokens = nom_dossier.split("_")
# tokens[0] = "AAAA-MM-JJ" ; tokens[1] = "HH-MM-SS" (+ éventuel compteur "-N")
# (les blocs date/heure ne contiennent jamais "_", donc tokens[0]/tokens[1] sont fiables
#  même si le slug contient "_")
```

Le motif `_MOTIF_HORODATAGE` n'est **pas ancré en fin** : un compteur de collision
(`-2`, `-3`… ajouté en toute fin de nom, §2.2) est simplement ignoré à la lecture.
Un nom sans secondes n'est plus reconnu — `date_heure_reunion` renvoie `None`.

---

## 3. Règle de slug (`slugifier_titre`)

Nouvelle fonction dans `core/fichiers.py` :

```python
def slugifier_titre(titre: str, longueur_max: int = 60) -> str:
    """Convertit un titre en segment de nom de dossier.

    - espaces (et blancs) → un seul tiret ;
    - caractères interdits par les systèmes de fichiers retirés :  /  \\  :  *  ?  "  <  >  |
      + caractères de contrôle et sauts de ligne ;
    - accents CONSERVÉS (é, à, ç… : macOS/Windows gèrent l'UTF-8) ;
    - tirets multiples repliés en un seul ; tirets/points/espaces en tête et fin supprimés ;
    - tronqué à `longueur_max` caractères (sans couper en plein milieu d'un mot si simple).

    Retourne "" si le titre est vide ou ne contient aucun caractère utile après nettoyage
    (dans ce cas le dossier reste horodaté seul).
    """
```

Exemples :
| Titre | Slug |
|---|---|
| `Point commerce Bastien` | `Point-commerce-Bastien` |
| `Réunion R&D — sprint 12` | `Réunion-R&D-sprint-12` |
| `Suivi client : Acme/Corp` | `Suivi-client-AcmeCorp` |
| `   ` (vide) | `` → dossier horodaté seul |

> `&` n'est pas interdit par les FS → conservé. Seuls les 9 caractères listés + contrôles sont
> retirés. Ne pas être plus agressif : le but est un nom **lisible**, pas un slug ASCII pur.

---

## 4. Modèle cible & correspondance des fichiers

Une réunion `2026-07-27_15-30-45` devient :

```
2026-07-27_15-30-45/
  transcription.md     (ex-<stem>.md, porte le H1/titre/durée)
  moi.opus             (ex-<stem>_moi.opus ; ou .wav)
  systeme.opus         (ex-<stem>_systeme.opus ; ou .wav)
  locuteurs.md         (ex-<stem>_locuteurs.md, si diarization faite)
  CR.md                (ex-<stem>_CR.md, si CR Mistral généré)
  bluemind.json        (ex-<stem>.bluemind.json, si associée)
```

Le **handle** manipulé partout dans l'app reste le chemin du `.md` — désormais
`<dossier>/transcription.md`. Comme tous les satellites sont **dans le même dossier**, les
helpers `with_name(...)` continuent de fonctionner ; seul le **nom** cible change (fixe au
lieu de `stem + suffixe`).

---

## 5. Changements par fichier

> Ordre de lecture = ordre de dépendance. `core/fichiers.py` est le pivot ; commencer par lui.

### 5.1 `core/fichiers.py` (pivot)

**Supprimer** la logique de suffixes dérivés devenue obsolète :
- constantes `_SUFFIXE_LOCUTEURS`, `_SUFFIXE_CR`, `_SUFFIXES_DERIVES` ;
- l'exclusion par suffixe dans le listing.

**Helpers de satellites** → noms fixes dans le dossier :
```python
def chemin_cr_mistral(md: Path) -> Path:   return md.with_name("CR.md")
def chemin_locuteurs(md: Path) -> Path:    return md.with_name("locuteurs.md")
def chemins_audio_reunion(md: Path) -> tuple[Path, Path]:
    return md.with_name("moi"), md.with_name("systeme")   # bases sans extension
```
`pistes_audio_existantes(md)` : inchangé (itère les 2 bases × `.opus`/`.wav`).

**Nom & création du dossier** :
```python
_MOTIF_HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})(?:-(\d{2}))?")
# (pas d'ancrage $ : on ne parse que le préfixe horodaté, cf. §2.3)

def slugifier_titre(titre: str, longueur_max: int = 60) -> str: ...   # §3

def nom_dossier_reunion(debut: datetime, titre: str | None = None) -> str:
    base = debut.strftime("%Y-%m-%d_%H-%M-%S")
    slug = slugifier_titre(titre or "")
    return f"{base}_{slug}" if slug else base

def chemin_reunion(dossier: Path, debut: datetime, titre: str | None = None) -> Path:
    """<dossier>/<nom[-N]>/transcription.md — nom unique (collision → -2, -3…).
    Ne crée pas le dossier ici ; EcrivainReunion.creer()/creer_placeholder() le fait."""
    nom = nom_dossier_reunion(debut, titre)
    cible = dossier / nom
    i = 2
    while cible.exists():
        cible = dossier / f"{nom}-{i}"
        i += 1
    return cible / "transcription.md"
```

**Parsing date** (lit le **dossier**, plus le stem) :
```python
def date_heure_reunion(md: Path) -> datetime | None:
    tokens = md.parent.name.split("_")
    if len(tokens) < 2:
        return None
    m = _MOTIF_HORODATAGE.match(f"{tokens[0]}_{tokens[1]}")
    if not m:
        return None
    a, mo, j, h, mi, ss = m.groups()
    try:
        return datetime(int(a), int(mo), int(j), int(h), int(mi), int(ss or 0))
    except ValueError:
        return None
```

**Renommage sur changement de titre** (nouveau — voir §6 pour les appelants) :
```python
def _prefixe_horodatage(nom_dossier: str) -> str:
    """Bloc horodaté du nom, slug exclu — conserve un éventuel compteur de collision
    pour ne pas fusionner deux réunions distinctes lors d'un renommage.
    '2026-07-27_20-12-45_Ancien-titre' -> '2026-07-27_20-12-45'."""
    tokens = nom_dossier.split("_")
    return "_".join(tokens[:2]) if len(tokens) >= 2 else nom_dossier

def renommer_dossier_reunion(md: Path, titre: str | None) -> Path:
    """Renomme le dossier pour refléter `titre` (ou horodatage seul si vide/None) et
    retourne le nouveau chemin du transcription.md. No-op (retourne `md`) si le nom ne
    change pas.

    ⚠️ NE JAMAIS appeler pendant un enregistrement actif (handles audio ouverts →
    échec du rename de dossier sous Windows, WinError 32). Cf. §6.3."""
    dossier = md.parent
    prefixe = _prefixe_horodatage(dossier.name)
    slug = slugifier_titre(titre or "")
    nouveau_nom = f"{prefixe}_{slug}" if slug else prefixe
    if nouveau_nom == dossier.name:
        return md
    cible = dossier.with_name(nouveau_nom)
    i = 2
    while cible.exists():
        cible = dossier.with_name(f"{nouveau_nom}-{i}")
        i += 1
    dossier.rename(cible)
    return cible / md.name
```

**Titre par défaut** (`titre_reunion`) : retirer la clause `reste == md.stem` (le stem vaut
désormais `"transcription"`). Le test `_MOTIF_DATE_HEURE.match(reste)` suffit à détecter le
titre par défaut `« Réunion — <date> »`. `definir_titre`/`definir_duree` : inchangés (ils
écrivent dans le `.md`), `date_heure_reunion` lit maintenant le dossier — OK.

**Listing** — **scinder** (le journal partage l'ancien `lister_enregistrements`, cf. §5.6) :
```python
def lister_reunions(dossier: Path) -> list[Path]:
    """transcription.md de chaque sous-dossier de réunion, trié récent → ancien
    (tri lexical sur le nom de dossier = chronologique, format ISO zéro-paddé)."""
    if not dossier.exists():
        return []
    out = [sous / "transcription.md" for sous in dossier.iterdir()
           if sous.is_dir() and (sous / "transcription.md").exists()]
    return sorted(out, key=lambda p: p.parent.name, reverse=True)

def lister_journal(dossier: Path) -> list[Path]:
    """Entrées de journal `AAAA-MM-JJ.md` (à plat) — inchangé vs l'ancien
    lister_enregistrements, mais sans l'exclusion de suffixes (le journal n'a pas de dérivés)."""
    if not dossier.exists():
        return []
    return sorted(dossier.glob("*.md"), reverse=True)
```
> Si tu préfères limiter le diff, garde le nom `lister_enregistrements` pour le **journal** et
> ajoute seulement `lister_reunions`. L'essentiel : le journal ne doit pas passer par le
> listing en sous-dossiers.

### 5.2 `core/reunion.py`

- `_demarrer` ([reunion.py:143](../src/debrief_meet/core/reunion.py)) : `self._debut = datetime.now()`
  (déjà à la seconde). Passer le **titre pré-associé** à `chemin_reunion` pour créer le dossier
  **déjà titré** en cas de démarrage pré-associé (F3), afin d'éviter tout renommage pendant
  l'enregistrement (cf. §6.3) :
  ```python
  titre_pre = self._evenement_pre_associe.titre if self._evenement_pre_associe else None
  fichier = chemin_reunion(Path(self._config.get("dossier_reunions")), self._debut, titre_pre)
  ```
- Ajouter le stockage/consommation de l'événement pré-associé :
  ```python
  def definir_evenement_pre_associe(self, evt) -> None:
      self._evenement_pre_associe = evt
  ```
  initialisé à `None` dans `__init__`, **consommé et remis à None** en fin de `_demarrer`.
- `chemins_audio_reunion(fichier)` : inchangé (renvoie les bases `moi`/`systeme` dans le dossier).
- `EcrivainReunion.creer`/`creer_placeholder` : le `parent.mkdir(parents=True, exist_ok=True)`
  crée bien le dossier de la réunion.

### 5.3 `ui/tray.py` (démarrage pré-associé F3)

- Avant de basculer en mode réunion pour un démarrage pré-associé, appeler
  `orchestrateur.definir_evenement_pre_associe(evt)` (l'événement est déjà connu via
  `_evenement_pre_associe`, [tray.py:127](../src/debrief_meet/ui/tray.py)).
- `_sur_reunion_demarree` ([tray.py:316](../src/debrief_meet/ui/tray.py)) : `associer_evenement`
  écrit alors sidecar + H1 + bloc invités dans un dossier **déjà titré** ; le renommage
  déclenché par l'association (§6.1) sera un **no-op** (nom déjà correct) → aucun rename pendant
  l'enregistrement. ✅

### 5.4 `ui/reunion_view.py`

- **Suppression** ([reunion_view.py:570](../src/debrief_meet/ui/reunion_view.py)) → radicalement
  simplifiée :
  ```python
  def _supprimer_un(self, chemin: Path) -> None:
      import shutil
      try:
          shutil.rmtree(chemin.parent)          # tout le dossier de la réunion
      except OSError:
          logger.warning("Suppression du dossier réunion impossible : %s", chemin.parent, exc_info=True)
  ```
  Garde-fou : vérifier que `chemin.parent` est bien un sous-dossier de `dossier_reunions`
  (jamais le dossier racine) avant `rmtree`. Les textes de confirmation restent valables.
- `_supprimer_audio_un` ([reunion_view.py:527](../src/debrief_meet/ui/reunion_view.py)) :
  inchangé (supprime seulement les pistes via `pistes_audio_existantes`, garde transcription+CR).
- **Édition manuelle du titre** : après `definir_titre(md, nouveau_titre)`, appeler
  `nouveau_md = renommer_dossier_reunion(md, nouveau_titre)`, puis mettre à jour le chemin
  retenu, `self._modele.recharger()` et re-sélectionner `nouveau_md`. (Localiser le handler
  d'édition de titre de la vue et y insérer le renommage.)
- **Association BlueMind** `_associer_bluemind` ([reunion_view.py:349](../src/debrief_meet/ui/reunion_view.py)) :
  après le dialog F1 (§6.1), recharger + re-sélectionner le **nouveau** chemin (le dossier a
  été renommé).
- Fallback d'affichage `chemin.stem` ([reunion_view.py:306](../src/debrief_meet/ui/reunion_view.py))
  → `chemin.parent.name`.
- **Surveillance live** : cf. §9.

### 5.5 `ui/capture_model.py`

- `recharger` ([capture_model.py:281](../src/debrief_meet/ui/capture_model.py)) :
  ```python
  fichiers = lister_reunions(self._dossier) if self._est_reunion else lister_journal(self._dossier)
  ```
- `_construire_ligne_reunion` fallback `chemin.stem`
  ([capture_model.py:97](../src/debrief_meet/ui/capture_model.py)) → `chemin.parent.name`.
- Imports : remplacer `lister_enregistrements` par `lister_reunions` + `lister_journal`.

### 5.6 Journal — **ne pas casser**

`ui/journal_view.py` + `_construire_ligne_journal` passent par `capture_model.recharger`. Après
§5.5, le journal utilise `lister_journal` (glob plat). Vérifier que la suppression d'une entrée
de journal ([journal_view.py:213](../src/debrief_meet/ui/journal_view.py)) reste un `unlink()`
de fichier (le journal n'a **pas** de dossier). ✅ Aucun changement de comportement attendu.

### 5.7 `core/diarization.py`

- Ligne [diarization.py:348](../src/debrief_meet/core/diarization.py) : remplacer
  `chemin_md.with_name(chemin_md.stem + "_locuteurs.md")` par l'appel au helper
  `chemin_locuteurs(chemin_md)` (import depuis `core.fichiers`).
- Ligne 349 : titre du fichier locuteurs `f"Réunion — {chemin_md.stem} — locuteurs"` →
  utiliser `chemin_md.parent.name` (ou le titre/date via helper).
- `chemins_audio_reunion` (ligne 315) : inchangé.

### 5.8 `core/transcription_differee.py`

- Ligne [transcription_differee.py:44](../src/debrief_meet/core/transcription_differee.py) :
  `f"Réunion — {md.stem}"` → `md.parent.name` (ou date formatée).
- `chemins_audio_reunion` (ligne 61) : inchangé.

### 5.9 `core/mistral/pipeline.py`

- Ligne [pipeline.py:162](../src/debrief_meet/core/mistral/pipeline.py) : fallback
  `chemin_md.stem` → `chemin_md.parent.name`.
- `chemin_cr_mistral`, `chemins_audio_reunion` : inchangés (via helpers).
- `core/mistral/transcription.py:134` (wav temporaire `chemin.stem + "_16k.wav"` = `transcription_16k.wav`) :
  laisser tel quel (dossier temporaire isolé, aucun conflit).

### 5.10 `ui/gestionnaire_diarization.py`

- Ligne [gestionnaire_diarization.py:194](../src/debrief_meet/ui/gestionnaire_diarization.py) :
  `md.stem` → `md.parent.name`.

### 5.11 `core/bluemind/association.py`

- `chemin_sidecar(md)` ([association.py:37](../src/debrief_meet/core/bluemind/association.py)) :
  `md.with_name(md.stem + ".bluemind.json")` → `md.with_name("bluemind.json")`.
- `finaliser_association` / `associer_evenement` : voir §6.1 (le renommage est déclenché par
  les **appelants UI**, pas ici, pour que le core reste sans effet de bord sur le nom de
  dossier et sans dépendre du contexte enregistrement/pas d'enregistrement).

---

## 6. Renommage du dossier sur changement de titre

### 6.1 Les 3 déclencheurs

| Déclencheur | Lieu | Enregistrement actif ? | Action |
|---|---|---|---|
| **Édition manuelle** du titre (H1) | `reunion_view` (handler d'édition) | Non (historique) | `definir_titre` → `renommer_dossier_reunion` → recharger + re-sélectionner |
| **Association F1** (post-réunion) | `bluemind_association` dialog / `reunion_view._associer_bluemind` | Non (historique) | `finaliser_association` (écrit dans le dossier) → `renommer_dossier_reunion` → recharger + re-sélectionner |
| **Pré-association F3** (démarrage) | `tray` → `reunion._demarrer` | **Oui** | Dossier créé **déjà titré** (§5.2/§5.3) → le renommage post-`reunion_demarree` est un **no-op** |

Le renommage retourne le **nouveau** chemin `transcription.md` : chaque appelant doit
remplacer le chemin qu'il détient et re-sélectionner la ligne.

### 6.2 Dissociation / titre vidé

`renommer_dossier_reunion(md, "")` (ou titre par défaut) → le slug est vide → le dossier
revient au **préfixe horodaté seul**. Cohérent avec la décision « le dossier reflète toujours
le titre courant ».

### 6.3 ⚠️ Piège Windows — ne pas renommer un dossier en cours d'enregistrement

Renommer un dossier qui contient des fichiers **ouverts** (`moi.opus`/`systeme.opus` écrits par
ffmpeg/`wave` pendant la réunion) **échoue sous Windows** (WinError 32, *sharing violation*) ;
c'est toléré sous macOS mais on ne s'y fie pas. **Stratégie retenue** : le seul cas où un titre
apparaît pendant un enregistrement actif est la **pré-association F3** → on crée le dossier
**déjà titré dès `_demarrer`** (§5.2), donc aucun renommage n'a lieu pendant l'enregistrement.
Les deux autres déclencheurs (édition manuelle, association F1) n'ont lieu que depuis
l'historique, réunion terminée. `renommer_dossier_reunion` reste donc toujours appelé **hors
enregistrement**.

### 6.4 ⚠️ Renommer pendant un **job de fond** — les chemins capturés se périment

Hors enregistrement ne veut pas dire « au repos » : un job a posteriori (CR Mistral,
transcription différée, diarization) dure des minutes et travaille sur le chemin capturé
à son lancement. Les deux déclencheurs de renommage restent disponibles pendant ce
temps — et le flux pré-CR **encourage** même l'association juste avant l'envoi (docs/42
§4.1). Le renommage réussit (aucun fichier ouvert), mais le job continue d'écrire à
l'ancienne adresse. Défaut réel, 5 échecs sur le poste de Sylvain entre le 2026-07-29 et
le 2026-08-26 ; **corrigé le 2026-08-28**, cf. §16.

---

## 7. Migration des réunions à plat — **retirée**, dossiers normalisés (2026-07-27)

> Le plan prévoyait ici un module `core/migration_dossiers.py` appelé au démarrage, qui
> convertissait les réunions du layout **à plat** d'avant docs/43 (`AAAA-MM-JJ_HH-MM.md` +
> satellites suffixés) vers le layout en dossiers. Il a tourné **une fois**, sur la seule
> installation existante (le poste de Sylvain, 23 réunions), puis **code et tests ont été
> supprimés** : l'app n'est déployée nulle part ailleurs, donc plus aucune donnée à plat ne
> peut se présenter.
>
> Cette migration laissait des dossiers en précision **minute** (`2026-07-02_15-01`), voire
> avec un compteur de collision (`2026-07-06_09-56-2`), ce qui obligeait à maintenir un
> parsing à deux formats. Ces 23 dossiers ont donc été **renommés en précision seconde** :
> `HH-MM` → `HH-MM-00`, et le compteur legacy `-2` → `-02` (la paire `09-56` / `09-56-2`
> devient `09-56-00` / `09-56-02`, distincte et dans le même ordre chronologique).
> Une sauvegarde a été prise avant l'opération.
>
> **Conséquence** : les secondes sont désormais **obligatoires** dans un nom de dossier de
> réunion, et tout le code de compatibilité legacy a été retiré de `core/fichiers.py`
> (`_MOTIF_HORODATAGE` exige les secondes, plus de désambiguïsation « 2 chiffres = secondes
> / 1 chiffre = compteur »). Un dossier sans secondes n'est plus reconnu comme une réunion.

## 8. Suppression simplifiée (rappel)

- **Une réunion** : `shutil.rmtree(chemin.parent)` (§5.4). Plus aucun artefact orphelin possible.
- **Audio seul** (`_supprimer_audio_un`) : inchangé (supprime les pistes, garde le reste).
- **Garde-fou** : refuser le `rmtree` si `chemin.parent` n'est pas strictement sous
  `dossier_reunions` (protège contre un chemin corrompu).

---

## 9. Rafraîchissement live (watcher)

`reunion_view._installer_surveillance` ([reunion_view.py:583](../src/debrief_meet/ui/reunion_view.py))
surveille aujourd'hui le dossier racine `reunions/`. Avec des sous-dossiers, l'**ajout de
tranches** dans `<dossier>/transcription.md` pendant une réunion **ne déclenche plus** le
watcher racine (un `QFileSystemWatcher` de dossier ne réagit qu'aux entrées ajoutées/retirées,
pas aux modifications d'un fichier dans un sous-dossier).

**Correctif** : surveiller aussi le **sous-dossier de la réunion active** et son
`transcription.md`.
- À `reunion_demarree` (relayer le signal jusqu'à la vue, ou via le contrôleur) : `addPath` du
  sous-dossier **et** du `transcription.md`.
- À l'arrêt / changement de réunion active : `removePath` correspondant.
- Le `_timer_refresh` (200 ms, déjà présent) reste le filet de sécurité.

Le watcher racine reste utile pour détecter l'**apparition/suppression** d'une réunion (nouveau
sous-dossier, `rmtree`).

---

## 10. Tests

> `make test` (`pytest -m "not integration"`) doit rester vert. Beaucoup de tests supposent le
> layout à plat — les mettre à jour, ne pas les contourner. Rapporter le nouveau total.

### 10.1 À mettre à jour (au minimum)
- `test_fichiers.py` — noms de fichiers dérivés, `chemin_reunion`, `date_heure_reunion`
  (parsing depuis le dossier), listing, titre par défaut.
- `test_reunion.py` / `test_reunion_view.py` — création en sous-dossier, suppression `rmtree`,
  fallback d'affichage.
- Tests BlueMind (`test_*bluemind*`, sidecar `bluemind.json`, `finaliser_association`).
- Tests Mistral (`test_generateur_cr_mistral.py`, `test_mistral_*`) — `CR.md`.
- Tests diarization (`locuteurs.md`).
- Tests journal (`test_*journal*`) — **doivent rester verts sans modification** (preuve que le
  journal n'est pas cassé) ; adapter uniquement si un test importait `lister_enregistrements`.

### 10.2 Nouveaux tests à écrire
- `slugifier_titre` : espaces→tirets, accents conservés, caractères interdits retirés, troncature,
  titre vide → `""`, tirets multiples repliés.
- `nom_dossier_reunion` / `chemin_reunion` : avec/sans titre, précision seconde, collision `-2`.
- `date_heure_reunion` : dossier seconde (`_15-30-45`), nom **sans secondes** → `None`,
  compteur de collision ignoré (`_10-02-30-2` → 10:02:30), dossier titré (slug ignoré pour
  la date), slug contenant `_`, date invalide → `None`.
- `renommer_dossier_reunion` : ajout de titre, changement de titre, titre vidé → retour à
  l'horodatage, no-op si nom inchangé, collision cible existante, préservation de
  l'horodatage et d'un éventuel compteur de collision.
- Suppression : `rmtree` retire bien tout le dossier ; garde-fou hors `dossier_reunions`.

---

## 11. Ordre d'exécution recommandé

1. `core/fichiers.py` : slug, `nom_dossier_reunion`, `chemin_reunion`, `date_heure_reunion`,
   helpers satellites (noms fixes), `renommer_dossier_reunion`, split listing, `titre_reunion`.
   → écrire/adapter `test_fichiers.py` immédiatement.
2. `core/bluemind/association.py` : `chemin_sidecar` → `bluemind.json`.
3. `core/diarization.py`, `core/transcription_differee.py`, `core/mistral/pipeline.py` :
   remplacer les `stem` d'affichage par `parent.name`, utiliser les helpers.
4. `core/reunion.py` + `ui/tray.py` : événement pré-associé → dossier titré à la création (F3).
5. `ui/capture_model.py` : listing scindé + fallback `parent.name`.
6. `ui/reunion_view.py` : suppression `rmtree`, renommage sur titre/association, re-sélection,
   watcher sous-dossier (§9).
7. `ui/gestionnaire_diarization.py` : `parent.name`.
8. Suite de tests complète + nouveaux tests (§10).
9. Mise à jour docs & mémoire (§14).

---

## 12. Definition of Done

- [ ] `make test` vert ; rapporter le total (pas de régression hors périmètre ; le journal
      reste vert sans modification de logique).
- [ ] Une nouvelle réunion crée `AAAA-MM-JJ_HH-MM-SS/transcription.md` + satellites génériques.
- [ ] Associer un événement BlueMind (ou éditer le titre) **renomme** le dossier et l'historique
      pointe vers le nouveau chemin (pas de ligne fantôme, re-sélection correcte).
- [ ] Vider le titre / dissocier → le dossier revient à l'horodatage seul.
- [ ] « Tout supprimer » retire **le dossier entier** (transcription, audio, locuteurs, **CR**,
      sidecar) — vérifier qu'il ne reste rien.
- [x] Migration one-shot (code retiré depuis, §7) : les 23 réunions réelles → 23 dossiers,
      les 6 associées avec slug, la collision `09-56` / `09-56-2` en 2 dossiers distincts.
- [ ] Transcription **live** : l'historique se rafraîchit pendant l'enregistrement (watcher
      sous-dossier).
- [ ] Journal & dictée : comportement inchangé.
- [ ] Validation manuelle avec Sylvain avant fusion (idéalement sur une **copie** du dossier
      `reunions/` réel — cf. §13).

---

## 13. Pièges & précautions

- **Windows / rename de dossier ouvert** (§6.3) : ne jamais renommer pendant un enregistrement.
- **Ne pas casser le journal** (§5.6) : listing scindé, journal en glob plat.
- **`date_heure_reunion` lit le dossier** : tout code lisant l'identité via `md.stem` doit passer
  à `md.parent.name` — vérifier avec `grep -rn "\.stem" src/debrief_meet` en fin de chantier.
- **Sécurité `rmtree`** : garde-fou « strictement sous `dossier_reunions` ».
- **Secondes obligatoires** (§7) : depuis la normalisation des dossiers legacy, un nom sans
  secondes n'est plus reconnu (`date_heure_reunion` → `None`). Une réunion créée hors de
  l'app avec un nom en `HH-MM` seul serait listée mais sans date ni durée.
- **`chemin_reunion` a une nouvelle signature** (`titre` optionnel) : vérifier tous les appelants.

---

## 14. Docs & mémoire à mettre à jour en fin de chantier

- `CLAUDE.md` : ajouter une ligne dans la table de suivi (« Réorganisation 1 dossier/réunion —
  docs/43 ») et, si utile, une note sur le nouveau layout de stockage.
- Table « Docs de référence » de `CLAUDE.md` : ajouter `docs/43`.
- Mémoire projet : consigner le nouveau modèle de stockage (1 dossier/réunion, noms génériques,
  renommage sur titre, migration one-shot) — utile pour toutes les sessions futures.

---

## 15. Bilan d'exécution (2026-07-27) — écarts au plan

Le plan a été suivi intégralement (§11), avec deux écarts et un ajout à noter.

### 15.1 Écart : la migration a tourné sur les données réelles sans sauvegarde

Le plan recommandait de sauvegarder `~/Documents/debriefMeet/reunions/` (ou de pointer
`dossier_reunions` vers une copie) **avant** le premier lancement. Ça n'a pas été fait :
l'app a été lancée pour vérifier qu'elle démarrait, elle a chargé la config réelle et a
migré les 23 réunions immédiatement. Résultat correct (vérifié : 23 dossiers, les 6
associées BlueMind ont leur slug, la collision `09-56` / `09-56-2` donne 2 dossiers
distincts), mais la précaution n'a pas joué son rôle.

**Conséquence durable, renforcée depuis le retrait du code de migration (§7)** : un
`git checkout` vers un commit antérieur à `1ed3b17` rendrait les réunions **invisibles**
dans l'UI (l'ancien listing ne lit que les `.md` à plat), et il n'existe plus de migration
à rejouer. Le rollback n'est donc pas une opération neutre — il demanderait une migration
inverse écrite pour l'occasion.

### 15.2 Écart : dans `__main__.py`, `configurer_logs()` doit précéder le code métier

Le plan situait l'appel de migration « après le chargement de la config et avant la
construction des vues ». Appliqué littéralement, il tombait **entre `config.charger()` et
`configurer_logs()`** : aucun handler installé, donc ses traces partaient dans le vide — y
compris les `WARNING` d'échec par réunion, alors que la migration continuait volontairement
sur les suivantes. Défaut invisible en tests unitaires (le `caplog` de pytest capture, lui),
trouvé seulement sur le vrai log de Sylvain, après coup.

Le code concerné a depuis été retiré (§7), mais **la leçon reste valable pour la suite** :
dans `__main__.py`, tout code métier qui touche aux fichiers de l'utilisateur doit être
placé après `configurer_logs()`, jamais entre le chargement de la config et l'installation
des logs.

### 15.3 Ajout hors plan : réunion active exclue du listing

Bug **pré-existant** (antérieur à docs/43) que la surveillance du sous-dossier (§9) rendait
systématiquement visible : le `transcription.md` de la réunion active étant créé dès le
démarrage de l'enregistrement, elle s'affichait à la fois comme ligne normale **et** comme
ligne « en cours ». Corrigé dans le même commit que docs/43 :
`CaptureModel.definir_chemin_actif` (posé par `reunion_view.definir_reunion_active`, remis
à `None` au retour en `Mode.IDLE`), + 6 tests de non-régression.

### 15.4 Piège de validation rencontré

Le premier test manuel a été mené **avec l'ancien code** : `make run` depuis le dépôt
principal (alors sur `main` d'avant fusion) n'exécute pas le code d'un worktree, et un
worktree fraîchement créé n'a pas son propre `.venv`. Symptômes trompeurs — réunions
migrées invisibles, enregistrements toujours à plat — tous attribuables au layout à plat
de l'ancien listing. Pour tester un worktree :
`PYTHONPATH=src <dépôt-principal>/.venv/bin/python -m debrief_meet`.

### 15.5 Reliquat connu, sans impact

6 fichiers `*_CR.md` du 21/07 restent à la racine de `reunions/` : des CR orphelins
(aucune réunion correspondante, restes de tests manuels de docs/42). La migration les
ignore volontairement — elle ne traite que les `.md` de réunion. Invisibles dans
l'Historique, supprimables à la main.

---

## 16. Correctif du 2026-08-28 — renommage pendant un job de fond

### 16.1 Symptôme et preuves

Cinq `FileNotFoundError` dans le log du poste de Sylvain, sur trois types de job
différents, tous du même moule — un `[Errno 2]` sur un chemin dont le **dossier** avait
été renommé entre-temps :

```
2026-07-29 12:12  CR Mistral échoué   (.../2026-07-29_10-48-11/transcription.md)
2026-08-12 15:06  Job transcription   (.../2026-08-12_14-53-42/transcription.md)
2026-08-12 16:45  CR Mistral échoué   (.../2026-08-12_15-47-28/transcription.md)
2026-08-26 16:19  CR Mistral échoué   : No such file .../2026-08-26_15-53-44/transcription.md
2026-08-26 16:26  CR Mistral échoué   : No such file .../2026-08-26_16-20-54/CR.md
```

Les deux cas du 26/08 sont datés à la seconde et documentent **deux étapes distinctes**
du même pipeline :

- **16:19** — job lancé à 16:19:14, upload Voxtral terminé à 16:19:31,043, échec
  **347 ms plus tard** : c'est la réécriture de `transcription.md`
  (`_ecrire_transcript_local`, récupération de la transcription en local) qui tombe dans
  le vide. Le renommage a donc eu lieu pendant les ~17 s de l'upload.
- **16:26** — la lecture initiale était passée (dossier encore à l'ancien nom), l'échec
  porte sur `CR.md` : le renommage est survenu **pendant la rédaction**, l'étape la plus
  longue.

Dans les deux cas la réunion a été associée à un événement BlueMind depuis l'Historique
pendant que le job tournait, et le CR a dû être relancé à la main (le second l'a d'ailleurs
été deux fois, un 503 Mistral s'étant intercalé).

### 16.2 Pourquoi ce n'est pas le flux pré-CR qui est en cause

`reunion_view._proposer_association_avant_cr` est correct : il retourne bien
`dlg.chemin_md` — le chemin **d'après** renommage — avec repli si le nouveau chemin
n'existe pas. Le trou est ailleurs, et il est structurel :

- `GestionnaireCRMistral.lancer` fige `chemin_md` dans le worker
  (`ui/generateur_cr_mistral.py`), idem `GestionnaireDiarization` ;
- `pipeline.generer_cr_reunion` touche le disque à **quatre moments séparés par des
  minutes** (sidecar + transcript, pistes audio, réécriture du `.md`, écriture du `CR.md`) ;
- **rien** ne verrouille l'association ni l'édition du titre pendant un job :
  `_etat_cr_mistral` ne grise que le bouton « Générer le CR », l'icône calendrier reste
  volontairement cliquable (§5.4) et `CaptureModel.setData` ne se protège que de
  `ligne.en_cours`, c'est-à-dire de l'**enregistrement** actif, pas d'un job.

### 16.3 Décision : rendre le job insensible au renommage, pas interdire le renommage

L'option « griser l'association et l'édition du titre tant qu'un job tourne » a été
écartée : elle bloque l'utilisateur plusieurs minutes **précisément au moment où il a
envie d'associer** — c'est le geste que le flux pré-CR (docs/42 §4.1) lui propose.

Retenu : l'**identité stable d'une réunion est son horodatage**, le renommage ne touchant
que le slug du titre (§2.1). `core/fichiers.resoudre_chemin_reunion(md)` retrouve donc le
dossier par son préfixe `AAAA-MM-JJ_HH-MM-SS`, et les jobs re-résolvent leur chemin avant
chaque écriture.

Trois garde-fous, tous délibérés :

| Situation | Comportement | Pourquoi |
|---|---|---|
| Dossier toujours présent | retour immédiat (**un seul `stat`**) | cas courant — le helper est appelé sur des chemins chauds |
| Aucun candidat (réunion supprimée) | chemin rendu **tel quel** | l'appelant échoue comme avant, avec le même message : réparer un renommage n'est pas inventer une réunion |
| **Plusieurs** candidats | chemin rendu **tel quel** | le compteur de collision (`-2`) est posé **après** le slug (§2.2) : deux réunions démarrées à la même seconde partagent le préfixe. Écrire le CR dans la mauvaise serait pire que l'échec réparé |

### 16.4 Points de re-résolution

Un avant chaque écriture, aux endroits exacts où ça a cassé en production :

| Fichier | Moment | Cas réel couvert |
|---|---|---|
| `core/mistral/pipeline.py` | entrée de `generer_cr_reunion` | renommage entre le clic et le démarrage effectif du worker |
| `core/mistral/pipeline.py` | après l'upload Voxtral, avant `_ecrire_transcript_local` | 2026-08-26 16:19 |
| `core/mistral/pipeline.py` | avant l'écriture de `CR.md` | 2026-08-26 16:26 |
| `core/transcription_differee.py` | avant la réécriture du `.md` | 2026-08-12 15:06 |
| `core/diarization.py` | avant l'écriture de `locuteurs.md` | même famille (jamais observé, même mécanisme) |

`_date_lisible` / `date_heure_reunion` n'ont pas besoin d'être protégés : ils ne lisent que
le **nom** du dossier, et l'horodatage survit au renommage.

### 16.5 Effet de bord trouvé en chemin : des signaux au chemin périmé

Les deux gestionnaires émettaient `termine`/`echoue` avec le chemin capturé au lancement.
Conséquence silencieuse côté diarization : `_inserer_bloc_invites_si_associe` lisait un
sidecar disparu et **ne disait rien** — le cartouche invités manquait sans le moindre
message (docs/40 §6.3). `_sur_terminee`/`_sur_erreur` re-résolvent désormais le chemin,
en **conservant l'ordre** `_job_en_cours = None` avant l'émission (invariant figé par les
tests de l'icône de job, cf. `CLAUDE.md`).

L'UI n'a **pas** été touchée par ailleurs : l'association reste cliquable pendant un job.
La seule séquelle est cosmétique — après le renommage la ligne perd l'icône de son job en
cours, jusqu'à la fin de celui-ci — et le bouton « Générer le CR » reste correctement
grisé entre-temps via `un_autre_job_tourne`.

### 16.6 Tests (15 nouveaux, 1599 passed)

Tous vérifiés **en contre-épreuve** (helper neutralisé → les 9 tests de régression
échouent, les 6 autres restent verts) :

- `test_fichiers.py` (8) : no-op, renommage dans les deux sens, nom de fichier conservé
  (`CR.md`/`locuteurs.md`), réunion supprimée, ambiguïté d'horodatage, dossier voisin non
  volé, nom non horodaté (journal) ;
- `test_mistral_pipeline.py` (3) : renommage pendant la rédaction, renommage pendant
  Voxtral, et **dossier supprimé → échoue toujours** (sans ce dernier, la re-résolution
  pourrait un jour masquer une vraie perte de données) ;
- `test_transcription_differee.py`, `test_diarization.py`,
  `test_generateur_cr_mistral.py`, `test_gestionnaire_diarization_bluemind.py` (1 chacun).

⚠️ Les tests de régression déclenchent le renommage **depuis le mock lui-même** (dans le
`side_effect` respx, dans `_transcrire_pret`, dans `diariser`) : c'est la vraie fenêtre de
course. Un renommage posé *avant* l'appel testerait un cas beaucoup plus facile — celui
que le code d'entrée gérait déjà — et resterait vert même en cas de régression.
