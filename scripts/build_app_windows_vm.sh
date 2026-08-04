#!/bin/sh
# Build NATIF du setup Windows debriefMeet sur la VM Proxmox (docs/32).
#
# Meme mecanique que scripts/build_windows_vm.sh / build_spike_backends_vm.sh :
# tar over ssh, sshpass, session SSH gardee OUVERTE pendant tout le build (un
# process detache est tue a la fermeture de session SSH).
#
# Usage (depuis le Mac) :
#   bash scripts/build_app_windows_vm.sh
#
# Un seul setup depuis docs/45 (les editions complete/lite de docs/44 ont disparu —
# le mode distant/local est un reglage utilisateur dans les Preferences).
#
# Pre-requis Mac : sshpass (brew install sshpass).
# Pre-requis VM (a installer une fois, cf. docs/32 §3.4) :
#   - Python 3.13 x64 (py launcher : "py -3.13") — PyInstaller ne supporte pas 3.14.
#   - Inno Setup 6 (ISCC.exe) — winget install JRSoftware.InnoSetup, ou telechargement
#     manuel ; chemin non standard -> definir ISCC_EXE avant de lancer build_app.cmd.
#   - Dossier C:\Users\sylvaing\build\debrief-meet (pas un clone git actif : les
#     sources sont synchronisees par tar a chaque build, pas par git pull).
set -eu

VM_HOST="${VM_HOST:-192.168.1.29}"
VM_USER="${VM_USER:-sylvaing}"
VM_PASS="${VM_PASS:-sylvaing}"
VM_REPO='C:\Users\sylvaing\build\debrief-meet'
VM_DONE_WIN='C:\Users\sylvaing\build\debrief-meet\build_app.done'
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
SORTIE="${SORTIE:-$RACINE/dist}"

PREFIXE_SETUP="debriefMeet-setup"

# Connexions SERIELLES (jamais en parallele) : sshd refuse les rafales d'auth
# password (MaxStartups) -> Permission denied. -o NumberOfPasswordPrompts=1 fait
# echouer vite plutot que reboucler.
ssh_vm() {
    sshpass -p "$VM_PASS" ssh \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
        "$VM_USER@$VM_HOST" "$@"
}

echo "=== debriefMeet — build setup Windows ==="
echo "VM      : ${VM_USER}@${VM_HOST}"

# BUILD_INFO : date + hash git court — la copie sur la VM n'est PAS un depot git
# (docs/32 §3.1), generer_version.py (execute sur la VM) en a besoin pour calculer
# VERSION_COMPLETE. Nettoye localement en sortie (jamais commite — .gitignore).
echo ""
echo "[1/4] Preparation de BUILD_INFO (date + hash git)..."
date -u +%Y%m%d > "$RACINE/BUILD_INFO"
git -C "$RACINE" rev-parse --short HEAD >> "$RACINE/BUILD_INFO"
trap 'rm -f "$RACINE/BUILD_INFO"' EXIT
cat "$RACINE/BUILD_INFO"

echo ""
echo "[2/4] Creation du repertoire sur la VM (idempotent)..."
ssh_vm "cmd /c mkdir C:\\Users\\sylvaing\\build\\debrief-meet 2>nul" || true
# Purge les anciens setups AVANT le build : sinon plusieurs
# debriefMeet-setup-*.exe (versions differentes) s'accumulent dans dist\ au fil
# des builds -- le rapatriement ci-dessous suppose un seul resultat (bug vecu
# le 2026-07-06 : dir /b a rendu 3 noms concatenes, scp a echoue).
# Deux globs : "debriefMeet-setup-*" ne matche PAS "debriefMeet-lite-setup-*" — le
# second purge les reliquats de l'ancienne edition lite (docs/44) encore sur la VM.
ssh_vm "cmd /c del /q $VM_REPO\\dist\\debriefMeet-setup-*.exe 2>nul" || true
ssh_vm "cmd /c del /q $VM_REPO\\dist\\debriefMeet-lite-setup-*.exe 2>nul" || true

echo ""
echo "[3/4] Sync sources Mac -> VM ($VM_REPO)"
# benchmark/ et spike/ sont des outils internes, pas le produit livre -- on ne les
# synchronise pas. build_app.cmd ignore les tests qui les importent (test_benchmark_*,
# test_spike_backends_*) plutot que de trainer leur code juste pour la collecte pytest.
COPYFILE_DISABLE=1 tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    -C "$RACINE" src tests pyproject.toml packaging/windows packaging/launcher.py BUILD_INFO \
    | ssh_vm "tar -xzf - -C $VM_REPO"

echo ""
echo "[4/4] Build natif sur la VM (venv + pytest bloquant + PyInstaller + Inno Setup)"
echo "      NE PAS fermer ce terminal — un process detache serait tue a la deconnexion SSH."
ssh_vm "cmd /c $VM_REPO\\packaging\\windows\\build_app.cmd"

RC="$(ssh_vm "type $VM_DONE_WIN" 2>/dev/null | tr -dc '0-9' | head -c 1)"
if [ "$RC" != "0" ]; then
    echo "" >&2
    echo "✗ build_app.cmd a echoue (RC=${RC:-?}) — consulter le log directement sur la VM" >&2
    exit 1
fi

echo ""
echo "Rapatriement du setup -> $SORTIE/"
mkdir -p "$SORTIE"
# /o-d : le plus recent en premier -- filet de securite si la purge ci-dessus
# a echoue et que plusieurs setups trainent encore (on ne garde que le 1er).
NOM_SETUP="$(ssh_vm "cmd /c dir /b /o-d $VM_REPO\\dist\\$PREFIXE_SETUP-*.exe" | tr -d '\r' | head -n 1)"
if [ -z "$NOM_SETUP" ]; then
    echo "✗ Aucun $PREFIXE_SETUP-*.exe trouve dans $VM_REPO\\dist sur la VM" >&2
    exit 1
fi
sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
    "$VM_USER@$VM_HOST:C:/Users/sylvaing/build/debrief-meet/dist/$NOM_SETUP" \
    "$SORTIE/$NOM_SETUP"

echo ""
echo "✓ $SORTIE/$NOM_SETUP"
