#!/bin/bash
# ThreatWatch Iran Monitor — Daily Pipeline Runner
# Cron example: 0 6 * * * /path/to/threatwatch-iran-monitor/run.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if it exists in the repo root
[ -f .env ] && source .env
export ANTHROPIC_API_KEY

python3 pipeline.py >> logs/cron.log 2>&1
echo "Exit: $? at $(date)" >> logs/cron.log
