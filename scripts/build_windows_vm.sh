#!/bin/sh
# Build NATIF du bundle benchmark Windows sur la VM Proxmox Windows 11.
#
# Pourquoi natif et pas le build croisé depuis le Mac (--os windows) :
#   pip résout alors les dépendances contre la VRAIE plateforme Windows/CPython —
#   markers corrects, pas d'explosion multi-tags, et les wheels Windows réelles
#   (torch, sherpa-onnx, sounddevice, livekit…) sont posées telles que l'utilisateur
#   final les aura. Le build croisé Mac convient aux cibles sans GPU torch ; pour
#   coller au parc Windows on assemble sur la VM. cf. docs/08-benchmark.md.
#
# Le script : 1) synchronise les sources Mac → VM (tar over ssh, sans assets/caches) ;
#             2) lance build.cmd EN GARDANT LA SESSION SSH OUVERTE (un process détaché
#                via start/Start-Process est tué quand la session SSH se ferme) ;
#             3) rapatrie out\benchmark-windows.zip dans bundles/.
#
# Pré-requis Mac : sshpass (brew install sshpass), un token HF dans l'environnement.
# Pré-requis VM (déjà en place, cf. doc) : OpenSSH server, Python 3.11 « full »
# (pip + huggingface_hub), build.cmd, dépôt sous C:\Users\sylvaing\build\debrief-meet.
set -eu

VM_HOST="${VM_HOST:-192.168.1.29}"
VM_USER="${VM_USER:-sylvaing}"
VM_PASS="${VM_PASS:-sylvaing}"
VM_REPO='C:\Users\sylvaing\build\debrief-meet'
VM_ZIP='/c/Users/sylvaing/out/benchmark-windows.zip'
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
SORTIE="${SORTIE:-$RACINE/bundles}"

# Connexions SÉRIELLES (jamais en parallèle) : sshd refuse les rafales de tentatives
# password (MaxStartups) → « Permission denied ». -o NumberOfPasswordPrompts=1 fait
# échouer vite plutôt que reboucler.
ssh_vm() {
    sshpass -p "$VM_PASS" ssh -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 "$VM_USER@$VM_HOST" "$@"
}

echo "[1/3] Sync sources Mac → VM ($VM_REPO)"
# Seules les sources changent ; assets/audio, rapports et caches restent sur la VM.
COPYFILE_DISABLE=1 tar czf - \
    --exclude='benchmark/assets' --exclude='benchmark/rapports' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    -C "$RACINE" benchmark src \
    | ssh_vm "tar -xzf - -C $VM_REPO"

echo "[2/3] Build natif sur la VM (long : ~20-40 min, ~8 Go)"
# build.cmd lance python -m benchmark.assembler_bundle --os windows --token ... --sortie out
# et écrit RC=<code> dans build.done à la fin. On reste connecté pour porter le process.
ssh_vm "cmd /c C:\\Users\\sylvaing\\build.cmd"
RC="$(ssh_vm 'type C:\Users\sylvaing\build.done' | tr -dc '0-9')"
if [ "$RC" != "0" ]; then
    echo "✗ build.cmd a échoué (RC=$RC) — voir C:\\Users\\sylvaing\\build.log sur la VM" >&2
    exit 1
fi

echo "[3/3] Rapatriement du zip → $SORTIE/"
mkdir -p "$SORTIE"
sshpass -p "$VM_PASS" scp -o StrictHostKeyChecking=no \
    "$VM_USER@$VM_HOST:$VM_ZIP" "$SORTIE/benchmark-windows.zip"
echo "✓ $SORTIE/benchmark-windows.zip"
