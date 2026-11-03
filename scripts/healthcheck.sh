#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/compose.sh ps
bash scripts/compose.sh exec -T bot python scripts/healthcheck.py "$@"
