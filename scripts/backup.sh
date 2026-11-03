#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
chmod 700 backups
exec 9>backups/.lock
flock -n 9 || exit 3
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest="backups/$stamp"
mkdir -m 700 "$dest"
dc() { bash scripts/compose.sh "$@"; }
docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then docker_cmd=(sudo -n docker); fi
napcat_id=$(dc ps -q napcat)
[[ -n "$napcat_id" ]] || { printf 'BACKUP_FAILED: NapCat container missing\n'; exit 1; }
napcat_image=$("${docker_cmd[@]}" inspect --format '{{.Image}}' "$napcat_id")
# Drain the Bot, then briefly freeze QQ while copying its files. Restarting
# NapCat can require another human login; a freeze preserves its process.
bot_stopped=0
napcat_paused=0
cleanup() {
    result=$?
    trap - EXIT
    if (( napcat_paused )); then dc unpause napcat >/dev/null || result=1; fi
    if (( bot_stopped )); then dc start bot >/dev/null || result=1; fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bot_stopped=1
dc stop bot
dc exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dest/postgres.dump"
dc exec -T postgres pg_restore --list < "$dest/postgres.dump" >/dev/null
napcat_paused=1
dc pause napcat
# Bound the freeze; compression happens after QQ resumes. This is a frozen
# filesystem snapshot, not an application-level QQ session restore guarantee.
timeout --kill-after=5s 45s "${docker_cmd[@]}" run --rm --network none \
    --user "$(id -u):$(id -g)" --read-only --cap-drop ALL --memory 128m \
    --volumes-from "$napcat_id:ro" --volume "$PWD/$dest:/backup" \
    --entrypoint tar "$napcat_image" -C /app/.config -cf /backup/qq-session.tar QQ
cp .env "$dest/.env"
tar -czf "$dest/napcat-config.tar.gz" -C runtime/napcat config
dc unpause napcat >/dev/null
napcat_paused=0
dc exec -T redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning SAVE' >/dev/null
dc exec -T redis cat /data/dump.rdb > "$dest/redis.rdb"
dc start bot >/dev/null
bot_stopped=0
gzip -1 "$dest/qq-session.tar"
(cd "$dest" && sha256sum .env postgres.dump qq-session.tar.gz napcat-config.tar.gz redis.rdb > SHA256SUMS)
chmod 600 "$dest"/* "$dest/.env"
printf 'BACKUP_OK: %s (sensitive; keep private)\n' "$dest"
