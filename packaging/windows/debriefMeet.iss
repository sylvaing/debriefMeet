; debriefMeet — installeur Windows (Inno Setup 6), docs/32.
;
; Per-user, sans droits admin (PrivilegesRequired=lowest) — postes pro potentiellement
; verrouillés. Mise à jour = réinstaller par-dessus (AppId figé + AppMutex détectent
; l'app existante). Désinstallation complète sauf Documents\debriefMeet (D4).
;
; #include "version.iss" est généré par generer_version.py juste avant la compilation
; ISCC (MonAppVersion/MonAppVersionNum) — ne pas le committer (cf. .gitignore).
#include "version.iss"

; Un seul setup depuis docs/45 (les éditions complete/lite de docs/44 ont disparu —
; le mode distant/local est un réglage utilisateur dans les Préférences). AppId
; identique à l'époque des deux éditions : le setup unifié remplace proprement une
; installation « debriefMeet Lite » existante (traitée comme une mise à jour).
#define MonAppNom "debriefMeet"
#define MonAppFichier "debriefMeet-setup"

[Setup]
; GUID figé une fois pour toutes (2026-07-03) — équivalent du bundle id macOS
; com.sylvaingarcia.debriefmeet. NE JAMAIS LE CHANGER : c'est lui qui fait qu'une
; réinstallation est traitée comme une mise à jour.
AppId={{C18F22B8-EBDF-46FD-8E97-2F4334DA3182}
AppName={#MonAppNom}
AppVersion={#MonAppVersion}
VersionInfoVersion={#MonAppVersionNum}
DefaultDirName={localappdata}\Programs\debriefMeet
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename={#MonAppFichier}-{#MonAppVersion}
OutputDir=..\..\dist
; Mutex créé par l'app au démarrage (platform/windows/instance_unique.py, docs/34 §6) —
; nom strictement identique des deux côtés : Inno détecte l'app en cours et propose
; de la fermer avant d'écraser ses fichiers.
AppMutex=debriefMeet-instance
CloseApplications=yes
RestartApplications=no
SetupIconFile=debriefMeet.ico
UninstallDisplayIcon={app}\debriefMeet.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible

; ── Nettoyage AVANT copie (hérité de docs/44, toujours nécessaire) ──────────────
;
; [Files] COPIE par-dessus, il ne fait jamais de miroir : les fichiers présents dans
; l'ancienne installation et absents de la nouvelle SURVIVENT (Inno ne les retire
; qu'au désinstall, depuis son log — or une MAJ ne rejoue pas l'ancien désinstalleur).
; `_internal` appartient à 100 % à l'installeur (PyInstaller >= 6 y met TOUT sauf
; debriefMeet.exe) → le vider est sûr et idempotent, et garantit qu'aucune DLL d'un
; ancien bundle ne survit à une MAJ. Coût : la totalité du bundle est recopiée à
; chaque MAJ (c'était déjà le cas en pratique). Une install interrompue APRÈS ce
; nettoyage laisse l'app inutilisable jusqu'au prochain run — acceptable, identique
; à toute MAJ interrompue. Cette section tourne après AppMutex/CloseApplications
; (app déjà fermée) et avant [Files].
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
; Les DEUX raccourcis historiques (le nôtre est recréé juste après par [Icons]) :
; « debriefMeet Lite.lnk » reste listé pour la transition depuis une installation
; lite d'avant docs/45 — le désinstalleur ne retire que les raccourcis de SON log.
Type: files; Name: "{userstartmenu}\debriefMeet.lnk"
Type: files; Name: "{userstartmenu}\debriefMeet Lite.lnk"

[Files]
Source: "..\..\dist\debriefMeet\*"; DestDir: "{app}"; Flags: recursesubdirs replacesameversion

[Icons]
Name: "{userstartmenu}\{#MonAppNom}"; Filename: "{app}\debriefMeet.exe"

[Run]
Filename: "{app}\debriefMeet.exe"; Description: "Lancer {#MonAppNom}"; Flags: postinstall nowait skipifsilent

; ── Désinstallation complète sauf données utilisateur (D4, docs/32 §4) ──────────
;
; config.json, Logs\ et modeles\ vivent TOUS sous {localappdata}\debriefMeet (une
; seule racine) : platformdirs.user_config_dir/user_log_dir/user_data_dir sont
; appelés avec appauthor=False (docs/32 §4 — sans lui, platformdirs double le
; dossier en traitant l'appname comme « author » par défaut, ce qui aurait donné
; {localappdata}\debriefMeet\debriefMeet). Supprimer cette racine suffit à tout
; nettoyer (app + config + logs + modèles téléchargés, plusieurs Go rendus) sans
; jamais toucher au cache Hugging Face global d'autres applications.
;
; Documents\debriefMeet (transcriptions + audio, core/config.py _DEFAUTS) n'est
; PAS listé ici : décision D4, préservé à la désinstallation.
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\debriefMeet"

; ── Nettoyage du Registre (démarrage auto, docs/34 §4) ──────────────────────────
;
; La valeur HKCU\...\Run\debriefMeet est écrite dynamiquement par l'app (Préférences
; → Démarrage auto), pas par cet installeur — un simple [Registry] avec
; uninsdeletevalue ne suffit pas (Inno ne retire que ce qu'IL a créé à l'install).
; On la supprime donc explicitement au désinstall, qu'elle existe ou non.
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'debriefMeet');
  end;
end;
