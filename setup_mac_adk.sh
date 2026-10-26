#!/usr/bin/env bash
# ==============================================================================
# Google ADK Local MacBook Setup & Web UI Launcher (Keyless Vertex AI ADC Mode)
# Corporate Policy Compliant: Does NOT use GOOGLE_API_KEY (AI Studio).
# Includes macOS Corporate Keychain + certifi SSL Certificate Bundle Fix
# Usage on Local MacBook Terminal (zsh/bash):
#   chmod +x setup_mac_adk.sh && ./setup_mac_adk.sh [GCP_PROJECT_ID]
# ==============================================================================
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE_DIR"

TARGET_PROJECT="${1:-ryan-sandbox-agent}"
TARGET_DATASET="${2:-thelook_ecommerce_agent}"

echo "============================================================"
echo " [1/6] Checking Python & uv Package Manager..."
echo "============================================================"
if ! command -v uv &> /dev/null; then
  echo " -> Installing uv (Astral Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

echo "============================================================"
echo " [2/6] Creating Python 3.11+ Virtual Environment (.venv)..."
echo "============================================================"
if [ ! -d ".venv" ]; then
  uv venv --python 3.11 .venv || uv venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "============================================================"
echo " [3/6] Installing google-adk, truststore & certifi..."
echo "============================================================"
# Pin mcp==1.29.1 (<2.0) to prevent ModuleNotFoundError: mcp.shared.session
# Install truststore & certifi to fix macOS SSL: CERTIFICATE_VERIFY_FAILED (_ssl.c:1006)
# Security Guardrail (CVE-2026-49468 / b/572522296): Do NOT install litellm (<1.84 vulnerable),
# and proactively uninstall litellm if present in an existing .venv.
uv pip install "google-adk>=2.7.1" "google-genai>=1.0.0" "mcp==1.29.1" "python-dotenv>=1.0.1" "truststore>=0.10.0" "certifi>=2024.8.30"
uv pip uninstall litellm >/dev/null 2>&1 || true

echo "============================================================"
echo " [4/6] Building Combined macOS Keychain + certifi CA Bundle..."
echo "============================================================"
mkdir -p "$WORKSPACE_DIR/.certs"
CA_BUNDLE="$WORKSPACE_DIR/.certs/combined_ca_bundle.pem"
python3 -c "import certifi, shutil; shutil.copyfile(certifi.where(), '$CA_BUNDLE')"

if [ -f "/etc/ssl/cert.pem" ]; then
  cat "/etc/ssl/cert.pem" >> "$CA_BUNDLE"
fi

if command -v security &> /dev/null; then
  security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> "$CA_BUNDLE" 2>/dev/null || true
  security find-certificate -a -p /Library/Keychains/System.keychain >> "$CA_BUNDLE" 2>/dev/null || true
fi
echo " -> Generated combined CA bundle at: $CA_BUNDLE"

export SSL_CERT_FILE="$CA_BUNDLE"
export REQUESTS_CA_BUNDLE="$CA_BUNDLE"
export CURL_CA_BUNDLE="$CA_BUNDLE"
export GRPC_DEFAULT_SSL_ROOTS_FILE_PATH="$CA_BUNDLE"
export GOOGLE_API_USE_CLIENT_CERTIFICATE="false"
export GOOGLE_API_USE_MTLS_ENDPOINT="never"
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"
export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"
export GOOGLE_CLOUD_PROJECT="$TARGET_PROJECT"
export BQ_DATASET_ID="$TARGET_DATASET"
export GOOGLE_CLOUD_LOCATION="us-central1"

echo "============================================================"
echo " [5/6] Configuring Keyless Vertex AI (.env) for ${TARGET_PROJECT}.${TARGET_DATASET}..."
echo "============================================================"
for AGENT_DIR in "sample_agent" "multi_agent_demo" "bq_caa_toolset_agent" "bq_caa_streaming_agent" "bq_caa_3domain_multi_agent"; do
  if [ -d "$AGENT_DIR" ]; then
    cat <<EOF > "$AGENT_DIR/.env"
# Keyless Vertex AI ADC Mode (No GOOGLE_API_KEY required)
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_GENAI_USE_ENTERPRISE=TRUE
GOOGLE_CLOUD_PROJECT=${TARGET_PROJECT}
BQ_DATASET_ID=${TARGET_DATASET}
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_API_USE_CLIENT_CERTIFICATE=false
GOOGLE_API_USE_MTLS_ENDPOINT=never
SSL_CERT_FILE=${CA_BUNDLE}
REQUESTS_CA_BUNDLE=${CA_BUNDLE}
EOF
    echo " -> Configured $AGENT_DIR/.env (Project: $TARGET_PROJECT, Dataset: $TARGET_DATASET, SSL_CERT_FILE wired)"
  fi
done

echo "============================================================"
echo " [6/6] Verifying Google Cloud ADC (Keyless Auth)..."
echo "============================================================"
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo " ⚠️  No active Application Default Credentials (ADC) found."
  echo " -> Launching browser OAuth for Keyless ADC login..."
  gcloud config set project "$TARGET_PROJECT"
  gcloud auth application-default login
  gcloud auth application-default set-quota-project "$TARGET_PROJECT"
else
  echo " ✔ Active ADC token verified."
fi

echo ""
.venv/bin/adk telemetry disable >/dev/null 2>&1 || true
echo "✅ Setup Complete! Installed ADK version: $(.venv/bin/adk --version)"
echo "🚀 Starting ADK Web UI at http://127.0.0.1:8000/dev-ui/ ..."
echo "   (Press Ctrl+C to stop)"
echo ""
printf "n\n" | .venv/bin/adk web --host 127.0.0.1 --port 8000 --reload_agents .
