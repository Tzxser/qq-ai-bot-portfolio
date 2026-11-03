#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p runtime
chmod 700 runtime
# Keep the script's own lock separate from the optional scheduler lock.  Older
# deployments wrapped this command in `flock runtime/qq-watchdog.lock`; using
# the same path here made the inner lock fail immediately and silently disabled
# the watchdog.  A distinct lock keeps direct invocations safe as well.
exec 9>runtime/qq-watchdog-script.lock
flock -n 9 || exit 0
line=$(python3 scripts/qq_watchdog.py)
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$line" >> runtime/qq-watchdog.log
tmp=runtime/.qq-watchdog.log.tmp
tail -n 1000 runtime/qq-watchdog.log > "$tmp"
mv "$tmp" runtime/qq-watchdog.log
chmod 600 runtime/qq-watchdog.log
