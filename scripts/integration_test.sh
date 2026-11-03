#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Uses namespaced disposable test rows; never truncates the application database.
bash scripts/compose.sh -f docker-compose.yml -f docker-compose.test.yml --profile test run --rm -T tests
