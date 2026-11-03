#!/usr/bin/env bash
set -uo pipefail
cat /etc/os-release
uname -m
nproc
free -m
df -h /
docker --version 2>/dev/null || true
docker compose version 2>/dev/null || true
ss -lnt
git status --short --branch 2>/dev/null || true
if sudo -n true; then printf 'SUDO_OK\n'; else printf 'SUDO_REQUIRES_USER\n'; exit 2; fi
