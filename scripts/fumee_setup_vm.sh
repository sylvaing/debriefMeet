#!/bin/sh
# Fumee automatisee du setup Windows via SSH sur la VM Proxmox (docs/37).
#
# Verifie tout ce qui est controlable SANS interface graphique : installation
# silencieuse, integrite du bundle (--version), mise a jour par-dessus (config
# et Documents preserves), desinstallation complete (docs/32 §4, Registre
# inclus). Le tray Qt, la dictee reelle et l'en-tete de session restent a
# verifier a la main sur la console Proxmox/RDP.
#
# Usage (depuis le Mac) :
#   bash scripts/fumee_setup_vm.sh [chemin/vers/debriefMeet-setup-X.exe]
#   (sans argument : prend le plus recent de dist/debriefMeet-setup-*.exe)
#
# Rejouable : chaque phase se nettoie avant de commencer, un second run
# consecutif doit repasser au vert (docs/37 §5-6).
#
# Pre-requis Mac : sshpass (brew install sshpass).
set -eu

VM_HOST="${VM_HOST:-192.168.1.29}"
VM_USER="${VM_USER:-sylvaing}"
VM_PASS="${VM_PASS:-sylvaing}"
VM_FUMEE_DIR='C:\Users\sylvaing\fumee'
# Racines per-user (docs/32 §4). Une seule racine de donnees grace a
# appauthor=False (config.json, Logs\, modeles\ tous sous VM_DATA) — cf.
# CLAUDE.md § piege platformdirs.
VM_APP='%LOCALAPPDATA%\Programs\debriefMeet'
VM_DATA='%LOCALAPPDATA%\debriefMeet'
VM_DOCS='%USERPROFILE%\Documents\debriefMeet'

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
ECHECS=0

# ── Connexion : SERIELLE, jamais en rafale (sshd MaxStartups, docs/37 §4.1) ──

ssh_vm() {
    sshpass -p "$VM_PASS" ssh \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 -o ConnectTimeout=15 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
        "$VM_USER@$VM_HOST" "$@" 2>/dev/null
}

scp_to_vm() {
    sshpass -p "$VM_PASS" scp \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 -o ConnectTimeout=15 \
        "$1" "$VM_USER@$VM_HOST:$2" 2>/dev/null
}

ssh_vm_retry() {
    # Une connexion SSH peut echouer transitoirement apres de nombreux appels
    # rapproches (sshd MaxStartups, docs/37 §4.1) -- 3 tentatives espacees pour
    # les commandes ponctuelles qui DOIVENT reussir (pas de simples sondes).
    tentative=0
    while [ "$tentative" -lt 3 ]; do
        if ssh_vm "$@"; then
            return 0
        fi
        tentative=$((tentative + 1))
        sleep 2
    done
    return 1
}

# ── Sondes ────────────────────────────────────────────────────────────────

existe_sur_vm() {
    # $1 : chemin Windows (les %VARS% sont resolues cote distant par cmd.exe)
    ssh_vm "cmd /c if exist \"$1\" (exit 0) else (exit 1)"
}

reg_valeur_existe_sur_vm() {
    # $1 : nom de la valeur sous HKCU\...\Run
    ssh_vm "reg query \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" /v $1" >/dev/null 2>&1
}

reg_cle_existe_sur_vm() {
    # $1 : chemin complet d'une cle de Registre (a la difference de la sonde
    # ci-dessus, qui code en dur la cle Run).
    ssh_vm "reg query \"$1\"" >/dev/null 2>&1
}

# ── Rapport ───────────────────────────────────────────────────────────────

verif() {
    # $1 = libelle, $2.. = commande dont le code retour vaut 0 (succes attendu)
    lib="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '[OK]    %s\n' "$lib"
    else
        printf '[ECHEC] %s\n' "$lib"
        ECHECS=$((ECHECS + 1))
    fi
}

supprimer_dossier_vm() {
    # rmdir /s /q peut echouer transitoirement (verrou bref laisse par le
    # nettoyage differe d'un desinstalleur precedent, cf. docs/37 §4) -- 3
    # tentatives espacees avant d'abandonner (best-effort, jamais fatal ici).
    tentative=0
    while [ "$tentative" -lt 3 ]; do
        if ! existe_sur_vm "$1"; then
            return 0
        fi
        ssh_vm "cmd /c rmdir /s /q \"$1\"" >/dev/null 2>&1 || true
        tentative=$((tentative + 1))
        sleep 1
    done
    return 0
}

verif_absence() {
    # Comme verif, mais la commande doit ECHOUER (chose absente) pour reussir.
    lib="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '[ECHEC] %s (toujours present)\n' "$lib"
        ECHECS=$((ECHECS + 1))
    else
        printf '[OK]    %s\n' "$lib"
    fi
}

avertir_si_present() {
    # Comme verif_absence, mais SANS compter dans ECHECS : reserve aux points
    # confirmes non fiables sous SSH (docs/37, investigation 2026-07-04) — a
    # revalider une fois via RDP/console avant de les traiter comme bloquants.
    lib="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '[INFO]  %s (toujours present — cf. note ci-dessous)\n' "$lib"
    else
        printf '[OK]    %s\n' "$lib"
    fi
}

# ── Sélection du setup ────────────────────────────────────────────────────

SETUP_LOCAL="${1:-}"
if [ -n "$SETUP_LOCAL" ]; then
    if [ ! -f "$SETUP_LOCAL" ]; then
        echo "Chemin fourni introuvable : $SETUP_LOCAL" >&2
        exit 1
    fi
else
    # Le glob couvre les DEUX editions (debriefMeet-setup-* et debriefMeet-lite-setup-*).
    SETUP_LOCAL="$(ls -t "$RACINE"/dist/debriefMeet*-setup-*.exe 2>/dev/null | head -n 1)"
    if [ -z "$SETUP_LOCAL" ] || [ ! -f "$SETUP_LOCAL" ]; then
        echo "Aucun setup trouve dans dist/debriefMeet*-setup-*.exe (et aucun chemin fourni en argument)." >&2
        exit 1
    fi
fi
NOM_SETUP="$(basename "$SETUP_LOCAL")"
VM_SETUP_WIN="$VM_FUMEE_DIR\\$NOM_SETUP"

# Edition deduite du NOM du setup : c'est precisement a ca que sert le nommage
# distinct decide en docs/44 — aucun argument supplementaire a passer, et l'artefact
# reste la source de verite (impossible de se tromper d'edition en le testant).
case "$NOM_SETUP" in
    *-lite-setup-*) EDITION=lite ;    NOM_LNK='debriefMeet Lite.lnk' ; NOM_LNK_AUTRE='debriefMeet.lnk' ;;
    *)              EDITION=complete ; NOM_LNK='debriefMeet.lnk' ;      NOM_LNK_AUTRE='debriefMeet Lite.lnk' ;;
esac
MENU_DEMARRER='%APPDATA%\Microsoft\Windows\Start Menu'

echo "=== Fumee debriefMeet — $NOM_SETUP ==="
echo "VM      : ${VM_USER}@${VM_HOST}"
echo "Edition : $EDITION"
echo "Taille  : $(ls -lh "$SETUP_LOCAL" | awk '{print $5}')"

echo ""
echo "[upload] Envoi du setup vers la VM..."
ssh_vm "cmd /c mkdir $VM_FUMEE_DIR 2>nul" || true
scp_to_vm "$SETUP_LOCAL" "C:/Users/sylvaing/fumee/$NOM_SETUP"

# ── Phase A — installation neuve ─────────────────────────────────────────

echo ""
echo "=== Phase A : installation neuve ==="

echo "Pre-nettoyage (rejouabilite)..."
if existe_sur_vm "$VM_APP\\unins000.exe"; then
    ssh_vm "cmd /c start /wait \"\" \"$VM_APP\\unins000.exe\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART" || true
    sleep 3
fi
supprimer_dossier_vm "$VM_DATA"
supprimer_dossier_vm "$VM_APP"

echo "Installation silencieuse..."
if ssh_vm "cmd /c start /wait \"\" \"$VM_SETUP_WIN\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; then
    printf '[OK]    %s\n' "Installation silencieuse"
else
    printf '[ECHEC] %s\n' "Installation silencieuse"
    ECHECS=$((ECHECS + 1))
fi

verif "exe installe (${VM_APP}\\debriefMeet.exe)" existe_sur_vm "$VM_APP\\debriefMeet.exe"
verif "desinstalleur present" existe_sur_vm "$VM_APP\\unins000.exe"
# {userstartmenu} (utilise dans le .iss) pointe la RACINE du Menu Demarrer, pas
# le sous-dossier Programs\ ({userprograms} ferait ca) -- verifie via /LOG
# d'installation le 2026-07-04 : "Dest filename: ...\Start Menu\debriefMeet.lnk".
verif "raccourci menu Demarrer ($NOM_LNK)" existe_sur_vm "$MENU_DEMARRER\\$NOM_LNK"
# Une seule entree : [InstallDelete] du .iss retire le raccourci de l'AUTRE edition
# (le desinstalleur, lui, ne retire que ce qui est dans SON log — docs/44).
verif_absence "pas de raccourci de l'autre edition ($NOM_LNK_AUTRE)" \
    existe_sur_vm "$MENU_DEMARRER\\$NOM_LNK_AUTRE"

VERSION_OUT="$(ssh_vm "cmd /c \"$VM_APP\\debriefMeet.exe\" --version" || true)"
if printf '%s' "$VERSION_OUT" | grep -q 'debriefMeet 0\.'; then
    printf '[OK]    %s\n' "--version (integrite du bundle PyInstaller)"
else
    printf '[ECHEC] %s\n' "--version (integrite du bundle PyInstaller)"
    ECHECS=$((ECHECS + 1))
fi
printf '        -> %s\n' "$VERSION_OUT"

echo ""
echo "--- ffmpeg embarque (docs/41) ---"
verif "ffmpeg.exe present dans le bundle" existe_sur_vm "$VM_APP\\_internal\\ffmpeg\\ffmpeg.exe"
if ssh_vm "cmd /c \"$VM_APP\\_internal\\ffmpeg\\ffmpeg.exe\" -encoders 2>nul | findstr /i libopus" >/dev/null 2>&1; then
    printf '[OK]    %s\n' "ffmpeg embarque : libopus present"
else
    printf '[ECHEC] %s\n' "ffmpeg embarque : libopus present"
    ECHECS=$((ECHECS + 1))
fi

# ── Contenu du bundle selon l'edition (docs/44) ──────────────────────────────
#
# Les tests statiques (tests/test_build.py::TestSpecWindowsEditions) verifient que le
# spec DEMANDE les exclusions ; seules ces sondes prouvent qu'elles ont PRIS.
echo ""
echo "--- pile de transcription locale (edition $EDITION) ---"
if [ "$EDITION" = "lite" ]; then
    for paquet in ctranslate2 av onnxruntime faster_whisper; do
        verif_absence "bundle lite sans $paquet" existe_sur_vm "$VM_APP\\_internal\\$paquet"
    done
else
    verif "bundle complet avec ctranslate2" existe_sur_vm "$VM_APP\\_internal\\ctranslate2"
fi

# ── Phase B — mise a jour par-dessus ─────────────────────────────────────

echo ""
echo "=== Phase B : mise a jour par-dessus (meme version rebuildee) ==="

ssh_vm "cmd /c mkdir \"$VM_DATA\" 2>nul" || true
ssh_vm "cmd /c mkdir \"$VM_DOCS\" 2>nul" || true
ssh_vm_retry "cmd /c echo TEMOIN_CONFIG_FUMEE > \"$VM_DATA\\config.json\""
ssh_vm_retry "cmd /c echo TEMOIN_DOCUMENTS_FUMEE > \"$VM_DOCS\\temoin_fumee.txt\""

echo "Reinstallation silencieuse par-dessus..."
if ssh_vm "cmd /c start /wait \"\" \"$VM_SETUP_WIN\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; then
    printf '[OK]    %s\n' "Reinstallation par-dessus"
else
    printf '[ECHEC] %s\n' "Reinstallation par-dessus"
    ECHECS=$((ECHECS + 1))
fi

CONFIG_OUT="$(ssh_vm "cmd /c type \"$VM_DATA\\config.json\"" || true)"
if printf '%s' "$CONFIG_OUT" | grep -q 'TEMOIN_CONFIG_FUMEE'; then
    printf '[OK]    %s\n' "config.json preserve apres MAJ"
else
    printf '[ECHEC] %s\n' "config.json preserve apres MAJ"
    ECHECS=$((ECHECS + 1))
fi

DOC_OUT="$(ssh_vm "cmd /c type \"$VM_DOCS\\temoin_fumee.txt\"" || true)"
if printf '%s' "$DOC_OUT" | grep -q 'TEMOIN_DOCUMENTS_FUMEE'; then
    printf '[OK]    %s\n' "Documents preserve apres MAJ"
else
    printf '[ECHEC] %s\n' "Documents preserve apres MAJ"
    ECHECS=$((ECHECS + 1))
fi

verif "exe toujours present apres MAJ" existe_sur_vm "$VM_APP\\debriefMeet.exe"

# ── Phase B' — changement d'edition par-dessus (docs/44) ─────────────────────
#
# Seul vrai risque de la decision « meme AppId » : [Files] COPIE par-dessus sans
# jamais faire de miroir, donc installer lite sur une install complete laisserait
# ~150-200 Mo de DLL Whisper mortes dans {app}\_internal et annulerait tout le gain de
# l'edition lite. C'est [InstallDelete] du .iss qui corrige ca, et c'est CETTE phase
# qui le prouve. Sautee (INFO) si l'autre edition n'est pas disponible localement.

if [ "$EDITION" = "lite" ]; then
    AUTRE_LOCAL="$(ls -t "$RACINE"/dist/debriefMeet-setup-*.exe 2>/dev/null | head -n 1)"
else
    AUTRE_LOCAL="$(ls -t "$RACINE"/dist/debriefMeet-lite-setup-*.exe 2>/dev/null | head -n 1)"
fi

echo ""
echo "=== Phase B' : changement d'edition par-dessus ==="
if [ -z "$AUTRE_LOCAL" ] || [ ! -f "$AUTRE_LOCAL" ]; then
    printf '[INFO]  %s\n' "Sautee : setup de l'autre edition absent de dist/ (builder les deux pour la jouer)"
else
    NOM_AUTRE="$(basename "$AUTRE_LOCAL")"
    case "$NOM_AUTRE" in
        *-lite-setup-*) AUTRE_EDITION=lite ;;
        *)              AUTRE_EDITION=complete ;;
    esac
    echo "Installation de l'edition $AUTRE_EDITION par-dessus l'edition $EDITION ($NOM_AUTRE)..."
    scp_to_vm "$AUTRE_LOCAL" "C:/Users/sylvaing/fumee/$NOM_AUTRE"
    if ssh_vm "cmd /c start /wait \"\" \"$VM_FUMEE_DIR\\$NOM_AUTRE\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; then
        printf '[OK]    %s\n' "Installation croisee $EDITION -> $AUTRE_EDITION"
    else
        printf '[ECHEC] %s\n' "Installation croisee $EDITION -> $AUTRE_EDITION"
        ECHECS=$((ECHECS + 1))
    fi

    verif "exe present apres changement d'edition" existe_sur_vm "$VM_APP\\debriefMeet.exe"
    if [ "$AUTRE_EDITION" = "lite" ]; then
        # L'assertion qui valide [InstallDelete] {app}\_internal.
        verif_absence "ctranslate2 RETIRE par le passage a lite" \
            existe_sur_vm "$VM_APP\\_internal\\ctranslate2"
    else
        verif "ctranslate2 present apres passage au complet" \
            existe_sur_vm "$VM_APP\\_internal\\ctranslate2"
    fi
    verif "config.json preserve au changement d'edition" existe_sur_vm "$VM_DATA\\config.json"
    verif "Documents preserve au changement d'edition" existe_sur_vm "$VM_DOCS\\temoin_fumee.txt"

    # Entree de desinstallation unique et inchangee : AppId identique des deux cotes,
    # donc l'edition croisee est vue comme une MAJ, pas comme un second produit.
    verif "entree de desinstallation unique (AppId partage)" reg_cle_existe_sur_vm \
        'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C18F22B8-EBDF-46FD-8E97-2F4334DA3182}_is1'

    ssh_vm "cmd /c del /q \"$VM_FUMEE_DIR\\$NOM_AUTRE\"" || true
fi

# ── Phase C — desinstallation complete (D4) ──────────────────────────────

echo ""
echo "=== Phase C : desinstallation complete ==="

echo "Pose d'une valeur autostart factice (pour verifier son retrait)..."
ssh_vm_retry 'reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v debriefMeet /t REG_SZ /d C:\fake\debriefMeet.exe /f' >/dev/null

echo "Desinstallation silencieuse..."
if ssh_vm "cmd /c start /wait \"\" \"$VM_APP\\unins000.exe\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; then
    printf '[OK]    %s\n' "Desinstallation silencieuse"
else
    printf '[ECHEC] %s\n' "Desinstallation silencieuse"
    ECHECS=$((ECHECS + 1))
fi
sleep 3

verif_absence "fichiers app supprimes (${VM_APP}\\debriefMeet.exe)" existe_sur_vm "$VM_APP\\debriefMeet.exe"
verif_absence "dossier donnees supprime (${VM_DATA} : config+logs+modeles)" existe_sur_vm "$VM_DATA"
verif "Documents preserve apres desinstallation (D4)" existe_sur_vm "$VM_DOCS\\temoin_fumee.txt"

# ⚠️ Limite confirmee (investigation 2026-07-04, docs/37) : quand l'installeur
# est lance via SSH (session sans desktop interactif), TUninstallStep atteint
# usUninstall (suppression des fichiers -- verifiee ci-dessus) mais N'ATTEINT
# JAMAIS usPostUninstall (confirme par un mini-.iss instrumente avec des
# marqueurs de fichier). Consequences, toutes les deux gatees sur
# usPostUninstall : (a) le desinstalleur ne s'auto-supprime pas
# (unins000.exe reste) ; (b) le RegDeleteValue en [Code] ne s'execute jamais.
# Non reproduit avec certitude en session interactive (RDP/console) -- a
# revalider une fois avant de considerer ceci comme un bug produit plutot
# qu'une limite de l'environnement de test SSH.
avertir_si_present "desinstalleur retire (${VM_APP}\\unins000.exe)" existe_sur_vm "$VM_APP\\unins000.exe"
avertir_si_present "valeur Registre autostart supprimee" reg_valeur_existe_sur_vm 'debriefMeet'

echo "Nettoyage du temoin Documents et des residus connus (rejouabilite)..."
ssh_vm "cmd /c del /q \"$VM_DOCS\\temoin_fumee.txt\"" || true
supprimer_dossier_vm "$VM_APP"
ssh_vm 'reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v debriefMeet /f' >/dev/null 2>&1 || true

# ── Bilan ─────────────────────────────────────────────────────────────────

echo ""
echo "=== Bilan ==="
echo "Les lignes [INFO] signalent une limite connue de l'execution via SSH"
echo "(docs/37) -- elles ne comptent pas comme des echecs mais meritent une"
echo "verification manuelle en session interactive (RDP/console)."
if [ "$ECHECS" -eq 0 ]; then
    echo "Toutes les verifications bloquantes sont OK."
    exit 0
else
    echo "$ECHECS verification(s) bloquante(s) en echec — voir le detail [ECHEC] ci-dessus." >&2
    exit 1
fi
