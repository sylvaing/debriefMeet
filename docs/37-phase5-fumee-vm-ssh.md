# Phase 5 — Fumée automatisée du setup Windows via SSH (VM)

> **Statut : 📝 SPEC à implémenter** (rédigée le 2026-07-04, pour une session LLM
> Sonnet dédiée). Dépend de : docs/32 ✅ (la chaîne de build produit
> `dist/debriefMeet-setup-<version>.exe`, premier build réussi le 2026-07-04).
>
> **Objectif :** automatiser depuis le Mac, via SSH sur la VM Proxmox, tout ce qui
> est vérifiable **sans interface graphique** dans la checklist docs/32 §6
> (install / mise à jour / désinstallation). La partie interactive (tray visible,
> dictée réelle, en-tête de session) reste manuelle sur la console Proxmox/RDP —
> ce script réduit la checklist manuelle à ces seuls points.

---

## 1. Contexte et périmètre

La VM (`192.168.1.29`, SSH `sylvaing` (mot de passe hors dépôt)) n'offre **pas de bureau via
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

- [ ] `bash scripts/fumee_setup_vm.sh` déroule A→C sans intervention et sort en 0.
- [ ] Un second run consécutif passe aussi (rejouable).
- [ ] Chaque ligne de la table docs/32 §4 est couverte par une vérification.
- [ ] Échec simulé détecté (ex. lancer avec un chemin de setup inexistant → code ≠ 0
      et message clair).
- [ ] CLAUDE.md : ligne ajoutée au § « Build Windows » + table des docs (docs/37).
- [ ] docs/32 §6 : les étapes couvertes par ce script y sont marquées
      « automatisées (docs/37) », la checklist manuelle résiduelle est réduite aux
      points GUI.
