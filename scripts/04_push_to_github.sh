#!/usr/bin/env bash
# ==============================================================================
# [Step 4] One-Click Git Initialize, Commit & Push to GitHub Repository
# Target Remote: https://github.com/rhkim77/adk_with_bq_caa_lab.git
#
# Usage on Local MacBook (`~/Dev/ADK_test`):
#   chmod +x scripts/04_push_to_github.sh && ./scripts/04_push_to_github.sh
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REMOTE_URL="${1:-https://github.com/rhkim77/adk_with_bq_caa_lab.git}"

echo "======================================================================"
echo " 🚀 Pushing Lab Repository to: ${REMOTE_URL}"
echo "======================================================================"

# If .git was copied from Cloudtop with 'reftable' extension unsupported by macOS Xcode git, re-init cleanly
if [ -d ".git" ] && grep -q "reftable" ".git/config" 2>/dev/null; then
  if ! git status >/dev/null 2>&1; then
    echo " -> Detected Cloudtop reftable .git format on macOS; re-initializing standard .git..."
    rm -rf .git
  fi
fi

if [ ! -d ".git" ]; then
  git init -b main
fi

git branch -M main

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git add .
if ! git diff --cached --quiet; then
  git commit -m "feat: BigQuery CAA + Google ADK 3-Domain Multi-Agent Qwiklabs Hands-on Lab"
else
  echo " -> Working tree already committed."
fi

echo " -> Pushing 'main' branch to ${REMOTE_URL}..."
git push -u origin main

echo ""
echo "✅ Successfully pushed to: ${REMOTE_URL}"
