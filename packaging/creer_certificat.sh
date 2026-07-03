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

if security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
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

# Clé + certificat auto-signé (10 ans), avec l'EKU codeSigning requis par codesign.
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
    -days 3650 -config "$TMP/cfg.conf" >/dev/null 2>&1

openssl pkcs12 -export \
    -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -out "$TMP/cert.p12" -name "$IDENTITY" -passout pass: >/dev/null 2>&1

# Import dans le trousseau de session, autorisé pour codesign.
security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "" -T /usr/bin/codesign

echo "✓ Identité « $IDENTITY » créée et importée."
echo "  Au premier build signé, autoriser l'accès au trousseau (Toujours autoriser)."
