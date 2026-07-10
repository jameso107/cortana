#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="$HOME/.cortana/certs"
CERT="$CERT_DIR/localhost.pem"
KEY="$CERT_DIR/localhost-key.pem"

mkdir -p "$CERT_DIR"

if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
    -keyout "$KEY" \
    -out "$CERT" \
    -subj "/CN=Cortana Local Bridge" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth"
  chmod 600 "$KEY"
fi

security add-trusted-cert -d -r trustRoot \
  -k "$HOME/Library/Keychains/login.keychain-db" "$CERT"

echo "Trusted local TLS certificate installed."
echo "Start the agent with: $ROOT/.venv/bin/cortana start"
