#!/bin/bash
# ThreatWatch Iran Monitor — One-time setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

pip3 install anthropic python-dotenv feedparser weasyprint
mkdir -p output/json output/docx output/pdf output/md output/html logs
[ -f output/json/manifest.json ] || echo '{"briefs":[]}' > output/json/manifest.json
echo "Setup complete. Copy .env.example to .env and add your ANTHROPIC_API_KEY."
