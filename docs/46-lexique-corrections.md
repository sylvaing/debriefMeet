# Spec — Lexique de corrections (termes mal transcrits, injectés dans les prompts)

> **Statut :** 📝 spec validée à implémenter (2026-08-05).
> **Besoin :** la transcription (locale Whisper comme Voxtral) écorche systématiquement
> les noms propres et le jargon métier (« Blue Moon » pour BlueMind, « Seppning Club »
> pour SecNumCloud, « Mappy » pour MAPI…). L'utilisateur maintient dans les Préférences
> un **tableau de correspondances « Entendu → À écrire »** ; l'app en dérive un **bloc
> d'instructions de correction** ajouté automatiquement aux prompts envoyés à l'IA —
> génération du CR Mistral **et** copie de transcription avec prompt. Bonus : les termes
> corrects nourrissent le `context_bias` Voxtral pour mieux transcrire dès le départ.

---

## 1. Décisions actées

1. **Lexique global unique** — un seul tableau pour toute l'app, pas de lexique par
   prompt (les termes métier valent pour toutes les réunions). S'applique à **tous**
   les prompts (actif, choix ponctuel « Générer le CR ▾ », repli CR simple).
2. **Injection à la volée, jamais dans les prompts stockés** — les prompts de l'onglet
   Prompts restent intacts ; le bloc est généré au moment de l'usage à partir de la
   config. Modifier le lexique corrige donc tous les prompts d'un coup, sans migration.
3. **Chapeau d'instructions figé dans le code** (constante de `core/lexique.py`) — seul
   le tableau est éditable. On le rendra paramétrable plus tard si le besoin apparaît.
4. **UI : section dédiée « Lexique »** dans la barre latérale des Préférences (pas un
   sous-bloc de « Prompts » — il faut de la place pour le tableau).
5. **Bonus Voxtral** : la colonne « À écrire » alimente le `context_bias` de la
   transcription Voxtral, **après** les noms d'invités BlueMind (prioritaires), dans la
   limite des 100 jetons existante.
6. **Défauts pré-remplis** avec le vocabulaire BlueMind (cf. §7) et lexique **actif par
   défaut** — les installations existantes (clé absente → défaut) en bénéficient
   immédiatement.

Détails actés (mineurs) :
- Une cellule « Entendu » accepte **plusieurs variantes séparées par des virgules**
  (`Blue Moon, Bluemine, Blue Mind`).
- La cellule « À écrire » peut porter une précision entre parenthèses
  (`ACME (société fictive)`) — reprise telle quelle dans le bloc injecté,
  **retirée** pour le `context_bias` (cf. §5).
- Ligne dont « Entendu » **ou** « À écrire » est vide → **ignorée** à l'usage (pas
  d'erreur, pas de nettoyage automatique de la config : l'utilisateur peut laisser une
  ligne en cours de saisie).
- Tableau vide (ou que des lignes ignorées) → **aucun bloc injecté**, même si
  `lexique_actif` est vrai.
- La copie **sans** prompt actif reste **brute** : le bloc n'est jamais injecté seul
  (c'est une instruction pour un LLM, pas un contenu autoportant).
- « Copier le CR » n'est pas concerné (le CR est déjà du texte rédigé/corrigé).

---

## 2. Stockage (config.json)

Deux nouvelles clés (ajoutées aux `_DEFAUTS`, rétro-compatibles : clé absente → défaut) :

| Clé | Type | Défaut |
|---|---|---|
| `lexique_corrections` | liste de `{ "entendu": str, "ecrire": str }` | tableau pré-rempli (§7) |
| `lexique_actif` | bool | `true` |

Comme pour `prompts`, le défaut est **mutable** → fourni par une fonction
`corrections_par_defaut()` de `core/lexique.py` (copie fraîche à chaque appel, même
motif que `prompts_par_defaut()` — le deepcopy des `_DEFAUTS` de `config.py` couvre
déjà le partage).

---

## 3. Module pur `core/lexique.py`

Aucun import Qt ni OS-spécifique (règle d'or `core/`). API :

```python
def corrections_par_defaut() -> list[dict]      # copie fraîche du tableau §7
def bloc_instructions(corrections) -> str | None
def completer_prompt(prompt: str, config) -> str
def termes_biais(corrections) -> list[str]      # colonne « À écrire », pour Voxtral
```

- `bloc_instructions(corrections)` : rend le bloc à injecter (§4), ou `None` si aucune
  ligne exploitable. Filtre les lignes vides/incomplètes, préserve l'ordre du tableau.
- `completer_prompt(prompt, config)` : retourne `prompt` + bloc si `lexique_actif` et
  bloc non-`None`, sinon `prompt` inchangé. **Seul point d'entrée** des deux sites
  d'injection (§5) — la politique (clé d'activation, tableau vide) vit ici, pas chez
  les appelants.
- `termes_biais(corrections)` : colonne « À écrire » des lignes exploitables, **sans**
  les précisions entre parenthèses (`ACME (société fictive)` → `MASA`).
  Le découpage en jetons sans espace ni virgule reste l'affaire de
  `_jetons_context_bias` (transcription.py), qui traite déjà ce cas pour les invités.

---

## 4. Bloc injecté (format)

Ajouté **à la fin du prompt** (après `rstrip()`), séparé par une ligne vide. Des lignes
simples plutôt qu'un tableau markdown — plus robuste pour le modèle. Gabarit exact :

```
Corrections de transcription :
la transcription contient des erreurs phonétiques sur les noms propres et le jargon
technique. Corrige-les silencieusement dans ta réponse, sans les signaler.
Correspondances fréquentes (« entendu » → à écrire) :
- « Blue Moon », « Bluemine », « Blue Mind » → BlueMind
- « Hotlook », « hot look » → Outlook
- « Seppning Club », « Second Club » → SecNumCloud
…
Étends cette logique à tout terme manifestement mal entendu : sigles, noms de produits,
noms de partenaires. Un nom de personne ou d'organisation dont tu n'es pas sûr : ne
l'invente pas — écris-le suivi de « (à confirmer) », ou omets-le.
```

Les variantes d'une cellule « Entendu » sont découpées sur la virgule et mises chacune
entre guillemets « … ». Le chapeau et la consigne finale sont des constantes du module.

Ordre final du message envoyé pour le CR (rappel `cr.py`) : prompt → **bloc lexique** →
lignes `(Sujet…)`, `(Date…)`, `(Participants…)` → transcription. Le bloc est ajouté par
le pipeline **avant** l'appel à `generer_cr` — `cr.py` ne change pas.

---

## 5. Points d'injection (2 + bonus Voxtral)

### 5.1 Génération du CR Mistral

`core/mistral/pipeline.py::generer_cr_reunion` — juste **après** la résolution du
prompt (ponctuel > actif > `CR_SIMPLE_CONTENU`) :

```python
prompt = lexique.completer_prompt(prompt, config)
```

Un seul site → couvre le bouton « Générer le CR », la flèche de choix ponctuel du
prompt, l'item du menu ⋯ et le repli CR simple.

### 5.2 Copie de transcription avec prompt (Historique)

`ui/reunion_view.py::_copier` — le contenu du prompt actif est complété avant le
préfixage :

```python
contenu = _prompts.contenu_actif(...)
if contenu:
    texte = _prompts.prefixer(texte, lexique.completer_prompt(contenu, self._config))
```

Pas de prompt actif → copie brute inchangée (décision §1). La copie auto du mode
Dictée reste brute (périmètre docs/12 inchangé).

### 5.3 Bonus — `context_bias` Voxtral

`pipeline.py` passe aujourd'hui `infos.noms_invites` aux deux appels
`_transcrire_via_voxtral`. Devient :

```python
context_bias = infos.noms_invites + lexique.termes_biais(config.get("lexique_corrections"))
```

Invités d'abord (prioritaires dans la coupe à 100 jetons de `_construire_donnees`),
dédoublonnage déjà assuré par `_jetons_context_bias`. Le biais s'applique **même si**
`lexique_actif` est faux ? **Non** — même interrupteur : sans lexique actif, on
n'ajoute rien (un seul réglage à comprendre pour l'utilisateur).

---

## 6. Section Préférences « Lexique »

Nouvelle entrée dans `_sections()` de `preferences_view.py`, entre **Prompts** et
**Dossiers** (proximité thématique avec Prompts) :

```python
("Lexique", "book-open", self._section_lexique),
```

> ⚠️ Icônes Phosphor **vendorées** : ajouter `book-open.svg` dans
> `ui/assets/icons/phosphor/` (même source/style que les 38 existantes).

Contenu de la section (`_section_lexique`, `setMaximumWidth(600)` comme les autres) :

- Texte d'intro : « Termes que la transcription écrit mal. Les correspondances sont
  ajoutées aux prompts (génération du CR et copie avec prompt) pour que l'IA corrige
  silencieusement. »
- Case **« Corriger les termes mal transcrits »** → `lexique_actif` (écriture
  immédiate). Décochée → tableau grisé (désactivé, pas masqué).
- **`QTableWidget` 2 colonnes** « Entendu (variantes séparées par des virgules) » /
  « À écrire », lignes éditables in-place, hauteur extensible (le tableau prend la
  place verticale disponible — c'est la raison de la section dédiée).
- Boutons **＋** / **−** sous le tableau (icônes `plus`/`minus` existantes, même motif
  que la liste des prompts) : ＋ ajoute une ligne vide et ouvre l'édition de la 1ʳᵉ
  cellule ; − supprime la (les) ligne(s) sélectionnée(s), sans confirmation (pas de
  perte grave — une ligne se retape en 10 s).
- Libellé d'aide sous le tableau : mention du garde-fou « (à confirmer) » et du fait
  que les termes « À écrire » guident aussi la transcription Voxtral.
- **Persistance** : autosave débouncée `_DELAI_AUTOSAVE_MS` (400 ms) sur édition de
  cellule, immédiate sur ajout/suppression de ligne et toggle de la case — mêmes
  helpers `_definir` / `_definir_differe` que le reste de la vue.

---

## 7. Tableau par défaut

Repris du besoin d'origine (vocabulaire BlueMind — l'app n'est déployée qu'en interne) :

| entendu | ecrire |
|---|---|
| afida | Acme |
| aron | Bastien |
| Blue Moon, Bluemine, Blue Mind | BlueMind |
| Hotlook, hot look | Outlook |
| Seppning Club, Second Club | SecNumCloud |
| Maza, Mazin | ACME (société fictive) |
| dire-câble, dircad | dircab (directeur de cabinet) |
| Mappy | MAPI |
| IMAT | IMAP |
| SNTP | SMTP |

(« IMAT, SNTP → IMAP, SMTP » de la capture d'origine est éclaté en 2 lignes : une
correspondance = un terme cible, sinon le rendu « → IMAP, SMTP » est ambigu et
`termes_biais` propre.)

Le chapeau mentionne déjà les sigles à étendre (MTE, MEAE, RIE, DINUM, ANSSI, SNUM,
RESCOM, UGAP) ? **Non** — ces sigles-là sont *corrects* quand ils sont bien entendus ;
les mettre en dur dans le chapeau le rendrait faux hors contexte BlueMind. S'ils sont
souvent écorchés, l'utilisateur les ajoute au tableau (et ils partent alors aussi en
`context_bias`, ce qui est le vrai fix).

---

## 8. Tests

Nouveau `tests/test_lexique.py` (pur, sans Qt) :
- `bloc_instructions` : rendu exact d'un tableau nominal (variantes multiples,
  guillemets), lignes vides/incomplètes ignorées, tableau vide → `None` ;
- `completer_prompt` : actif + tableau → prompt suffixé ; `lexique_actif=False` ou
  tableau vide → prompt inchangé (identité, pas de `\n` parasite) ;
- `termes_biais` : parenthèses retirées, lignes ignorées filtrées, ordre préservé.

Extensions de tests existants :
- `test_mistral_pipeline.py` : le prompt passé à `generer_cr` contient le bloc quand
  le lexique est actif ; ne le contient pas sinon ; `context_bias` transmis =
  invités + termes du lexique (invités en tête) ;
- `test_reunion_view.py` : copie avec prompt actif + lexique → presse-papiers =
  prompt + bloc + transcription ; sans prompt actif → brute même avec lexique ;
- `test_preferences_view.py` (ou module dédié) : édition de cellule → config après
  débounce ; ajout/suppression de ligne ; toggle → `lexique_actif` ; tableau grisé
  quand décoché ;
- `test_config.py` : défauts présents, copie fraîche (pas de partage du mutable).

Env de test : rien de nouveau — `QT_QPA_PLATFORM=offscreen` + `PYTHONPATH` du worktree
(cf. mémoire « tests Qt bloqués »).

---

## 9. Hors périmètre (explicitement)

- Correction **a posteriori** des `.md` déjà transcrits (rechercher/remplacer local) —
  autre feature, autre spec ; ici on ne corrige qu'au moment où un LLM intervient.
- Lexique par prompt, import/export du tableau, chapeau éditable — YAGNI tant que le
  besoin n'est pas constaté.
- Le **hotword/initial_prompt Whisper local** : le lexique pourrait un jour biaiser
  aussi le moteur local (paramètre `initial_prompt`), mais l'effet est moins prévisible
  (risque d'hallucination du prompt dans la sortie) — à explorer séparément si besoin.

---

## 10. Récap fichiers touchés

| Fichier | Changement |
|---|---|
| `core/lexique.py` | **nouveau** — défauts, bloc, `completer_prompt`, `termes_biais` |
| `core/config.py` | 2 clés dans `_DEFAUTS` (import de `lexique` comme pour `prompts`) |
| `core/mistral/pipeline.py` | `completer_prompt` après résolution du prompt ; lexique dans le `context_bias` |
| `ui/reunion_view.py` | `_copier` : contenu complété avant `prefixer` |
| `ui/preferences_view.py` | section « Lexique » (nav + page tableau) |
| `ui/assets/icons/phosphor/book-open.svg` | **nouveau** — icône de la section |
| `tests/test_lexique.py` | **nouveau** |
| `tests/test_mistral_pipeline.py`, `test_reunion_view.py`, `test_preferences_view.py`, `test_config.py` | extensions §8 |
| `CLAUDE.md`, `docs/46` (ce fichier) | table des docs + statut |
