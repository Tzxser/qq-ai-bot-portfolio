#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if docker info >/dev/null 2>&1; then
  exec docker compose "$@"
else
  exec sudo -n docker compose "$@"
fi
