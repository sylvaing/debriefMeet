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
# packaging/ est synchronise : test_generer_version.py charge
# packaging/windows/generer_version.py par son chemin (7 erreurs de collecte sans lui).
ssh_lxc "rm -rf $DEPOT/src $DEPOT/tests $DEPOT/packaging && mkdir -p $DEPOT"
COPYFILE_DISABLE=1 tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    --exclude='packaging/vendor' \
    -C "$RACINE" src tests packaging pyproject.toml BUILD_INFO \
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
#
# Exclusions — TOUTES pour cause de source non synchronisee, aucune pour masquer un
# echec (un glob, pas une liste nominative : une liste incomplete avait fait tomber
# la gate en erreur de collecte le 2026-08-10, 4 modules test_spike_backends_* oublies).
#   test_benchmark_*     -> benchmark/ non synchronise (outil interne, pas le produit)
#   test_spike_backends_*-> spike/ non synchronise (idem)
#   test_build           -> packaging/ non synchronise ; a reintegrer avec TestSpecLinux
#                           quand packaging/linux/ existera (docs/49 §6.1)
set +e
ssh_lxc "set -eu
    cd $DEPOT
    QT_QPA_PLATFORM=offscreen \$HOME/build/.venv-build/bin/python -m pytest \
        -m 'not integration' -q --no-cov \
        --ignore-glob='tests/test_benchmark_*.py' \
        --ignore-glob='tests/test_spike_backends_*.py' \
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
