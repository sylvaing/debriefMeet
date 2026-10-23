#!/bin/bash
# publier_manifeste.sh — prépare les assets d'une Release pour la mise à jour
# automatique (docs/53 §4) : renommage en noms publics sans `+<date>.<hash>`, puis
# manifest.json généré, signé par le secret MAJ_CLE_PRIVEE_PEM et VÉRIFIÉ avec la
# clé publique embarquée dans l'app (même fonction que l'app — un secret qui ne
# correspond pas casse la release ici, jamais les postes).
#
# Usage : bash packaging/publier_manifeste.sh <version> <tag> <owner/repo> <dossier-artefacts>
#   ex.   bash packaging/publier_manifeste.sh 0.4.0 v0.4.0 sylvaing/debriefMeet artefacts
# Prérequis : python3 avec `cryptography`, variable d'environnement MAJ_CLE_PRIVEE_PEM.
# Appelé par les jobs `release` (tag) et `manifeste` (dispatch) de build.yml.
set -euo pipefail

VERSION="${1:?version (ex. 0.4.0)}"
TAG="${2:?tag (ex. v0.4.0)}"
DEPOT="${3:?owner/repo}"
ARTEFACTS="${4:?dossier des artefacts}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "${MAJ_CLE_PRIVEE_PEM:-}" ]; then
  echo "::error::secret MAJ_CLE_PRIVEE_PEM absent — la release ne peut pas être signée (docs/53 §4)"
  exit 1
fi

renommer() {   # renommer <motif-glob> <nom-final> : exactement un fichier attendu
  local motif="$1" cible="$2" trouves
  trouves=$(ls -1 "$ARTEFACTS"/$motif 2>/dev/null | wc -l | tr -d ' ')
  if [ "$trouves" != "1" ]; then
    echo "::error::$trouves fichier(s) pour $motif dans $ARTEFACTS (1 attendu)"
    exit 1
  fi
  # Déjà renommé (relance du script) : le glob matche le nom final lui-même.
  [ -e "$ARTEFACTS/$cible" ] || mv "$ARTEFACTS"/$motif "$ARTEFACTS/$cible"
}

renommer "debriefMeet-setup-*.exe"  "debriefMeet-setup-$VERSION.exe"
renommer "debriefmeet_*_amd64.deb"  "debriefmeet_${VERSION}_amd64.deb"
renommer "debriefMeet-*.dmg"        "debriefMeet-$VERSION.dmg"
renommer "debriefMeet-*.zip"        "debriefMeet-$VERSION.zip"

python3 "$ROOT/packaging/generer_manifeste.py" generer \
  --version "$VERSION" --tag "$TAG" --depot "$DEPOT" \
  --artefacts "$ARTEFACTS" --sortie "$ARTEFACTS/manifest.json"
python3 "$ROOT/packaging/generer_manifeste.py" signer \
  --manifeste "$ARTEFACTS/manifest.json" --sortie "$ARTEFACTS/manifest.sig"
python3 "$ROOT/packaging/generer_manifeste.py" verifier \
  --manifeste "$ARTEFACTS/manifest.json" --signature "$ARTEFACTS/manifest.sig"

cat "$ARTEFACTS/manifest.json"
