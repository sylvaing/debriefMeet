#!/bin/bash
# creer_certificat.sh — crée (une seule fois) un certificat de signature local
# STABLE pour debriefMeet. La stabilité de cette identité est ce qui garantit que
# macOS conserve les permissions (Micro, Enregistrement de l'écran) entre deux
# rebuilds : TCC indexe les apps par leur signature, pas par leur chemin.
#
# Idempotent : si l'identité existe déjà, ne fait rien (NE PAS la régénérer, sinon
# les permissions seraient redemandées).
#
# Au premier `codesign` qui suit, macOS peut afficher une fenêtre « codesign veut
# signer avec la clé… » → cliquer **Toujours autoriser** (une seule fois).
set -euo pipefail

IDENTITY="debriefMeet Local"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

# ⚠️ PAS de `-v` (valides seulement) : un cert auto-signé est marqué
# CSSMERR_TP_NOT_TRUSTED et serait exclu → le script régénérerait une nouvelle
# identité à chaque run, et TCC redemanderait toutes les permissions.
# codesign, lui, signe très bien avec une identité non « trusted ».
if security find-identity -p codesigning | grep -q "$IDENTITY"; then
    echo "✓ Identité « $IDENTITY » déjà présente — rien à faire."
    exit 0
fi

echo "==> Création de l'identité de signature « $IDENTITY »…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/cfg.conf" <<'EOF'
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = debriefMeet Local
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

# /usr/bin/openssl (LibreSSL, toujours présent sur macOS) et PAS l'openssl de
# Homebrew : la sortie p12 d'OpenSSL 3 n'est pas toujours relisible par
# `security import`. Et un mot de passe **vide** est refusé dans tous les cas
# (« MAC verification failed during PKCS12 import ») → mot de passe jetable,
# utilisé uniquement le temps de l'import (le .p12 est détruit à la sortie).
OPENSSL=/usr/bin/openssl
P12_PWD="$(uuidgen)"

# Clé + certificat auto-signé (10 ans), avec l'EKU codeSigning requis par codesign.
"$OPENSSL" req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
    -days 3650 -config "$TMP/cfg.conf" >/dev/null 2>&1

"$OPENSSL" pkcs12 -export \
    -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -out "$TMP/cert.p12" -name "$IDENTITY" -passout "pass:$P12_PWD" >/dev/null 2>&1

# Import dans le trousseau de session, autorisé pour codesign.
security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "$P12_PWD" -T /usr/bin/codesign

echo "✓ Identité « $IDENTITY » créée et importée."
echo "  Au premier build signé, autoriser l'accès au trousseau (Toujours autoriser)."
