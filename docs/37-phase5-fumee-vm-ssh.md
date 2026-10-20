# Phase 5 — Fumée automatisée du setup Windows via SSH (VM)

> **Statut : ✅ TERMINÉ** (implémenté et validé le 2026-07-04 —
> `scripts/fumee_setup_vm.sh`, deux runs consécutifs verts sur la VM réelle).
> Dépend de : docs/32 ✅.
>
> **Objectif :** automatiser depuis le Mac, via SSH sur la VM Proxmox, tout ce qui
> est vérifiable **sans interface graphique** dans la checklist docs/32 §6
> (install / mise à jour / désinstallation). La partie interactive (tray visible,
> dictée réelle, en-tête de session) reste manuelle sur la console Proxmox/RDP —
> ce script réduit la checklist manuelle à ces seuls points.
>
> **Découverte lors de l'implémentation** (§7 ci-dessous, absente de la spec
> initiale) : `usPostUninstall` ne se déclenche jamais quand le désinstalleur Inno
> est lancé via SSH (session sans desktop) — l'auto-suppression de `unins000.exe`
> et le nettoyage `[Code]` de la clé Registre autostart en dépendent tous les
> deux. Confirmé par un mini-`.iss` instrumenté avec des marqueurs de fichier par
> étape. **Revalidé par Sylvain le 2026-07-04 en session interactive (RDP) :
> désinstallation complète et propre** (dossier app + dossier données + clé
> Registre tous supprimés, `Documents\debriefMeet` préservé) — confirme que c'est
> une limite de l'exécution via SSH, pas un bug du `.iss`. Aucune action produit
> requise ; les deux vérifications restent en `[INFO]` dans le script (fidèle à
> ce que SSH peut réellement observer).

---

## 1. Contexte et périmètre

La VM (`192.168.1.29`, SSH `sylvaing`, mot de passe hors dépôt) n'offre **pas de bureau via
SSH** (OpenSSH Windows = session sans desktop interactif) : le tray Qt n'y est pas
testable. En revanche, l'installeur Inno Setup s'exécute en silencieux, le système
de fichiers et le Registre se vérifient par commandes, et `debriefMeet.exe
--version` s'exécute **avant** toute init Qt (cf. `__main__.py:main()` — le routage
`--version` précède la création du `QApplication`), ce qui valide l'intégrité du
bundle PyInstaller (bootloader, imports du paquet, `_version.py` embarqué).

| Vérifiable via SSH (ce script) | Reste manuel (console/RDP) |
|---|---|
| Install silencieuse + arborescence | Tray visible, icône, menu |
| `--version` = intégrité du bundle | Dictée réelle (micro) |
| MAJ par-dessus : config préservée | En-tête de session dans les logs |
| Désinstallation : table docs/32 §4 | Notification, préférences |
| Nettoyage Registre (autostart) | Export diagnostic (clic tray) |

## 2. Livrable

Un script **`scripts/fumee_setup_vm.sh`** (Mac, `sh` strict comme les autres
`scripts/*_vm.sh`), sans argument obligatoire :

1. prend le setup le plus récent de `dist/debriefMeet-setup-*.exe` (ou le chemin
   passé en `$1`) ;
2. le téléverse sur la VM (`C:\Users\sylvaing\fumee\`) ;
3. déroule les phases §3 ;
4. imprime un tableau récapitulatif `OK`/`ECHEC` par vérification, et sort avec un
   code ≠ 0 si au moins une vérification obligatoire échoue.

Aucun fichier `.cmd` persistant côté VM si évitable : préférer des commandes
`cmd /c ...` / `powershell -NoProfile -Command ...` envoyées par SSH une à une
(plus simple à maintenir qu'un script distant à synchroniser).

## 3. Phases et vérifications

Chemins exacts (tous per-user, cf. docs/32 §4 et le piège `platformdirs
appauthor=False` — une seule racine de données) :

- App : `%LOCALAPPDATA%\Programs\debriefMeet\` (exe : `debriefMeet\debriefMeet.exe`
  — **vérifier le chemin réel produit par le onedir : `...\Programs\debriefMeet\debriefMeet.exe`
  ou un niveau plus profond selon la section `[Files]` du `.iss`** ; le script doit
  sonder les deux et rapporter celui trouvé) ;
- Données : `%LOCALAPPDATA%\debriefMeet\` (config.json, `Logs\`, `modeles\`) ;
- Documents : `%USERPROFILE%\Documents\debriefMeet\` (préservé) ;
- Autostart : valeur `debriefMeet` sous `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

### Phase A — install neuve

1. Pré-nettoyage best-effort : désinstaller silencieusement si un `unins000.exe`
   existe d'un run précédent, supprimer `%LOCALAPPDATA%\debriefMeet`.
2. `debriefMeet-setup-<v>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
   (le `[Run]` postinstall du `.iss` porte `skipifsilent` → l'app ne se lance pas).
   ⚠️ Attendre la fin réelle : lancer via `cmd /c start /wait "" <setup>` sinon la
   commande SSH rend la main avant la fin de l'installation.
3. Vérifier : exe présent, `unins000.exe` présent, raccourci menu Démarrer
   (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\debriefMeet.lnk`).
4. `debriefMeet.exe --version` → sortie contenant `debriefMeet 0.` (code retour 0).

### Phase B — mise à jour par-dessus

1. Créer un marqueur : écrire `%LOCALAPPDATA%\debriefMeet\config.json` avec un
   contenu JSON minimal valide contenant une clé reconnaissable (ex.
   `"modele": "small"`) + un fichier témoin dans `Documents\debriefMeet\`.
2. Relancer le même setup `/VERYSILENT` (même version rebuildée = cas nominal,
   docs/32 §6.3).
3. Vérifier : `config.json` intact (contient toujours `"small"`), fichier
   `Documents` intact, exe toujours présent.

### Phase C — désinstallation complète (D4)

1. `"%LOCALAPPDATA%\Programs\debriefMeet\unins000.exe" /VERYSILENT /NORESTART`
   (même remarque `start /wait`). NB : Inno copie le désinstalleur et se supprime
   après coup — prévoir une courte attente/boucle avant les vérifications.
2. Poser au préalable une valeur autostart factice
   (`reg add HKCU\...\Run /v debriefMeet /d "\"C:\fake\debriefMeet.exe\"" /f`)
   pour vérifier que le `[Code]` du `.iss` la retire bien.
3. Vérifier la table docs/32 §4 :
   - `%LOCALAPPDATA%\Programs\debriefMeet` **supprimé** ;
   - `%LOCALAPPDATA%\debriefMeet` **supprimé** (config + logs + modèles) ;
   - valeur Registre `debriefMeet` **absente** (`reg query` → introuvable) ;
   - `Documents\debriefMeet` et son fichier témoin **préservés**.
4. Nettoyage final du fichier témoin Documents (le run doit être rejouable).

## 4. Pièges connus (payés lors du premier build — ne pas les redécouvrir)

1. **SSH en série, jamais en rafale** : sshd refuse les authentifications password
   rapprochées (`MaxStartups`) → `Permission denied` intermittents. Une seule
   connexion à la fois, `sleep` entre les appels, options
   `-o NumberOfPasswordPrompts=1 -o StrictHostKeyChecking=no` (cf.
   `build_app_windows_vm.sh`).
2. **`printf '%s' "$OUT"`, jamais `echo "$OUT"`** pour afficher/parser une sortie
   VM : `echo` (zsh) interprète `\t`, `\U`, `\c` des chemins Windows — `\c` tronque
   la sortie et fait rater les `grep` (faux négatifs vécus le 2026-07-04).
3. **Sortie ASCII pur** dans tout ce qui s'exécute côté VM (console cp1252 — pas
   de `→`, `✓` dans les commandes distantes ; le Mac peut en afficher localement).
4. **Chemins scp** : format `C:/Users/...` (slash), pas `/c/Users/...`.
5. Le prompt SSH imprime des avertissements (« post-quantum ») sur stderr : ne pas
   les confondre avec des erreurs ; filtrer sans masquer les vrais échecs.
6. `reg query` sort avec un code ≠ 0 quand la valeur n'existe pas — c'est le
   résultat **attendu** en phase C (ne pas le traiter comme une erreur de script
   sous `set -e` : encapsuler).

## 5. Tests et validation

- `bash -n scripts/fumee_setup_vm.sh` propre ; pas de test pytest (script
  d'infrastructure, comme les autres `scripts/*_vm.sh`).
- Validation = exécution réelle contre la VM avec le setup produit par docs/32,
  **deux fois de suite** (prouve la rejouabilité, phase A incluant le
  pré-nettoyage).
- Chaque vérification imprime une ligne `[OK]`/`[ECHEC] <libellé>` ; le
  récapitulatif final reprend les échecs.

## 6. Definition of Done

- [x] `bash scripts/fumee_setup_vm.sh` déroule A→C sans intervention et sort en 0.
- [x] Un second run consécutif passe aussi (rejouable) — deux runs verts le 2026-07-04.
- [x] Chaque ligne de la table docs/32 §4 est couverte par une vérification (les
      deux gatées sur `usPostUninstall` sont en `[INFO]` non bloquant, cf. §7).
- [x] Échec simulé détecté (chemin de setup inexistant → code ≠ 0, message clair).
- [x] CLAUDE.md : ligne ajoutée au § « Build Windows » + table des docs (docs/37).
- [x] docs/32 §6 : les étapes couvertes par ce script y sont marquées
      « automatisées (docs/37) », la checklist manuelle résiduelle est réduite aux
      points GUI + la revalidation interactive de `usPostUninstall`.

## 7. Découverte : `usPostUninstall` ne se déclenche jamais via SSH

Investigation menée le 2026-07-04 après deux échecs systématiques et reproductibles
(désinstalleur non auto-supprimé, valeur Registre non nettoyée) — **survivant même
à un run parfaitement propre** (pas un artefact de tests manuels antérieurs).

**Méthode** : mini-`.iss` isolé (`TestRegDel2`, hors dépôt), avec dans
`CurUninstallStepChanged` un `SaveStringToFile` inconditionnel écrivant
`marker_step_<Ord(CurUninstallStep)>.txt` à CHAQUE étape, avant tout autre
traitement. Cycle install → pose d'une fausse valeur Registre → désinstallation
`/VERYSILENT` → inspection des marqueurs.

**Résultat** : `marker_step_0.txt` (`usAppMutexCheck`) et `marker_step_1.txt`
(`usUninstall`) sont créés — les fichiers de l'app sont bien supprimés à cette
étape. **`marker_step_2.txt` (`usPostUninstall`) n'apparaît jamais**, même après
20+ secondes d'attente (élimine l'hypothèse d'un simple délai de relance
asynchrone du désinstalleur). Conséquence directe : tout code `[Code]` gaté sur
`usPostUninstall` — dont notre nettoyage `RegDeleteValue` (docs/34 §4) — ne
s'exécute jamais dans ce contexte, et l'auto-suppression de `unins000.exe`
(qui semble dépendre du même point) n'a pas lieu non plus.

**Hypothèse** : liée à l'absence de session desktop interactive sous sshd Windows
(pas de jeton d'élévation/session complet).

**✅ Confirmée par Sylvain le 2026-07-04** : désinstallation interactive normale
(double-clic sur `unins000.exe` en session RDP) → dossier app **et** dossier
données **entièrement supprimés** (`unins000.exe` inclus), clé Registre autostart
**absente** après coup, `Documents\debriefMeet` **préservé**. Confirme sans
ambiguïté que la limite est propre à l'exécution via SSH — **le `.iss` est
correct, aucune action produit requise.** Les deux vérifications restent en
`[INFO]` (non bloquant) dans `scripts/fumee_setup_vm.sh`, qui ne peut de toute
façon pas piloter une session interactive.
