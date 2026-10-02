#!/bin/bash
set -Eeuo pipefail

base=/mnt/user/appdata/irons-grotto-bot
name=irons-grotto-bot
image=ghcr.io/danjsmith4/ironsgrottodiscordbot:approved
exec 9>/var/run/irons-grotto-bot-update.lock
flock -n 9 || exit 0

# Respect a manual stop and do not interfere while the array is unavailable.
[[ -d "$base/data" ]] || exit 0
[[ $(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null) == true ]] || exit 0
docker pull "$image" >/dev/null
candidate=$(docker image inspect -f '{{.Id}}' "$image")
current=$(docker inspect -f '{{.Image}}' "$name")
[[ "$candidate" != "$current" ]] || exit 0
[[ ! -f "$base/failed-image" || $(cat "$base/failed-image") != "$candidate" ]] || exit 0

stamp=$(date -u +%Y%m%dT%H%M%SZ)
previous="$name-previous-$stamp"
mkdir -p "$base/backups"
renamed=0
stopped=0
rollback() {
  trap - ERR INT TERM
  set +e
  if [[ "$renamed" == 1 ]]; then
    docker rm -f "$name" >/dev/null 2>&1
    docker rename "$previous" "$name"
  fi
  if [[ "$stopped" == 1 ]]; then
    docker start "$name" >/dev/null
  fi
  printf '%s\n' "$candidate" > "$base/failed-image"
  logger -t irons-grotto-bot 'Update failed; restored previous container. See bot logs and data backup.'
  exit 1
}
trap rollback ERR INT TERM

docker stop -t 30 "$name" >/dev/null
stopped=1
tar -czf "$base/backups/data-$stamp.tar.gz" -C "$base" data
docker rename "$name" "$previous"
renamed=1
sh "$base/start-unraid.sh" "$candidate" >/dev/null

# A fresh container has fresh logs. Require Discord login and no restart loop.
ready=0
for attempt in {1..30}; do
  sleep 2
  [[ $(docker inspect -f '{{.State.Running}}' "$name") == true ]] || break
  [[ $(docker inspect -f '{{.RestartCount}}' "$name") == 0 ]] || break
  if docker logs "$name" 2>&1 | grep -q 'Logged in as '; then
    ready=1
    break
  fi
done
[[ "$ready" == 1 ]]
trap - ERR INT TERM
printf '%s\n' "$candidate" > "$base/deployed-image"
logger -t irons-grotto-bot "Approved update installed: $candidate; previous container: $previous"
