#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/setup.sh
bash scripts/test.sh
bash scripts/compose.sh pull postgres redis
bash scripts/compose.sh build bot napcat
bash scripts/compose.sh up -d --wait --wait-timeout 240
bash scripts/healthcheck.sh --infrastructure
printf 'Infrastructure ready. QQ login, API key and human-initiated E2E are separate gates.\n'
