#!/usr/bin/env bash
# Quick launcher for ADK Web UI with macOS SSL Certificate & mTLS fix
set -euo pipefail
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE_DIR"

PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

unset VIRTUAL_ENV || true

if [ -x ".venv/bin/adk" ] && [ -x ".venv/bin/python3" ] && .venv/bin/python3 -c "import sys" >/dev/null 2>&1 && grep -Fq "$WORKSPACE_DIR/.venv" ".venv/bin/activate" 2>/dev/null; then
  ADK_BIN=".venv/bin/adk"
  PY_BIN=".venv/bin/python3"
elif command -v adk &> /dev/null; then
  ADK_BIN="$(command -v adk)"
  PY_BIN="python3"
else
  echo " -> Valid local .venv not found (or synced from another OS). Running ./setup_mac_adk.sh to initialize..."
  exec ./setup_mac_adk.sh
fi

mkdir -p "$WORKSPACE_DIR/.certs"
CA_BUNDLE="$WORKSPACE_DIR/.certs/combined_ca_bundle.pem"
if [ ! -f "$CA_BUNDLE" ]; then
  "$PY_BIN" -c "import certifi, shutil; shutil.copyfile(certifi.where(), '$CA_BUNDLE')"
  [ -f "/etc/ssl/cert.pem" ] && cat "/etc/ssl/cert.pem" >> "$CA_BUNDLE"
  if command -v security &> /dev/null; then
    security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> "$CA_BUNDLE" 2>/dev/null || true
    security find-certificate -a -p /Library/Keychains/System.keychain >> "$CA_BUNDLE" 2>/dev/null || true
  fi
fi

export SSL_CERT_FILE="$CA_BUNDLE"
export REQUESTS_CA_BUNDLE="$CA_BUNDLE"
export CURL_CA_BUNDLE="$CA_BUNDLE"
export GRPC_DEFAULT_SSL_ROOTS_FILE_PATH="$CA_BUNDLE"
export GOOGLE_API_USE_CLIENT_CERTIFICATE="false"
export GOOGLE_API_USE_MTLS_ENDPOINT="never"
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"
export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-ryan-sandbox-agent}"
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"

echo "🚀 Launching ADK Web UI on http://${HOST}:${PORT}/dev-ui/ (SSL_CERT_FILE=${CA_BUNDLE})..."
"$ADK_BIN" telemetry disable >/dev/null 2>&1 || true
printf "n\n" | "$ADK_BIN" web --host "$HOST" --port "$PORT" --reload_agents .
