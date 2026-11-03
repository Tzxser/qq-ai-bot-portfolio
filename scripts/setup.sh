#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
python3 scripts/setup.py
python3 scripts/check_config.py
bash scripts/compose.sh config --quiet
