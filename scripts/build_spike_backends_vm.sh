#!/bin/sh
# Build NATIF du bundle spike backends Windows sur la VM Proxmox Windows 11.
#
# Adapte de scripts/build_windows_vm.sh (meme mecanique : tar over ssh, sshpass,
# session SSH ouverte pendant le build).
#
# Usage (depuis le Mac) :
#   bash scripts/build_spike_backends_vm.sh
#
# Pre-requis Mac : sshpass (brew install sshpass) + prebuild local des modeles
#   (bash scripts/prebuild_spike_modeles.sh) — la VM ne telecharge plus rien
#   (doc 18 §13.3/13.4), le transfert des modeles se fait par tar comme le code.
# Pre-requis VM (deja en place) : OpenSSH server, Python 3.11 "full" (py launcher).
# Build estime : plus rapide qu'avant (pas de telechargement HF sur la VM) mais
# le transfert tar des modeles peut prendre du temps selon leur taille totale.
#
# IMPORTANT : garder la session SSH ouverte — un process detache est tue a la
# fermeture de session SSH. Le script bloque jusqu'a la fin du build.
set -eu

VM_HOST="${VM_HOST:-192.168.1.29}"
VM_USER="${VM_USER:-sylvaing}"
VM_PASS="${VM_PASS:-sylvaing}"
VM_REPO='C:\Users\sylvaing\spike_backends_build'
VM_BUILD_CMD='C:\Users\sylvaing\spike_backends_build\scripts\spike_build.cmd'
VM_DONE_WIN='C:\Users\sylvaing\spike_backends_build\spike_build.done'
VM_ZIP_UNIX='C:/Users/sylvaing/spike_backends_build/bundles/spike-backends-windows.zip'
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
SORTIE="${SORTIE:-$RACINE/bundles}"

# Connexions SERIELLES (jamais en parallele) : sshd refuse les rafales d'auth
# password (MaxStartups) -> Permission denied. -o NumberOfPasswordPrompts=1 fait
# echouer vite plutot que reboucler.
ssh_vm() {
    sshpass -p "$VM_PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=1000 \
        "$VM_USER@$VM_HOST" "$@"
}

echo "=== Spike backends Windows — build VM ==="
echo "VM : ${VM_USER}@${VM_HOST}"

# 0. Verifier que le prebuild local (Mac) est complet AVANT de se connecter —
# la VM ne doit plus telecharger de modeles (cf. scripts/prebuild_spike_modeles.sh,
# doc 18 §13.3/13.4). Echec explicite plutot qu'un telechargement partiel sur la VM.
echo ""
echo "[0/4] Verification des modeles prebuild locaux..."
if ! (cd "$RACINE" && python3 -m spike.backends_windows.assembler --verifier-modeles); then
    echo "" >&2
    echo "✗ Modeles locaux incomplets — lancer d'abord :" >&2
    echo "    bash scripts/prebuild_spike_modeles.sh" >&2
    exit 1
fi

# 1. Creer l'arborescence sur la VM (idempotent — mkdir Windows cree les parents).
echo ""
echo "[1/4] Creation des repertoires sur la VM..."
ssh_vm "cmd /c mkdir C:\\Users\\sylvaing\\spike_backends_build\\benchmark\\assets 2>nul" || true
ssh_vm "cmd /c mkdir C:\\Users\\sylvaing\\spike_backends_build\\scripts 2>nul" || true
echo "  Repertoires OK."

# Transmettre HF_TOKEN a la VM si defini sur le Mac (reduit les rate limits HF).
if [ -n "${HF_TOKEN:-}" ]; then
    ssh_vm "cmd /c echo set HF_TOKEN=${HF_TOKEN} > C:\\Users\\sylvaing\\spike_backends_build\\spike_token.cmd"
    echo "  HF_TOKEN transmis a la VM."
else
    echo "  (HF_TOKEN non defini — telechargements non authentifies, rate limits plus bas)"
fi

# 2. Sync sources + modeles prebuild Mac -> VM (tar over ssh — meme mecanique
# que l'audio ci-dessous, aucun telechargement HF cote VM, doc 18 §13.4).
echo ""
echo "[2/4] Sync sources + modeles Mac -> VM ($VM_REPO)"
COPYFILE_DISABLE=1 tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    -C "$RACINE" spike src scripts/spike_build.cmd \
    | ssh_vm "tar -xzf - -C $VM_REPO"

# Sync audio canonique via tar (le format /c/ ne fonctionne pas pour les uploads scp).
AUDIO_SRC="$RACINE/benchmark/assets/audio_canonique.wav"
if [ -f "$AUDIO_SRC" ]; then
    COPYFILE_DISABLE=1 tar czf - -C "$RACINE" benchmark/assets/audio_canonique.wav \
        | ssh_vm "tar -xzf - -C $VM_REPO"
    echo "  audio canonique synchronise."
else
    echo "  AVERTISSEMENT : benchmark/assets/audio_canonique.wav absent localement."
    echo "  Le bundle sera assemble sans audio ; ajouter manuellement avant de lancer."
fi

# 3. Build natif (synchrone — reste connecte pendant tout le build).
echo ""
echo "[3/4] Build natif sur la VM (rapide — modeles deja presents)..."
echo "      NE PAS fermer ce terminal."
ssh_vm "cmd /c $VM_BUILD_CMD"

# Verifier le code retour ecrit par spike_build.cmd.
RC="$(ssh_vm "type $VM_DONE_WIN" 2>/dev/null | tr -dc '0-9' | head -c 1)"
if [ "$RC" != "0" ]; then
    echo "" >&2
    echo "✗ spike_build.cmd a echoue (RC=${RC:-?})" >&2
    echo "  Consulter le log directement sur la VM." >&2
    exit 1
fi

# 4. Rapatriement du zip.
echo ""
echo "[4/4] Rapatriement du bundle -> $SORTIE/"
mkdir -p "$SORTIE"
sshpass -p "$VM_PASS" scp \
    -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
    "$VM_USER@$VM_HOST:$VM_ZIP_UNIX" \
    "$SORTIE/spike-backends-windows.zip"

echo ""
echo "✓ $SORTIE/spike-backends-windows.zip"
echo ""
echo "Etapes suivantes :"
echo "  1. Copier le zip sur Bastien et Alix"
echo "  2. Dezipper -> double-cliquer lancer.bat"
echo "  3. Recuperer les 2 zip rapport"
echo "  4. Analyser -> decision documentee dans docs/03 §Phase 5"
