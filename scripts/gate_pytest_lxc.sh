#!/bin/sh
# Gate pytest sur le conteneur LXC Ubuntu 26.04 (docs/49 §6.2, etape 1 du §8).
#
# C'est le smoke test de l'architecture en couches : la suite doit etre quasi verte
# d'emblee sur un OS jamais teste. Les echecs qu'elle revele sont des hypotheses
# macOS/Windows implicites dans les tests (docs/44 en avait revele 2 sur Windows).
#
# Usage (depuis le Mac) :
#   sh scripts/gate_pytest_lxc.sh
#
# Pre-requis : sshpass (Mac), conteneur provisionne (scripts/provisionner_lxc_ubuntu.sh).
set -eu

LXC_HOST="${LXC_HOST:-192.168.1.32}"
LXC_USER="${LXC_USER:-root}"
LXC_PASS="${LXC_PASS:-sylvain}"
RACINE="$(cd "$(dirname "$0")/.." && pwd)"

ssh_lxc() {
    sshpass -p "$LXC_PASS" ssh \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
        "$LXC_USER@$LXC_HOST" "$@"
}

echo "=== Gate pytest LXC — ${LXC_USER}@${LXC_HOST} ==="

# BUILD_INFO : la copie sur le conteneur n'est pas un depot git, mais _version.py
# peut etre regenere — meme mecanique que la VM Windows.
date -u +%Y%m%d > "$RACINE/BUILD_INFO"
git -C "$RACINE" rev-parse --short HEAD >> "$RACINE/BUILD_INFO"
trap 'rm -f "$RACINE/BUILD_INFO"' EXIT

DEPOT='$HOME/build/debrief-meet'

echo "[1/3] Sync sources Mac -> conteneur"
# Purge src/ et tests/ AVANT extraction : tar ecrase les fichiers mais ne supprime
# jamais ceux retires a la source — un module supprime survivrait indefiniment
# (bug vecu sur la VM Windows le 2026-08-05).
ssh_lxc "rm -rf $DEPOT/src $DEPOT/tests && mkdir -p $DEPOT"
COPYFILE_DISABLE=1 tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    -C "$RACINE" src tests pyproject.toml BUILD_INFO \
    | ssh_lxc "tar -xzf - -C $DEPOT"

echo "[2/3] Installation des dependances (mode distant : ni mlx, ni pyannote)"
ssh_lxc "set -eu
    cd $DEPOT
    VENV=\$HOME/build/.venv-build
    \$VENV/bin/pip install --quiet --upgrade pip
    # Extras volontairement omis : le mode distant (docs/49 L1) n'embarque aucun
    # moteur local. Les tests qui en dependent sont deja gardes par importorskip.
    \$VENV/bin/pip install --quiet -e '.[dev]'
    echo '  dependances installees'"

echo "[3/3] pytest -m 'not integration' en offscreen"
# QT_QPA_PLATFORM=offscreen : le conteneur est headless, sans quoi Qt ne demarre pas.
# benchmark/ et spike/ ne sont pas synchronises (outils internes, pas le produit) —
# leurs tests sont donc ignores, comme sur la VM Windows.
set +e
ssh_lxc "set -eu
    cd $DEPOT
    QT_QPA_PLATFORM=offscreen \$HOME/build/.venv-build/bin/python -m pytest \
        -m 'not integration' -q --no-cov \
        --ignore=tests/test_benchmark_divers.py \
        --ignore=tests/test_benchmark_doc.py \
        --ignore=tests/test_benchmark_main.py \
        --ignore=tests/test_benchmark_materiel.py \
        --ignore=tests/test_benchmark_moteurs.py \
        --ignore=tests/test_benchmark_pipeline.py \
        --ignore=tests/test_benchmark_qualite.py \
        --ignore=tests/test_benchmark_rapport.py \
        --ignore=tests/test_benchmark_sondes.py \
        --ignore=tests/test_spike_backends_windows.py \
        --ignore=tests/test_build.py"
RC=$?
set -e

echo
if [ "$RC" -eq 0 ]; then
    echo "✓ Gate verte — consigner le compte dans CLAUDE.md (docs/49 §6.2)"
else
    echo "✗ Gate rouge (RC=$RC) — chaque echec est soit un vrai bug de portage,"
    echo "  soit une hypothese macOS/Windows implicite dans un test."
fi
exit "$RC"
