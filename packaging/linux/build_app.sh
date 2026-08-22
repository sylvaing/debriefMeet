#!/bin/sh
# Build natif du .deb debriefMeet — exécuté SUR le conteneur LXC (docs/49 §6).
# Ne pas lancer manuellement : nécessite BUILD_INFO (généré par le script Mac,
# scripts/build_app_linux_lxc.sh, qui synchronise aussi les sources).
#
# Miroir de packaging/windows/build_app.cmd — 5 étapes au lieu de 6 : pas de
# téléchargement ffmpeg (Depends: ffmpeg, décision L3) et dpkg-deb remplace ISCC.
# Écrit build_app.done (RC=<code>) pour le script Mac, comme la VM Windows.
set -u

RACINE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RACINE"
trap 'echo "RC=$?" > build_app.done' EXIT

echo "[1/5] Venv de build (Python systeme — decision L7)..."
rm -rf .venv-build
python3 -m venv .venv-build || exit 1
./.venv-build/bin/pip install --quiet --upgrade pip || exit 1
./.venv-build/bin/pip install --quiet -e '.[linux,dev]' pyinstaller || exit 1
./.venv-build/bin/python --version

echo "[2/5] Generation de la version (_version.py)..."
./.venv-build/bin/python packaging/windows/generer_version.py --build-info BUILD_INFO || exit 1

echo "[3/5] Suite de tests (bloquant — build refuse si rouge, comme docs/32)..."
# Memes exclusions que scripts/gate_pytest_lxc.sh, memes raisons (sources non
# synchronisees : benchmark/ et spike/ sont des outils internes, test_build teste
# l'hygiene du depot Mac).
#
# RC=139 (SIGSEGV) tolere UNIQUEMENT si le resume pytest ne rapporte aucun test en
# echec : crash confirme (gdb, 2026-08-22) dans Shiboken::Object::destroy() pendant
# la finalisation de l'interpreteur Python 3.14 (__run_exit_handlers, apres exit()),
# donc APRES que tous les tests aient deja reussi — bug connu PySide6 6.11.2 /
# Python 3.14, sans rapport avec le code de l'app. Tout autre code de sortie, ou un
# resume indiquant un echec, bloque le build normalement.
TESTS_OUT="$(mktemp)"
QT_QPA_PLATFORM=offscreen ./.venv-build/bin/python -m pytest -m "not integration" -q --no-cov \
    --ignore-glob='tests/test_benchmark_*.py' \
    --ignore-glob='tests/test_spike_backends_*.py' \
    --ignore=tests/test_build.py > "$TESTS_OUT" 2>&1
RC_TESTS=$?
cat "$TESTS_OUT"
if [ "$RC_TESTS" -ne 0 ]; then
    if [ "$RC_TESTS" -eq 139 ] && grep -qE '[0-9]+ passed' "$TESTS_OUT" \
        && ! grep -qE '[0-9]+ failed' "$TESTS_OUT"; then
        echo "⚠ pytest RC=139 (segfault connu Python 3.14/PySide6 en fin de process) — tous les tests ont réussi, build non bloqué."
    else
        rm -f "$TESTS_OUT"
        exit 1
    fi
fi
rm -f "$TESTS_OUT"

echo "[4/5] PyInstaller (onedir)..."
rm -rf dist/debriefMeet
./.venv-build/bin/pyinstaller packaging/linux/debriefMeet.spec --noconfirm \
    --distpath dist --workpath build/work || exit 1

echo "[5/5] Assemblage du .deb..."
sh packaging/linux/build_deb.sh || exit 1

# Menage : les intermediaires PyInstaller (~1,6 Go) et l arbre de staging du .deb ne
# servent plus une fois le paquet ecrit, et ils s accumulent d un build a l autre. Le
# conteneur (7,8 Go) est arrive a saturation le 2026-08-19, faisant echouer la fumee
# sur un « No space left on device » qui n avait rien a voir avec le paquet.
rm -rf build/work build/deb
echo "    espace libre : $(df -h / | awk "NR==2 {print \$4}")"

echo "=== Build termine avec succes ==="
